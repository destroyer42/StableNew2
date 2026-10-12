"""PR-IMG-CNET-210: editor Validate/readiness for OpenPose conditioning (pure, in-memory pack)."""

from __future__ import annotations

import json

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.conditioning.openpose import new_declaration
from src.gui.models.prompt_pack_model import PromptPackModel
from src.image_backends.model_policy import resolve_model_policy
from src.prompting.pack_target_readiness import assess_pack_readiness, validate_pack_structure

SDXL = "juggernaut.safetensors"
KLEIN = "flux-2-klein-4b-fp8.safetensors"
MYSTERY = "mystery.safetensors"
_SDXL = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
POSE = new_declaration("Standing/relaxed.png", model="xinsir_openpose_sdxl")


def _lookup(name: str):
    return {SDXL: _SDXL}.get(name)


def _pack(openpose, text: str = "a person") -> PromptPackModel:
    model = PromptPackModel.new("pose", slot_count=1)
    model.slots[0].text = text
    model.slots[0].openpose = openpose
    model.preset_data = {"txt2img": {"width": 1024, "height": 1024}}
    return model


def _assess(model: PromptPackModel, target: str, backend: str = "forge_webui"):
    policy = resolve_model_policy(target, family_lookup=_lookup)
    return assess_pack_readiness(
        model, policy, model_name=target, backend_id=backend, dirty=True, lora_resolver=lambda name: None
    )


# --- editor readiness --------------------------------------------------------------------------------------------


def test_a_supported_target_has_no_openpose_refusal() -> None:
    readiness = _assess(_pack(POSE), SDXL)

    assert readiness.clean and not readiness.refusals
    assert "openpose_target_unverified_checked_at_preview" not in readiness.notes


@pytest.mark.parametrize("target", [KLEIN])
def test_an_unsupported_target_is_a_named_refusal_for_the_row(target: str) -> None:
    readiness = _assess(_pack(POSE), target)

    assert not readiness.clean
    assert any(item.startswith("row 1:") and "does not support ControlNet" in item for item in readiness.refusals)


def test_a1111_is_a_refusal() -> None:
    readiness = _assess(_pack(POSE), SDXL, backend="a1111_webui")

    assert any("Forge WebUI backend" in item for item in readiness.refusals)


def test_an_unidentified_checkpoint_is_a_note_not_a_false_refusal() -> None:
    readiness = _assess(_pack(POSE), MYSTERY)

    assert readiness.refusals == ()
    assert "openpose_target_unverified_checked_at_preview" in readiness.notes


def test_a_disabled_declaration_is_never_a_refusal() -> None:
    readiness = _assess(_pack({**POSE, "enabled": False}), KLEIN)

    assert readiness.refusals == ()


def test_structure_flags_an_invalid_declaration_and_a_missing_model() -> None:
    invalid = validate_pack_structure(_pack({**POSE, "weight": 9}))
    unmodelled = validate_pack_structure(_pack({**POSE, "model": ""}))
    garbage = validate_pack_structure(_pack("not-an-object"))

    assert not invalid.valid and "Slot 1: OpenPose conditioning is invalid" in invalid.errors[0]
    assert unmodelled.valid and any("no ControlNet model" in item for item in unmodelled.warnings)
    assert not garbage.valid


def test_validation_never_edits_the_pack() -> None:
    model = _pack(POSE)
    before = json.dumps(model.slots[0].openpose, sort_keys=True)

    _assess(model, KLEIN)

    assert json.dumps(model.slots[0].openpose, sort_keys=True) == before


