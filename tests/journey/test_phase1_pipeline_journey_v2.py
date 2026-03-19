from __future__ import annotations

import tkinter as tk
import time
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import PackJobEntry
from src.gui.main_window_v2 import MainWindowV2
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service_with_queue


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
    job_service, job_queue, _ = make_stubbed_job_service_with_queue()
    controller = AppController(None, threaded=False, pipeline_runner=None, job_service=job_service)
    controller.resource_service = FakeResourceService()
    controller.app_state.add_packs_to_job_draft(
        [
            PackJobEntry(
                pack_id="learning_phase1_pack",
                pack_name="learning_phase1_pack",
                config_snapshot={
                    "prompt": "phase1 journey prompt",
                    "model": "model_a",
                    "sampler": "Sampler A",
                    "steps": 20,
                    "width": 512,
                    "height": 512,
                },
            )
        ]
    )

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
        deadline = time.time() + 1.0
        while len(job_queue.list_jobs()) < 1 and time.time() < deadline:
            tk_root.update()
            time.sleep(0.01)

        jobs = job_queue.list_jobs()
        assert len(jobs) == 1
        submitted_job = jobs[0]
        assert submitted_job.run_mode == "queue"
        assert submitted_job.prompt_pack_id == "learning_phase1_pack"
    finally:
        window.cleanup()
