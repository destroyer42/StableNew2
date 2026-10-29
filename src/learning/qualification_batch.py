"""Whole-selection preflight and bounded coordination over existing Learning admission.

Sessions are the durable intent/association record; SQLite alone owns job lifecycle.
There is no automatic submission retry, cross-experiment transaction, or runtime here.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from src.gui.learning_state import LearningState
from src.learning.evidence_autopilot import (
    ProposalPlan,
    ProposalPlanningContext,
    execution_baseline,
    selected_proposals,
    validate_current,
)
from src.learning.evidence_proposals import ExperimentProposal, proposal_payload
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_execution import freeze_snapshot
from src.learning.experiment_reconciliation import read_job_evidence, unresolved
from src.learning.experiment_store import LearningExperimentStore
from src.learning.preview_summary import PreviewSummary
from src.pipeline.job_models_v2 import NormalizedJobRecord

logger = logging.getLogger(__name__)

Freeze = Callable[
    [LearningState, ProposalPlanningContext, bool],
    tuple[tuple[NormalizedJobRecord, ...], PreviewSummary],
]


@dataclass(frozen=True)
class PreparedExperiment:
    state: LearningState
    records: tuple[NormalizedJobRecord, ...]
    saved_revision: str
    summary: PreviewSummary | None = None


@dataclass(frozen=True)
class QualificationBatch:
    plan: ProposalPlan
    experiments: tuple[PreparedExperiment, ...]
    confirmation: str


@dataclass(frozen=True)
class BatchOutcome:
    admitted: tuple[str, ...]
    existing: tuple[str, ...]
    stopped: str = ""

    def describe(self) -> str:
        return (
            f"Confirmed admissions: {len(self.admitted)} experiments; "
            f"existing work preserved: {len(self.existing)}. "
            + (
                f"Stopped: {self.stopped} Subsequent experiments were not submitted."
                if self.stopped
                else "Open Experiment Library to review and rate."
            )
        )


class QualificationBatchService:
    def __init__(
        self,
        store: LearningExperimentStore,
        execution: LearningExecutionController,
        freeze: Freeze,
    ) -> None:
        self.store, self.execution, self.freeze = store, execution, freeze
        self.execution.bind_checkpoint(self.checkpoint)
        self.execution.bind_admission_guard(self.guard_admission)

    def guard_admission(self, state: LearningState, ids: list[str]) -> None:
        """Fence stale ordinary Run as well as repeated catalog queue actions."""
        experiment = state.current_experiment
        if experiment is None:
            raise ValueError("Learning experiment unavailable")
        saved = self.store.load_session(experiment.experiment_id) or {}
        previous = saved.get("current_experiment") or {}
        if not (previous.get("metadata") or {}).get("qualification_batch"):
            return
        saved_ids = [str(item.get("job_id") or "") for item in saved.get("plan") or []]
        if (
            saved_ids != ids
            or not saved_ids
            or any(
                self.execution.repository.get_job_model(job_id) is not None for job_id in saved_ids
            )
        ):
            raise ValueError(
                "This experiment already has recorded admission work; open/reconcile it or create a new experiment for a rerun"
            )

    def checkpoint(self, state: LearningState) -> None:
        experiment = state.current_experiment
        if experiment is None or not experiment.metadata.get("qualification_batch"):
            return
        with self.store.lock:
            saved = self.store.load_session(experiment.experiment_id)
            if saved is None:
                raise RuntimeError(
                    "Batch session unavailable; exact associations require attention"
                )
            old_experiment = saved.get("current_experiment") or {}
            if (old_experiment.get("metadata") or {}).get("qualification_batch"):
                # Background completion owns execution projections, never newer
                # operator edits, review drafts or presentation selections.
                payload = copy.deepcopy(saved)
                payload["plan"] = [variant.to_dict() for variant in state.plan]
                metadata = payload["current_experiment"].setdefault("metadata", {})
                for key in (
                    "qualification_batch",
                    "observed_seed_vector",
                    "observed_subseed_vector",
                    "observed_launch_profile",
                    "resume_persistence_error",
                ):
                    if key in experiment.metadata:
                        metadata[key] = copy.deepcopy(experiment.metadata[key])
            else:
                payload = {**saved, **state.to_dict(), "resume_schema_version": 1}
            self.store.save_session(
                display_name=payload["current_experiment"]["name"],
                payload=payload,
                experiment_id=experiment.experiment_id,
            )

    def saved_prompt_context(self, ids: tuple[str, ...]) -> tuple[str, str, dict[str, Any]] | None:
        """Reuse one existing context without changing saved drafts."""
        selected: tuple[str, str, dict[str, Any]] | None = None
        for identity in ids:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                raise ValueError("Invalid qualification experiment identity")
            experiment = (self.store.load_session(identity) or {}).get("current_experiment") or {}
            prompt = str(experiment.get("prompt_text") or "")
            metadata = experiment.get("metadata") or {}
            negative = str(metadata.get("selected_prompt_negative_text") or "")
            if not prompt.strip() or len(prompt) > 16000 or len(negative) > 16000:
                continue
            source = {
                key: copy.deepcopy(value)
                for key, value in metadata.items()
                if key == "prompt_source" or key.startswith("selected_prompt_")
            }
            context = (prompt, negative, source)
            if selected is not None and selected[:2] != context[:2]:
                raise ValueError(
                    "Saved experiments use different prompt contexts; edit intentionally in Learning before batching"
                )
            selected = context
        return selected

    def restore(self) -> tuple[str, ...]:
        """Rebind every saved batch on startup; never scan history or resubmit."""
        restored = []
        with self.execution._lock:
            for handle in self.store.list_handles():
                if not re.fullmatch(r"[A-Za-z0-9_-]+", handle.experiment_id):
                    continue
                payload = self.store.load_session(handle.experiment_id)
                metadata = ((payload or {}).get("current_experiment") or {}).get("metadata") or {}
                if payload is None or not metadata.get("qualification_batch"):
                    continue
                state = LearningState.from_dict(payload)
                if (
                    state.current_experiment is None
                    or state.current_experiment.experiment_id != handle.experiment_id
                ):
                    raise ValueError("Batch Library identity conflicts with its session")
                self.execution.reconcile(state)
                self.checkpoint(self.execution._sessions[handle.experiment_id])
                restored.append(handle.experiment_id)
        return tuple(restored)

    def prepare(
        self,
        plan: ProposalPlan,
        ids: tuple[str, ...],
        context: ProposalPlanningContext,
        prompt: tuple[str, str, dict[str, Any]],
        *,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> QualificationBatch:
        validate_current(plan, context)
        proposals = selected_proposals(plan, ids)
        if not proposals:
            raise ValueError("Select at least one eligible experiment")
        prepared: list[PreparedExperiment] = []
        lines: list[str] = []
        warnings: list[str] = []
        images, work = 0, 0
        for proposal in proposals:
            if cancelled():
                raise InterruptedError("Batch preflight cancelled; zero jobs admitted")
            identity = proposal.proposal_id
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                raise ValueError("Invalid qualification experiment identity")
            with self.store.lock:
                payload = self.store.load_session(identity)
                if payload is None:
                    if self.store.session_path_for(identity).exists():
                        raise ValueError(
                            f"{identity}: saved draft is unreadable; preserve and repair it"
                        )
                    document = copy.deepcopy(dict(proposal.document))
                    document.update(
                        baseline=execution_baseline(context),
                        prompt=prompt[0],
                        negative_prompt=prompt[1],
                        prompt_source_context=prompt[2],
                    )
                    payload = proposal_payload(ExperimentProposal(document))
                    self.store.save_session(
                        display_name=document["name"],
                        payload=payload,
                        experiment_id=identity,
                        create_only=True,
                    )
            revision = freeze_snapshot(payload)
            state = LearningState.from_dict(copy.deepcopy(payload))
            experiment = state.current_experiment
            try:
                if experiment is None or experiment.experiment_id != identity:
                    raise ValueError("Saved experiment identity conflicts with selected proposal")
                if any(v.job_id or v.status != "pending" for v in state.plan):
                    if not state.plan or any(not v.job_id for v in state.plan):
                        raise ValueError(
                            "Existing admission has missing associations; reconcile before continuing"
                        )
                    for variant in state.plan:
                        evidence = read_job_evidence(self.execution.repository, experiment, variant)
                        if evidence.error:
                            raise ValueError(evidence.error + " Do not retry; reconcile exact IDs.")
                    prepared.append(PreparedExperiment(state, (), revision))
                    lines.append(f"{experiment.name}: existing jobs preserved (no rerun)")
                    continue
                if not experiment.prompt_text.strip():
                    experiment.prompt_text = prompt[0]
                    experiment.metadata.update(copy.deepcopy(prompt[2]))
                    experiment.metadata["selected_prompt_negative_text"] = prompt[1]
                if experiment.values != proposal.document["values"]:
                    raise ValueError(
                        "Saved alternatives were edited; preserve them and create a new experiment"
                    )
                if (
                    experiment.prompt_text != prompt[0]
                    or experiment.metadata.get("selected_prompt_negative_text", "") != prompt[1]
                ):
                    raise ValueError(
                        "Saved prompt context differs from the batch; edit it intentionally in Learning first"
                    )
                records, summary = self.freeze(state, context, True)
                if len(records) != len(state.plan) or summary.total_images != sum(
                    v.planned_images for v in state.plan
                ):
                    raise ValueError("Compiled NJRs disagree with the frozen experiment budget")
                if summary.total_images != proposal.document["expected_images"]:
                    raise ValueError("Saved design changed its expected image count")
                images += summary.total_images
                for record in records:
                    cfg = record.config["txt2img"]
                    work += int(cfg["steps"]) * experiment.images_per_value
                warnings.extend(summary.warnings)
                lines.append(f"{experiment.name}: {summary.headline}")
                prepared.append(PreparedExperiment(state, records, revision, summary))
            except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                raise ValueError(
                    f"{getattr(experiment, 'name', identity)}: {exc}. Zero jobs admitted."
                ) from exc
        prompt_source = prompt[2].get("prompt_source", "custom")
        confirmation = (
            f"Checkpoint: {context.target.identity.display_name}\nSHA-256: {context.target.identity.sha256}\n"
            f"Selected experiments: {len(prepared)}\nNew images: {images}\n"
            f"Estimated denoising work: {work} steps (elapsed time unknown)\nPrompt source: {prompt_source}\n"
            + "\n".join(lines)
            + "\nBlocked selected items: none (whole-selection preflight passed).\n"
            + "\n".join(dict.fromkeys(warnings))
            + "\nQueueing may start GPU generation under the current queue policy. "
            "Admission is atomic per experiment; earlier experiments remain admitted if a later one fails. "
            "No profile is published. Queue these experiments?"
        )
        return QualificationBatch(plan, tuple(prepared), confirmation)

    def admit(
        self,
        batch: QualificationBatch,
        context: ProposalPlanningContext,
        *,
        confirmed: bool,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> BatchOutcome:
        if not confirmed:
            raise ValueError("Explicit generation confirmation is required")
        admitted: list[str] = []
        existing: list[str] = []
        with self.execution._lock:
            validate_current(batch.plan, context)
            # Recheck every saved revision and compile every frozen experiment
            # before the first submission. Never rebuild accepted intent at admission.
            for entry in batch.experiments:
                experiment = entry.state.current_experiment
                if experiment is None:
                    raise ValueError("Prepared experiment unavailable; zero jobs admitted")
                saved = self.store.load_session(experiment.experiment_id)
                if freeze_snapshot(saved or {}) != entry.saved_revision:
                    raise ValueError(
                        f"{experiment.name}: Library changed after confirmation; zero jobs admitted"
                    )
                if entry.records:
                    current, _ = self.freeze(copy.deepcopy(entry.state), context, False)
                    if len(current) != len(entry.records) or any(
                        replace(new, job_id=old.job_id).to_dict() != old.to_dict()
                        for new, old in zip(current, entry.records, strict=True)
                    ):
                        raise ValueError(
                            f"{experiment.name}: expected NJRs changed; zero jobs admitted"
                        )
            for entry in batch.experiments:
                experiment, state = entry.state.current_experiment, entry.state
                if experiment is None:
                    raise ValueError("Prepared experiment unavailable")
                if not entry.records:
                    existing.append(experiment.experiment_id)
                    continue
                if cancelled():
                    return BatchOutcome(
                        tuple(admitted), tuple(existing), "Cancelled before next experiment"
                    )
                reserved = False
                try:
                    with self.store.lock:
                        if (
                            freeze_snapshot(self.store.load_session(experiment.experiment_id) or {})
                            != entry.saved_revision
                        ):
                            raise ValueError(
                                "Library changed during admission; preserve edited work"
                            )
                        experiment.metadata["qualification_batch"] = {"admission": "attempted"}
                        for variant, record in zip(state.plan, entry.records, strict=True):
                            variant.job_id = record.job_id
                        self.checkpoint(state)  # Write-ahead exact IDs before crossing JobService.
                    reserved = True
                    self.execution.track_session(state)
                    self.execution.submit_experiment_jobs(
                        entry.records,
                        state.plan,
                        experiment.name,
                        experiment.variable_under_test,
                        state=state,
                    )
                    evidence = [
                        read_job_evidence(self.execution.repository, experiment, v)
                        for v in state.plan
                    ]
                    if any(item.error for item in evidence):
                        raise RuntimeError(
                            "Admission IDs were returned but exact repository evidence is unresolved"
                        )
                    admitted.append(experiment.experiment_id)
                    experiment.metadata["qualification_batch"]["admission"] = "confirmed"
                    self.checkpoint(state)
                except Exception as exc:
                    logger.exception(
                        "Qualification admission stopped; reconciling exact repository IDs"
                    )
                    if not reserved:
                        return BatchOutcome(
                            tuple(admitted),
                            tuple(existing),
                            f"{experiment.name}: {exc}; no submission attempted for this experiment",
                        )
                    # Submission might have committed. Retain every expected ID,
                    # inspect exact immutable repository truth, and stop without retry.
                    for variant, record in zip(state.plan, entry.records, strict=True):
                        variant.job_id = record.job_id
                    self.execution.reconcile(state)
                    facts = [
                        read_job_evidence(self.execution.repository, experiment, v)
                        for v in state.plan
                    ]
                    if (
                        all(not item.error for item in facts)
                        and experiment.experiment_id not in admitted
                    ):
                        admitted.append(experiment.experiment_id)
                    for variant, fact in zip(state.plan, facts, strict=True):
                        if fact.error:
                            unresolved(variant, fact.error)
                        variant.execution_metadata["admission_error"] = str(exc)
                    try:
                        self.checkpoint(state)
                    except (OSError, ValueError, RuntimeError) as save_error:
                        return BatchOutcome(
                            tuple(admitted),
                            tuple(existing),
                            f"{experiment.name}: {exc}; checkpoint: {save_error}. Do not retry",
                        )
                    return BatchOutcome(
                        tuple(admitted),
                        tuple(existing),
                        f"{experiment.name}: {exc}. Inspect exact saved job IDs; do not retry",
                    )
        return BatchOutcome(tuple(admitted), tuple(existing))
