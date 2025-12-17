import os
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest

from src.gui.app_state_v2 import CurrentConfig
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.learning.model_profiles import get_model_profile_defaults_for_model

# Setup TCL/TK environment variables at module load time
if sys.platform.startswith("win"):
    tcl_library = os.environ.get("TCL_LIBRARY")
    tk_library = os.environ.get("TK_LIBRARY")
    if not tcl_library or not tk_library:
        base_dir = os.path.dirname(os.path.abspath(tk.__file__))
        candidate_tcl = os.path.join(base_dir, "tcl", "tcl8.6")
        candidate_tk = os.path.join(base_dir, "tcl", "tk8.6")
        if os.path.isdir(candidate_tcl):
            os.environ.setdefault("TCL_LIBRARY", candidate_tcl)
        if os.path.isdir(candidate_tk):
            os.environ.setdefault("TK_LIBRARY", candidate_tk)


def _create_root() -> tk.Tk:
    """Create a Tk root window with proper environment setup."""
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Tkinter unavailable: {exc}")


class DummyController:
    def __init__(self, state: SimpleNamespace) -> None:
        self.state = state

    def list_models(self) -> list:
        return []

    def list_vaes(self) -> list:
        return []

    def list_upscalers(self) -> list:
        return []


def test_txt2img_card_respects_model_profile_defaults() -> None:
    root = _create_root()
    try:
        current = CurrentConfig()
        current.model_name = "sdxl-base-realism"
        defaults = get_model_profile_defaults_for_model(current.model_name)
        current.refiner_model_name = defaults.get("default_refiner_id", "")
        current.hires_upscaler_name = defaults.get("default_hires_upscaler_id", "Latent")
        current.hires_denoise = defaults.get("default_hires_denoise", 0.3)
        controller_state = SimpleNamespace(current_config=current)
        controller = DummyController(controller_state)

        card = AdvancedTxt2ImgStageCardV2(root, controller=controller)
        card._apply_refiner_hiress_defaults()

        assert card.refiner_model_var.get() == current.refiner_model_name
        assert card.hires_upscaler_var.get() == current.hires_upscaler_name
        assert abs(card.hires_denoise_var.get() - current.hires_denoise) < 1e-6
    finally:
        root.destroy()


def test_txt2img_card_configuration_overrides_update_state() -> None:
    root = _create_root()
    try:
        current = CurrentConfig()
        controller_state = SimpleNamespace(current_config=current)
        controller = DummyController(controller_state)
        card = AdvancedTxt2ImgStageCardV2(root, controller=controller)

        card.refiner_model_var.set("custom-refiner")
        card._on_refiner_model_changed()
        assert controller_state.current_config.refiner_model_name == "custom-refiner"

        card.hires_upscaler_var.set("custom-upscaler")
        card._on_hires_upscaler_changed()
        assert controller_state.current_config.hires_upscaler_name == "custom-upscaler"
    finally:
        root.destroy()
