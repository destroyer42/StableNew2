"""N1 / W8: the Forge ControlNet dispatch check reads the registry's family evidence.

Before the repair ``validate_target`` resolved the model policy without a family lookup, so every ordinary
checkpoint had "no evidence" and ordered ControlNet units were refused at dispatch for models the compiler had
admitted (the integration test patched ``resolve_model_policy`` and hid it). This pins the real lookup seam.
"""

from __future__ import annotations

import pytest

import src.image_backends.forge_controlnet_units as units
from src.image_backends.forge_controlnet import OpenPoseDispatchError
from tests.pipeline.test_openpose_compile_210 import OLD, SDXL, family_lookup


class _Lookup:
    def __call__(self, name: str):
        return family_lookup(name)


@pytest.fixture
def registry_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(units, "RegistryFamilyLookup", _Lookup)


def test_a_registry_verified_sdxl_checkpoint_passes_the_dispatch_check(registry_lookup) -> None:
    units.validate_target(SDXL, "forge_webui", {"image": {"backend_id": "forge_webui"}})


def test_a_registry_sd1_checkpoint_and_an_unknown_one_are_still_refused(registry_lookup) -> None:
    for model in (OLD, "mystery.safetensors"):
        with pytest.raises(OpenPoseDispatchError, match="registry-verified SDXL"):
            units.validate_target(model, "forge_webui", {"image": {"backend_id": "forge_webui"}})
