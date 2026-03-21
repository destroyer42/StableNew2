from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


@pytest.mark.gui
def test_pipeline_sync_uses_base_generation_for_shared_fields(gui_app_factory) -> None:
    app = gui_app_factory()
    pipeline_tab: PipelineTabFrame = app.pipeline_tab  # type: ignore[assignment]
    if pipeline_tab.state_manager is None:
        pipeline_tab.state_manager = type("DummyStateManager", (), {"pipeline_overrides": {}})()

    pipeline_tab.sidebar.base_generation_panel.model_var.set("sdxl-base")
    pipeline_tab.sidebar.base_generation_panel.sampler_var.set("Euler")
    pipeline_tab.sidebar.base_generation_panel.width_var.set(1024)
    pipeline_tab.sidebar.base_generation_panel.height_var.set(1024)
    pipeline_tab.stage_cards_panel.txt2img_card.clip_skip_var.set(3)

    pipeline_tab._sync_state_overrides()
    overrides = pipeline_tab.state_manager.pipeline_overrides

    assert overrides["model"] == "sdxl-base"
    assert overrides["sampler"] == "Euler"
    assert overrides["width"] == 1024
    assert overrides["height"] == 1024
    assert "metadata" in overrides
    assert "txt2img" in overrides["metadata"]
    assert "clip_skip" in overrides["metadata"]["txt2img"]


@pytest.mark.gui
def test_stage_cards_panel_no_longer_exports_shared_base_fields(gui_app_factory) -> None:
    app = gui_app_factory()
    panel = app.pipeline_tab.stage_cards_panel

    overrides = panel.to_overrides(prompt_text="portrait")

    assert overrides["prompt"] == "portrait"
    for key in ("model", "model_name", "sampler", "width", "height", "steps", "cfg_scale"):
        assert key not in overrides
