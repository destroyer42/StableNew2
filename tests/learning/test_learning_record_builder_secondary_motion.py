from __future__ import annotations

from dataclasses import dataclass, field

from src.learning.learning_record_builder import build_learning_record
from tests.learning.test_learning_record_builder import _run_result_stub


@dataclass
class _MinimalLearningConfig:
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


def test_learning_record_builder_secondary_motion_uses_top_level_backend_metadata() -> None:
    cfg = _MinimalLearningConfig(
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
    result = _run_result_stub("run-secondary-motion-learning")
    result.metadata.update(
        {
            "video_primary_backend_id": "comfy",
            "secondary_motion": {
                "summary": {
                    "enabled": True,
                    "status": "applied",
                    "policy_id": "workflow_motion_v1",
                    "application_path": "video_reencode_worker",
                    "backend_mode": "apply_shared_postprocess_candidate",
                    "intent": {"mode": "apply", "intent": "micro_sway"},
                    "metrics": {
                        "frames_in": 16,
                        "frames_out": 16,
                        "applied_frame_count": 12,
                        "intensity": 0.25,
                        "cap_pixels": 12,
                        "avg_abs_dx": 1.0,
                        "avg_abs_dy": 0.25,
                        "max_abs_dx": 2,
                        "max_abs_dy": 1,
                    },
                }
            },
            "secondary_motion_source_video_path": "clip.mp4",
        }
    )

    record = build_learning_record(cfg, result)

    secondary_motion = record.metadata["secondary_motion"]
    assert secondary_motion["backend_id"] == "comfy"
    assert secondary_motion["policy_id"] == "workflow_motion_v1"
    assert secondary_motion["application_path"] == "video_reencode_worker"
    assert secondary_motion["quality_risk_score"] > 0.0
    assert "secondary_motion_source_video_path" not in secondary_motion