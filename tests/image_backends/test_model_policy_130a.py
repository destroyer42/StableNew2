"""PR-IMG-130A: the model-family capability/policy registry (pure, deterministic, no I/O).

Concepts kept distinct: backend identity, broad family, exact qualified profile, capability policy. The exact Klein
profile is consulted before any family inference; unknown/conflicting evidence is never guessed as SDXL; the compiler
seam is equivalent to the accepted Klein compile policy and a no-op for ordinary models.
"""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.image_backends import forge_klein_profile as klein
from src.image_backends import model_policy as mp
from src.image_backends.model_policy import (
    ControlMode,
    RegistryFamilyLookup,
    Support,
    apply_model_compile_policy,
    policy_for_model_profile_reference,
    policy_for_profile,
    resolve_model_policy,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"


def _compat(status: CompatibilityStatus, family: ModelFamily | None = None) -> CompatibilityProfile:
    return CompatibilityProfile(status, family, ())


def _lookup(status: CompatibilityStatus, family: ModelFamily | None = None) -> Mock:
    return Mock(return_value=_compat(status, family))


# --- SDXL: existing behavior, not narrowed, not claimed qualified --------------------------------------------------


def test_sdxl_by_registry_evidence_keeps_every_control_configurable_and_is_not_a_qualification() -> None:
    policy = resolve_model_policy("juggernaut.safetensors", family_lookup=_lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL))

    assert (policy.family, policy.policy_id, policy.evidence) == (mp.FAMILY_SDXL, "sdxl", mp.EVIDENCE_REGISTRY)
    assert all(policy.control(name).mode is ControlMode.CONFIGURABLE and not policy.control(name).allowed for name in mp.VALUE_CONTROLS)
    assert not policy.constrained and not policy.qualified and policy.profile_ref is None
    assert policy.required_backend is None and set(policy.allowed_backends) == {"forge_webui", "a1111_webui"}
    for feature in ("negative_prompt", "prompt_optimizer", "embeddings", "lora", "hires", "refiner", "adetailer", "upscale"):
        assert policy.feature(feature).support is Support.SUPPORTED, feature
    assert policy.feature("controlnet").support is Support.UNSUPPORTED  # the image path exposes none
    assert policy.prompt_dialect == mp.DIALECT_WEIGHTED_TAGS
    assert {"sampler", "scheduler", "steps", "cfg_scale", "vae", "lora_strength"} <= set(policy.learning_variables())
    assert "geometry" in policy.learning_variables() and policy.feature("lora").limit is None


def test_a_plain_sdxl_checkpoint_selection_projects_exactly_like_before() -> None:
    from src.gui_v2.model_policy_projection import project_model_selection

    projection = project_model_selection(
        "juggernaut.safetensors", "forge_webui", family_lookup=_lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL)
    )

    assert not projection.constrained and projection.presets == () and projection.note == "" and projection.blocking == ""
    assert all(state.mode is ControlMode.CONFIGURABLE for state in projection.controls.values())


# --- exact Klein identity: first, exact, versioned -------------------------------------------------------------------


def test_the_exact_klein_transformer_resolves_to_the_current_profile_before_any_family_inference() -> None:
    lookup = _lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL)  # even evidence claiming SDXL cannot win

    policy = resolve_model_policy(KLEIN, family_lookup=lookup)

    lookup.assert_not_called()
    profile = klein.latest_klein_profile()
    assert (policy.policy_id, policy.family, policy.evidence) == ("flux2_klein_4b_fp8", mp.FAMILY_FLUX2_KLEIN, mp.EVIDENCE_PROFILE)
    assert policy.profile_ref == {"id": "flux2_klein_4b_fp8", "version": profile.version} == profile.reference()
    assert policy.qualified


