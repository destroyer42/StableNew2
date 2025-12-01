from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2


class DummyPipelinePanel:
    def __init__(self):
        self.applied = []

    def apply_run_config(self, config):
        self.applied.append(config)


class DummyConfigManager:
    def __init__(self, preset: dict[str, Any]) -> None:
        self.preset = preset
        self.listed = ["demo"]

    def list_presets(self) -> list[str]:
        return list(self.listed)

    def load_preset(self, name: str) -> dict[str, Any] | None:
        if name == "demo":
            return dict(self.preset)
        return None

    def set_default_preset(self, name: str) -> bool:
        return True


@pytest.fixture
def controller():
    preset = {
        "txt2img": {"steps": 25},
        "pipeline": {"txt2img_enabled": False, "upscale_enabled": True},
        "randomization_enabled": True,
        "max_variants": 4,
    }
    cm = DummyConfigManager(preset)
    controller = AppController(None, threaded=False, config_manager=cm)
    controller.app_state = AppStateV2()
    controller.main_window = SimpleNamespace(pipeline_config_panel_v2=DummyPipelinePanel())
    return controller, cm


def test_on_apply_to_default_updates_run_config(controller):
    controller, cm = controller
    controller.on_pipeline_preset_apply_to_default("demo")
    assert controller.app_state.run_config.get("pipeline", {}).get("txt2img_enabled") is False
    assert controller.main_window.pipeline_config_panel_v2.applied[-1]["randomization_enabled"]


def test_apply_to_default_missing_runs_safely(controller):
    controller, _ = controller
    controller.on_pipeline_preset_apply_to_default("missing")
    assert controller.app_state.run_config == {}
