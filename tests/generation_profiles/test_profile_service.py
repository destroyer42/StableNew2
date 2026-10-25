"""Profile application planning, the session service and startup defaults (PR-IMG-PROFILE-630). No Tk, no runtime."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.generation_profiles.application import (
    NOTE_NOT_OFFERED,
    NOTE_POLICY,
    NOTE_RESET,
    NOTE_UNAVAILABLE,
    STATUS_APPLIED,
    STATUS_NO_PROFILE,
    STATUS_PROFILE_MISSING,
)
from src.generation_profiles.contract import KIND_CUSTOM, KIND_RESEARCH, ProfileError, ProfileRef
from src.generation_profiles.identity import ModelIdentityResolver
from src.generation_profiles.research import KLEIN_RESEARCH_ID, SDXL_RESEARCH_ID
from src.generation_profiles.service import GenerationProfileService
from src.generation_profiles.startup import (
    STARTUP_SCHEMA,
    StartupDefaults,
    build_startup_defaults,
    plan_startup_restore,
    sanitize_stage_settings,
)
from src.generation_profiles.store import GenerationProfileStore
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1

SDXL_MODEL = "juggernaut.safetensors"
OTHER_SDXL = "pony.safetensors"
SD15_MODEL = "sd15.safetensors"
KLEIN = KLEIN_PROFILE_V1.transformer.filename
ZIMAGE = ZIMAGE_PROFILE_V1.transformer.filename


def _compat(family: str):
    return SimpleNamespace(
        status=SimpleNamespace(value="resolved"),
        family=SimpleNamespace(value=family),
        checkpoint_architecture=None,
        structural_error=None,
    )


FAMILIES = {SDXL_MODEL: "sdxl", OTHER_SDXL: "sdxl", SD15_MODEL: "sd1"}


def _service(tmp_path: Path) -> GenerationProfileService:
    resolver = ModelIdentityResolver(
        family_lookup=lambda name: _compat(FAMILIES[name]) if name in FAMILIES else None,
        sha_lookup=lambda name: None,
    )
    return GenerationProfileService(GenerationProfileStore(tmp_path / "store"), resolver)


WORKING = {
    "sampler_name": "DPM++ 2M",
    "scheduler": "Karras",
    "steps": 30,
    "cfg_scale": 7.0,
    "width": 768,
    "height": 768,
    "vae": "sdxl_vae.safetensors",
}


def test_sdxl_model_switch_applies_only_sourced_geometry_and_reports_unavailable(
    tmp_path: Path,
) -> None:
    plan, state = _service(tmp_path).on_model_changed(SDXL_MODEL, WORKING)
    assert plan.status == STATUS_APPLIED and plan.profile.profile_id == SDXL_RESEARCH_ID
    assert dict(plan.changes) == {
        "width": 1024,
        "height": 1024,
    }  # nothing invented for sampler / steps / cfg
    for key in ("sampler_name", "scheduler", "steps", "cfg_scale"):
        assert plan.note_for(key).status in (NOTE_UNAVAILABLE,)
    assert state.selected == plan.profile and not state.modified


def test_exact_model_policy_remains_final_for_fixed_controls(tmp_path: Path) -> None:
    plan, state = _service(tmp_path).on_model_changed(KLEIN, WORKING)
    # the executable profile owns these values; the profile never writes them and says why
    assert set(plan.changes) <= {"width", "height"}  # only the qualified geometry the policy allows
    assert not state.modified  # values the policy owns never make a profile look edited
    assert {
        n.status for n in plan.notes if n.key in ("sampler_name", "scheduler", "steps", "cfg_scale")
    } == {NOTE_POLICY}
    assert state.selected.profile_id == KLEIN_RESEARCH_ID


def test_never_carries_a_vae_across_families_or_a_sampler_the_runtime_lacks(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.on_model_changed(SDXL_MODEL, WORKING)
    working = {**WORKING, "width": 1024, "height": 1024}
    plan, _ = service.on_model_changed(
        SD15_MODEL, working, catalogs={"samplers": ["Euler a"], "schedulers": ["Automatic"]}
    )
    assert plan.status == STATUS_NO_PROFILE
    assert plan.changes["vae"] == "" and plan.note_for("vae").status == NOTE_RESET
    assert (
        plan.note_for("sampler_name").status == NOTE_NOT_OFFERED
    )  # disclosed, not silently rewritten
    assert "sampler_name" not in plan.changes
    # staying inside one family keeps the VAE
    stay = _service(tmp_path / "same-family")
    stay.on_model_changed(SDXL_MODEL, WORKING)
    same, _ = stay.on_model_changed(OTHER_SDXL, working)
    assert "vae" not in same.changes
    # ...and "no VAE recommendation" for the new family is not permission to keep another family's VAE
    stay.on_model_changed(KLEIN, WORKING)
    back, _ = stay.on_model_changed(SDXL_MODEL, {**WORKING, "vae": "klein_ae.safetensors"})
    assert back.changes["vae"] == "" and any(
        n.key == "vae" and n.status == NOTE_RESET for n in back.notes
    )


def test_unknown_model_gets_no_profile_and_keeps_settings(tmp_path: Path) -> None:
    plan, state = _service(tmp_path).on_model_changed("mystery.safetensors", WORKING)
    assert plan.status == STATUS_NO_PROFILE and not plan.changes
    assert state.options == () and state.unverified_reason


def test_profile_application_never_carries_stage_enablement(tmp_path: Path) -> None:
    plan, _ = _service(tmp_path).on_model_changed(
        SDXL_MODEL, {**WORKING, "adetailer_enabled": False}
    )
    assert not any("enabled" in key for key in plan.changes)


def test_custom_profile_is_saved_selected_restorable_and_policy_values_excluded(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    working = {**WORKING, "width": 1024, "height": 1024}
    saved = service.save_custom("Daily", SDXL_MODEL, working)
    assert saved.kind == KIND_CUSTOM and saved.settings["steps"] == 30
    changed = {**working, "steps": 12}
    state = service.state_for(SDXL_MODEL, changed)
    assert state.selected == saved.ref and state.modified
    plan, state2 = service.restore_selected(SDXL_MODEL, changed)
    assert plan.changes["steps"] == 30 and not state2.modified
    klein_saved = service.save_custom("Klein mine", KLEIN, WORKING)
    assert (
        set(klein_saved.settings) <= {"vae", "width", "height"}
        and "steps" not in klein_saved.settings
    )
    assert klein_saved.unavailable["steps"]


def test_favorite_becomes_preferred_and_a_missing_favorite_falls_back_with_disclosure(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    saved = service.save_custom("Fav", SDXL_MODEL, {**WORKING, "width": 1024, "height": 1024})
    service.set_favorite(SDXL_MODEL, saved.ref)
    other = _service(tmp_path)  # a new session reads the same store
    plan, _ = other.on_model_changed(SDXL_MODEL, {**WORKING, "steps": 5})
    assert plan.profile.profile_id == saved.profile_id and plan.changes["steps"] == 30
    other.delete_custom(saved.profile_id)
    plan2, _ = other.on_model_changed(SDXL_MODEL, WORKING)
    assert plan2.profile.profile_id == SDXL_RESEARCH_ID  # research is the explicit fallback
    plain = GenerationProfileStore(tmp_path / "store")
    plain.set_favorite("model:sdxl:ghost", ProfileRef(KIND_CUSTOM, "gone"))
    ghost_plan, _ = _service(tmp_path).select(SDXL_MODEL, ProfileRef(KIND_CUSTOM, "gone"), WORKING)
    assert ghost_plan.status == STATUS_PROFILE_MISSING and not ghost_plan.changes


def test_a_profile_for_another_model_is_refused(tmp_path: Path) -> None:
    service = _service(tmp_path)
    saved = service.save_custom("Only A", SDXL_MODEL, WORKING)
    plan, _ = service.select(OTHER_SDXL, saved.ref, WORKING)
    assert plan.status == "identity_conflict" and not plan.changes
    with pytest.raises(ProfileError):
        service.set_favorite(OTHER_SDXL, saved.ref)


def test_research_profiles_cannot_be_modified_through_the_service(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ProfileError):
        service.save_custom(
            "x", SDXL_MODEL, WORKING, update_ref=ProfileRef(KIND_RESEARCH, SDXL_RESEARCH_ID, 1)
        )


# ---------------------------------------------------------------- startup defaults


STAGE_SETTINGS = {
    "txt2img": {"steps": 30, "model_path": "C:/models/x.safetensors", "negative_prompt": "bad"},
    "img2img": {
        "denoising_strength": 0.4,
        "input_image_path": "C:/in/a.png",
        "mask": "m.png",
        "init_images": ["a.png"],
    },
    "adetailer": {"model": "face_yolov8n.pt", "enabled": False},
    "upscale": {"upscaler": "R-ESRGAN 4x+", "scale": 2.0, "result_dir": "C:/out"},
    "learning": {"experiment_id": "e1"},
}


def test_startup_defaults_keep_settings_and_exclude_inputs_results_and_experiments(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    flags = {"txt2img": True, "img2img": False, "adetailer": False, "upscale": True, "bogus": True}
    record = service.save_startup_defaults(
        SDXL_MODEL, {**WORKING, "width": 1024, "height": 1024, "seed": 5}, flags, STAGE_SETTINGS
    )
    document = json.loads(
        (tmp_path / "store" / "startup_defaults.json").read_text(encoding="utf-8")
    )
    assert document["schema_version"] == STARTUP_SCHEMA and document["model_name"] == SDXL_MODEL
    assert document["generation"]["steps"] == 30 and "seed" not in document["generation"]
    assert document["stage_flags"] == {
        "txt2img": True,
        "img2img": False,
        "adetailer": False,
        "upscale": True,
    }
    blob = json.dumps(document["stage_settings"])
    for forbidden in (
        "model_path",
        "input_image_path",
        "mask",
        "init_images",
        "result_dir",
        "experiment_id",
        "learning",
        ".png",
        "C:/",
    ):
        assert forbidden not in blob
    assert document["stage_settings"]["upscale"] == {"upscaler": "R-ESRGAN 4x+", "scale": 2.0}
    assert StartupDefaults.from_document(document) == record


def test_save_failure_is_reported_and_leaves_previous_defaults(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path)
    service.save_startup_defaults(SDXL_MODEL, WORKING, {"txt2img": True}, {})
    import src.generation_profiles.store as store_module

    monkeypatch.setattr(
        store_module,
        "atomic_write_json",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only disk")),
    )
    with pytest.raises(ProfileError, match="read-only disk"):
        service.save_startup_defaults(SDXL_MODEL, {**WORKING, "steps": 99}, {"txt2img": True}, {})
    assert service.startup_defaults().generation["steps"] == 30


def test_startup_restore_applies_saved_values_and_remembers_the_profile(tmp_path: Path) -> None:
    service = _service(tmp_path)
    saved = service.save_custom("Daily", SDXL_MODEL, {**WORKING, "width": 1024, "height": 1024})
    service.save_startup_defaults(
        SDXL_MODEL,
        {**WORKING, "width": 1024, "height": 1024},
        {"txt2img": True, "adetailer": False},
        {},
    )
    fresh = _service(tmp_path)
    defaults, plan = fresh.plan_startup(available_models=[SDXL_MODEL, OTHER_SDXL])
    assert plan.model_name == SDXL_MODEL and plan.profile == saved.ref
    assert plan.stage_flags == {"txt2img": True, "adetailer": False}
    assert fresh.state_for(SDXL_MODEL).selected == saved.ref


def test_startup_restore_reports_missing_model_and_unavailable_values_without_substituting(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.save_startup_defaults(SDXL_MODEL, WORKING, {"txt2img": True}, {})
    fresh = _service(tmp_path)
    _, missing = fresh.plan_startup(available_models=[OTHER_SDXL])
    assert (
        missing.model_name is None
        and "not available" in missing.issues[0]
        and not missing.generation
    )
    _, partial = fresh.plan_startup(
        available_models=[SDXL_MODEL],
        catalogs={
            "samplers": ["Euler"],
            "schedulers": ["Karras"],
            "vaes": ["sdxl_vae.safetensors"],
        },
    )
    assert "sampler_name" not in partial.generation and partial.generation["scheduler"] == "Karras"
    assert any("DPM++ 2M" in issue for issue in partial.issues)


def test_corrupt_or_future_startup_document_is_ignored_safely(tmp_path: Path) -> None:
    service = _service(tmp_path)
    folder = tmp_path / "store"
    folder.mkdir(parents=True)
    (folder / "startup_defaults.json").write_text("{broken", encoding="utf-8")
    assert service.startup_defaults() is None
    (folder / "startup_defaults.json").write_text(
        json.dumps({"schema_version": 9}), encoding="utf-8"
    )
    assert service.startup_defaults() is None and service.plan_startup(available_models=None) == (
        None,
        None,
    )


def test_startup_does_not_scan_or_launch_anything() -> None:
    identity = (
        ModelIdentityResolver(family_lookup=lambda n: None, sha_lookup=lambda n: None)
        .resolve(SDXL_MODEL)
        .identity
    )
    assert (
        "available_models" in plan_startup_restore.__code__.co_varnames
    )  # pure: callers pass what is installed
    record = build_startup_defaults(
        model_name=SDXL_MODEL,
        model=identity,
        profile=None,
        generation={},
        stage_flags={},
        stage_settings={},
    )
    assert record.model_name == SDXL_MODEL


def test_sanitizer_drops_nested_paths_images_and_unserialisable_values() -> None:
    clean = sanitize_stage_settings(
        {
            "a": {"image_path": "x", "ok": 1, "weights_file": "w", "refs": ["z.png", "keep"]},
            "obj": object(),
        }
    )
    assert clean == {"a": {"ok": 1, "refs": ["keep"]}}
