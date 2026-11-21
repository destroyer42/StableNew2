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
    assert list(base_panel._scheduler_combo["values"]) == resources["schedulers"]
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


@pytest.mark.gui
def test_base_picker_uses_component_catalog_and_preserves_exact_backend_values(tk_root):
    from src.api.webui_resources import WebUIResource, WebUIResourceType
    from src.assets.component_evidence import (
        ROLE_BUNDLED,
        ROLE_TEXT_ENCODER,
        ROLE_VAE,
        ComponentEvidence,
    )
    from src.assets.picker_compatibility import PickerEvidence
    from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1

    def resource(kind, name, label, role, **evidence):
        facts = {"vae_family": "ldm_kl_4ch"} if role == ROLE_VAE else {}
        return WebUIResource(kind, name, label, picker=PickerEvidence(ComponentEvidence(role, facts=facts), **evidence))

    model = WebUIResourceType.MODEL
    vae = WebUIResourceType.VAE
    x = resource(model, "xl.safetensors", "XL [hash]", ROLE_BUNDLED, family="sdxl")
    one = resource(model, "one.safetensors", "One", ROLE_BUNDLED, family="sd1")
    refused = resource(model, "refused.safetensors", "Refused", ROLE_BUNDLED, refusal="Existing refusal")
    klein_name = KLEIN_PROFILE_V1.transformer.filename
    klein = resource(model, klein_name, klein_name, ROLE_BUNDLED)
    text = resource(model, "encoder.safetensors", "Encoder", ROLE_TEXT_ENCODER, excluded=True)
    x_vae = resource(vae, "xl_backend.safetensors", "XL VAE", ROLE_VAE, family="sdxl")
    one_vae = resource(vae, "one_backend.safetensors", "One VAE", ROLE_VAE, family="sd1")
    unknown = resource(vae, "vae_backend.safetensors", "Ambiguous", ROLE_VAE)
    resources = {"models": [x, one, refused, klein, text], "vaes": [x_vae, one_vae, unknown]}

    app_state = AppStateV2()
    tab = PipelineTabFrame(tk_root, app_state=app_state, pipeline_controller=DummyPipelineController())
    panel = tab.sidebar.base_generation_panel
    app_state.set_resources(resources)
    panel.apply_profile_values({"model": x.name, "vae": x_vae.name})
    assert panel.model_var.get() == "XL"
    assert "Encoder" not in panel._model_combo["values"]
    assert tuple(panel._vae_combo["values"]) == ("No VAE (model default)", "XL VAE", "Ambiguous (unverified)")
    assert panel.get_overrides()["vae"] == x_vae.name

    panel.model_var.set("One")
    panel._on_model_chosen()
    assert panel.get_overrides()["vae"] == ""
    assert "reset to model default" in panel._helper_label.cget("text")
    panel.vae_var.set("One VAE")
    panel.model_var.set("XL")
    panel._on_model_chosen()
    assert panel.get_overrides()["vae"] == ""
    panel.vae_var.set("Ambiguous (unverified)")
    assert tab.stage_cards_panel.txt2img_card.to_config_dict()["txt2img"]["vae"] == unknown.name
    app_state.set_resources({"models": [], "vaes": []})
    assert panel.get_overrides()["vae"] == unknown.name

    panel.model_var.set("Refused (unsupported)")
    panel._on_model_chosen()
    assert panel._helper_label.cget("text") == "Existing refusal"

    panel.apply_profile_values({"model": klein_name, "vae": x_vae.name})
    app_state.set_resources(resources)
    assert str(panel._vae_combo.cget("state")) == "disabled"
    assert panel.get_overrides()["vae"] == ""
