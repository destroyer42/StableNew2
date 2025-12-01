from __future__ import annotations

import tkinter as tk
from typing import Any

import pytest

from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel


class FakeController:
    def __init__(self) -> None:
        self.toggle_calls: list[bool] = []
        self.max_variant_values: list[int] = []

    def get_current_config(self) -> dict[str, Any]:
        return {"pipeline": {}}

    def on_randomization_toggled(self, enabled: bool) -> None:
        self.toggle_calls.append(enabled)

    def on_randomizer_max_variants_changed(self, value: int) -> None:
        self.max_variant_values.append(value)


@pytest.mark.gui
def test_randomizer_panel_updates_controller_and_config() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        controller = FakeController()
        panel = PipelineConfigPanel(root, controller=controller, on_change=lambda: None)

        # Check spinbox initially disabled when randomization is off
        assert panel._max_variants_spinbox is not None
        state = str(panel._max_variants_spinbox.cget("state"))
        assert "disabled" in state

        # Enable randomization and ensure controller sees the toggle
        panel.randomizer_enabled_var.set(True)
        panel._on_randomizer_toggle()
        assert controller.toggle_calls == [True]
        assert str(panel._max_variants_spinbox.cget("state")) == "normal"

        # Change max variants via the spinbox handler
        panel.max_variants_var.set(5)
        panel._on_max_variants_change()
        assert 5 in controller.max_variant_values

        config = panel.get_randomizer_config()
        assert config["randomization_enabled"] is True
        assert config["max_variants"] == 5
    finally:
        root.destroy()
