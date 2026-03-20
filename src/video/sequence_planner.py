"""Sequence planner for multi-segment long-form video.

PR-VIDEO-216: Produces a deterministic list of VideoSegmentPlan from a
VideoSequenceJob.  The plan is fully determined at plan-time; only the
`source_image_path` for carry-forward segments is resolved at runtime via
``apply_carry_forward``.
"""

from __future__ import annotations

import hashlib
from typing import Any

from src.video.sequence_models import (
    CarryForwardPolicy,
    VideoSegmentPlan,
    VideoSequenceJob,
)


def _segment_id(sequence_id: str, index: int) -> str:
    """Deterministic, short segment identifier.

    The same (sequence_id, index) pair always yields the same id,
    enabling safe replay and de-duplication.
    """
    raw = f"{sequence_id}:seg:{index:04d}"
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:12]


class VideoSequencePlanner:
    """Translates a VideoSequenceJob into an ordered list of VideoSegmentPlan."""

    # Policies where the anchor image is known at plan-time.
    _STATIC_SOURCE_POLICIES: frozenset[CarryForwardPolicy] = frozenset(
        {"first_frame", "provided", "none"}
    )

    def plan(self, seq_job: VideoSequenceJob) -> list[VideoSegmentPlan]:
        """Return deterministic per-segment plans for *seq_job*.

        Rules:
        - ``first_frame``: every segment uses the same base source image.
        - ``last_frame``: segment 0 uses base source; segments 1+ have
          ``source_image_path=None`` until ``apply_carry_forward`` fills it in.
        - ``provided``: per-segment override must supply ``source_image_path``;
          base source is used as fallback for segment 0.
        - ``none``: no anchor image on any segment.
        """
        if seq_job.total_segments < 1:
            raise ValueError(
                f"total_segments must be >= 1, got {seq_job.total_segments}"
            )

        plans: list[VideoSegmentPlan] = []
        policy = seq_job.carry_forward_policy

        for idx in range(seq_job.total_segments):
            overrides: dict[str, Any] = {}
            if idx < len(seq_job.per_segment_overrides):
                overrides = seq_job.per_segment_overrides[idx] or {}

            source_image_path = self._resolve_source(seq_job, policy, idx, overrides)
            prompt = overrides.get("prompt") or seq_job.base_prompt
            negative_prompt = overrides.get("negative_prompt") or seq_job.base_negative_prompt
            workflow_id = overrides.get("workflow_id") or seq_job.workflow_id

            # Extra: everything in overrides that is not a known top-level field.
            _reserved = {
                "prompt",
                "negative_prompt",
                "workflow_id",
                "source_image_path",
                "segment_length_frames",
                "overlap_frames",
            }
            extra = {k: v for k, v in overrides.items() if k not in _reserved}

            plans.append(
                VideoSegmentPlan(
                    segment_index=idx,
                    segment_id=_segment_id(seq_job.sequence_id, idx),
                    source_image_path=source_image_path,
                    carry_forward_policy=policy,
                    overlap_frames=overrides.get(
                        "overlap_frames", seq_job.overlap_frames
                    ),
                    segment_length_frames=overrides.get(
                        "segment_length_frames", seq_job.segment_length_frames
                    ),
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    workflow_id=workflow_id,
                    extra=extra,
                )
            )
        return plans

    # ------------------------------------------------------------------
    # Runtime helpers
    # ------------------------------------------------------------------

    def apply_carry_forward(
        self,
        segment_plan: VideoSegmentPlan,
        *,
        prior_output_path: str,
    ) -> VideoSegmentPlan:
        """Return a new plan with ``source_image_path`` filled in from the
        prior segment's primary output.

        Only meaningful for ``last_frame`` policy segments after the first one.
        For all other policies's this returns the plan unchanged.
        """
        if (
            segment_plan.carry_forward_policy == "last_frame"
            and segment_plan.segment_index > 0
            and segment_plan.source_image_path is None
        ):
            return VideoSegmentPlan(
                segment_index=segment_plan.segment_index,
                segment_id=segment_plan.segment_id,
                source_image_path=prior_output_path,
                carry_forward_policy=segment_plan.carry_forward_policy,
                overlap_frames=segment_plan.overlap_frames,
                segment_length_frames=segment_plan.segment_length_frames,
                prompt=segment_plan.prompt,
                negative_prompt=segment_plan.negative_prompt,
                workflow_id=segment_plan.workflow_id,
                extra=dict(segment_plan.extra),
            )
        return segment_plan

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_source(
        self,
        seq_job: VideoSequenceJob,
        policy: CarryForwardPolicy,
        idx: int,
        overrides: dict[str, Any],
    ) -> str | None:
        if policy == "none":
            return None
        if policy == "first_frame":
            return seq_job.base_source_image_path
        if policy == "last_frame":
            # Segment 0 uses the base; later segments resolved at runtime.
            return seq_job.base_source_image_path if idx == 0 else None
        if policy == "provided":
            # Per-segment override is authoritative; fall back to base for seg 0.
            return overrides.get("source_image_path") or (
                seq_job.base_source_image_path if idx == 0 else None
            )
        return None
