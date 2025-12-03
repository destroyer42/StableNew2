import tkinter as tk
import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


class DummyPipelineController:
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


@pytest.mark.gui
def test_pipeline_dropdown_refresh_updates_stage_cards():
    root = tk.Tk()
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
    assert list(txt_card.vae_combo["values"]) == resources["vaes"]
    assert list(txt_card.sampler_combo["values"]) == resources["samplers"]
    assert list(txt_card.scheduler_combo["values"]) == resources["schedulers"]

    assert list(img_card.sampler_combo["values"]) == resources["samplers"]
    assert list(txt_card.hires_upscaler_combo["values"]) == resources["upscalers"]
    assert list(txt_card.refiner_model_combo["values"]) == ["SDXL Refiner"]

    root.destroy()
