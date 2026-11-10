"""Operator tasks for the Video Workflow tab (PR-VID-UX-360).

A *task* is what the operator is trying to make.  It is a GUI-side intent only: it selects an engine and
suggests settings, and never reaches a submitted form, an NJR or a replay.

Pure functions over the plain workflow records ``VideoWorkflowController.list_workflow_specs`` returns.
Eligibility and choice read only what a record declares (governance state, form visibility, an admission
block reason); nothing here branches on a workflow id or a model family, and nothing is ever opted in or
routed silently: the chosen engine is returned with the reason it was chosen and whether it still needs
the job's own opt-in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.video.workflow_contracts import WORKFLOW_GOVERNANCE_APPROVED

TASK_ANIMATE = "animate"
TASK_FOLLOW_CLIP = "follow_clip"
TASK_SEQUENCE = "sequence"
TASK_BATCH = "batch"

NO_ENGINE_MESSAGE = "No installed workflow supports this."


@dataclass(frozen=True)
class VideoTask:
    task_id: str
    label: str
    description: str


TASKS: tuple[VideoTask, ...] = (
    VideoTask(
        TASK_ANIMATE,
        "Animate from a prompt",
        "Turn one image into a clip; the prompt describes the motion.",
    ),
    VideoTask(
        TASK_FOLLOW_CLIP,
        "Follow a driving clip",
        "Transfer the motion of a short video onto the character in the image.",
    ),
    VideoTask(
        TASK_SEQUENCE,
        "Multi-shot sequence",
        "Chain several shots into one longer clip, each with its own prompt and length.",
    ),
    VideoTask(
        TASK_BATCH,
        "Many images",
        "Queue the same settings for a set of images, one clip per image.",
    ),
)

_TASK_IDS = frozenset(task.task_id for task in TASKS)


@dataclass(frozen=True)
class EngineChoice:
    workflow_id: str
    reason: str
    needs_opt_in: bool
    block_reason: str


def _visibility(record: Mapping[str, Any]) -> Mapping[str, Any]:
    visible = record.get("form_visibility")
    return visible if isinstance(visible, Mapping) else {}


def _accepts_driving_clip(record: Mapping[str, Any]) -> bool:
    return bool(_visibility(record).get("pose_video", False))


def _is_approved(record: Mapping[str, Any]) -> bool:
    return str(
        record.get("governance_state") or ""
    ) == WORKFLOW_GOVERNANCE_APPROVED and not record.get("experimental")


def _block_reason(record: Mapping[str, Any]) -> str:
    projection = record.get("operator_projection")
    if not isinstance(projection, Mapping):
        return ""
    return str(projection.get("admission_block_reason") or "")


def _is_eligible(task_id: str, record: Mapping[str, Any]) -> bool:
    if not record.get("workflow_id"):
        return False
    if task_id == TASK_FOLLOW_CLIP:
        return _accepts_driving_clip(record)
    if _accepts_driving_clip(record):
        return False
    if task_id == TASK_SEQUENCE:
        return bool(_visibility(record).get("frame_count", False))
    return task_id in _TASK_IDS


def eligible_workflows(task_id: str, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The records that can serve ``task_id``, in catalog order."""

    return [dict(record) for record in records if _is_eligible(task_id, record)]


def _choice(record: Mapping[str, Any], reason: str) -> EngineChoice:
    return EngineChoice(
        workflow_id=str(record["workflow_id"]),
        reason=reason,
        needs_opt_in=not _is_approved(record),
        block_reason=_block_reason(record),
    )


def choose_workflow(
    task_id: str,
    records: Iterable[Mapping[str, Any]],
    pinned_workflow_id: str = "",
) -> EngineChoice | None:
    """The engine for ``task_id``: the operator's own eligible choice, else the first approved engine,
    else the first one that is not blocked, else the first one (with its block reason).  ``None`` when
    no installed workflow can serve the task."""

    eligible = eligible_workflows(task_id, records)
    if not eligible:
        return None
    if pinned_workflow_id:
        for record in eligible:
            if record["workflow_id"] == pinned_workflow_id:
                return _choice(record, "Your choice.")
    for record in eligible:
        if _is_approved(record):
            return _choice(record, "Recommended: approved for production.")
    for record in eligible:
        if not _block_reason(record):
            return _choice(
                record,
                "The only kind of engine for this task is experimental; it needs this job's opt-in.",
            )
    return _choice(eligible[0], "No engine for this task can run here yet.")


def infer_task(record: Mapping[str, Any] | None, saved_task: Any = None) -> str:
    """The task for a restored form: a saved task the engine can serve, else what the engine implies."""

    if record is None:
        return TASK_ANIMATE
    saved = str(saved_task or "")
    if saved in _TASK_IDS and _is_eligible(saved, record):
        return saved
    return TASK_FOLLOW_CLIP if _accepts_driving_clip(record) else TASK_ANIMATE


__all__ = [
    "NO_ENGINE_MESSAGE",
    "TASKS",
    "TASK_ANIMATE",
    "TASK_BATCH",
    "TASK_FOLLOW_CLIP",
    "TASK_SEQUENCE",
    "EngineChoice",
    "VideoTask",
    "choose_workflow",
    "eligible_workflows",
    "infer_task",
]
