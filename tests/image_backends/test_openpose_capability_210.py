"""OpenPose conditioning target eligibility (PR-IMG-CNET-210): pure policy + backend classification."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.gui_v2.model_policy_projection import project_model_selection
from src.image_backends import model_policy as mp
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1
from src.image_backends.model_policy import Support, resolve_model_policy
from src.image_backends.openpose_capability import (
    FEATURE,
    REASON_BACKEND,
    REASON_CONFLICT,
    REASON_EXACT_PROFILE,
    REASON_FAMILY,
    REASON_STAGE,
    REASON_UNVERIFIED,
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
    STATUS_UNVERIFIED,
    assess_openpose_target,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
FORGE, A1111 = "forge_webui", "a1111_webui"


def _lookup(status: CompatibilityStatus, family: ModelFamily | None = None) -> Mock:
    return Mock(return_value=CompatibilityProfile(status, family, ()))


def _sdxl():
    return resolve_model_policy("x.safetensors", family_lookup=_lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL))


def test_sdxl_on_forge_is_the_only_supported_target() -> None:
    target = assess_openpose_target(_sdxl(), FORGE)

    assert (target.status, target.executable, target.blocked) == (STATUS_SUPPORTED, True, False)


def test_the_generic_controlnet_feature_and_the_frozen_policy_contract_are_unchanged() -> None:
    # The bounded OpenPose contract must never widen "ControlNet" in general (Model Comparison keys off this) and must
    # not add a feature to the persisted policy contract that frozen Learning studies compare against.
    policy = _sdxl()
    assert policy.feature("controlnet").support is Support.UNSUPPORTED
    assert FEATURE not in policy.features and FEATURE not in mp.FEATURES


def test_a1111_is_never_claimed() -> None:
    target = assess_openpose_target(_sdxl(), A1111)

    assert (target.status, target.reason, target.executable) == (STATUS_UNSUPPORTED, REASON_BACKEND, False)
    assert "Forge" in target.message


@pytest.mark.parametrize("backend", [None, "", "comfy_webui"])
def test_an_unknown_backend_is_unsupported(backend) -> None:
    assert assess_openpose_target(_sdxl(), backend).status == STATUS_UNSUPPORTED


def test_an_unclassified_checkpoint_is_unverified_and_not_executable() -> None:
    policy = resolve_model_policy("mystery.safetensors", family_lookup=None)

    target = assess_openpose_target(policy, FORGE)

    assert (target.status, target.reason, target.executable) == (STATUS_UNVERIFIED, REASON_UNVERIFIED, False)
    assert not target.blocked  # it can still become supported once identified


@pytest.mark.parametrize("family", [ModelFamily.SD1, ModelFamily.SD2])
def test_an_identified_non_sdxl_family_is_unsupported(family) -> None:
    policy = resolve_model_policy("old.safetensors", family_lookup=_lookup(CompatibilityStatus.RESOLVED, family))

    target = assess_openpose_target(policy, FORGE)

    assert (target.status, target.reason) == (STATUS_UNSUPPORTED, REASON_FAMILY)


def test_conflicting_evidence_is_unsupported() -> None:
    policy = resolve_model_policy("dup.safetensors", family_lookup=_lookup(CompatibilityStatus.CONFLICTING))

    target = assess_openpose_target(policy, FORGE)

    assert (target.status, target.reason) == (STATUS_UNSUPPORTED, REASON_CONFLICT)


@pytest.mark.parametrize("name", [KLEIN, ZIMAGE_PROFILE_V1.transformer.filename])
def test_exact_qualified_profiles_are_unsupported(name: str) -> None:
    policy = resolve_model_policy(name, family_lookup=_lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL))

    target = assess_openpose_target(policy, FORGE)

    assert (target.status, target.reason, target.executable) == (STATUS_UNSUPPORTED, REASON_EXACT_PROFILE, False)


@pytest.mark.parametrize("stage", ["img2img", "adetailer", "upscale"])
def test_only_the_base_txt2img_stage_is_supported(stage: str) -> None:
    target = assess_openpose_target(_sdxl(), FORGE, stage=stage)

    assert (target.status, target.reason) == (STATUS_UNSUPPORTED, REASON_STAGE)


def test_the_panel_projection_carries_the_same_decision() -> None:
    lookup = _lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL)

    supported = project_model_selection("x.safetensors", FORGE, family_lookup=lookup)
    refused = project_model_selection("x.safetensors", A1111, family_lookup=lookup)
    klein = project_model_selection(KLEIN, FORGE, family_lookup=lookup)

    assert supported.openpose is not None and supported.openpose.executable
    assert refused.openpose is not None and refused.openpose.reason == REASON_BACKEND
    assert klein.openpose is not None and klein.openpose.reason == REASON_EXACT_PROFILE
    assert project_model_selection(None, None).openpose is not None  # never absent once projected


def test_every_resolved_policy_gets_an_answer() -> None:
    for name in ("x.safetensors", KLEIN, ZIMAGE_PROFILE_V1.transformer.filename, "unknown.safetensors"):
        policy = resolve_model_policy(name, family_lookup=_lookup(CompatibilityStatus.RESOLVED, ModelFamily.SDXL))
        assert assess_openpose_target(policy, FORGE).status in {STATUS_SUPPORTED, STATUS_UNSUPPORTED, STATUS_UNVERIFIED}
