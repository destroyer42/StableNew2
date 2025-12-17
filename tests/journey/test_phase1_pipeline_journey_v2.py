from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


class FakeResourceService:
    def refresh_all(self) -> dict[str, list[object]]:
        model = SimpleNamespace(name="model_a", display_name="Model A")
        vae = SimpleNamespace(name="vae_a", display_name="VAE A")
        return {
            "models": [model],
            "vaes": [vae],
            "samplers": ["Sampler A"],
            "schedulers": ["Scheduler A"],
        }

    def list_models(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="model_a", display_name="Model A")]

    def list_vaes(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="vae_a", display_name="VAE A")]

    def list_upscalers(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="upscaler", display_name="Upscaler A")]


@pytest.mark.gui
def test_phase1_pipeline_journey_v2(tk_root: tk.Tk) -> None:
    runner = FakePipelineRunner()
    controller = AppController(None, threaded=False, pipeline_runner=runner)
    controller.app_state = AppStateV2()
    controller.resource_service = FakeResourceService()

    window = MainWindowV2(
        tk_root,
        app_state=controller.app_state,
        app_controller=controller,
        pipeline_controller=controller,
    )
    try:
        controller.refresh_resources_from_webui()

        stage_cards = window.pipeline_tab.stage_cards_panel
        txt_card = stage_cards.txt2img_card
        sampler_values = tuple(txt_card.sampler_combo["values"])
        assert "Sampler A" in sampler_values
        assert "Model A" in tuple(txt_card.model_combo["values"])
        assert "VAE A" in tuple(txt_card.vae_combo["values"])
        assert "Scheduler A" in tuple(txt_card.scheduler_combo["values"])

        txt_card.model_var.set("Model A")
        txt_card.vae_var.set("VAE A")
        txt_card.sampler_var.set("Sampler A")
        txt_card.scheduler_var.set("Scheduler A")

        controller.state.current_config.model_name = "model_a"
        controller.state.current_config.sampler_name = "Sampler A"
        controller.state.current_config.width = 512
        controller.state.current_config.height = 512
        controller.state.current_config.steps = 20
        controller.state.current_config.cfg_scale = 7.0

        controller.on_run_clicked()
        assert len(runner.run_calls) == 1
        config = runner.run_calls[0].config
        assert config.model == "model_a"
        assert config.sampler == "Sampler A"
    finally:
        window.cleanup()
