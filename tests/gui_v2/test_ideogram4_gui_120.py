"""PR-IMG-120: Ideogram 4 appears as one Base Generation model entry only when installed; its policy projects cleanly."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui_v2.model_policy_projection import project_model_controls
from src.image_backends import model_backend_routing as routing
from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1 as P
from src.image_backends.diffusers_readiness import InstallationStatus
from src.image_backends.model_policy import ControlMode, resolve_model_policy

SDXL = "sdxl_a.safetensors"


def _installed(monkeypatch: pytest.MonkeyPatch, ready: bool) -> None:
    import src.image_backends.diffusers_readiness as readiness

    status = InstallationStatus(ready, () if ready else ("weights missing",), None)
    monkeypatch.setattr(readiness, "check_installation", lambda *a, **k: status)


def test_offer_follows_the_installation_and_survives_a_broken_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _installed(monkeypatch, True)
    assert routing.offered_backend_models() == ((P.display_name, P.model_name),)
    _installed(monkeypatch, False)
    assert routing.offered_backend_models() == ()

    def broken():
        raise OSError("cache unreadable")

    monkeypatch.setattr(routing, "_OFFERS", (broken,))
    assert routing.offered_backend_models() == ()


@pytest.mark.parametrize("ready", [True, False])
def test_base_generation_lists_ideogram_only_when_installed(
    tk_root: tk.Tk, monkeypatch, ready: bool
) -> None:
    _installed(monkeypatch, ready)
    panel = BaseGenerationPanelV2(tk_root, models=[SDXL], samplers=["Euler"], include_vae=True)
    try:
        values = panel._build_model_values()
        assert (P.display_name in values) is ready and SDXL in values
        if ready:
            assert panel._model_name_map[P.display_name] == P.model_name
    finally:
        panel.destroy()


def test_policy_projection_locks_fixed_values_and_never_blocks_on_the_webui_setting() -> None:
    policy = resolve_model_policy(P.model_name)
    for backend_id in ("forge_webui", "a1111_webui", None):
        projection = project_model_controls(policy, backend_id, model_name=P.model_name)
        assert projection.blocking == ""
        assert projection.controls["sampler"].mode is ControlMode.FIXED
        assert projection.controls["cfg_scale"].value == P.cfg_scale
        assert [(w, h) for _label, w, h in projection.presets] == list(P.geometries)
        assert "Non-commercial" in projection.note
