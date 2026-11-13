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


def build_plan_snapshot(
    base_panel: Any, app_controller: Any, visibility_mode: str
) -> PlanSnapshot:
    """Read the closed lists and their facts now (GUI thread). Missing sources give empty lists, never invented ones."""

    targets = tuple(prompt_ai_targets(base_panel, visibility_mode))
    backend = configured_image_backend_id()
    target_facts: dict[str, TargetFact] = {}
    for key, label in targets:
        projection = project_model_selection(key, backend)
        target_facts[key] = TargetFact(
            label, tuple(projection.policy.stages), projection.blocking
        )
    workflows: list[tuple[str, str]] = []
    workflow_facts: dict[str, WorkflowFact] = {}
    video_controller = None
    getter: Callable[[], Any] | None = getattr(app_controller, "get_video_workflow_controller", None)
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
    facts = (
        PlanFacts(target_facts, workflow_facts, controller_preflight(video_controller))
        if video_controller is not None
        else PlanFacts(target_facts, workflow_facts)
    )
    return PlanSnapshot(targets, tuple(workflows), stages, facts)


__all__ = ["PlanSnapshot", "build_plan_snapshot", "controller_preflight"]
