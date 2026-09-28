from pathlib import Path

import pytest

from src.utils.config import ConfigManager


@pytest.fixture
def config_manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(presets_dir=tmp_path / "presets")


def test_presets_roundtrip_refiner_and_hires_defaults(config_manager: ConfigManager):
    custom_config = {
        "txt2img": {
            "refiner_enabled": True,
            "refiner_model_name": "sdxl_custom_refiner",
            "refiner_switch_at": 0.6,
        },
        "hires_fix": {
            "enabled": True,
            "upscaler_name": "ESRGAN 4x+",
            "upscale_factor": 3.0,
            "steps": 32,
            "denoise": 0.28,
            "use_base_model": False,
        },
    }
    assert config_manager.save_preset("test_refiner", custom_config)
    loaded = config_manager.load_preset("test_refiner")
    assert loaded is not None
    txt2img = loaded["txt2img"]
    assert txt2img["refiner_enabled"] is True
    assert txt2img["refiner_model_name"] == "sdxl_custom_refiner"
    assert abs(txt2img["refiner_switch_at"] - 0.6) < 1e-6
    hires = loaded["hires_fix"]
    assert hires["enabled"] is True
    assert hires["upscaler_name"] == "ESRGAN 4x+"
    assert hires["upscale_factor"] == 3.0
    assert hires["steps"] == 32
    assert abs(hires["denoise"] - 0.28) < 1e-6
    assert hires["use_base_model"] is False


def test_config_defaults_always_include_refiner_hires(config_manager: ConfigManager):
    config = config_manager._merge_config_with_defaults({})
    pipeline = config["pipeline"]
    assert pipeline["txt2img_enabled"] is True
    assert pipeline["img2img_enabled"] is False
    assert pipeline["adetailer_enabled"] is False
    assert pipeline["upscale_enabled"] is False
    assert config["txt2img"]["refiner_enabled"] is False
    assert config["txt2img"]["refiner_model_name"] == ""
    assert abs(config["txt2img"]["refiner_switch_at"] - 0.8) < 1e-6
    hires = config["hires_fix"]
    assert hires["upscaler_name"] == "Latent"
    assert hires["hires_upscale_factor"] == 2.0
    assert hires["denoise"] == 0.3
    assert hires["use_base_model"] is True


# --- PR-PACK-110: ADetailer stage-enablement persistence synchronization -----------------------


def test_defaults_merge_synchronizes_adetailer_enablement(config_manager: ConfigManager):
    """WP-PACK-AUDIT-100: pipeline.adetailer_enabled=True must not persist alongside
    adetailer.enabled=False after the defaults merge."""

    config = config_manager._merge_config_with_defaults({"pipeline": {"adetailer_enabled": True}})
    assert config["pipeline"]["adetailer_enabled"] is True
    assert config["adetailer"]["enabled"] is True
    assert config["adetailer"]["adetailer_enabled"] is True


def test_explicit_disabled_pipeline_intent_wins_over_stale_mirrors(config_manager: ConfigManager):
    """An explicit pipeline.adetailer_enabled=False must win over stale
    adetailer.enabled/adetailer_enabled=True mirrors, not merely the True case."""

    config = config_manager._merge_config_with_defaults(
        {
            "pipeline": {"adetailer_enabled": False},
            "adetailer": {"enabled": True, "adetailer_enabled": True},
        }
    )
    assert config["pipeline"]["adetailer_enabled"] is False
    assert config["adetailer"]["enabled"] is False
    assert config["adetailer"]["adetailer_enabled"] is False


def test_section_flag_fallback_when_pipeline_flag_genuinely_absent():
    """When pipeline.adetailer_enabled is absent (not merely defaulted), an explicit
    adetailer.enabled must be preserved and synchronized, not replaced by an
    unrelated default."""

    from src.utils.config import synchronize_adetailer_enablement

    result = synchronize_adetailer_enablement({"adetailer": {"enabled": True}})
    assert result["pipeline"]["adetailer_enabled"] is True
    assert result["adetailer"]["enabled"] is True
    assert result["adetailer"]["adetailer_enabled"] is True


