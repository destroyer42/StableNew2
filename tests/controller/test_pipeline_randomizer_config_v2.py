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


def _make_controller(
    config: dict[str, Any],
) -> tuple[AppController, DummyConfigManager]:
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
    controller.main_window = SimpleNamespace()
    controller._spawn_tracked_thread = lambda *, target, name, purpose: target()
    return controller, config_manager


def test_load_randomizer_settings_apply_to_panel() -> None:
    config = {"randomization_enabled": True, "max_variants": 5}
    controller, _ = _make_controller(config)

    controller.on_pipeline_pack_load_config("pack1")

    assert controller.app_state.run_config["randomization_enabled"] is True
    assert controller.app_state.run_config["max_variants"] == 5
    assert controller.state.current_config.randomization_enabled is True
    assert controller.state.current_config.max_variants == 5


def test_apply_config_writes_randomizer_settings_to_pack() -> None:
    controller, config_manager = _make_controller({})
    controller.app_state.set_run_config({"randomization_enabled": True, "max_variants": 8})

    controller.on_pipeline_pack_apply_config(["pack-x"])

    saved = config_manager.saved.get("pack-x", {})
    assert saved.get("randomization_enabled") is True
    assert saved.get("max_variants") == 8


def test_add_packs_to_job_snapshots_randomizer_settings() -> None:
    controller, _ = _make_controller({})
    controller.app_state.set_run_config({"randomization_enabled": True, "max_variants": 6})
    
    # Mock both the pack finder and pack reader
    from pathlib import Path
    mock_pack = SimpleNamespace(name="pack-7", path=Path("fake/pack-7.json"))
    controller._find_pack_by_id = lambda pack_id: mock_pack
    
    # Mock the pack reading to return a simple prompt
    import src.controller.app_controller as app_controller_module
    original_read_prompt_pack = app_controller_module.read_prompt_pack
    app_controller_module.read_prompt_pack = lambda path: [
        {"positive": "test prompt", "negative": "test negative"}
    ]
    
    try:
        controller.on_pipeline_add_packs_to_job(["pack-7"])

        entries = controller.app_state.job_draft.packs
        assert entries
        assert entries[0].config_snapshot["randomization_enabled"] is True
        assert entries[0].config_snapshot["max_variants"] == 6
    finally:
        # Restore the original function
        app_controller_module.read_prompt_pack = original_read_prompt_pack
