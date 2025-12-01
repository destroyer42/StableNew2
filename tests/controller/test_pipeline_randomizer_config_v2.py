from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2


class NoopPipelineRunner:
    def run(self, config, cancel_token, log_fn=None):
        return {}


class DummyConfigManager:
    def __init__(self, initial: dict[str, Any]) -> None:
        self.initial = dict(initial)
        self.saved: dict[str, dict[str, Any]] = {}

    def load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        return dict(self.initial)

    def save_pack_config(self, pack_id: str, config: dict[str, Any]) -> bool:
        self.saved[pack_id] = dict(config)
        return True


class StubPipelineConfigPanel:
    def __init__(self) -> None:
        self.applied_configs: list[dict[str, Any]] = []
        self.randomizer_config: dict[str, Any] = {"randomization_enabled": False, "max_variants": 1}

    def apply_run_config(self, config: dict[str, Any]) -> None:
        self.applied_configs.append(dict(config))

    def get_randomizer_config(self) -> dict[str, Any]:
        return dict(self.randomizer_config)


def _make_controller(config: dict[str, Any]) -> tuple[AppController, DummyConfigManager, StubPipelineConfigPanel]:
    config_manager = DummyConfigManager(config)
    controller = AppController(
        None,
        pipeline_runner=NoopPipelineRunner(),
        threaded=False,
        config_manager=config_manager,
    )
    controller.app_state = AppStateV2()
    controller.get_available_models = lambda: ["model-a"]
    controller.get_available_samplers = lambda: ["sampler-a"]
    controller.state.current_config.model_name = "model-a"
    controller.state.current_config.sampler_name = "sampler-a"
    panel = StubPipelineConfigPanel()
    controller.main_window = SimpleNamespace(pipeline_config_panel_v2=panel)
    return controller, config_manager, panel


def test_load_randomizer_settings_apply_to_panel() -> None:
    config = {"randomization_enabled": True, "max_variants": 5}
    controller, _, panel = _make_controller(config)

    controller.on_pipeline_pack_load_config("pack1")

    assert panel.applied_configs
    assert panel.applied_configs[-1]["randomization_enabled"] is True
    assert panel.applied_configs[-1]["max_variants"] == 5
    assert controller.state.current_config.randomization_enabled is True
    assert controller.state.current_config.max_variants == 5


def test_apply_config_writes_randomizer_settings_to_pack() -> None:
    controller, config_manager, panel = _make_controller({})
    panel.randomizer_config = {"randomization_enabled": True, "max_variants": 8}

    controller.on_pipeline_pack_apply_config(["pack-x"])

    saved = config_manager.saved.get("pack-x", {})
    assert saved.get("randomization_enabled") is True
    assert saved.get("max_variants") == 8


def test_add_packs_to_job_snapshots_randomizer_settings() -> None:
    controller, _, _ = _make_controller({})
    controller.app_state.set_run_config({"randomization_enabled": True, "max_variants": 6})
    controller._find_pack_by_id = lambda pack_id: SimpleNamespace(name=pack_id)

    controller.on_pipeline_add_packs_to_job(["pack-7"])

    entries = controller.app_state.job_draft.packs
    assert entries
    assert entries[0].config_snapshot["randomization_enabled"] is True
    assert entries[0].config_snapshot["max_variants"] == 6
