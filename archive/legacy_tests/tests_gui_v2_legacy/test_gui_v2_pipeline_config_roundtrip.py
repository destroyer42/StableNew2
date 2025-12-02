"""Tests covering PipelinePanelV2 <-> config roundtrip behavior."""

from __future__ import annotations

from types import SimpleNamespace


def test_pipeline_panel_loads_initial_config(gui_app_with_dummies):
    app, _controller, config_manager = gui_app_with_dummies
    panel = app.pipeline_panel_v2
    base_cfg = config_manager.get_default_config()

    txt_card = panel.txt2img_card
    txt_cfg = base_cfg["txt2img"]
    assert txt_card.model_var.get() == txt_cfg["model"]
    assert txt_card.vae_var.get() == txt_cfg["vae"]
    assert txt_card.sampler_var.get() == txt_cfg["sampler_name"]
    assert txt_card.scheduler_var.get() == txt_cfg["scheduler"]
    assert txt_card.steps_var.get() == str(txt_cfg["steps"])
    assert txt_card.cfg_var.get() == str(txt_cfg["cfg_scale"])
    assert txt_card.width_var.get() == str(txt_cfg["width"])
    assert txt_card.height_var.get() == str(txt_cfg["height"])

    img_cfg = base_cfg["img2img"]
    img_card = panel.img2img_card
    assert img_card.sampler_var.get() == img_cfg["sampler_name"]

    up_card = panel.upscale_card
    up_cfg = base_cfg["upscale"]
    assert up_card.upscaler_var.get() == up_cfg["upscaler"]


def test_pipeline_panel_run_roundtrip(gui_app_with_dummies):
    app, controller, _config_manager = gui_app_with_dummies
    panel = app.pipeline_panel_v2

    txt_card = panel.txt2img_card
    txt_card.model_var.set("new_model")
    txt_card.vae_var.set("new_vae")
    txt_card.sampler_var.set("DPM++")
    txt_card.scheduler_var.set("Karras")
    txt_card.steps_var.set("42")
    txt_card.cfg_var.set("9.5")
    txt_card.width_var.set("960")
    txt_card.height_var.set("640")

    app._get_selected_packs = lambda: [SimpleNamespace(name="pack1", stem="pack1")]

    run_button = getattr(app, "run_button", app.run_pipeline_btn)
    run_button.invoke()

    assert controller.start_calls == 1
    run_cfg = controller.last_run_config
    assert run_cfg is not None
    txt2img = run_cfg.get("txt2img") or {}

    assert txt2img["model"] == "new_model"
    assert txt2img["vae"] == "new_vae"
    assert txt2img["sampler_name"] == "DPM++"
    assert txt2img["scheduler"] == "Karras"
    assert txt2img["steps"] == 42
    assert txt2img["cfg_scale"] == 9.5
    assert txt2img["width"] == 960
    assert txt2img["height"] == 640
