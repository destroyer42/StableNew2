"""Toolkit-neutral state for the Video Workflow "Compare one control" section (PR-VID-194).

The session holds only transient, unsaved form state: whether comparing is on, which declared
control is under test, the candidate texts and the most recent preview.  It owns no experiment
authority: previewing and queueing are delegated to injected callables (the Video Workflow
controller), and it never builds a backend payload, touches the queue or names a workflow/model.
The control list comes exclusively from the selected workflow's ``operator_controls`` projection.
"""

from __future__ import annotations

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

    @property
    def preview_valid(self) -> bool:
        return self._plan is not None

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

    def build_preview(self, source_image_path: str, form_data: dict[str, Any]) -> bool:
        """Non-generating: freeze a baseline and build every arm; never queues anything."""

        self._clear_preview("")
        if not (self.enabled and self.available):
            self._set_message("Turn on 'Compare one control' first.")
            return False
        try:
            plan = self._build_preview(
                source_image_path=source_image_path,
                form_data=form_data,
                variable_name=self.variable_name,
                candidates=list(self.candidates),
            )
        except Exception as exc:  # the service explains why in operator language
            self._set_message(f"Preview refused: {exc}")
            return False
        self._plan = plan
        self.preview = _preview_view(plan)
        self._fingerprint = self._inputs_fingerprint(source_image_path, form_data)
        self._set_message("Preview ready. Nothing is queued until you press Queue Experiment.")
        return True

    def invalidate_if_changed(self, source_image_path: str, form_data: Mapping[str, Any]) -> bool:
        """Drop a preview whose inputs no longer match the form; returns True when dropped."""

        if self._plan is None:
            return False
        if self._inputs_fingerprint(source_image_path, form_data) == self._fingerprint:
            return False
        self._clear_preview("The form changed after the preview; build the preview again.")
        return True

    def cancel_preview(self) -> None:
        self._clear_preview("Preview canceled; nothing was queued.")

    def queue(self, source_image_path: str, form_data: Mapping[str, Any]) -> list[str]:
        """Queue the previewed experiment (one admission) or return [] with a reason."""

        if self._plan is None:
            self._set_message("Build a valid preview first.")
            return []
        if self.invalidate_if_changed(source_image_path, form_data):
            return []
        plan = self._plan
        try:
            result = self._submit_plan(plan)
        except Exception as exc:
            self._clear_preview(f"Queue refused, nothing was queued: {exc}")
            return []
        self._clear_preview("")
        job_pairs = ", ".join(
            f"{label}={format_value(value)} -> {job_id}" for label, value, job_id in result.arms
        )
        self._set_message(
            f"Queued experiment {result.experiment_id} ({plan.variable_label}): {job_pairs}. "
            "Follow progress and results in Queue / History."
        )
        return list(result.job_ids)

    # ------------------------------------------------------------------ internals

    def _clear_preview(self, message: str) -> None:
        self._plan = None
        self.preview = None
        self._fingerprint = ""
        self._set_message(message)

    def _set_message(self, message: str) -> None:
        self.message = message
        if self._on_change is not None:
            self._on_change()


__all__ = ["ExperimentPreviewView", "MAX_CANDIDATES", "VideoExperimentSession", "format_value"]
