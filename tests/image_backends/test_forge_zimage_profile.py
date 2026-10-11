"""IMG155 deterministic exact-profile, compiler and served-byte contracts; no runtime/GPU."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.image_backends.exact_model_profile import model_profile_for_model, resolve_model_profile
from src.image_backends.forge_klein_assets import verify_zimage_assets
from src.image_backends.forge_klein_profile import (
    KLEIN_PROFILE_V1,
    KLEIN_PROFILE_V2,
    KleinProfileError,
)
from src.image_backends.forge_klein_readiness import HostMemorySnapshot, check_klein_host_memory
from src.image_backends.forge_zimage_profile import (
    ZIMAGE_PROFILE_V1 as P,
)
from src.image_backends.forge_zimage_profile import (
    ZImageProfileError,
    apply_zimage_compile_policy,
    is_zimage_transformer_name,
    project_zimage_wire_payload,
    validate_zimage_njr,
)
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_policy import resolve_model_policy
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import NormalizedJobRecord


def config(**changes):
    return {
        "model": P.transformer.filename, "prompt": "A ceramic teapot on a wooden table.", "seed": 42,
        "sampler": "Euler", "sampler_name": "Euler", "scheduler": "Beta", "steps": 9,
        "cfg_scale": 1.0, "width": 1024, "height": 1024, "negative_prompt": "",
        "prompt_optimizer": {"enabled": False}, "clip_skip": 1,
        "backend_options": {"image": {"backend_id": "forge_webui", "model_profile": P.reference()}},
        **changes,
    }


def test_identity_resolution_is_exact_and_old_versions_keep_meaning():
    for name in (P.transformer.filename, P.transformer.logical_name, "C:/models/" + P.transformer.filename + " [12345678]"):
        assert is_zimage_transformer_name(name)
        assert model_profile_for_model(name) == P.reference()
    for name in ("z_image.safetensors", "prefix-" + P.transformer.filename, "zImageTurboQuantized_fp16.safetensors"):
        assert not is_zimage_transformer_name(name)
        assert model_profile_for_model(name) is None
        assert resolve_model_policy(name).profile_ref is None
    assert resolve_model_profile({"image": {"model_profile": P.reference()}}) is P
    for old in (KLEIN_PROFILE_V1, KLEIN_PROFILE_V2):
        assert resolve_model_profile({"image": {"model_profile": old.reference()}}) is old
    for reference in ({"id": P.profile_id, "version": 2}, {"id": P.profile_id, "version": "1"},
                      {"id": P.profile_id, "version": True}, {"id": P.profile_id, "version": 1.0},
                      {"id": "unknown", "version": 1}):
        with pytest.raises(KleinProfileError):
            resolve_model_profile({"image": {"model_profile": reference}})


@pytest.mark.parametrize("change", [
    {"steps": 4}, {"cfg_scale": 0}, {"scheduler": "Karras"}, {"sampler": "Euler a"}, {"width": 768},
    {"shift": 3}, {"distilled_cfg_scale": 3}, {"negative_prompt": "bad"}, {"batch_size": 2}, {"n_iter": 2},
    {"pipeline": {"images_per_prompt": 2}}, {"prompt_optimizer": {"enabled": True}},
    {"global_positive_prompt": "quality"}, {"global_negative_prompt": "bad"}, {"enable_hr": True},
    {"use_refiner": True}, {"adetailer": {"enabled": True}}, {"upscale": {"enabled": True}},
    {"pipeline": {"img2img_enabled": True}}, {"aesthetic": {"enabled": True}},
    {"hypernetwork": "foo"}, {"controlnet": {"enabled": True}}, {"style_lora": {"enabled": True}},
    {"prompt": "portrait <lora:x:1>"}, {"prompt": "embedding:x"}, {"seed": 4_294_967_296},
    {"seed": 1.5}, {"vae": "other.safetensors"}, {"additional_modules": ["wrong.safetensors"]},
    {"txt2img": {"additional_modules": ["wrong.safetensors"]}},
    {"txt2img": {"forge_additional_modules": ["wrong.safetensors"]}},
    {"restore_faces": True}, {"tiling": True}, {"styles": ["cinematic"]}, {"clip_skip": 2},
])
def test_compiler_rejects_conflicts_without_silently_normalizing(change):
    data = config(**change)
    before = copy.deepcopy(data)
    with pytest.raises(ZImageProfileError):
        apply_zimage_compile_policy(data)
    assert data == before


def test_cli_builder_and_serialized_replay_preserve_the_exact_version():
    source = config()
    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "z-cli").build_jobs(base_config=source)[0]
    validate_zimage_njr(record)
    restored = NormalizedJobRecord.from_dict(record.to_dict())
    assert restored.backend_options["image"]["model_profile"] == P.reference()
    validate_zimage_njr(restored)
    assert source == config()
    assert normalize_image_backend_options({}, backend_id="forge_webui", model_name=P.transformer.filename)["image"]["model_profile"] == P.reference()


@pytest.mark.parametrize("backend", ["a1111_webui", "unknown"])
def test_no_backend_switch_or_foreign_profile(backend):
    with pytest.raises(ZImageProfileError):
        apply_zimage_compile_policy(config(backend_options={"image": {"backend_id": backend}}))


def test_resource_policy_has_only_the_owner_accepted_total_ram_floor():
    readings = HostMemorySnapshot(32_000_000_000, 1, 0)
    assert check_klein_host_memory(P, probe=lambda: readings).snapshot is readings
    with pytest.raises(KleinProfileError, match="32-GB-class"):
        check_klein_host_memory(P, probe=lambda: replace(readings, total_bytes=31_999_999_999))


def test_wire_contract_uses_only_the_pinned_api_shift_key_and_leaves_other_models_alone():
    data = apply_zimage_compile_policy(config())
    payload = {k: data[k] for k in ("prompt", "negative_prompt", "seed", "steps", "sampler_name", "scheduler", "cfg_scale", "width", "height")}
    payload.update(batch_size=1, n_iter=1, clip_skip=1, sd_model=P.transformer.filename)
    effective = project_zimage_wire_payload(data, payload, prompt=data["prompt"])
    assert effective["distilled_cfg_scale"] == 9.0 and "shift" not in effective
    assert effective["cfg_scale"] == 1.0
    with pytest.raises(ZImageProfileError, match="shift is not"):
        project_zimage_wire_payload(data, {**payload, "shift": 9}, prompt=data["prompt"])
    ordinary = {"prompt": "p", "sd_model": "sdxl"}
    assert project_zimage_wire_payload({}, ordinary, prompt="p") is ordinary
    with pytest.raises(ZImageProfileError, match="without its exact"):
        project_zimage_wire_payload({}, payload, prompt=data["prompt"])


def _tiny_assets(tmp_path, monkeypatch):
    assets = []
    for asset in P.assets:
        content = asset.role.encode()
        path = tmp_path / asset.filename
        path.write_bytes(content)
        assets.append(replace(asset, size=len(content), sha256=hashlib.sha256(content).hexdigest()))
    profile = replace(P, transformer=assets[0], text_encoder=assets[1], vae=assets[2])
    entries = [{"filename": str(tmp_path / a.filename), "model_name": a.filename} for a in assets]
    manager = SimpleNamespace(launch_session_command=["python", "launch.py"], _config=SimpleNamespace(working_dir="source"))
    monkeypatch.setattr("src.image_backends.forge_klein_assets.resolve_owned_forge_data_dir", lambda endpoint, **kw: tmp_path)
    monkeypatch.setattr("src.image_backends.forge_klein_assets._active_manager", lambda: manager)
    monkeypatch.setattr("src.utils.managed_forge_runtime.verify_pinned_launch", lambda *args: {"revision": P.forge_revision})
    client = SimpleNamespace(base_url="http://127.0.0.1:1", get_models=lambda: entries[:1], get_module_catalog=lambda: entries[1:])
    return profile, client, entries


def test_served_hashes_and_fingerprint_cache_bind_actual_paths(tmp_path, monkeypatch):
    profile, client, _ = _tiny_assets(tmp_path, monkeypatch)
    identity = verify_zimage_assets(profile, client=client)
    assert identity["transformer"]["sha256"] == profile.transformer.sha256
    assert verify_zimage_assets(profile, client=client)["vae"]["cache"] == "hit"
    (tmp_path / profile.vae.filename).write_bytes(b"xxx")  # same size, changed bytes
    with pytest.raises(KleinProfileError, match="SHA-256"):
        verify_zimage_assets(profile, client=client)


@pytest.mark.parametrize("kind", ["absent", "unreadable", "duplicate", "wrong_path"])
def test_catalog_binding_refuses_missing_ambiguous_or_substituted_paths(tmp_path, monkeypatch, kind):
    profile, client, entries = _tiny_assets(tmp_path, monkeypatch)
    if kind == "absent":
        client.get_module_catalog = lambda: entries[1:2]
    elif kind == "unreadable":
        client.get_module_catalog = lambda: None
    elif kind == "duplicate":
        client.get_models = lambda: [entries[0], {**entries[0], "filename": str(tmp_path / "elsewhere" / P.transformer.filename)}]
    else:
        client.get_models = lambda: [{**entries[0], "filename": str(tmp_path / "different.safetensors")}]
    with pytest.raises(KleinProfileError):
        verify_zimage_assets(profile, client=client)


def test_zimage_policy_is_limited_not_generic_family_qualification():
    policy = resolve_model_policy(P.transformer.filename)
    assert policy.family == "z_image" and policy.stages == ("txt2img",)
    assert policy.controls["geometry"].allowed == ((1024, 1024),)
    assert all(not item.supported for item in policy.features.values())
    assert "INSTRUMENTATION" not in policy.note or "incomplete" in policy.note
    assert "repeated-run stability remain incomplete" in policy.note


def test_mixed_checkpoint_aliases_never_fall_into_klein_normalization():
    from src.image_backends.model_policy import apply_model_compile_policy

    with pytest.raises(ZImageProfileError, match="conflicting checkpoint"):
        apply_model_compile_policy(config(txt2img={"model": KLEIN_PROFILE_V1.transformer.filename}))


def test_external_and_wrong_endpoint_forge_are_not_adopted(tmp_path, monkeypatch):
    from src.image_backends.forge_klein_assets import resolve_owned_forge_data_dir

    manager = SimpleNamespace(runtime_identity="forge_webui", owns_process=False, endpoint="http://127.0.0.1:1")
    with pytest.raises(KleinProfileError, match="does not own"):
        resolve_owned_forge_data_dir("http://127.0.0.1:1", manager=manager)
    manager.owns_process = True
    with pytest.raises(KleinProfileError, match="not the client endpoint"):
        resolve_owned_forge_data_dir("http://127.0.0.1:2", manager=manager)
