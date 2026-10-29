"""Learning admission and reconciliation through the existing JobService callback owner."""

from __future__ import annotations

import copy
import logging
import threading
import weakref
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.gui.learning_state import LearningState, LearningVariant
from src.learning.experiment_reconciliation import (
    TERMINAL,
    completion_evidence,
    completion_result,
    mark_completion_unavailable,
    note_missing_artifacts,
    project_status,
    read_job_evidence,
    reconciliation_summary,
    unresolved,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord

_logger = logging.getLogger(__name__)


@dataclass
class LearningJobContext:
    variant: LearningVariant
    experiment_name: str
    variable_under_test: str
    variant_value: Any
    job_id: str
    state: LearningState


class LearningAdmissionError(RuntimeError):
    """An unconfirmed response, with repository truth retained for reconciliation."""


class LearningExecutionController:
    """One tracking map and lock serialize restore, admission and terminal events.

    JobService retains its existing UI-thread dispatcher. No new event stream,
    worker, queue, repository mutation or retry is introduced here.
    """

    def __init__(self, learning_state: LearningState, job_service: Any = None) -> None:
        self.learning_state = learning_state
        self.job_service = job_service
        self._lock = threading.RLock()
        self._job_to_variant: dict[str, LearningVariant] = {}
        self._job_contexts: dict[str, LearningJobContext] = {}
        self._terminal_variants: dict[str, LearningVariant] = {}
        self._completing: set[str] = set()
        self._validating: set[str] = set()
        self._deferred: dict[str, tuple[str, Any]] = {}
        self._sessions: dict[str, LearningState] = {}
        self._checkpoint: Callable[[LearningState], None] | None = None
        self._admission_guard: Callable[[LearningState, list[str]], None] | None = None
        self._closed = False
        self._on_variant_completed: Callable[[LearningVariant, dict[str, Any]], None] | None = None
        self._on_variant_published: Callable[[LearningVariant, dict[str, Any]], None] | None = None
        self._on_variant_failed: Callable[[LearningVariant, Exception], None] | None = None
        if job_service and callable(getattr(job_service, "register_callback", None)):
            binding = vars(job_service).get("_learning_callback_binding")
            if binding is not None:
                binding["owner"] = weakref.ref(self)
                return
            binding = {"owner": weakref.ref(self)}
            job_service._learning_callback_binding = binding

            def finished(job: Any) -> None:
                controller = binding["owner"]() if binding["owner"] else None
                if controller is not None:
                    controller._handle_job_finished(job)

            def failed(job: Any, error: Any = None) -> None:
                controller = binding["owner"]() if binding["owner"] else None
                if controller is not None:
                    controller._handle_job_failed(job, error)

            job_service.register_callback("job_finished", finished)
            job_service.register_callback("job_failed", failed)

    @property
    def repository(self) -> Any:
        return getattr(self.job_service, "history_store", None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._job_to_variant.clear()
            self._job_contexts.clear()
            self._terminal_variants.clear()
            self._completing.clear()
            self._validating.clear()
            self._deferred.clear()
            self._sessions.clear()
            self._on_variant_completed = self._on_variant_failed = None
            self._on_variant_published = None

    def set_completion_callback(
        self, callback: Callable[[LearningVariant, dict[str, Any]], None]
    ) -> None:
        self._on_variant_completed = callback

    def set_failure_callback(self, callback: Callable[[LearningVariant, Exception], None]) -> None:
        self._on_variant_failed = callback

    def set_presentation_callback(
        self, callback: Callable[[LearningVariant, dict[str, Any]], None]
    ) -> None:
        """Present/checkpoint the safe terminal projection, after evidence publication."""
        self._on_variant_published = callback

    def bind_checkpoint(self, checkpoint: Callable[[LearningState], None]) -> None:
        self._checkpoint = checkpoint

    def bind_admission_guard(self, guard: Callable[[LearningState, list[str]], None]) -> None:
        self._admission_guard = guard

    def _present(
        self, state: LearningState, variant: LearningVariant, value: Any, *, failed: bool = False
    ) -> None:
        """Use JobService's existing dispatcher, with a fresh foreground identity check."""

        def deliver() -> None:
            if threading.current_thread() is not threading.main_thread():
                raise RuntimeError("Learning presentation requires the main UI thread")
            with self._lock:
                if (
                    self._closed
                    or state.current_experiment is not self.learning_state.current_experiment
                    or not any(item is variant for item in self.learning_state.plan)
                ):
                    return
                if failed and self._on_variant_failed:
                    self._on_variant_failed(variant, value)
                elif not failed and self._on_variant_published:
                    self._on_variant_published(variant, value)

        dispatcher = getattr(self.job_service, "_event_dispatcher", None)
        if threading.current_thread() is threading.main_thread():
            # JobService may already have dispatched this completion to Tk.
            # Present within that delivery rather than scheduling it a second time.
            deliver()
        elif callable(dispatcher):
            dispatcher(deliver)
        else:
            raise RuntimeError("Learning UI dispatcher unavailable for worker presentation")

    def track_session(self, state: LearningState) -> None:
        with self._lock:
            experiment = state.current_experiment
            if self._closed or experiment is None or not experiment.experiment_id:
                raise ValueError("A durable Learning experiment is required")
            self._sessions[experiment.experiment_id] = state

    def _save_session(self, state: LearningState) -> None:
        if self._checkpoint is not None:
            try:
                self._checkpoint(state)
            except (OSError, ValueError, RuntimeError) as exc:
                if state.current_experiment is not None:
                    state.current_experiment.metadata["resume_persistence_error"] = str(exc)
                raise

    def _track(
        self,
        job_id: str,
        variant: LearningVariant,
        experiment_name: str,
        variable_under_test: str,
        state: LearningState | None = None,
    ) -> None:
        if state is None:
            state = copy.copy(self.learning_state)
        self._job_to_variant[job_id] = variant
        self._job_contexts[job_id] = LearningJobContext(
            variant,
            experiment_name,
            variable_under_test,
            variant.param_value,
            job_id,
            state,
        )

    def _forget(self, job_id: str) -> None:
        self._job_to_variant.pop(job_id, None)
        self._job_contexts.pop(job_id, None)

    def _current_variant(self, job_id: str) -> LearningVariant | None:
        if self._closed:
            return None
        variant = self._job_to_variant.get(job_id)
        context = self._job_contexts.get(job_id)
        if (
            variant is not None
            and context is None
            and any(v is variant for v in self.learning_state.plan)
        ):
            # Preserve the existing explicitly installed synthetic/legacy tracking seam.
            experiment = self.learning_state.current_experiment
            self._track(
                job_id,
                variant,
                getattr(experiment, "name", ""),
                getattr(experiment, "variable_under_test", ""),
            )
            context = self._job_contexts[job_id]
        if (
            variant is not None
            and context is not None
            and any(v is variant for v in context.state.plan)
        ):
            if not variant.job_id or variant.job_id == job_id:
                return variant
        self._forget(job_id)
        return None

    def reconcile(self, state: LearningState | None = None) -> str:
        """Bind before reading; newer terminal callbacks cannot be downgraded."""
        with self._lock:
            state = state if state is not None else self.learning_state
            visible = self.learning_state.current_experiment
            incoming = state.current_experiment
            if (
                visible is not None
                and incoming is not None
                and visible.experiment_id == incoming.experiment_id
                and visible.execution_snapshot_json == incoming.execution_snapshot_json
                and {(v.variant_id, v.job_id) for v in self.learning_state.plan}
                == {(v.variant_id, v.job_id) for v in state.plan}
            ):
                state = self.learning_state
            if state is self.learning_state:
                state = copy.copy(state)
            experiment = state.current_experiment
            if self._closed or experiment is None:
                return ""
            if not experiment.experiment_id:
                # Historical sessions remain readable, but names, directory IDs
                # and today's compiler cannot reconstruct missing lineage.
                for variant in state.plan:
                    unresolved(
                        variant,
                        "Saved experiment has no durable experiment ID; exact job/artifact associations are retained. No automatic recovery or retry.",
                    )
                return reconciliation_summary(state.plan)
            self.track_session(state)
            for job_id, context in list(self._job_contexts.items()):
                bound_experiment = context.state.current_experiment
                if (
                    bound_experiment is not None
                    and bound_experiment.experiment_id == experiment.experiment_id
                ):
                    self._forget(job_id)
            job_counts = Counter(v.job_id for v in state.plan if v.job_id)
            variant_counts = Counter(v.variant_id for v in state.plan if v.variant_id)
            duplicates = {
                id(v)
                for v in state.plan
                if job_counts[v.job_id] > 1 or variant_counts[v.variant_id] > 1
            }
            # Validate every rebound mapping before allowing any completion to
            # act on it, including reentrant notifications during a repository read.
            for variant in state.plan:
                if variant.job_id and id(variant) not in duplicates:
                    self._track(
                        variant.job_id,
                        variant,
                        experiment.name,
                        experiment.variable_under_test,
                        state,
                    )
                    self._validating.add(variant.job_id)
            for variant in state.plan:
                if id(variant) in duplicates:
                    unresolved(
                        variant,
                        "Saved plan has duplicate job or variant identities; reconcile manually.",
                    )
                    continue
                if not variant.job_id and variant.status == "pending":
                    continue
                evidence = read_job_evidence(self.repository, experiment, variant)
                self._validating.discard(variant.job_id)
                deferred = self._deferred.pop(variant.job_id, None)
                if evidence.error:
                    self._forget(variant.job_id)
                    unresolved(variant, evidence.error)
                    continue
                variant.executed_config = evidence.executed_config
                prior = self._terminal_variants.get(variant.job_id)
                if (
                    prior
                    and prior.variant_id == variant.variant_id
                    and prior.experiment_id == variant.experiment_id
                ):
                    variant.__dict__.update(copy.deepcopy(prior.__dict__))
                    self._terminal_variants[variant.job_id] = variant
                    self._forget(variant.job_id)
                    continue
                if deferred is not None:
                    kind, value = deferred
                    if kind == "completed":
                        self.on_job_completed(variant.job_id, value)
                    elif kind == "failed_job":
                        self._handle_job_failed(*value)
                    else:
                        self.on_job_failed(variant.job_id, value)
                    continue
                status = str(getattr(evidence.job.status, "value", evidence.job.status))
                if variant.status in TERMINAL and status != "completed":
                    self._forget(variant.job_id)
                    self._terminal_variants[variant.job_id] = variant
                    if variant.status != status:
                        unresolved(
                            variant,
                            f"Saved terminal state conflicts with repository status {status}.",
                        )
                    else:
                        project_status(variant, evidence.job)
                    continue
                was_uncontrolled = variant.status == "uncontrolled"
                if was_uncontrolled and status == "completed":
                    refs = self._extract_image_refs(completion_result(evidence.job))
                    variant.image_refs = list(dict.fromkeys([*variant.image_refs, *refs]))
                    variant.completed_images = max(
                        variant.completed_images, len(variant.image_refs)
                    )
                    variant.execution_metadata["controlled_evidence_valid"] = False
                    note_missing_artifacts(variant)
                    self._terminal_variants[variant.job_id] = variant
                    self._forget(variant.job_id)
                    continue
                status = project_status(variant, evidence.job)
                if status == "completed":
                    self.on_job_completed(variant.job_id, completion_result(evidence.job))
                elif status in {"failed", "cancelled"}:
                    self._forget(variant.job_id)
                    self._terminal_variants[variant.job_id] = variant
            return reconciliation_summary(state.plan)

    def submit_experiment_jobs(
        self,
        records: list[NormalizedJobRecord] | tuple[NormalizedJobRecord, ...],
        variants: list[LearningVariant],
        experiment_name: str,
        variable_under_test: str,
        *,
        state: LearningState | None = None,
    ) -> list[str]:
        if self._closed:
            raise RuntimeError("Learning execution controller is closed")
        if not self.job_service or not callable(getattr(self.job_service, "submit_njrs", None)):
            raise RuntimeError("JobService.submit_njrs is unavailable")
        if not records or len(records) != len(variants):
            raise ValueError("records and variants must be non-empty and aligned")
        expected = [record.job_id for record in records]
        if len(set(expected)) != len(expected):
            raise ValueError("compiled NJR identities must be unique")
        with self._lock:
            state = state if state is not None else self.learning_state
            if self._admission_guard is not None:
                self._admission_guard(state, expected)
            if state is self.learning_state:
                state = copy.copy(state)
            experiment = state.current_experiment
            self.track_session(state)
            for record, variant in zip(records, variants, strict=True):
                variant.job_id = record.job_id
                self._track(record.job_id, variant, experiment_name, variable_under_test, state)
                self._validating.add(record.job_id)
            failure = None
            try:
                returned = self.job_service.submit_njrs(list(records), SubmissionPolicy())
                if not isinstance(returned, (list, tuple)):
                    raise LearningAdmissionError("JobService returned no valid admission ID list")
                ids = [str(value) for value in (returned or [])]
                if len(ids) != len(expected) or set(ids) != set(expected):
                    raise LearningAdmissionError(
                        "JobService returned IDs inconsistent with the compiled batch"
                    )
            except Exception as exc:
                _logger.exception(
                    "Learning admission response failed; checking exact repository IDs"
                )
                failure = exc
            if failure is None:
                for record, variant in zip(records, variants, strict=True):
                    variant.job_id = record.job_id
                    if variant.status not in TERMINAL:
                        variant.status = "queued"
                for record in records:
                    self._validating.discard(record.job_id)
                    deferred = self._deferred.pop(record.job_id, None)
                    if deferred:
                        kind, value = deferred
                        if kind == "completed":
                            self.on_job_completed(record.job_id, value)
                        elif kind == "failed_job":
                            self._handle_job_failed(*value)
                        else:
                            self.on_job_failed(record.job_id, value)
                return expected

            # A lost/raised response says nothing about a committed transaction.
            for record, variant in zip(records, variants, strict=True):
                variant.job_id = record.job_id
                self._validating.discard(record.job_id)
            evidence = [
                read_job_evidence(self.repository, experiment, variant) for variant in variants
            ]
            if all(item.absent for item in evidence):
                for variant in variants:
                    self._forget(variant.job_id)
                    variant.job_id = ""
                raise LearningAdmissionError(f"No jobs admitted: {failure}") from failure
            message = f"Admission response requires attention: {failure}. Do not retry; reconcile recorded job IDs."
            for variant in variants:
                if variant.status not in TERMINAL:
                    unresolved(variant, message)
                variant.execution_metadata["admission_error"] = message
            self.reconcile(state)
            raise LearningAdmissionError(message) from failure

    def submit_variant_job(
        self,
        record: NormalizedJobRecord,
        variant: LearningVariant,
        experiment_name: str,
        variable_under_test: str,
    ) -> bool:
        try:
            self.submit_experiment_jobs([record], [variant], experiment_name, variable_under_test)
            return True
        except Exception:
            _logger.exception("Learning variant admission was not confirmed")
            return False

    def _handle_job_finished(self, job: Any) -> None:
        self.on_job_completed(str(getattr(job, "job_id", "") or ""), completion_result(job))

    def _handle_job_failed(self, job: Any, error: Any = None) -> None:
        reason = str(error or getattr(job, "error_message", "") or "Job failed")
        job_id = str(getattr(job, "job_id", "") or "")
        with self._lock:
            variant = self._current_variant(job_id)
            if variant is None or job_id in self._completing:
                return
            if variant is not None and job_id in self._validating:
                self._deferred.setdefault(job_id, ("failed_job", (job, error)))
                return
            if variant is not None and job_id not in self._validating:
                project_status(variant, job)
            self.on_job_failed(job_id, Exception(reason))

    def on_job_completed(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            variant = self._current_variant(job_id)
            if variant is None or job_id in self._terminal_variants or job_id in self._completing:
                return
            if job_id in self._validating:
                self._deferred.setdefault(job_id, ("completed", copy.deepcopy(result)))
                return
            before = copy.deepcopy(variant.__dict__)
            state = self._job_contexts[job_id].state
            experiment = state.current_experiment
            before_experiment_metadata = copy.deepcopy(experiment.metadata) if experiment else None
            self._completing.add(job_id)
            variant.job_id = job_id
            variant.image_refs = list(
                dict.fromkeys([*variant.image_refs, *self._extract_image_refs(result)])
            )
            variant.completed_images = max(variant.completed_images, len(variant.image_refs))
            variant.status = "completed"
            note_missing_artifacts(variant)
            completion_images, completion_count = list(variant.image_refs), variant.completed_images
            try:
                if (
                    experiment is self.learning_state.current_experiment
                    and self._on_variant_completed
                    and threading.current_thread() is threading.main_thread()
                ):
                    self._on_variant_completed(variant, result)
                else:
                    evidence = completion_evidence(experiment, variant, result)
                    variant.status = evidence.status
                    variant.execution_metadata = evidence.execution_metadata
                    if experiment is not None and evidence.experiment_metadata is not None:
                        experiment.metadata = evidence.experiment_metadata
            except Exception as exc:
                _logger.exception("Learning completion callback rejected evidence for %s", job_id)
                variant.__dict__.update(before)
                variant.job_id = job_id
                variant.image_refs = completion_images
                variant.completed_images = completion_count
                if experiment is not None and before_experiment_metadata is not None:
                    experiment.metadata = before_experiment_metadata
                mark_completion_unavailable(variant, f"Completion evidence unavailable: {exc}")
            finally:
                self._completing.discard(job_id)
            self._forget(job_id)
            self._terminal_variants[job_id] = variant
            self._save_session(state)
            if experiment is self.learning_state.current_experiment and self._on_variant_published:
                try:
                    self._present(state, variant, result)
                except Exception as exc:
                    _logger.exception(
                        "Learning completion presentation/checkpoint failed for %s", job_id
                    )
                    variant.execution_metadata.update(
                        completion_presentation_error=str(exc), action_required=True
                    )

    def on_job_failed(self, job_id: str, error: Exception) -> None:
        with self._lock:
            variant = self._current_variant(job_id)
            if variant is None or job_id in self._terminal_variants or job_id in self._completing:
                return
            if job_id in self._validating:
                self._deferred.setdefault(job_id, ("failed", error))
                return
            state = self._job_contexts[job_id].state
            self._forget(job_id)
            self._terminal_variants[job_id] = variant
            variant.job_id = job_id
            variant.status = "cancelled" if variant.status == "cancelled" else "failed"
            variant.execution_metadata["job_error"] = str(error)
            self._save_session(state)
            if (
                state.current_experiment is self.learning_state.current_experiment
                and self._on_variant_failed
            ):
                self._present(state, variant, error, failed=True)

    def _extract_image_refs(self, result: dict[str, Any]) -> list[str]:
        return [str(path) for path in completion_result(SimpleNamespace(result=result))["images"]]
