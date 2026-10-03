"""Toolkit-neutral state for the Video Workflow "Compare one control" section (PR-VID-194).

The session holds only transient, unsaved form state: whether comparing is on, which declared
control is under test, the candidate texts and the most recent preview.  It owns no experiment
authority: previewing and queueing are delegated to injected callables (the Video Workflow
controller), and it never builds a backend payload, touches the queue or names a workflow/model.
The control list comes exclusively from the selected workflow's ``operator_controls`` projection.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_CANDIDATES = 3  # mirrors the service limit; the service remains the authority


@dataclass(frozen=True)
class ExperimentPreviewView:
    """Everything the operator needs to see before queueing, as plain text rows."""

    experiment_id: str
    variable_label: str
    statement: str
    common_seed: str
    arms: tuple[tuple[str, str], ...]  # (arm label, "<control label> = <effective value>")
    fixed: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PreviewWork:
    """Plain, immutable snapshot a preview worker runs on (no Tk variables or widgets)."""

    token: int
    source_image_path: str
    form_data: dict[str, Any]
    variable_name: str
    candidates: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class QueueWork:
    plan: Any


@dataclass(frozen=True)
class WorkOutcome:
    value: Any = None
    error: str = ""


class BackgroundWorkRunner:
    """Runs one unit of work off the UI thread and delivers its outcome back ON the UI thread.

    ``spawn`` starts an owned worker (the Tk panel injects ``ThreadRegistry.spawn``) and
    ``dispatch`` marshals a callable onto the UI thread (``TkUiDispatcher.invoke``); this class has
    no scheduler, queue or lifecycle of its own.
    """

    def __init__(
        self,
        *,
        spawn: Callable[[str, Callable[[], None]], Any],
        dispatch: Callable[[Callable[[], None]], None],
    ) -> None:
        self._spawn = spawn
        self._dispatch = dispatch

    def start(
        self,
        name: str,
        work: Callable[[], WorkOutcome],
        on_done: Callable[[WorkOutcome], None],
    ) -> None:
        def worker() -> None:
            try:
                outcome = work()
            except BaseException as exc:  # a worker must always report back
                outcome = WorkOutcome(error=str(exc) or type(exc).__name__)
            try:
                self._dispatch(lambda: on_done(outcome))
            except Exception:
                pass  # the UI is gone; nothing to render

        self._spawn(name, worker)


def format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _preview_view(plan: Any) -> ExperimentPreviewView:
    return ExperimentPreviewView(
        experiment_id=plan.experiment_id,
        variable_label=plan.variable_label,
        statement=plan.statement,
        common_seed="n/a" if plan.common_seed is None else str(plan.common_seed),
        arms=tuple(
            (
                f"{arm.label} (baseline)" if arm.index == 0 else arm.label,
                f"{plan.variable_label} = {format_value(arm.value)}",
            )
            for arm in plan.arms
        ),
        fixed=tuple(plan.fixed_inputs()),
    )


class VideoExperimentSession:
    """View-model for one Video Workflow tab's experiment section."""

    def __init__(
        self,
        *,
        resolve_baseline: Callable[[dict[str, Any], str], Any],
        build_preview: Callable[..., Any],
        submit_plan: Callable[[Any], Any],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._resolve_baseline = resolve_baseline
        self._build_preview = build_preview
        self._submit_plan = submit_plan
        self._on_change = on_change
        self.controls: list[dict[str, Any]] = []
        self.enabled = False
        self.variable_name = ""
        self.candidates: list[str] = [""]
        self.message = ""
        self.preview: ExperimentPreviewView | None = None
        self._plan: Any = None
        self._fingerprint = ""
        self._token = 0
        self.busy: str | None = None  # "preview" | "queue" while a worker is outstanding

    # ------------------------------------------------------------------ capability

    @property
    def available(self) -> bool:
        """Offered only when the selected workflow declares at least one operator control."""

        return bool(self.controls)

    @property
    def variable_choices(self) -> list[tuple[str, str]]:
        return [(control["name"], control["label"]) for control in self.controls]

    @property
    def variable_control(self) -> dict[str, Any] | None:
        return next((c for c in self.controls if c["name"] == self.variable_name), None)

    def apply_controls(self, controls: Sequence[Mapping[str, Any]] | None) -> None:
        declared = [dict(control) for control in controls or []]
        if declared == self.controls:
            return
        self.controls = declared
        self.variable_name = declared[0]["name"] if declared else ""
        self.candidates = [""]
        if not declared:
            self.enabled = False
        self._clear_preview("")

    # ------------------------------------------------------------------ editing

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled) and self.available
        self._clear_preview("")

    def select_variable(self, name: str) -> None:
        if name in {control["name"] for control in self.controls} and name != self.variable_name:
            self.variable_name = name
            self.candidates = [""]
            self._clear_preview("")

    def add_candidate(self) -> bool:
        if len(self.candidates) >= MAX_CANDIDATES:
            return False
        self.candidates.append("")
        self._clear_preview("")
        return True

    def remove_candidate(self, index: int) -> bool:
        if len(self.candidates) <= 1 or not 0 <= index < len(self.candidates):
            return False
        del self.candidates[index]
        self._clear_preview("")
        return True

    def set_candidate(self, index: int, text: str) -> None:
        if 0 <= index < len(self.candidates) and self.candidates[index] != text:
            self.candidates[index] = text
            self._clear_preview("")

    def baseline_text(self, form_data: dict[str, Any]) -> str:
        """Current RESOLVED effective value of the control under test (never an invented one)."""

        if not self.variable_name:
            return ""
        try:
            return format_value(self._resolve_baseline(form_data, self.variable_name))
        except ValueError as exc:
            return f"(invalid: {exc})"

    # ------------------------------------------------------------------ preview / queue
    #
    # Previewing and queueing hash files, prepare the source image and build NJRs, so the Tk
    # surface never runs them inline.  Each is split into three steps: ``begin_*`` (UI thread:
    # claims the busy state and captures a plain snapshot of the inputs), ``run_*`` (worker thread:
    # touches no session state) and ``finish_*`` (UI thread: applies the result unless a newer edit
    # made it stale).  ``build_preview`` / ``queue`` compose the same steps synchronously.

    @property
    def preview_valid(self) -> bool:
        return self._plan is not None

    @property
    def busy_text(self) -> str:
        return {"preview": "Building preview...", "queue": "Queueing experiment..."}.get(
            self.busy or "", ""
        )

    @property
    def status_text(self) -> str:
        return self.message or self.busy_text

    def _inputs_fingerprint(self, source_image_path: str, form_data: Mapping[str, Any]) -> str:
        return json.dumps(
            {
                "source": source_image_path,
                "form": dict(form_data),
                "variable": self.variable_name,
                "candidates": list(self.candidates),
            },
            sort_keys=True,
            default=str,
        )

    def begin_preview(
        self, source_image_path: str, form_data: dict[str, Any]
    ) -> PreviewWork | None:
        """UI thread: claim the busy state and snapshot the inputs, or None with a reason."""

        if self.busy:
            self._set_message(f"{self.busy_text} Wait for it to finish.")
            return None
        self._clear_preview("")
        if not (self.enabled and self.available):
            self._set_message("Turn on 'Compare one control' first.")
            return None
        work = PreviewWork(
            token=self._token,
            source_image_path=source_image_path,
            form_data=copy.deepcopy(dict(form_data)),
            variable_name=self.variable_name,
            candidates=tuple(self.candidates),
            fingerprint=self._inputs_fingerprint(source_image_path, form_data),
        )
        self.busy = "preview"
        self._set_message("")
        return work

    def run_preview(self, work: PreviewWork) -> WorkOutcome:
        """Worker thread: only the plain snapshot is used; no session or Tk state is touched."""

        try:
            plan = self._build_preview(
                source_image_path=work.source_image_path,
                form_data=work.form_data,
                variable_name=work.variable_name,
                candidates=list(work.candidates),
            )
        except Exception as exc:  # the service explains why in operator language
            return WorkOutcome(error=str(exc))
        return WorkOutcome(value=plan)

    def finish_preview(
        self,
        work: PreviewWork,
        outcome: WorkOutcome,
        current_source_image_path: str,
        current_form_data: Mapping[str, Any],
    ) -> bool:
        """UI thread: accept the result only if no edit happened since ``begin_preview``."""

        self.busy = None
        if work.token != self._token or (
            self._inputs_fingerprint(current_source_image_path, current_form_data)
            != work.fingerprint
        ):
            self._clear_preview(
                "The form changed while the preview was building; build the preview again."
            )
            return False
        if outcome.error:
            self._set_message(f"Preview refused: {outcome.error}")
            return False
        self._plan = outcome.value
        self.preview = _preview_view(outcome.value)
        self._fingerprint = work.fingerprint
        self._set_message("Preview ready. Nothing is queued until you press Queue Experiment.")
        return True

    def build_preview(self, source_image_path: str, form_data: dict[str, Any]) -> bool:
        """Synchronous composition of the preview steps (the Tk panel runs them off-thread)."""

        work = self.begin_preview(source_image_path, form_data)
        if work is None:
            return False
        return self.finish_preview(work, self.run_preview(work), source_image_path, form_data)

    def invalidate_if_changed(self, source_image_path: str, form_data: Mapping[str, Any]) -> bool:
        """Drop a preview whose inputs no longer match the form; returns True when dropped."""

        if self._plan is None:
            return False
        if self._inputs_fingerprint(source_image_path, form_data) == self._fingerprint:
            return False
        self._clear_preview("The form changed after the preview; build the preview again.")
        return True

    def cancel_preview(self) -> None:
        if self.busy:
            return  # an outstanding worker finishes first; edits already make its result stale
        self._clear_preview("Preview canceled; nothing was queued.")

    def begin_queue(self, source_image_path: str, form_data: Mapping[str, Any]) -> QueueWork | None:
        """UI thread: claim the busy state for ONE admission of the current valid preview."""

        if self.busy:
            self._set_message(f"{self.busy_text} Wait for it to finish.")
            return None
        if self._plan is None:
            self._set_message("Build a valid preview first.")
            return None
        if self.invalidate_if_changed(source_image_path, form_data):
            return None
        self.busy = "queue"
        self._set_message("")
        return QueueWork(plan=self._plan)

    def run_queue(self, work: QueueWork) -> WorkOutcome:
        """Worker thread: re-verify, run the controlled-diff gate and admit once."""

        try:
            return WorkOutcome(value=self._submit_plan(work.plan))
        except Exception as exc:
            return WorkOutcome(error=str(exc))

    def finish_queue(self, work: QueueWork, outcome: WorkOutcome) -> list[str]:
        """UI thread: report the admission (or the refusal; nothing was queued)."""

        self.busy = None
        if outcome.error:
            self._clear_preview(f"Queue refused, nothing was queued: {outcome.error}")
            return []
        result = outcome.value
        self._clear_preview("")
        job_pairs = ", ".join(
            f"{label}={format_value(value)} -> {job_id}" for label, value, job_id in result.arms
        )
        self._set_message(
            f"Queued experiment {result.experiment_id} ({work.plan.variable_label}): {job_pairs}. "
            "Follow progress and results in Queue / History."
        )
        return list(result.job_ids)

    def queue(self, source_image_path: str, form_data: Mapping[str, Any]) -> list[str]:
        """Synchronous composition of the queue steps (the Tk panel runs them off-thread)."""

        work = self.begin_queue(source_image_path, form_data)
        if work is None:
            return []
        return self.finish_queue(work, self.run_queue(work))

    # ------------------------------------------------------------------ internals

    def _clear_preview(self, message: str) -> None:
        self._token += 1  # any in-flight preview result is now stale
        self._plan = None
        self.preview = None
        self._fingerprint = ""
        self._set_message(message)

    def _set_message(self, message: str) -> None:
        self.message = message
        if self._on_change is not None:
            self._on_change()


__all__ = [
    "BackgroundWorkRunner",
    "ExperimentPreviewView",
    "MAX_CANDIDATES",
    "PreviewWork",
    "QueueWork",
    "VideoExperimentSession",
    "WorkOutcome",
    "format_value",
]
