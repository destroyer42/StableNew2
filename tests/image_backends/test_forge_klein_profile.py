"""PR-IMG-116: the immutable FLUX.2 Klein 4B FP8 profile, its envelope, compile policy and readiness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.image_backends.forge_klein_profile import (
    KLEIN_PROFILE_ID,
    KLEIN_PROFILE_V1,
    KleinProfileError,
    apply_klein_compile_policy,
    detect_unsupported_features,
    is_klein_transformer_name,
    klein_edit_config,
    klein_selected,
    model_profile_for_model,
    resolve_model_profile,
    validate_klein_intent,
)
from src.image_backends.forge_klein_readiness import HostMemorySnapshot, check_klein_host_memory
from src.image_backends.image_backend_types import normalize_image_backend_options
from tests.helpers.njr_factory import make_pipeline_njr

REPO = Path(__file__).resolve().parents[2]
KLEIN = "flux-2-klein-4b-fp8.safetensors"
GOOD = {
    "backend_id": "forge_webui",
    "stage_names": ("txt2img",),
    "model_name": KLEIN,
    "sampler": "Euler",
    "scheduler": "Beta",
    "steps": 4,
    "cfg_scale": 1.0,
    "width": 768,
    "height": 1024,
    "negative_prompt": "",
}


def test_profile_pins_the_accepted_img115_assets_exactly() -> None:
    p = KLEIN_PROFILE_V1
    assert (p.profile_id, p.version, p.backend_id) == (KLEIN_PROFILE_ID, 1, "forge_webui")
    assert (p.transformer.filename, p.transformer.size) == (KLEIN, 4_070_624_520)
    assert p.transformer.sha256 == "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6"
    assert p.text_encoder.filename == "qwen_3_4b.safetensors"
    assert p.text_encoder.sha256 == "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a"
    assert p.vae.filename == "flux2-vae.safetensors"
    assert p.vae.sha256 == "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"
    assert p.text_encoder.revision == p.vae.revision == "5f526678002e43af5551dadb73ce2e8c91b43afe"
    assert (p.sampler, p.scheduler, p.steps, p.cfg_scale) == ("Euler", "Beta", 4, 1.0)
    assert p.geometries == ((768, 1024), (1024, 1024))
    assert [a.filename for a in p.modules] == ["qwen_3_4b.safetensors", "flux2-vae.safetensors"]
    assert "/" not in json.dumps(p.reference())  # no machine-local path in the persisted reference


def test_installer_manifest_matches_the_profile_hash_for_hash() -> None:
    manifest = json.loads((REPO / "config" / "forge_klein_assets.json").read_text(encoding="utf-8"))
    by_role = {entry["role"]: entry for entry in manifest["assets"]}
    for asset in KLEIN_PROFILE_V1.assets:
        entry = by_role[asset.role]
        assert (entry["filename"], entry["size"], entry["sha256"]) == (
            asset.filename,
            asset.size,
            asset.sha256,
        )
        assert (entry["models_subdir"], entry["repo"], entry["revision"]) == (
            asset.models_subdir,
            asset.repo,
            asset.revision,
        )


def test_profile_resolves_from_the_persisted_reference_and_fails_closed_otherwise() -> None:
    options = {"image": {"backend_id": "forge_webui", "model_profile": {"id": KLEIN_PROFILE_ID, "version": 1}}}
    assert resolve_model_profile(options) is KLEIN_PROFILE_V1
    assert resolve_model_profile({"image": {"backend_id": "forge_webui"}}) is None
    assert resolve_model_profile(None) is None
    for bad in (
        {"id": KLEIN_PROFILE_ID, "version": 2},
        {"id": "other", "version": 1},
        {"id": KLEIN_PROFILE_ID},
        "flux2_klein_4b_fp8",
    ):
        with pytest.raises(KleinProfileError):
            resolve_model_profile({"image": {"model_profile": bad}})


def test_klein_is_identified_by_exact_transformer_name_only() -> None:
    for name in (KLEIN, "flux-2-klein-4b-fp8", f"{KLEIN} [97ed34fe]", "C:\\m\\Stable-diffusion\\" + KLEIN):
        assert is_klein_transformer_name(name)
    for name in ("flux-2-klein-4b-fp8-bf16.safetensors", "flux-2-klein-9b-fp8.safetensors", "sdxl.safetensors", "", None):
        assert not is_klein_transformer_name(name)
    assert model_profile_for_model("sdxl.safetensors") is None
    assert model_profile_for_model(KLEIN) == {"id": KLEIN_PROFILE_ID, "version": 1}


def test_the_qualified_envelope_is_accepted() -> None:
    assert validate_klein_intent(KLEIN_PROFILE_V1, **GOOD) == "txt2img"
    assert validate_klein_intent(KLEIN_PROFILE_V1, **{**GOOD, "width": 1024, "height": 1024}) == "txt2img"
    edit = validate_klein_intent(KLEIN_PROFILE_V1, **{**GOOD, "stage_names": ("img2img",)})
    assert edit == "single_reference_edit"


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"steps": 30}, "steps 30 conflicts"),
        ({"cfg_scale": 7.0}, "CFG 7.0 conflicts"),
        ({"sampler": "DPM++ 2M"}, "sampler 'DPM++ 2M' conflicts"),
        ({"scheduler": "Karras"}, "scheduler 'Karras' conflicts"),
        ({"backend_id": "a1111_webui"}, "backend 'a1111_webui'"),
        ({"width": 832, "height": 1216}, "geometry 832x1216 is not qualified"),
        ({"width": 1024, "height": 768}, "geometry 1024x768 is not qualified"),
        ({"negative_prompt": "blurry"}, "negative prompt"),
        ({"stage_names": ("txt2img", "adetailer")}, "stage chain"),
        ({"stage_names": ("txt2img", "upscale")}, "stage chain"),
        ({"stage_names": ("txt2img", "img2img")}, "stage chain"),
        ({"model_name": "sdxl.safetensors"}, "not the qualified"),
        ({"unsupported_features": ["LoRA"]}, "LoRA is not supported"),
    ],
)
def test_conflicting_or_unsupported_intent_is_rejected_not_rewritten(override: dict, fragment: str) -> None:
    with pytest.raises(KleinProfileError, match="cannot run this work") as caught:
        validate_klein_intent(KLEIN_PROFILE_V1, **{**GOOD, **override})
    assert fragment in str(caught.value)


def test_every_conflict_is_reported_at_once() -> None:
    with pytest.raises(KleinProfileError) as caught:
        validate_klein_intent(KLEIN_PROFILE_V1, **{**GOOD, "steps": 30, "cfg_scale": 7.0, "width": 512})
    message = str(caught.value)
    assert "steps 30" in message and "CFG 7.0" in message and "geometry 512x1024" in message


def test_unsupported_features_are_detected_from_the_execution_config() -> None:
    assert detect_unsupported_features({"txt2img": {"hypernetwork": "None"}, "hires_fix": {"enabled": False}}) == []
    config = {
        "txt2img": {"enable_hr": True, "refiner_enabled": True, "hypernetwork": "x"},
        "hires_fix": {"enabled": True},
        "prompt_optimizer": {"enabled": True},
        "aesthetic": {"enabled": True},
        "style_lora": {"enabled": True},
        "controlnet_units": [1],
    }
    found = detect_unsupported_features(config, positive_prompt="a cat <lora:x:1>")
    assert {"hires fix", "refiner", "the prompt optimizer", "aesthetic embeddings", "LoRA", "ControlNet", "hypernetwork"} <= set(found)
    assert detect_unsupported_features({}, positive_prompt="a cat <lora:x:0.8>") == ["LoRA"]


def test_compile_policy_freezes_the_distilled_semantics_for_klein_only() -> None:
    config = {
        "txt2img": {"model": KLEIN, "sampler_name": "Euler a", "scheduler": "Normal", "steps": 20, "cfg_scale": 7.0, "negative_prompt": "blurry", "vae": "sdxl_vae"},
        "steps": 20,
        "prompt_optimizer": {"enabled": True, "dedupe_enabled": True},
        "pipeline": {"apply_global_negative_txt2img": True},
        "global_negative_prompt": "nsfw",
    }
    assert klein_selected(config)
    frozen = apply_klein_compile_policy(config)
    t = frozen["txt2img"]
    assert (t["sampler_name"], t["scheduler"], t["steps"], t["cfg_scale"], t["negative_prompt"], t["vae"]) == ("Euler", "Beta", 4, 1.0, "", "")
    assert frozen["steps"] == 4
    assert frozen["prompt_optimizer"] == {"enabled": False, "dedupe_enabled": True}
    assert frozen["pipeline"]["apply_global_negative_txt2img"] is False
    assert frozen["pipeline"]["apply_global_positive_txt2img"] is False
    assert (frozen["global_positive_prompt"], frozen["global_negative_prompt"]) == ("", "")
    assert frozen["backend_options"]["image"]["model_profile"] == {"id": KLEIN_PROFILE_ID, "version": 1}
    # geometry, hires and LoRA are not owned by the policy: conflicts remain visible to the validators
    assert "width" not in t and "enable_hr" not in t


def test_compile_policy_leaves_normal_models_untouched() -> None:
    config = {"txt2img": {"model": "sdxl.safetensors", "steps": 30, "cfg_scale": 7.0}, "prompt_optimizer": {"enabled": True}}
    before = json.dumps(config, sort_keys=True)
    assert apply_klein_compile_policy(config) is config
    assert json.dumps(config, sort_keys=True) == before
    assert not klein_selected(config)


def test_edit_config_is_the_proven_img2img_semantics_with_one_reference_and_no_stitch() -> None:
    config = klein_edit_config(width=768, height=1024)
    stage = config["img2img"]
    assert (stage["steps"], stage["cfg_scale"], stage["sampler_name"], stage["scheduler"]) == (4, 1.0, "Euler", "Beta")
    assert stage["denoising_strength"] == 1.0
    assert (config["width"], config["height"], config["negative_prompt"]) == (768, 1024, "")
    assert "ImageStitch" not in json.dumps(config)


def test_normalize_stamps_the_profile_only_for_klein_and_never_overwrites() -> None:
    stamped = normalize_image_backend_options(None, backend_id="forge_webui", model_name=KLEIN)
    assert stamped["image"] == {"backend_id": "forge_webui", "model_profile": {"id": KLEIN_PROFILE_ID, "version": 1}}
    plain = normalize_image_backend_options(None, backend_id="forge_webui", model_name="sdxl.safetensors")
    assert plain["image"] == {"backend_id": "forge_webui"}
    explicit = {"image": {"model_profile": {"id": KLEIN_PROFILE_ID, "version": 1}, "backend_id": "a1111_webui"}}
    assert normalize_image_backend_options(explicit, model_name="sdxl.safetensors")["image"]["model_profile"]["version"] == 1


def test_profile_reference_survives_njr_serialization_and_replay_identity() -> None:
    from src.pipeline.job_models_v2 import NormalizedJobRecord

    njr = make_pipeline_njr(
        job_id="klein-ser",
        backend_options={"image": {"backend_id": "forge_webui", "model_profile": {"id": KLEIN_PROFILE_ID, "version": 1}}},
    )
    payload = njr.to_dict()
    assert payload["workload"]["backend_options"]["image"]["model_profile"] == {"id": KLEIN_PROFILE_ID, "version": 1}
    restored = NormalizedJobRecord.from_dict(json.loads(json.dumps(payload)))
    assert resolve_model_profile(restored.backend_options) is KLEIN_PROFILE_V1


def _snapshot(total_gb: float, available_gb: float) -> HostMemorySnapshot:
    return HostMemorySnapshot(total_bytes=int(total_gb * 1e9), available_bytes=int(available_gb * 1e9))


def test_total_ram_below_the_32_gb_class_hard_fails() -> None:
    for total in (16.0, 25.0, 31.99):
        with pytest.raises(KleinProfileError, match="32-GB-class host"):
            check_klein_host_memory(KLEIN_PROFILE_V1, probe=lambda total=total: _snapshot(total, 20.0))


def test_the_threshold_is_decimal_32e9_bytes_not_32_gib_and_not_machine_specific() -> None:
    assert KLEIN_PROFILE_V1.min_total_ram_bytes == 32_000_000_000
    # a physically installed 32 GiB machine reports less than 32 GiB after hardware reservation: it must pass
    for total in (32_000_000_000, 34_107_092_992, 31_764_705_657 + 300_000_000):
        snapshot = HostMemorySnapshot(total_bytes=total, available_bytes=1_000_000_000)
        assert check_klein_host_memory(KLEIN_PROFILE_V1, probe=lambda snapshot=snapshot: snapshot).snapshot.total_bytes == total
    with pytest.raises(KleinProfileError):
        check_klein_host_memory(KLEIN_PROFILE_V1, probe=lambda: HostMemorySnapshot(total_bytes=31_999_999_999, available_bytes=20_000_000_000))


def test_currently_available_ram_never_blocks_or_warns_with_a_numeric_threshold() -> None:
    for available in (0.0, 0.5, 6.0, 30.0):
        readiness = check_klein_host_memory(KLEIN_PROFILE_V1, probe=lambda available=available: _snapshot(34.2, available))
        assert readiness.as_dict()["available_physical_gb"] == available  # recorded as evidence only
        assert "warnings" not in readiness.as_dict()
        assert readiness.as_dict()["available_ram_policy"] == "observational only; no floor"
