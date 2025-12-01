from __future__ import annotations

import tkinter as tk

import pytest

from src.app_factory import build_v2_app


@pytest.mark.gui
def test_pipeline_preset_dropdown_applies_to_run_config():
    root = tk.Tk()
    root.withdraw()
    _, app_state, controller, window = build_v2_app(root=root)

    preset = {
        "pipeline": {"txt2img_enabled": False, "upscale_enabled": True},
        "randomization_enabled": True,
    }

    controller._config_manager.load_preset = lambda name: preset if name == "demo" else None
    controller._config_manager.list_presets = lambda: ["demo"]

    sidebar = window.pipeline_tab.sidebar
    sidebar.config_manager.load_preset = controller._config_manager.load_preset
    sidebar.config_manager.list_presets = controller._config_manager.list_presets
    sidebar._populate_preset_combo()

    sidebar.preset_var.set("demo")
    sidebar._on_preset_selected()
    sidebar._on_preset_apply_to_default()

    assert app_state.run_config.get("pipeline", {}).get("txt2img_enabled") is False

    root.destroy()
