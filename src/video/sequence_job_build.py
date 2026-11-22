"""Build the one NJR of a Comfy sequence job: freeze segment 0's inputs and the typed plan, then the job (PR-VID-STORY-380).

The shared core of ``VideoSequenceControllerMixin.build_sequence_job`` (moved here unchanged) so the Storyboard
submission service admits its takes through exactly the same path. Every refusal happens before the NJR exists; nothing
is queued here. A storyboard take passes its ``StoryboardPlanLink`` (the plan becomes policy v2) and, when it continues
from a handoff frame, ``exact_source=True`` so segment 0 starts from that exact PNG rather than a prepared copy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.video.sequence_admission import freeze_sequence_plan
from src.video.sequence_plan import (
    STAGE_VIDEO_WORKFLOW,
    SequencePlan,
    SequencePlanError,
    StoryboardPlanLink,
)
from src.video.storyboard_cut import CutManifestError
from src.video.storyboard_readiness import unsupported_controls
from src.video.video_workflow_intent import EXPERIMENTAL_OPT_IN_FIELD
from src.video.video_workflow_njr_builder import (
    FrozenVideoInputs,
    VideoWorkflowBuild,
    VideoWorkflowNjrBuilder,
)
from src.video.workflow_frame_count import frame_count_policy


def build_sequence_njr(
    *,
    njr_builder: VideoWorkflowNjrBuilder,
    registry: Any,
    source_image_path: str,
    form_data: Mapping[str, Any],
    sequence_intent: Mapping[str, Any],
    continuity: Mapping[str, Any] | None = None,
    plan_origin: Mapping[str, Any] | None = None,
    storyboard: StoryboardPlanLink | None = None,
    exact_source: bool = False,
    check_frozen: Callable[[FrozenVideoInputs], None] | None = None,
    check_plan: Callable[[SequencePlan], None] | None = None,
) -> VideoWorkflowBuild:
    """Freeze the first segment's inputs and the typed plan, and build the one NJR; nothing is queued.

    ``check_frozen`` runs right after segment 0's inputs are frozen and ``check_plan`` right after the plan is frozen,
    both before the NJR is built; a caller with its own agreement checks (the linear Storyboard editor) raises there.
    """

    form = dict(form_data)
    controls = unsupported_controls(form)
    if controls:
        raise SequencePlanError(" ".join(controls))
    if (form.get("interpolation") or {}).get("enabled"):
        raise SequencePlanError(
            "RIFE smoothing is not applied inside a sequence; the sequence is assembled from each segment's "
            "original frames"
        )
    segments = sequence_intent.get("segments")
    first = segments[0] if isinstance(segments, (list, tuple)) and segments else {}
    if isinstance(first, Mapping):
        if first.get("seed") not in (None, ""):
            form["seed"] = first["seed"]
        if first.get("frame_count") not in (None, ""):
            form["frame_count"] = first["frame_count"]
    frozen = njr_builder.freeze_inputs(
        source_image_path, form, prompt_per_segment=True, exact_source=exact_source
    )
    lead_in = None if storyboard is None else storyboard.lead_in
    if exact_source and lead_in is not None and frozen.source_sha256 != lead_in.handoff_sha256:
        raise CutManifestError(
            f"the handoff frame changed since it was recorded: {frozen.source_image_path}"
        )
    if check_frozen is not None:
        check_frozen(frozen)
    spec = njr_builder.spec_for(form)
    policy = frame_count_policy(spec)
    if policy is None:
        raise SequencePlanError(
            f"workflow {spec.workflow_id} has no declared frame-count policy; it cannot run as a sequence"
        )
    dimensions = (frozen.source_preparation or {}).get("target_dimensions") or {}
    target = (
        (int(dimensions["width"]), int(dimensions["height"]))
        if dimensions.get("width") and dimensions.get("height")
        else None
    )
    plan = freeze_sequence_plan(
        sequence_intent,
        stage=STAGE_VIDEO_WORKFLOW,
        fps=int(policy["fps"]),
        base_prompt=str(form.get("prompt") or "").strip(),
        # The value the job really carries (a blank form negative becomes the workflow's default), so the plan
        # freezes what will be dispatched.
        base_negative_prompt=njr_builder.resolved_negative_prompt(spec, form),
        base_workflow=(spec.workflow_id, spec.workflow_version),
        registry=registry,
        target_size=target,
        segment_zero_seed=frozen.seed,
        experimental_opt_in=form.get(EXPERIMENTAL_OPT_IN_FIELD) is True,
        source={"path": frozen.prepared_source_path, "sha256": frozen.prepared_source_sha256},
        continuity=continuity,
        plan_origin=plan_origin,
        storyboard=storyboard,
    )
    if check_plan is not None:
        check_plan(plan)
    return njr_builder.build_job(form, frozen, sequence_plan=plan.to_dict())


__all__ = ["build_sequence_njr"]
