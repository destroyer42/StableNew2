"""Closed lists and judge facts for advisory planning, read from the existing authorities (AI-210).

Models: the Base Generation picker through ``prompt_ai_target_projections``, with eligibility and stages from the same
registry-backed checkpoint policy. Workflows: the Video Workflow
controller's catalogue records (``list_workflow_specs``, with governance state) and its read-only ``workflow_preflight``
gates, which are the only input that is read off the GUI thread. Nothing is derived from the operator's goal text, and nothing
here can change a selection, a form or a job.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.ai_assist.contracts import VIDEO_STAGE
from src.gui.prompt_ai_targets import prompt_ai_target_projections
from src.gui_v2.ai_plan_advice import PlanFacts, Preflight, TargetFact, WorkflowFact
from src.gui_v2.model_policy_projection import ModelControlProjection
from src.image_backends.model_policy import GENERIC_IMAGE_STAGES

_MAX_WORKFLOWS = 64


@dataclass(frozen=True, slots=True)
class PlanSnapshot:
    """Everything one plan request was built from, captured on the GUI thread."""

    targets: tuple[tuple[str, str], ...]
    workflows: tuple[tuple[str, str], ...]
    stages: tuple[str, ...]
    facts: PlanFacts
    target_policy_id: str = ""
    #: The operator's selected model when it is one of ``targets`` and supports an image stage (AI-211); otherwise empty,
    #: which the dialog states in one fixed sentence. The label and stages come from the same closed-list facts.
    current_target: str = ""
    current_target_label: str = ""
    current_target_stages: tuple[str, ...] = ()


def _gate_sentence(gate: Any) -> str:
    return f"{getattr(gate, 'label', '')}: {getattr(gate, 'detail', '')}".strip(": ")


def controller_preflight(video_controller: Any) -> Preflight:
    """Adapt ``VideoWorkflowController.workflow_preflight`` (safe on a worker thread) to the judge's shape."""

    def run(workflow_id: str, version: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        result = video_controller.workflow_preflight(workflow_id, version)
        gates = tuple(getattr(result, "gates", ()))
        blocked = tuple(_gate_sentence(g) for g in gates if getattr(g, "state", "") == "blocked")
        unknown = tuple(_gate_sentence(g) for g in gates if getattr(g, "state", "") == "unknown")
        return blocked, unknown

    return run


def _current_selection(
    selection: ModelControlProjection | None,
    targets: dict[str, tuple[str, ModelControlProjection]],
    stages: tuple[str, ...],
) -> tuple[str, str, tuple[str, ...], str]:
    """``(id, label, stages, policy id)`` of the model selected in Pipeline, or empty values when it cannot anchor a plan.

    ``selection`` is the Prompt tab's ``_model_projection``: the model-policy projection of the Base Generation selection,
    the same object the "Prompt Target" header is built from. Only a selection that is one of the closed ``targets`` (so
    not blocked, not hidden by the visibility mode, with explicit capabilities) and supports an allowed image stage counts.
    Nothing is read from the goal text or the prompt.
    """

    if selection is None or selection.blocking or selection.model_name not in targets:
        return "", "", (), ""
    label, candidate = targets[selection.model_name]
    if selection.policy != candidate.policy:
        return "", "", (), ""
    supported = tuple(s for s in stages if s != VIDEO_STAGE and s in candidate.policy.stages)
    if not supported:
        return "", "", (), ""
    return selection.model_name, label, supported, candidate.policy.policy_id


def build_plan_snapshot(
    base_panel: Any,
    app_controller: Any,
    visibility_mode: str,
    selection: ModelControlProjection | None = None,
) -> PlanSnapshot:
    """Read the closed lists and their facts now (GUI thread). Missing sources give empty lists, never invented ones.

    ``selection`` is the Prompt tab's current model projection (``tab._model_projection``); see ``_current_selection``.
    """

    candidates = prompt_ai_target_projections(base_panel, visibility_mode)
    targets = tuple((key, label) for key, (label, _projection) in candidates.items())
    target_facts = {
        key: TargetFact(label, projection.policy.stages, projection.blocking)
        for key, (label, projection) in candidates.items()
    }
    workflows: list[tuple[str, str]] = []
    workflow_facts: dict[str, WorkflowFact] = {}
    video_controller = None
    getter: Callable[[], Any] | None = getattr(
        app_controller, "get_video_workflow_controller", None
    )
    if callable(getter):
        video_controller = getter()
        for record in list(video_controller.list_workflow_specs())[:_MAX_WORKFLOWS]:
            workflow_id = str(record.get("workflow_id") or "")
            if not workflow_id or workflow_id in workflow_facts:
                continue
            label = str(record.get("display_name") or workflow_id)
            workflows.append((workflow_id, label))
            workflow_facts[workflow_id] = WorkflowFact(
                label,
                str(record.get("workflow_version") or ""),
                str(record.get("governance_state") or ""),
            )
    image_stages = {stage for fact in target_facts.values() for stage in fact.stages}
    stages = tuple(stage for stage in GENERIC_IMAGE_STAGES if stage in image_stages)
    if workflows:
        stages += (VIDEO_STAGE,)
    current, label, supported, policy_id = _current_selection(selection, candidates, stages)
    facts = (
        PlanFacts(target_facts, workflow_facts, controller_preflight(video_controller), current)
        if video_controller is not None
        else PlanFacts(target_facts, workflow_facts, current_target=current)
    )
    return PlanSnapshot(
        targets, tuple(workflows), stages, facts, policy_id, current, label, supported
    )


__all__ = ["PlanSnapshot", "build_plan_snapshot", "controller_preflight"]
