from __future__ import annotations

from src.controller.app_controller_services.gui_config_service import GuiConfigService
from src.gui.app_state_v2 import AppStateV2, CurrentConfig
from src.utils.config import LoraRuntimeConfig


def test_gui_config_service_updates_randomizer_via_adapter() -> None:
    app_state = AppStateV2()
    service = GuiConfigService()

    updated = service.update_randomizer(app_state=app_state, enabled=True, max_variants=6)

    assert updated is True
    assert app_state.run_config["randomization_enabled"] is True
    assert app_state.run_config["max_variants"] == 6
    assert app_state.intent_config == {}


def test_gui_config_service_builds_run_config_with_lora_and_prompt_optimizer() -> None:
    app_state = AppStateV2()
    app_state.set_run_config({"model": "sdxl"})
    app_state.lora_strengths = [
        LoraRuntimeConfig(name="detail-xl", strength=0.8, enabled=True),
    ]
    service = GuiConfigService()
    fallback = CurrentConfig(randomization_enabled=True, max_variants=3)

    payload = service.build_run_config_with_lora(
        app_state=app_state,
        fallback_current_config=fallback,
        prompt_optimizer_config={"enabled": True, "dedupe_enabled": True},
    )

    assert payload["model"] == "sdxl"
    assert payload["lora_strengths"][0]["name"] == "detail-xl"
    assert payload["prompt_optimizer"]["enabled"] is True
    assert payload["randomization_enabled"] is True
    assert payload["max_variants"] == 3
