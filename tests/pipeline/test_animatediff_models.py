from __future__ import annotations

from src.pipeline.animatediff_models import (
    AnimateDiffCapability,
    AnimateDiffConfig,
    attach_animatediff_to_payload,
    infer_animatediff_model_family,
    parse_animatediff_capability,
    resolve_animatediff_motion_module,
)


def test_parse_animatediff_capability_detects_script_and_motion_modules() -> None:
    payload = {
        "txt2img": [
            {
                "name": "AnimateDiff",
                "args": [
                    {
                        "label": "Motion module",
                        "choices": ["mm_sd_v15_v2.ckpt", "mm_sdxl_v10.ckpt"],
                    }
                ],
            }
        ]
    }

    capability = parse_animatediff_capability(payload)

    assert capability.available is True
    assert capability.script_name == "AnimateDiff"
    assert capability.motion_modules == ["mm_sd_v15_v2.ckpt", "mm_sdxl_v10.ckpt"]


def test_parse_animatediff_capability_returns_unavailable_when_missing() -> None:
    capability = parse_animatediff_capability({"txt2img": [{"name": "ADetailer", "args": []}]})

    assert capability.available is False
    assert "not reported" in (capability.reason or "")


def test_parse_animatediff_capability_detects_string_list_format() -> None:
    capability = parse_animatediff_capability(
        {"txt2img": ["adetailer", "animatediff"], "img2img": ["animatediff"]}
    )

    assert capability.available is True
    assert capability.script_name == "AnimateDiff"
    assert capability.motion_modules == []


def test_attach_animatediff_to_payload_adds_script_args() -> None:
    base_payload = {"prompt": "test"}
    config = AnimateDiffConfig.from_dict(
        {
            "enabled": True,
            "motion_module": "mm_sd_v15_v2.ckpt",
            "fps": 12,
            "video_length": 24,
            "closed_loop": "R-P",
        }
    )
    capability = AnimateDiffCapability(available=True, script_name="AnimateDiff")

    payload = attach_animatediff_to_payload(base_payload, config, capability)

    script = payload["alwayson_scripts"]["AnimateDiff"]["args"][0]
    assert payload["prompt"] == "test"
    assert script["enable"] is True
    assert script["model"] == "mm_sd_v15_v2.ckpt"
    assert script["fps"] == 12
    assert script["video_length"] == 24
    assert script["closed_loop"] == "R-P"


def test_infer_animatediff_model_family_detects_expected_families() -> None:
    assert infer_animatediff_model_family("realismFromHadesXL_2ndAnniversary") == "sdxl"
    assert infer_animatediff_model_family("mm_sdxl_hs.safetensors") == "sdxl"
    assert infer_animatediff_model_family("mm_sd15_v3.safetensors") == "sd15"


def test_resolve_animatediff_motion_module_prefers_sdxl_default_for_sdxl_models() -> None:
    config = AnimateDiffConfig.from_dict({"enabled": True})
    capability = AnimateDiffCapability(available=True, script_name="AnimateDiff", motion_modules=[])

    resolved = resolve_animatediff_motion_module(
        config,
        capability,
        "realismFromHadesXL_2ndAnniversary",
    )

    assert resolved == "mm_sdxl_hs.safetensors"


def test_resolve_animatediff_motion_module_prefers_matching_available_family() -> None:
    config = AnimateDiffConfig.from_dict({"enabled": True})
    capability = AnimateDiffCapability(
        available=True,
        script_name="AnimateDiff",
        motion_modules=["mm_sd15_v3.safetensors", "mm_sdxl_v10_beta.safetensors"],
    )

    resolved = resolve_animatediff_motion_module(
        config,
        capability,
        "realismFromHadesXL_2ndAnniversary",
    )

    assert resolved == "mm_sdxl_v10_beta.safetensors"
