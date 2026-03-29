import tkinter as tk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.dropdown_loader_v2 import DropdownLoader
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
        return {"run_mode": "queue"}


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
        "hypernetworks": ["hyper-a"],
        "embeddings": ["embed-a"],
    }

    app_state.set_resources(resources)

    txt_card = tab.stage_cards_panel.txt2img_card
    img_card = tab.stage_cards_panel.img2img_card
    base_panel = tab.sidebar.base_generation_panel

    assert txt_card.vae_var is base_panel.vae_var
    assert txt_card.model_var is base_panel.model_var

    assert list(img_card.sampler_combo["values"]) == resources["samplers"]
    hires_values = list(txt_card.hires_upscaler_combo["values"])
    for upscaler in resources["upscalers"]:
        assert upscaler in hires_values
    assert "SDXL Refiner" in list(txt_card.refiner_model_combo["values"])
    assert app_state.resources["hypernetworks"] == ["hyper-a"]
    assert app_state.resources["embeddings"] == ["embed-a"]

    root.destroy()


def test_dropdown_loader_keeps_no_vae_option_on_refresh():
    loader = DropdownLoader()

    assert loader._combo_options(["vae1"], resource_key="vaes") == (
        "No VAE (model default)",
        "vae1",
    )
    assert loader._combo_options(
        ["No VAE (model default)", "vae1"],
        resource_key="vaes",
    ) == (
        "No VAE (model default)",
        "vae1",
    )
