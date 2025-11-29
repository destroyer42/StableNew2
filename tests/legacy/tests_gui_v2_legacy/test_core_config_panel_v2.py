import tkinter as tk

import pytest

from src.config import app_config
from src.gui.core_config_panel_v2 import CoreConfigPanelV2


@pytest.mark.usefixtures("tk_root")
def test_core_panel_initializes_from_app_config(tk_root: tk.Tk):
    app_config.set_core_model_name("demo-model")
    app_config.set_core_sampler_name("Euler")
    app_config.set_core_steps(28)
    app_config.set_core_cfg_scale(8.5)
    app_config.set_core_resolution_preset("768x768")

    panel = CoreConfigPanelV2(tk_root)

    assert panel.model_var.get() == "demo-model"
    assert panel.sampler_var.get() == "Euler"
    assert panel.steps_var.get() == "28"
    assert panel.cfg_var.get() == "8.5"
    assert panel.resolution_var.get() == "768x768"


@pytest.mark.usefixtures("tk_root")
def test_core_panel_get_overrides_roundtrip(tk_root: tk.Tk):
    panel = CoreConfigPanelV2(tk_root)
    panel.model_var.set("m2")
    panel.sampler_var.set("DDIM")
    panel.steps_var.set("40")
    panel.cfg_var.set("12.0")
    panel.resolution_var.set("1024x1024")

    overrides = panel.get_overrides()
    assert overrides["model"] == "m2"
    assert overrides["sampler"] == "DDIM"
    assert overrides["steps"] == 40
    assert overrides["cfg_scale"] == pytest.approx(12.0)
    assert overrides["width"] == 1024
    assert overrides["height"] == 1024

    panel.apply_from_overrides({"model": "m3", "resolution_preset": "640x640"})
    assert panel.model_var.get() == "m3"
    assert panel.resolution_var.get() == "640x640"
