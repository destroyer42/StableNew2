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
    pipeline_tab.sidebar.base_generation_panel.steps_var.set(33)
    pipeline_tab.sidebar.base_generation_panel.cfg_var.set(8.5)
    pipeline_tab.sidebar.base_generation_panel.width_var.set(1024)
    pipeline_tab.sidebar.base_generation_panel.height_var.set(1024)
    pipeline_tab.stage_cards_panel.txt2img_card.clip_skip_var.set(3)

    pipeline_tab._sync_state_overrides()
    overrides = pipeline_tab.state_manager.pipeline_overrides

    assert overrides["model"] == "sdxl-base"
    assert overrides["sampler"] == "Euler"
    assert overrides["steps"] == 33
    assert overrides["cfg_scale"] == 8.5
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


@pytest.mark.gui
def test_base_generation_dimensions_and_subseed_export_authoritative_overrides(
    gui_app_factory,
) -> None:
    app = gui_app_factory()
    base_generation = app.pipeline_tab.sidebar.base_generation_panel

    base_generation.resolution_preset_var.set("1024x1024 (1:1)")
    base_generation.width_var.set("1111")
    base_generation.height_var.set("777")
    base_generation.subseed_var.set("123456")
    base_generation.subseed_strength_var.set("0.35")
    base_generation._on_dimension_commit()

    overrides = base_generation.get_overrides()

    assert overrides["width"] == 1111
    assert overrides["height"] == 777
    assert overrides["resolution_preset"] == "1111x777"
    assert overrides["subseed"] == 123456
    assert overrides["subseed_strength"] == 0.35


@pytest.mark.gui
def test_base_generation_steps_and_cfg_do_not_overlap_resolution_row(gui_app_factory) -> None:
    app = gui_app_factory()
    base_generation = app.pipeline_tab.sidebar.base_generation_panel

    steps_row = int(base_generation._steps_spin.grid_info()["row"])
    cfg_row = int(base_generation._cfg_spin.grid_info()["row"])
    width_row = int(base_generation._width_combo.grid_info()["row"])

    assert steps_row == cfg_row
    assert steps_row < width_row
