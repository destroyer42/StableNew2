from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.utils.config import LoraRuntimeConfig


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


def _make_controller(config: dict[str, any]) -> tuple[AppController, DummyConfigManager]:
    config_manager = DummyConfigManager(config)
    controller = AppController(
        None,
        pipeline_runner=NoopPipelineRunner(),
        threaded=False,
        config_manager=config_manager,
    )
    # Provide AppStateV2 instance rather than GUI stub
    controller.app_state = AppStateV2()
    controller.get_available_models = lambda: ["model-a"]
    controller.get_available_samplers = lambda: ["sampler-a"]
    controller.state.current_config.model_name = "model-a"
    controller.state.current_config.sampler_name = "sampler-a"
    controller._get_selected_pack = (
        lambda: None
    )  # stub since controller helper is missing in test env
    controller.get_current_config = lambda: {
        "model": controller.state.current_config.model_name,
        "sampler": controller.state.current_config.sampler_name,
        "width": controller.state.current_config.width,
        "height": controller.state.current_config.height,
        "steps": controller.state.current_config.steps,
        "cfg_scale": controller.state.current_config.cfg_scale,
    }
    return controller, config_manager


def test_load_lora_strengths_populates_app_state() -> None:
    config = {"lora_strengths": [{"name": "LoRA1", "strength": 0.7, "enabled": True}]}
    controller, _ = _make_controller(config)

    controller.on_pipeline_pack_load_config("pack1")

    assert controller.app_state.lora_strengths
    assert controller.app_state.lora_strengths[0].name == "LoRA1"
    assert controller.app_state.lora_strengths[0].strength == 0.7


def test_apply_config_writes_lora_strengths_to_packs() -> None:
    controller, config_manager = _make_controller({})
    controller.app_state.set_lora_strengths(
        [LoraRuntimeConfig(name="LoRA-A", strength=1.2, enabled=False)]
    )

    controller.on_pipeline_pack_apply_config(["pack-x"])

    saved = config_manager.saved.get("pack-x", {})
    assert saved.get("lora_strengths")
    assert saved["lora_strengths"][0]["name"] == "LoRA-A"


def test_pipeline_payload_includes_lora_settings() -> None:
    controller, _ = _make_controller({})
    controller.app_state.set_lora_strengths(
        [
            LoraRuntimeConfig(name="LoRA-A", strength=0.5, enabled=True),
            LoraRuntimeConfig(name="LoRA-B", strength=1.5, enabled=False),
        ]
    )

    payload = controller._build_pipeline_config()
    assert payload.lora_settings
    assert payload.lora_settings["LoRA-A"]["strength"] == 0.5
    assert payload.lora_settings["LoRA-B"]["enabled"] is False
