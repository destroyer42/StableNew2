"""Pipeline ADetailer configuration tests."""

from __future__ import annotations

from src.pipeline.stage_sequencer import build_stage_execution_plan


def _base_pipeline_config() -> dict[str, object]:
    return {
        "txt2img": {
            "enabled": True,
            "model": "demo",
            "sampler_name": "Euler a",
            "width": 512,
            "height": 512,
            "steps": 20,
            "cfg_scale": 7.5,
        },
        "pipeline": {
            "txt2img_enabled": True,
            "adetailer_enabled": False,
        },
        "adetailer": {
            "enabled": False,
        },
    }


def test_stage_plan_includes_adetailer_when_enabled() -> None:
    config = _base_pipeline_config()
    config["pipeline"]["adetailer_enabled"] = True  # type: ignore[index]
    config["adetailer"]["enabled"] = True  # type: ignore[index]

    plan = build_stage_execution_plan(config)

    assert any(stage.stage_type == "adetailer" for stage in plan.stages)


def test_stage_plan_excludes_adetailer_by_default() -> None:
    plan = build_stage_execution_plan(_base_pipeline_config())

    assert all(stage.stage_type != "adetailer" for stage in plan.stages)


def test_stage_plan_preserves_selected_model_and_detector() -> None:
    config = _base_pipeline_config()
    config["pipeline"]["adetailer_enabled"] = True  # type: ignore[index]
    config["adetailer"] = {
        "enabled": True,
        "adetailer_model": "face_yolov8n.pt",
        "detector": "face",
    }

    plan = build_stage_execution_plan(config)
    ad_stage = next((stage for stage in plan.stages if stage.stage_type == "adetailer"), None)
    assert ad_stage is not None
    payload = ad_stage.config.payload
    assert payload.get("adetailer_model") == "face_yolov8n.pt"
    assert payload.get("detector") == "face"
