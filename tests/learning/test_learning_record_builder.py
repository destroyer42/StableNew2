"""Learning record builder tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.learning.learning_record import LearningRecord
from src.learning.learning_record_builder import build_learning_record
from src.pipeline.pipeline_runner import PipelineRunResult
from src.pipeline.stage_sequencer import StageConfig, StageExecution, StageExecutionPlan


def _run_result_stub(run_id: str = "run-123") -> PipelineRunResult:
    stage_plan = StageExecutionPlan(
        stages=[
            StageExecution(
                stage_type="txt2img",
                config=StageConfig(enabled=True, payload={}, metadata={}),
                order_index=0,
                requires_input_image=False,
                produces_output_image=True,
            )
        ],
        run_id=run_id,
    )
    return PipelineRunResult(
        run_id=run_id,
        success=True,
        error=None,
        variants=[{"txt2img": {"model": "m", "sampler_name": "Euler", "steps": 10}}],
        learning_records=[],
        randomizer_mode="fanout",
        randomizer_plan_size=1,
        metadata={"timestamp": "t0"},
        stage_plan=stage_plan,
        stage_events=[
            {
                "stage": "txt2img",
                "phase": "exit",
                "image_index": 1,
                "total_images": 1,
                "cancelled": False,
            }
        ],
    )


@dataclass
class MinimalLearningConfig:
    prompt: str
    model: str
    sampler: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    metadata: dict[str, str] = field(default_factory=dict)
    config: dict[str, str | int | float] = field(default_factory=dict)
    variant_configs: list[dict[str, object]] = field(default_factory=list)
    randomizer_mode: str = ""
    randomizer_plan_size: int = 0
    base_model: str = ""


def test_learning_record_builder_basic_roundtrip():
    cfg = MinimalLearningConfig(
        prompt="p",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
        metadata={"user": "tester"},
        base_model="m",
        config={
            "model": "m",
            "sampler": "Euler",
            "steps": 20,
            "cfg_scale": 7.5,
            "width": 512,
            "height": 512,
        },
    )
    result = _run_result_stub()
    record = build_learning_record(cfg, result)
    assert isinstance(record, LearningRecord)
    assert record.run_id == result.run_id
    assert record.stage_plan == ["txt2img"]
    assert record.stage_events
    assert record.base_config["txt2img"]["model"] == "m"
    assert record.primary_model == "m"


def test_learning_record_builder_includes_compact_adaptive_refinement_metadata(tmp_path: Path):
    output_path = tmp_path / "output.png"
    output_path.write_bytes(b"not-a-real-image")
    cfg = MinimalLearningConfig(
        prompt="portrait woman",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
        base_model="m",
        config={"model": "m", "sampler": "Euler", "steps": 20, "cfg_scale": 7.5, "width": 512, "height": 512},
    )
    result = _run_result_stub("run-refine")
    result.variants = [{"path": str(output_path)}]
    result.metadata["adaptive_refinement"] = {
        "intent": {
            "mode": "full",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "algorithm_version": "v1",
        },
        "prompt_intent": {
            "intent_band": "portrait",
            "requested_pose": "profile",
            "wants_face_detail": True,
        },
        "decision_bundle": {
            "algorithm_version": "v1",
            "policy_id": "full_upscale_detail_v1",
            "detector_id": "null",
            "observation": {
                "subject_assessment": {
                    "scale_band": "small",
                    "pose_band": "profile",
                    "detection_count": 1,
                    "face_area_ratio": 0.14,
                }
            },
            "applied_overrides": {"upscale_steps": 18},
            "prompt_patch": {"add_positive": ["clear irises"]},
        },
        "image_decisions": [
            {"decision_bundle": {"policy_id": "full_upscale_detail_v1"}},
            {"decision_bundle": {"policy_id": "full_upscale_detail_v1"}},
        ],
    }

    record = build_learning_record(cfg, result)

    refinement = record.metadata["adaptive_refinement"]
    assert refinement["mode"] == "full"
    assert refinement["policy_id"] == "full_upscale_detail_v1"
    assert refinement["policy_ids"] == ["full_upscale_detail_v1"]
    assert refinement["scale_band"] == "small"
    assert refinement["pose_band"] == "profile"
    assert refinement["face_detected"] is True
    assert refinement["face_count"] == 1
    assert refinement["face_area_ratio"] == 0.14
    assert refinement["has_prompt_patch"] is True
    assert refinement["has_applied_overrides"] is True
    assert refinement["prompt_patch_ops"] == "add_positive"
    assert refinement["applied_override_keys"] == "upscale_steps"
    assert refinement["image_decision_count"] == 2


def test_learning_record_builder_includes_compact_secondary_motion_metadata() -> None:
    cfg = MinimalLearningConfig(
        prompt="portrait woman",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
        base_model="m",
        config={"model": "m", "sampler": "Euler", "steps": 20, "cfg_scale": 7.5, "width": 512, "height": 512},
    )
    result = _run_result_stub("run-motion")
    result.metadata["secondary_motion"] = {
        "summary": {
            "enabled": True,
            "status": "applied",
            "policy_id": "workflow_motion_v1",
            "application_path": "shared_postprocess_engine",
            "backend_mode": "apply_shared_postprocess_candidate",
            "intent": {"mode": "apply", "intent": "micro_sway"},
            "metrics": {"regions_applied": 2, "frames_in": 16, "frames_out": 16},
        }
    }

    record = build_learning_record(cfg, result)

    secondary_motion = record.metadata["secondary_motion"]
    assert secondary_motion["status"] == "applied"
    assert secondary_motion["policy_id"] == "workflow_motion_v1"
    assert secondary_motion["application_path"] == "shared_postprocess_engine"
