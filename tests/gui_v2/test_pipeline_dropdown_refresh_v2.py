import tkinter as tk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


class DummyPipelineController:
    def __init__(self):
        self.state_manager = None

    def list_models(self):
        return []

    def list_vaes(self):
        return []

    def list_upscalers(self):
        return []

    def list_embeddings(self):
        return []

    def get_available_samplers(self):
        return []

    def get_available_schedulers(self):
        return []

    def get_current_config(self):
        return {"run_mode": "direct"}


@pytest.mark.gui
def test_pipeline_dropdown_refresh_updates_stage_cards():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    app_state = AppStateV2()
    controller = DummyPipelineController()
    tab = PipelineTabFrame(root, app_state=app_state, pipeline_controller=controller)

    resources = {
        "models": ["SDXL Base", "SDXL Refiner"],
        "vaes": ["vae1"],
        "samplers": ["samplerA"],
        "schedulers": ["schedulerX"],
        "upscalers": ["Latent", "R-ESRGAN 4x+"],
    }

    app_state.set_resources(resources)

    txt_card = tab.stage_cards_panel.txt2img_card
    img_card = tab.stage_cards_panel.img2img_card

    assert list(txt_card.model_combo["values"]) == resources["models"]
    vae_values = list(txt_card.vae_combo["values"])
    filtered_vae_values = [value for value in vae_values if not value.startswith("No VAE")]
    assert filtered_vae_values == resources["vaes"]
    assert list(txt_card.sampler_combo["values"]) == resources["samplers"]
    assert list(txt_card.scheduler_combo["values"]) == resources["schedulers"]

    assert list(img_card.sampler_combo["values"]) == resources["samplers"]
    assert list(txt_card.hires_upscaler_combo["values"]) == resources["upscalers"]
    assert "SDXL Refiner" in list(txt_card.refiner_model_combo["values"])

    root.destroy()