def test_klein_projects_exactly_the_accepted_v2_semantics() -> None:
    profile = klein.latest_klein_profile()
    policy = policy_for_profile(profile)

    assert policy.required_backend == policy.allowed_backends[0] == "forge_webui"
    for name, value in (("sampler", "Euler"), ("scheduler", "Beta"), ("steps", 4), ("cfg_scale", 1.0)):
        assert policy.control(name).mode is ControlMode.FIXED and policy.control(name).value == value
        assert value == {"sampler": profile.sampler, "scheduler": profile.scheduler, "steps": profile.steps, "cfg_scale": profile.cfg_scale}[name]
    assert policy.control("vae").mode is ControlMode.FIXED and policy.control("vae").value == ""
    assert policy.control("geometry").allowed == ((768, 1024), (1024, 1024)) == tuple(profile.geometries)
    assert policy.modes == ("txt2img", "single_reference_edit") and policy.stages == ("txt2img", "img2img")
    for feature in ("negative_prompt", "prompt_optimizer", "embeddings", "hires", "refiner", "adetailer", "controlnet", "upscale"):
        assert policy.feature(feature).support is Support.UNSUPPORTED, feature
    lora = policy.feature("lora")
    assert lora.supported and lora.limit == 1 and lora.compatibility_policy == mp.LORA_POLICY_KLEIN_4B_EXPLICIT
    assert policy.constrained and policy.learning_variables() == ("lora_strength",)
    assert "fixed distilled settings" in policy.note and policy.prompt_dialect == mp.DIALECT_NATURAL_LANGUAGE


def test_persisted_profile_versions_keep_their_own_policy() -> None:
    v1 = policy_for_model_profile_reference({"image": {"model_profile": {"id": "flux2_klein_4b_fp8", "version": 1}}})
    v2 = policy_for_model_profile_reference({"image": {"model_profile": {"id": "flux2_klein_4b_fp8", "version": 2}}})

    assert v1.profile_ref["version"] == 1 and v1.feature("lora").support is Support.UNSUPPORTED  # v1 never admits a LoRA
    assert v2.profile_ref["version"] == 2 and v2.feature("lora").limit == 1
    assert policy_for_model_profile_reference({"image": {}}) is None
    with pytest.raises(klein.KleinProfileError):
        policy_for_model_profile_reference({"image": {"model_profile": {"id": "flux2_klein_4b_fp8", "version": 99}}})


def test_a_klein_lookalike_name_is_not_klein() -> None:
    policy = resolve_model_policy("my-flux-2-klein-4b-fp8-merge.safetensors")

    assert policy.family == mp.FAMILY_UNKNOWN and not policy.qualified


# --- unknown / conflicting evidence is never guessed -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("lookup", "evidence"),
    [
        (None, mp.EVIDENCE_NONE),
        (Mock(return_value=None), mp.EVIDENCE_NONE),
        (Mock(side_effect=RuntimeError("cache unreadable")), mp.EVIDENCE_NONE),
        (_lookup(CompatibilityStatus.UNKNOWN), mp.EVIDENCE_UNKNOWN),
        (_lookup(CompatibilityStatus.CONFLICTING), mp.EVIDENCE_CONFLICTING),
    ],
)
def test_missing_unknown_or_conflicting_evidence_is_not_guessed_as_sdxl(lookup, evidence: str) -> None:
    policy = resolve_model_policy("mystery.safetensors", family_lookup=lookup)

    assert policy.family == mp.FAMILY_UNKNOWN and policy.policy_id != "sdxl" and policy.evidence == evidence
    assert not policy.qualified and not policy.constrained  # generic WebUI usability preserved for compatibility
    assert all(policy.control(name).mode is ControlMode.CONFIGURABLE for name in mp.VALUE_CONTROLS)
    for feature in ("negative_prompt", "lora", "hires", "refiner", "adetailer", "upscale"):
        assert policy.feature(feature).support is Support.UNVERIFIED, feature  # no capability claim either way
    assert policy.prompt_dialect == mp.DIALECT_UNSPECIFIED


@pytest.mark.parametrize("family", [ModelFamily.SD1, ModelFamily.SD2, ModelFamily.SD3, ModelFamily.FLUX])
def test_other_resolved_families_are_labeled_but_never_qualified_or_called_sdxl_or_klein(family: ModelFamily) -> None:
    policy = resolve_model_policy("x.safetensors", family_lookup=_lookup(CompatibilityStatus.RESOLVED, family))

    assert policy.family == family.value and policy.evidence == mp.EVIDENCE_REGISTRY
    assert not policy.qualified and policy.policy_id != "sdxl" and policy.family != mp.FAMILY_FLUX2_KLEIN
    assert policy.feature("lora").support is Support.UNVERIFIED


