"""PR-IMG-COMFY-100: each Qwen-Image 2.1 variant appears as a Base Generation model entry only when its exact files are
installed; its policy projects fixed values and never blocks on the WebUI-family backend setting."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui_v2.model_policy_projection import project_model_controls
from src.image_backends import comfy_image_readiness as readiness
from src.image_backends import model_backend_routing as routing
from src.image_backends.comfy_image_readiness import ComfyInstallationStatus
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_PROFILE_V1 as BASE
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_TURBO_PROFILE_V1 as TURBO
from src.image_backends.model_policy import ControlMode, resolve_model_policy

SDXL = "sdxl_a.safetensors"


def _installed(monkeypatch: pytest.MonkeyPatch, *installed) -> None:
    import src.image_backends.diffusers_readiness as diffusers_readiness
    from src.image_backends.diffusers_readiness import InstallationStatus

    monkeypatch.setattr(
        diffusers_readiness,
        "check_installation",
        lambda *a, **k: InstallationStatus(False, ("missing",), None),
    )
    monkeypatch.setattr(readiness, "comfy_model_folders", lambda: {})
    monkeypatch.setattr(
        readiness,
        "check_installation",
        lambda profile, **k: ComfyInstallationStatus(
            profile in installed, () if profile in installed else ("x",)
        ),
    )


def test_offers_follow_each_variant_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch)
    assert routing.offered_backend_models() == ()
    _installed(monkeypatch, TURBO)
    assert routing.offered_backend_models() == ((TURBO.display_name, TURBO.model_name),)
    _installed(monkeypatch, BASE, TURBO)
    assert routing.offered_backend_models() == (
        (BASE.display_name, BASE.model_name),
        (TURBO.display_name, TURBO.model_name),
    )


def test_an_unreadable_comfy_configuration_offers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch, BASE)

    def broken():
        raise ValueError("no StableNew-managed ComfyUI launch configuration is set")

    monkeypatch.setattr(readiness, "comfy_model_folders", broken)
    assert routing.offered_backend_models() == ()


@pytest.mark.parametrize("installed", [(), (BASE,), (BASE, TURBO)])
def test_base_generation_lists_qwen_variants_only_when_installed(
    tk_root: tk.Tk, monkeypatch, installed
) -> None:
    _installed(monkeypatch, *installed)
    panel = BaseGenerationPanelV2(tk_root, models=[SDXL], samplers=["Euler"], include_vae=True)
    try:
        values = panel._build_model_values()
        assert SDXL in values
        for profile in (BASE, TURBO):
            assert (profile.display_name in values) is (profile in installed)
            if profile in installed:
                assert panel._model_name_map[profile.display_name] == profile.model_name
    finally:
        panel.destroy()


@pytest.mark.parametrize("profile", [BASE, TURBO])
def test_policy_projection_locks_fixed_values_and_never_blocks_on_the_webui_setting(
    profile,
) -> None:
    policy = resolve_model_policy(profile.model_name)
    for backend_id in ("forge_webui", "a1111_webui", None):
        projection = project_model_controls(policy, backend_id, model_name=profile.model_name)
        assert projection.blocking == ""
        assert projection.controls["sampler"].mode is ControlMode.FIXED
        assert projection.controls["steps"].value == profile.steps
        assert projection.controls["cfg_scale"].value == 1.0
        assert [(w, h) for _label, w, h in projection.presets] == list(profile.geometries)
        assert "Non-commercial" in projection.note
