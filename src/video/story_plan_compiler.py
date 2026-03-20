from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.video.continuity_models import prefer_continuity_link
from src.video.sequence_models import VideoSequenceJob
from src.video.story_plan_models import AnchorPlan, ScenePlan, ShotPlan, StoryPlan


def _safe_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in str(value))
    return safe.strip("_") or "unnamed"


def _sequence_id(plan: StoryPlan, scene: ScenePlan, shot: ShotPlan) -> str:
    return f"story_{_safe_id(plan.plan_id)}__scene_{_safe_id(scene.scene_id)}__shot_{_safe_id(shot.shot_id)}"


def _build_plan_origin(
    plan: StoryPlan,
    scene: ScenePlan,
    shot: ShotPlan,
    *,
    scene_index: int,
    shot_index: int,
) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "plan_display_name": plan.display_name,
        "scene_id": scene.scene_id,
        "scene_display_name": scene.display_name,
        "scene_index": scene_index,
        "shot_id": shot.shot_id,
        "shot_display_name": shot.display_name,
        "shot_index": shot_index,
    }


class StoryPlanCompiler:
    def compile(
        self,
        plan: StoryPlan,
        *,
        default_workflow_id: str | None = None,
    ) -> list[VideoSequenceJob]:
        compiled: list[VideoSequenceJob] = []

        for scene_index, scene in enumerate(plan.scenes):
            for shot_index, shot in enumerate(scene.shots):
                compiled.append(
                    self._compile_shot(
                        plan,
                        scene,
                        shot,
                        scene_index=scene_index,
                        shot_index=shot_index,
                        default_workflow_id=default_workflow_id,
                    )
                )
        return compiled

    def _compile_shot(
        self,
        plan: StoryPlan,
        scene: ScenePlan,
        shot: ShotPlan,
        *,
        scene_index: int,
        shot_index: int,
        default_workflow_id: str | None,
    ) -> VideoSequenceJob:
        workflow_id = shot.workflow_id or default_workflow_id
        if not workflow_id:
            raise ValueError(
                f"Shot '{shot.shot_id}' requires an explicit workflow_id or a compiler default"
            )

        anchor_list = list(shot.anchors)
        total_segments = max(int(shot.total_segments or 1), len(anchor_list), 1)
        base_source_image_path = anchor_list[0].source_image_path if anchor_list else None

        per_segment_overrides: list[dict[str, Any]] = []
        for index in range(total_segments):
            anchor = anchor_list[index] if index < len(anchor_list) else None
            per_segment_overrides.append(self._anchor_override(anchor))

        sequence_id = _sequence_id(plan, scene, shot)
        effective_continuity = prefer_continuity_link(
            shot.continuity_link,
            scene.continuity_link,
            plan.continuity_link,
        )

        return VideoSequenceJob(
            sequence_id=sequence_id,
            job_id=f"plan::{sequence_id}",
            workflow_id=workflow_id,
            total_segments=total_segments,
            segment_length_frames=int(shot.segment_length_frames or 0),
            overlap_frames=int(shot.overlap_frames or 0),
            carry_forward_policy=str(shot.carry_forward_policy or "none"),
            base_source_image_path=base_source_image_path,
            base_prompt=shot.prompt,
            base_negative_prompt=shot.negative_prompt,
            per_segment_overrides=per_segment_overrides,
            continuity_link=effective_continuity,
            plan_origin=_build_plan_origin(
                plan,
                scene,
                shot,
                scene_index=scene_index,
                shot_index=shot_index,
            ),
        )

    @staticmethod
    def _anchor_override(anchor: AnchorPlan | None) -> dict[str, Any]:
        if anchor is None:
            return {}

        override: dict[str, Any] = {
            "anchor_id": anchor.anchor_id,
            "anchor_display_name": anchor.display_name,
        }
        if anchor.source_image_path:
            override["source_image_path"] = anchor.source_image_path
        if anchor.prompt:
            override["prompt"] = anchor.prompt
        if anchor.negative_prompt:
            override["negative_prompt"] = anchor.negative_prompt
        if anchor.workflow_id:
            override["workflow_id"] = anchor.workflow_id
        if anchor.segment_length_frames is not None:
            override["segment_length_frames"] = int(anchor.segment_length_frames)
        if anchor.overlap_frames is not None:
            override["overlap_frames"] = int(anchor.overlap_frames)
        if anchor.metadata:
            override["anchor_metadata"] = dict(anchor.metadata)
        return override


__all__ = ["StoryPlanCompiler"]