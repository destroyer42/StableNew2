"""PR-IMG-FLUX-130: the FLUX.1 [dev] family profile, the FLUX policy branches, readiness refusals and asset identity.

Deterministic: no Forge, no GPU, no model bytes. The structural variant seam is installed per test and always restored.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.assets.component_evidence import classify_tensor_table, inspect_component_file
from src.gui_v2.model_policy_projection import project_model_controls, project_model_selection
from src.image_backends import forge_klein_assets
from src.image_backends.exact_model_profile import resolve_model_profile, validate_profile_intent
from src.image_backends.forge_flux1_profile import (
    FLUX1_DEV_PROFILE_V1 as P,
)
from src.image_backends.forge_flux1_profile import (
    FLUX1_PROFILE_ID,
    FLUX1_UNPROFILED_HINT,
    Flux1ProfileError,
    apply_flux1_compile_policy,
    distilled_cfg_conflicts,
    flux1_provenance,
    flux1_selected,
    flux_variant_refusal,
    install_variant_lookup,
    project_flux1_wire_payload,
    resolve_flux1_reference,
    validate_flux1_intent,
)
from src.image_backends.forge_klein_profile import KleinAsset, KleinProfileError
from src.image_backends.model_policy import (
    EVIDENCE_STRUCTURAL,
    FAMILY_FLUX1,
    FAMILY_FLUX2_KLEIN,
    apply_model_compile_policy,
    policy_for_model_profile_reference,
    registry_variant_lookup,
    resolve_model_policy,
)
from src.image_backends.model_readiness import (
    CatalogModule,
    ReadinessStatus,
    assess_model_readiness,
)
from tests.assets.flux_fixtures_130 import (
    FTYPE_Q6_K,
    GGML_Q6_K,
    dtypes_of,
    flux1_table,
    klein_table,
    qwen3_vl_table,
    unrecognized_dit_table,
    write_gguf,
)

FLUX1 = "flux1-dev-Q4_K_S.gguf"


def _compat(architecture: str | None, family=ModelFamily.FLUX, status=CompatibilityStatus.RESOLVED):
    return CompatibilityProfile(status, family, (), checkpoint_architecture=architecture)


@pytest.fixture
def variants():
    """Install a structural variant lookup over a mutable name -> architecture map; restore the previous one after."""

    table: dict[str, str] = {}
    previous = install_variant_lookup(
        registry_variant_lookup(lambda name: _compat(table[name]) if name in table else None)
    )
    try:
        yield table
    finally:
        install_variant_lookup(previous)


# ------------------------------------------------------------------------------------------- policy


def test_a_transformer_only_flux1_dev_layout_resolves_to_the_family_profile_policy():
    policy = resolve_model_policy(FLUX1, family_lookup=lambda _n: _compat("flux1_dev"))
    assert policy.policy_id == FLUX1_PROFILE_ID and policy.family == FAMILY_FLUX1
    assert policy.profile_ref == P.reference() and policy.qualified
    assert (
        policy.evidence == EVIDENCE_STRUCTURAL and not policy.exact_identity_authority
    )  # Model Comparison refuses it
    assert (
        policy.required_backend == "forge_webui"
        and policy.modes == ("txt2img",)
        and not policy.refusal
    )
    assert policy.control("steps").value == 20 and policy.control("cfg_scale").value == 1.0
    assert (
        policy.control("sampler").value == "Euler" and policy.control("scheduler").value == "Simple"
    )
    assert policy.control("geometry").allowed == P.geometries
    frozen = policy_for_model_profile_reference({"image": {"model_profile": P.reference()}})
    assert frozen is not None and frozen.policy_id == FLUX1_PROFILE_ID


@pytest.mark.parametrize(
    "architecture,family,phrase",
    [
        ("flux2_klein_9b", FAMILY_FLUX2_KLEIN, "NO-GO"),
        ("flux2_klein_4b", FAMILY_FLUX2_KLEIN, "flux-2-klein-4b-fp8.safetensors"),
        ("flux_unrecognized", "flux", "matches no StableNew profile"),
    ],
)
def test_other_flux_layouts_are_labelled_and_refused(architecture, family, phrase):
    policy = resolve_model_policy("candidate.gguf", family_lookup=lambda _n: _compat(architecture))
    assert policy.policy_id == f"flux_refused:{architecture}" and policy.family == family
    assert policy.refusal and phrase in policy.refusal and policy.profile_ref is None
    assert policy.stages == () and policy.modes == ()
    projection = project_model_controls(policy, "forge_webui")
    # N1: shown even on the right backend and never auto-fixed, but as a warning: Queue still runs it.
    assert projection.blocking == ""
    assert policy.refusal in projection.note and "Queue still runs it" in projection.note


@pytest.mark.parametrize(
    "architecture", ["flux1_dev_bundled", "flux2_klein_9b_bundled", None, "unrecognized"]
)
def test_bundled_or_label_only_flux_keeps_the_previous_unverified_projection(architecture):
    policy = resolve_model_policy(
        "flux-thing.safetensors", family_lookup=lambda _n: _compat(architecture)
    )
    assert policy.policy_id == "unverified_generic:flux" and policy.family == "flux"
    assert not policy.refusal and policy.profile_ref is None


def test_conflicting_flux_evidence_is_unknown_and_the_variant_seam_answers_nothing():
    conflicting = CompatibilityProfile(CompatibilityStatus.CONFLICTING, None, ())
    assert (
        resolve_model_policy("x.gguf", family_lookup=lambda _n: conflicting).evidence
        == "conflicting_evidence"
    )
    assert registry_variant_lookup(lambda _n: conflicting)("x.gguf") is None
    assert registry_variant_lookup(lambda _n: _compat("sdxl_base", ModelFamily.SDXL))("x") is None
    assert registry_variant_lookup(lambda _n: _compat("flux2_klein_9b"))("x") == (
        "flux2_klein_9b",
        False,
    )


def test_the_gui_projection_for_the_exact_klein_and_sdxl_names_is_unchanged():
    klein = project_model_selection("flux-2-klein-4b-fp8.safetensors", "forge_webui")
    assert klein.policy.policy_id == "flux2_klein_4b_fp8" and not klein.blocking
    sdxl = project_model_selection(
        "juggernaut.safetensors",
        "forge_webui",
        family_lookup=lambda _n: _compat("sdxl_base", ModelFamily.SDXL),
    )
    assert sdxl.policy.policy_id == "sdxl" and not sdxl.blocking


# ------------------------------------------------------------------------------------------- profile references


def test_only_the_exact_frozen_reference_resolves():
    assert resolve_flux1_reference({"id": FLUX1_PROFILE_ID, "version": 1}) is P
    assert resolve_model_profile({"image": {"model_profile": P.reference()}}) is P
    for bad in (
        {"id": FLUX1_PROFILE_ID, "version": 2},
        {"id": FLUX1_PROFILE_ID, "version": "1"},
        {"id": FLUX1_PROFILE_ID, "version": True},
        {"id": FLUX1_PROFILE_ID, "version": 1, "extra": 1},
    ):
        with pytest.raises(Flux1ProfileError):
            resolve_flux1_reference(bad)


def test_profile_pins_match_the_owner_decisions():
    assert P.transformer_variant == "flux1_dev" and "Q4_K_S" in P.transformer_precisions
    assert (
        P.recommended_transformer.filename == FLUX1
        and P.recommended_transformer.size == 6_805_988_640
    )
    assert [a.filename for a in P.modules] == [
        "clip_l.safetensors",
        "t5xxl_fp8_e4m3fn.safetensors",
        "flux1AE_v10.safetensors",
    ]
    assert all(len(a.sha256) == 64 for a in (*P.modules, P.recommended_transformer))
    assert (P.sampler, P.scheduler, P.steps, P.cfg_scale, P.distilled_cfg_scale) == (
        "Euler",
        "Simple",
        20,
        1.0,
        3.5,
    )
    assert P.max_loras == 0 and P.modes == ("txt2img",)


# ------------------------------------------------------------------------------------------- intent and compile


def _intent(**changes):
    intent = {
        "backend_id": "forge_webui",
        "stage_names": ("txt2img",),
        "model_name": FLUX1,
        "sampler": "Euler",
        "scheduler": "Simple",
        "steps": 20,
        "cfg_scale": 1.0,
        "width": 1024,
        "height": 1024,
        "negative_prompt": "",
    }
    intent.update(changes)
    return intent


def test_the_envelope_admits_exactly_txt2img_at_the_fixed_settings():
    assert validate_flux1_intent(P, **_intent()) == "txt2img"
    assert validate_profile_intent(P, **_intent(width=832, height=1216)) == "txt2img"


def test_every_conflict_is_listed_in_one_refusal():
    with pytest.raises(Flux1ProfileError) as caught:
        validate_flux1_intent(
            P,
            **_intent(
                backend_id="a1111_webui",
                stage_names=("txt2img", "adetailer"),
                steps=28,
                cfg_scale=3.5,
                width=1280,
                height=720,
                negative_prompt="blurry",
                unsupported_features=("LoRA",),
            ),
        )
    message = str(caught.value)
    for phrase in (
        "backend 'a1111_webui'",
        "stage chain",
        "steps 28",
        "CFG 3.5",
        "geometry 1280x720",
        "negative prompt",
        "LoRA is not supported",
    ):
        assert phrase in message


def test_a_distilled_cfg_other_than_the_profile_value_is_a_conflict_never_a_rewrite():
    assert distilled_cfg_conflicts({"distilled_cfg_scale": 3.5}, P) == []
    assert distilled_cfg_conflicts({"txt2img": {"distilled_cfg_scale": 4}}, P) == [
        "distilled CFG 4 (the profile fixes 3.5)"
    ]


def test_compile_policy_stamps_the_reference_only_when_the_registry_says_flux1_dev(variants):
    def config():
        return {
            "txt2img": {
                "model": FLUX1,
                "steps": 30,
                "cfg_scale": 7.0,
                "sampler_name": "DPM++ 2M",
                "negative_prompt": "ugly",
                "vae": "sdxl_vae.safetensors",
            },
            "pipeline": {"apply_global_negative_txt2img": True},
            "global_negative_prompt": "bad",
            "backend_options": {"image": {"backend_id": "forge_webui"}},
        }

    untouched = apply_model_compile_policy(config())
    assert (
        "model_profile" not in untouched["backend_options"]["image"]
    )  # no evidence: nothing stamped, gate refuses

    variants[FLUX1] = "flux1_dev"
    assert flux1_selected({"txt2img": {"model": FLUX1}})
    compiled = apply_model_compile_policy(config())
    t2i = compiled["txt2img"]
    assert compiled["backend_options"]["image"]["model_profile"] == P.reference()
    assert (t2i["steps"], t2i["cfg_scale"], t2i["sampler_name"], t2i["scheduler"]) == (
        20,
        1.0,
        "Euler",
        "Simple",
    )
    assert t2i["distilled_cfg_scale"] == 3.5 and t2i["clip_skip"] == 1 and t2i["vae"] == ""
    assert t2i["negative_prompt"] == "" and t2i["prompt_optimizer"] == {"enabled": False}
    assert (
        compiled["pipeline"]["apply_global_negative_txt2img"] is False
        and compiled["global_negative_prompt"] == ""
    )

    variants[FLUX1] = "flux2_klein_9b"
    refused = apply_model_compile_policy(config())
    assert (
        "model_profile" not in refused["backend_options"]["image"]
    )  # a refused layout is never stamped


def test_a_frozen_reference_is_never_upgraded_or_swapped(variants):
    variants[FLUX1] = "flux1_dev"
    frozen = {
        "txt2img": {"model": FLUX1},
        "backend_options": {
            "image": {"model_profile": {"id": "z_image_turbo_fp8_scaled", "version": 1}}
        },
    }
    with pytest.raises(Flux1ProfileError, match="frozen to profile"):
        apply_flux1_compile_policy(frozen)
    with pytest.raises(Flux1ProfileError):
        apply_flux1_compile_policy(
            {
                "backend_options": {
                    "image": {"model_profile": {"id": FLUX1_PROFILE_ID, "version": 9}}
                }
            }
        )


def test_the_wire_payload_carries_distilled_guidance_and_ordinary_payloads_are_untouched():
    config = {"backend_options": {"image": {"model_profile": P.reference()}}}
    assert (
        project_flux1_wire_payload(config, {"cfg_scale": 1.0, "negative_prompt": ""})[
            "distilled_cfg_scale"
        ]
        == 3.5
    )
    with pytest.raises(Flux1ProfileError):
        project_flux1_wire_payload(config, {"cfg_scale": 3.5, "negative_prompt": ""})
    ordinary = {"cfg_scale": 7.0, "negative_prompt": "x"}
    assert project_flux1_wire_payload({"backend_options": {}}, dict(ordinary)) == ordinary


def test_provenance_is_path_free_and_says_not_physically_qualified():
    evidence = flux1_provenance(P, model_name=FLUX1)
    assert evidence["model_profile"] == P.reference() and evidence["transformer"]["name"] == FLUX1
    assert evidence["qualification_status"] == "not physically qualified"
    assert "\\" not in str(evidence) and "/data" not in str(evidence)


# ------------------------------------------------------------------------------------------- readiness


def test_a_gguf_klein_9b_transformer_is_named_and_refused_by_readiness(tmp_path):
    path = write_gguf(
        tmp_path / "flux-2-klein-base-9b-Q6_K.gguf",
        klein_table("9b"),
        tensor_type=GGML_Q6_K,
        file_type=FTYPE_Q6_K,
    )
    readiness = assess_model_readiness(
        path.name, checkpoint=inspect_component_file(path), catalog=[], selected=[]
    )
    assert readiness.blocks_dispatch and readiness.evidence_type == "gguf_tensor_table"
    summary = " ".join(readiness.reasons)
    assert "FLUX.2 Klein 9B-class, GGUF Q6_K, identity not pinned" in summary
    assert flux_variant_refusal("flux2_klein_9b") in summary


def test_a_flux1_dev_transformer_without_its_profile_points_at_the_inventory_refresh(tmp_path):
    path = write_gguf(tmp_path / FLUX1, flux1_table())
    readiness = assess_model_readiness(
        FLUX1, checkpoint=inspect_component_file(path), catalog=[], selected=[]
    )
    assert readiness.blocks_dispatch
    assert FLUX1_UNPROFILED_HINT in " ".join(readiness.reasons)


def test_an_encoder_in_the_checkpoint_folder_is_not_a_checkpoint():
    table = qwen3_vl_table()
    readiness = assess_model_readiness(
        "flux3Klein_txt.safetensors",
        checkpoint=classify_tensor_table(table, dtypes_of(table)),
        catalog=[],
        selected=[],
    )
    assert readiness.status is ReadinessStatus.NOT_A_CHECKPOINT and readiness.blocks_dispatch
    assert readiness.reason_code == "component_not_checkpoint" and "text encoder" in " ".join(
        readiness.reasons
    )


def test_an_unrecognised_transformer_only_dit_is_refused():
    table = unrecognized_dit_table()
    readiness = assess_model_readiness(
        "flux3Klein_pruned_int8.safetensors",
        checkpoint=classify_tensor_table(table, dtypes_of(table)),
        catalog=[CatalogModule("qwen_3_4b.safetensors")],
        selected=[],
    )
    assert readiness.blocks_dispatch and "no StableNew profile" in " ".join(readiness.reasons)


# ------------------------------------------------------------------------------------------- served asset identity


def _small_profile(tmp_path: Path):
    root = tmp_path / "forge-data"
    assets = []
    for role, name, sub in (
        ("text_encoder", "clip_l.safetensors", "text_encoder"),
        ("text_encoder_2", "t5xxl_fp8_e4m3fn.safetensors", "text_encoder"),
        ("vae", "flux1AE_v10.safetensors", "VAE"),
    ):
        path = root / "models" / sub / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode() * 3)
        assets.append(
            KleinAsset(
                role,
                name,
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                sub,
                "",
                "",
            )
        )
    profile = replace(P, clip_l=assets[0], t5xxl=assets[1], vae=assets[2])
    modules = [
        {"model_name": a.filename, "filename": str(root / "models" / a.models_subdir / a.filename)}
        for a in assets
    ]
    return root, profile, modules


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root, profile, modules = _small_profile(tmp_path)
    manager = SimpleNamespace(
        runtime_identity="forge_webui",
        owns_process=True,
        endpoint="http://127.0.0.1:7861",
        launch_session_command=["python", "launch.py", "--data-dir", str(root)],
        _config=SimpleNamespace(working_dir="src"),
    )
    monkeypatch.setattr(forge_klein_assets, "_active_manager", lambda: manager)
    now = [0.0]
    monkeypatch.setattr(forge_klein_assets, "_monotonic", lambda: now[0])
    monkeypatch.setattr(
        forge_klein_assets, "_sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    forge_klein_assets.clear_verified_cache()
    yield root, profile, modules
    forge_klein_assets.clear_verified_cache()


def _client(models, modules):
    return SimpleNamespace(
        base_url="http://127.0.0.1:7861",
        get_models=lambda: models,
        get_module_catalog=lambda: modules,
    )


def _verify(profile, models, modules, name=FLUX1):
    return forge_klein_assets.verify_flux1_assets(
        profile,
        client=_client(models, modules),
        model_name=name,
        verify_launch=lambda *a: {"revision": a[2]},
    )


def test_a_structurally_matching_transformer_is_admitted_and_its_sha_recorded_not_required(managed):
    root, profile, modules = managed
    transformer = write_gguf(root / "models" / "Stable-diffusion" / FLUX1, flux1_table())
    result = _verify(profile, [{"model_name": FLUX1, "filename": str(transformer)}], modules)
    assert result["forge"] == {"revision": profile.forge_revision}
    record = result["transformer"]
    assert (
        record["variant"] == "flux1_dev"
        and record["precision"] == "Q4_K_S"
        and record["container"] == "gguf"
    )
    assert (
        record["identity"] == "derivative_or_other_conversion"
    )  # not the published bytes, still admitted by structure
    assert record["sha256"] == hashlib.sha256(transformer.read_bytes()).hexdigest()
    assert {result[role]["verified"] for role in ("text_encoder", "text_encoder_2", "vae")} == {
        "sha256"
    }


@pytest.mark.parametrize(
    "table,kwargs,phrase",
    [
        (klein_table("9b"), {}, "Klein 9B-class"),
        (flux1_table(guidance=False), {}, "schnell"),
        (flux1_table(bundled=True), {}, "bundled"),
        (flux1_table(), {"file_type": 2}, "Q4_0"),
    ],
)
def test_a_served_transformer_of_another_layout_or_precision_is_refused(
    managed, table, kwargs, phrase
):
    root, profile, modules = managed
    transformer = write_gguf(
        root / "models" / "Stable-diffusion" / "candidate.gguf", table, **kwargs
    )
    with pytest.raises(KleinProfileError, match=phrase):
        _verify(
            profile,
            [{"model_name": "candidate.gguf", "filename": str(transformer)}],
            modules,
            name="candidate.gguf",
        )


def test_a_wrong_module_or_an_ambiguous_listing_is_refused(managed):
    root, profile, modules = managed
    transformer = write_gguf(root / "models" / "Stable-diffusion" / FLUX1, flux1_table())
    models = [{"model_name": FLUX1, "filename": str(transformer)}]
    Path(modules[2]["filename"]).write_bytes(b"not the pinned vae bytes")
    with pytest.raises(KleinProfileError, match="flux1AE_v10"):
        _verify(profile, models, modules)
    with pytest.raises(KleinProfileError, match="one unambiguous served file"):
        _verify(
            profile,
            models + [{"model_name": FLUX1, "filename": str(root / "elsewhere" / FLUX1)}],
            modules,
        )


def test_a_catalog_forge_is_still_rebuilding_is_re_read_before_the_served_identity_check(managed):
    root, profile, modules = managed
    transformer = write_gguf(root / "models" / "Stable-diffusion" / FLUX1, flux1_table())
    served = [{"model_name": FLUX1, "filename": str(transformer)}]
    # Each read pair (checkpoints, modules) is what Forge answers while list_models()/refresh_models() run.
    reads = [([], modules[:1]), ([], modules), (served, modules)]
    index = [-1]

    def get_models():
        index[0] = min(index[0] + 1, len(reads) - 1)
        return reads[index[0]][0]

    client = SimpleNamespace(
        base_url="http://127.0.0.1:7861",
        get_models=get_models,
        get_module_catalog=lambda: reads[index[0]][1],
    )
    result = forge_klein_assets.verify_flux1_assets(
        profile, client=client, model_name=FLUX1, verify_launch=lambda *a: {"revision": a[2]}
    )
    assert result["transformer"]["variant"] == "flux1_dev"
    assert {result[role]["verified"] for role in ("text_encoder", "text_encoder_2", "vae")} == {
        "sha256"
    }
    assert index[0] == 2  # read three times, then admitted
