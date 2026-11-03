"""Create new authoring intent only from a canonical frozen sequence snapshot, never from artifacts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.pipeline.njr_core_v26 import thaw_json
from src.video.sequence_plan import SequencePlan, default_overlap
from src.video.sequence_resume import PLAN_KEY, sequence_stage_name
from src.video.sequence_shots import ShotDraft
from src.video.storyboard import StoryboardDraft, StoryboardError


def from_history(repository: Any, job_id: str) -> StoryboardDraft:
    reader = getattr(repository, "get_job_model", None)
    if not callable(reader):
        raise StoryboardError(
            "Canonical job repository is unavailable; cached History rows are not sufficient."
        )
    job = reader(job_id)
    njr = getattr(job, "_normalized_record", None)
    if job is None or njr is None or str(job.job_id) != job_id or str(njr.job_id) != job_id:
        raise StoryboardError(
            "The canonical job or its frozen NJR is unavailable or has a different identity."
        )
    stage_name = sequence_stage_name(njr)
    stage = next(s for s in njr.stage_chain if s.stage_type == stage_name)
    config = thaw_json(stage.extra)
    plan = SequencePlan.from_dict(config.get(PLAN_KEY))
    errors = plan.validate()
    if errors:
        raise StoryboardError("Invalid frozen sequence: " + "; ".join(errors))
    if plan.backend != "comfy":
        raise StoryboardError(
            "Native SVD model/settings cannot be expressed by the Video Workflow editor; use its existing Resume/Replay actions."
        )
    if not plan.source:
        raise StoryboardError(
            "Frozen plan has no recorded source identity; a source will not be inferred."
        )
    if len(plan.segments) < 2:
        raise StoryboardError("This editor requires at least two recorded shots.")
    identities = {(s.workflow_id, s.workflow_version) for s in plan.segments}
    negatives = {s.negative_prompt for s in plan.segments}
    if len(identities) != 1 or len(negatives) != 1:
        raise StoryboardError(
            "The editor cannot safely project mixed workflows or per-shot negative prompts."
        )
    if (
        plan.color_match.enabled
        or not plan.assembly.enabled
        or any(
            s.overlap_frames != default_overlap(s.anchor_policy, i)
            for i, s in enumerate(plan.segments)
        )
        or plan.assembly.codec != "libx264"
        or plan.assembly.quality != "balanced"
    ):
        raise StoryboardError(
            "The frozen plan has custom assembly, overlap or color settings this editor cannot express."
        )
    workflow_id, workflow_version = next(iter(identities))
    draft = StoryboardDraft.new(f"Sequence {job_id}")
    return replace(
        draft,
        backend=plan.backend,
        workflow_id=workflow_id or "",
        workflow_version=workflow_version or "",
        source_path=str(plan.source["path"]),
        source_sha256=str(plan.source["sha256"]),
        shots=tuple(
            ShotDraft(
                prompt=s.prompt,
                frame_count=s.frame_count,
                seed=str(s.seed),
                keyframe_path=s.anchor_path or "",
                keyframe_sha256=s.anchor_sha256 or "",
            )
            for s in plan.segments
        ),
        settings=tuple(
            sorted(
                {
                    "negative_prompt": next(iter(negatives)),
                    "seed": str(plan.segments[0].seed),
                    "prompt": plan.segments[0].prompt,
                }.items()
            )
        ),
        clip_name=plan.assembly.clip_name,
        origin_job_id=job_id,
        origin_plan_digest=plan.plan_sha256(),
    )
