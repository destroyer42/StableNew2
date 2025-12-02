"""Roundtrip tests for stage cards."""

from __future__ import annotations


def test_stage_cards_roundtrip(gui_app_with_dummies):
    gui, _controller, config_manager = gui_app_with_dummies
    panel = gui.pipeline_panel_v2
    base_config = config_manager.get_default_config()
    panel.load_from_config(base_config)
    delta = panel.to_config_delta()
    for key in ("model", "vae", "sampler_name"):
        assert delta["txt2img"][key] == base_config["txt2img"][key]
    assert delta["img2img"]["sampler_name"] == base_config["img2img"]["sampler_name"]
    assert delta["upscale"]["upscaler"] == base_config["upscale"]["upscaler"]
