"""Tests for ConfigPanel GUI."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.config_panel import ConfigPanel


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on environment
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def test_refresh_populates_widgets(tk_root):
    changes: list[tuple[str, str]] = []

    def on_change(field, value):
        changes.append((field, str(value)))

    panel = ConfigPanel(tk_root, on_change)

    config = {
        "model": "StableNew-XL",
        "sampler": "Euler",
        "width": 1024,
        "height": 768,
        "steps": 25,
        "cfg_scale": 8.5,
    }
    models = ["StableNew-XL", "SDXL-Lightning"]
    samplers = ["Euler", "DPM++ 2M"]

    panel.refresh_from_controller(config, models, samplers)

    assert panel.model_var.get() == "StableNew-XL"
    assert panel.sampler_var.get() == "Euler"
    assert panel.width_var.get() == "1024"
    assert panel.height_var.get() == "768"
    assert panel.steps_var.get() == "25"
    assert panel.cfg_var.get() == "8.5"

    panel.model_var.set("SDXL-Lightning")
    panel._handle_model_change(None)
    panel.sampler_var.set("DPM++ 2M")
    panel._handle_sampler_change(None)
    panel.width_var.set("832")
    panel.height_var.set("640")
    panel._handle_resolution_change(None)
    panel.steps_var.set("32")
    panel._handle_steps_change(None)
    panel.cfg_var.set("11.0")
    panel._handle_cfg_change(None)

    assert ("model", "SDXL-Lightning") in changes
    assert ("sampler", "DPM++ 2M") in changes
    assert ("width", "832") in changes
    assert ("height", "640") in changes
    assert ("steps", "32") in changes
    assert ("cfg_scale", "11.0") in changes
