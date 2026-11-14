"""Closed lists and judge facts for advisory planning, read from the existing authorities (AI-210).

Models: the Prompt tab's model picker through ``prompt_ai_targets`` (explicit-capability, non-blocked, visibility filtered
choices), with each model's stages and blocking sentence from ``project_model_selection``. Workflows: the Video Workflow
controller's catalogue records (``list_workflow_specs``, with governance state) and its read-only ``workflow_preflight``
gates, which are the only input that is read off the GUI thread. Nothing is derived from the operator's goal text, and nothing
here can change a selection, a form or a job.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.ai_assist.contracts import VIDEO_STAGE
from src.gui.prompt_ai_targets import prompt_ai_targets
from src.gui_v2.ai_plan_advice import PlanFacts, Preflight, TargetFact, WorkflowFact
from src.gui_v2.model_policy_projection import project_model_selection
from src.image_backends.image_backend_types import configured_image_backend_id
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
    projection: Any,
    targets: tuple[tuple[str, str], ...],
    target_facts: dict[str, TargetFact],
    stages: tuple[str, ...],
) -> tuple[str, str, tuple[str, ...], str]:
    """``(id, label, stages, policy id)`` of the model selected in Pipeline, or empty values when it cannot anchor a plan.

    ``projection`` is the Prompt tab's ``_model_projection``: the model-policy projection of the Base Generation selection,
    the same object the "Prompt Target" header is built from. Only a selection that is one of the closed ``targets`` (so
    not blocked, not hidden by the visibility mode, with explicit capabilities) and supports an allowed image stage counts.
    Nothing is read from the goal text or the prompt.
    """

    name = str(getattr(projection, "model_name", "") or "")
    labels = dict(targets)
    fact = target_facts.get(name)
    if not name or name not in labels or fact is None:
        return "", "", (), ""
    supported = tuple(s for s in stages if s != VIDEO_STAGE and s in fact.stages)
    if not supported:
        return "", "", (), ""
    policy_id = str(getattr(getattr(projection, "policy", None), "policy_id", "") or "")
    return name, labels[name], supported, policy_id


def build_plan_snapshot(
    base_panel: Any, app_controller: Any, visibility_mode: str, selection: Any = None
) -> PlanSnapshot:
    """Read the closed lists and their facts now (GUI thread). Missing sources give empty lists, never invented ones.

    ``selection`` is the Prompt tab's current model projection (``tab._model_projection``); see ``_current_selection``.
    """

    targets = tuple(prompt_ai_targets(base_panel, visibility_mode))
    backend = configured_image_backend_id()
    target_facts: dict[str, TargetFact] = {}
    for key, label in targets:
        projection = project_model_selection(key, backend)
        target_facts[key] = TargetFact(label, tuple(projection.policy.stages), projection.blocking)
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
    stages = (
        *(GENERIC_IMAGE_STAGES if targets else ()),
        *((VIDEO_STAGE,) if workflows else ()),
    )
    current, label, supported, policy_id = _current_selection(
        selection, targets, target_facts, stages
    )
    facts = (
        PlanFacts(target_facts, workflow_facts, controller_preflight(video_controller), current)
        if video_controller is not None
        else PlanFacts(target_facts, workflow_facts, current_target=current)
    )
    return PlanSnapshot(
        targets, tuple(workflows), stages, facts, policy_id, current, label, supported
    )


__all__ = ["PlanSnapshot", "build_plan_snapshot", "controller_preflight"]
