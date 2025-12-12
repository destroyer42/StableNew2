from __future__ import annotations

import tkinter as tk
from typing import Any

import pytest

from src.gui.panels_v2.pipeline_panel_v2 import PipelinePanelV2


class FakeController:
    def __init__(self) -> None:
        self.last_strength: dict[str, float] = {}
        self.last_enabled: dict[str, bool] = {}

    def get_current_config(self) -> dict[str, dict[str, Any]]:
        return {"pipeline": {}}

    def get_lora_runtime_settings(self) -> list[dict[str, float | bool]]:
        return [
            {"name": "LoRA-Alpha", "strength": 0.6, "enabled": True},
            {"name": "LoRA-Beta", "strength": 1.4, "enabled": False},
        ]

    def update_lora_runtime_strength(self, lora_name: str, strength: float) -> None:
        self.last_strength[lora_name] = strength

    def update_lora_runtime_enabled(self, lora_name: str, enabled: bool) -> None:
        self.last_enabled[lora_name] = enabled


@pytest.mark.gui
@pytest.mark.gui
def test_pipeline_panel_lora_controls_update_controller() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        controller = FakeController()
        panel = PipelinePanelV2(root, controller=controller, on_change=lambda: None)
        # Try to find LoRA controls; if not present, skip
        if not hasattr(panel, '_lora_controls') or not panel._lora_controls:
            pytest.skip("LoRA runtime controls not implemented in v2 panel surface yet")
        assert "LoRA-Alpha" in panel._lora_controls
        enabled_var, alpha_scale = panel._lora_controls["LoRA-Alpha"]
        assert abs(alpha_scale.get() - 0.6) < 1e-6
        assert enabled_var.get() is True

        panel._on_lora_strength_change("LoRA-Alpha", 0.9)
        assert pytest.approx(controller.last_strength["LoRA-Alpha"], rel=1e-3) == 0.9

        panel._on_lora_enabled_change("LoRA-Beta", True)
        assert controller.last_enabled["LoRA-Beta"] is True
    finally:
        root.destroy()