def test_legacy_flag_fallback_when_no_stronger_representation_present():
    """The legacy adetailer.adetailer_enabled mirror is honored only when neither
    pipeline.adetailer_enabled nor adetailer.enabled is explicitly present."""

    from src.utils.config import synchronize_adetailer_enablement

    result = synchronize_adetailer_enablement({"adetailer": {"adetailer_enabled": True}})
    assert result["pipeline"]["adetailer_enabled"] is True
    assert result["adetailer"]["enabled"] is True
    assert result["adetailer"]["adetailer_enabled"] is True


def test_synchronize_helper_never_mutates_the_caller_config():
    from src.utils.config import synchronize_adetailer_enablement

    original = {"pipeline": {"adetailer_enabled": True}, "adetailer": {"enabled": False}}
    snapshot = {"pipeline": {"adetailer_enabled": True}, "adetailer": {"enabled": False}}
    synchronize_adetailer_enablement(original)
    assert original == snapshot


def test_synchronize_helper_invents_no_intent_when_nothing_explicit():
    from src.utils.config import synchronize_adetailer_enablement

    result = synchronize_adetailer_enablement({"txt2img": {"steps": 20}})
    assert "adetailer" not in result
    assert "pipeline" not in result


def test_other_stages_are_never_synchronized_by_the_adetailer_helper():
    """img2img/upscale/animatediff/video_workflow must pass through untouched even
    when they carry their own contradictory dual-representation-style values."""

    from src.utils.config import synchronize_adetailer_enablement

    config = {
        "pipeline": {"adetailer_enabled": True, "img2img_enabled": True, "upscale_enabled": False},
        "img2img": {"enabled": False},
        "upscale": {"enabled": True},
        "animatediff": {"enabled": True},
        "video_workflow": {"enabled": False},
    }
    result = synchronize_adetailer_enablement(config)
    assert result["pipeline"]["img2img_enabled"] is True
    assert result["pipeline"]["upscale_enabled"] is False
    assert result["img2img"]["enabled"] is False
    assert result["upscale"]["enabled"] is True
    assert result["animatediff"]["enabled"] is True
    assert result["video_workflow"]["enabled"] is False


def test_save_preset_roundtrip_synchronizes_adetailer_enablement(
    config_manager: ConfigManager, tmp_path: Path
):
    """Standalone saved recipe: reload the raw preset JSON directly (not through
    load_preset's own merge) and verify every representation agrees."""

    import json

    assert config_manager.save_preset(
        "ad_sync_test",
        {
            "pipeline": {"adetailer_enabled": True},
            "adetailer": {"enabled": False, "adetailer_enabled": False},
        },
    )
    raw = json.loads((config_manager.presets_dir / "ad_sync_test.json").read_text(encoding="utf-8"))
    assert raw["pipeline"]["adetailer_enabled"] is True
    assert raw["adetailer"]["enabled"] is True
    assert raw["adetailer"]["adetailer_enabled"] is True


def test_runtime_stage_plan_still_enables_adetailer_after_persistence_sync(
    config_manager: ConfigManager,
):
    """The synchronization must not accidentally disable ADetailer while making
    the metadata consistent: a canonical-enabled config still produces an
    enabled ADetailer stage in the execution plan after persistence/load."""

    from src.pipeline.stage_sequencer import build_stage_execution_plan

    assert config_manager.save_preset(
        "ad_runtime_test",
        {
            "pipeline": {"txt2img_enabled": True, "adetailer_enabled": True},
            "adetailer": {"enabled": False},
            "txt2img": {"model": "test.safetensors"},
        },
    )
    loaded = config_manager.load_preset("ad_runtime_test")
    assert loaded is not None
    assert loaded["adetailer"]["enabled"] is True  # sync proof

    plan = build_stage_execution_plan(loaded)
    adetailer_stages = [s for s in plan.stages if s.stage_type == "adetailer"]
    assert adetailer_stages, "ADetailer stage must still be admitted into the plan"
    assert adetailer_stages[0].config.enabled is True