def test_a_blank_selection_has_no_evidence() -> None:
    assert resolve_model_policy("", family_lookup=Mock()).evidence == mp.EVIDENCE_NONE
    assert resolve_model_policy(None).family == mp.FAMILY_UNKNOWN


# --- registry family lookup: persisted snapshot only ----------------------------------------------------------------


class _FakeRegistry:
    def __init__(self, records, webui_root=Path("C:/webui")) -> None:
        self.webui_root = webui_root
        self._records = records
        self.refresh = Mock(side_effect=AssertionError("a UI-thread lookup must never scan or hash"))

    def cached_snapshot(self):
        return SimpleNamespace(records_for=lambda kind: tuple(self._records))


def _record(name: str, compat: CompatibilityProfile | None):
    from src.assets import AssetKind

    return SimpleNamespace(
        compatibility=compat,
        locations=(SimpleNamespace(kind=AssetKind.CHECKPOINT, path=Path("C:/webui/models/Stable-diffusion") / name),),
    )


def test_the_registry_lookup_reads_only_the_persisted_snapshot_and_matches_by_file_name() -> None:
    registry = _FakeRegistry([_record("Juggernaut.safetensors", _compat(CompatibilityStatus.RESOLVED, ModelFamily.SDXL))])
    lookup = RegistryFamilyLookup(registry)

    assert lookup("juggernaut [abc123ef]").family is ModelFamily.SDXL  # a listing title with a short hash
    assert lookup("other.safetensors") is None
    registry.refresh.assert_not_called()
    assert resolve_model_policy("juggernaut.safetensors", family_lookup=lookup).family == mp.FAMILY_SDXL


def test_the_registry_lookup_reports_disagreeing_records_as_conflicting_not_a_pick() -> None:
    registry = _FakeRegistry([
        _record("dup.safetensors", _compat(CompatibilityStatus.RESOLVED, ModelFamily.SDXL)),
        _record("dup.safetensors", _compat(CompatibilityStatus.RESOLVED, ModelFamily.SD1)),
    ])

    assert resolve_model_policy("dup.safetensors", family_lookup=RegistryFamilyLookup(registry)).evidence == mp.EVIDENCE_CONFLICTING


def test_without_a_local_webui_root_nothing_is_known() -> None:
    assert RegistryFamilyLookup(_FakeRegistry([], webui_root=None))("x.safetensors") is None


def test_no_policy_module_can_scan_hash_or_use_the_network() -> None:
    from src.gui import model_policy_panel_projection as glue
    from src.gui_v2 import model_policy_projection as projection

    for module in (mp, projection, glue):
        source = inspect.getsource(module)
        for banned in (".refresh(", "hashlib", "import requests", "import socket", "urllib"):
            assert banned not in source, (module.__name__, banned)


# --- compiler seam ----------------------------------------------------------------------------------------------------


def _klein_config() -> dict:
    return {
        "txt2img": {"model": KLEIN, "sampler_name": "Euler a", "scheduler": "Normal", "steps": 20, "cfg_scale": 7.0, "negative_prompt": "blurry", "vae": "sdxl_vae"},
        "steps": 20,
        "prompt_optimizer": {"enabled": True, "dedupe_enabled": True},
        "pipeline": {"apply_global_negative_txt2img": True},
        "global_negative_prompt": "nsfw",
    }


def test_the_model_compile_policy_is_equivalent_to_the_accepted_klein_compile_policy() -> None:
    expected = klein.apply_klein_compile_policy(_klein_config())
    actual = apply_model_compile_policy(_klein_config())

    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert actual["backend_options"]["image"]["model_profile"] == klein.latest_klein_profile().reference()


def test_the_model_compile_policy_leaves_ordinary_models_untouched() -> None:
    config = {"txt2img": {"model": "sdxl.safetensors", "steps": 30, "cfg_scale": 7.0}, "prompt_optimizer": {"enabled": True}}
    before = copy.deepcopy(config)

    assert apply_model_compile_policy(config) is config and config == before


def test_every_compiler_entry_point_uses_the_one_model_compile_policy() -> None:
    from src.pipeline import cli_njr_builder, job_builder_v2, prompt_pack_job_builder

    for module in (cli_njr_builder, job_builder_v2, prompt_pack_job_builder):
        assert module.apply_model_compile_policy is apply_model_compile_policy, module.__name__
        assert not hasattr(module, "apply_klein_compile_policy"), module.__name__
