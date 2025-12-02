"""Validation tests for GUI v2 txt2img configuration."""

from __future__ import annotations

import tkinter as tk
from copy import deepcopy

import pytest

from src.gui_v2.validation.pipeline_txt2img_validator import validate_txt2img
from tests.gui_v2.conftest import DEFAULT_TXT2IMG_CFG


# --- Pure validator tests -------------------------------------------------


def test_validator_accepts_valid_config():
    cfg = deepcopy(DEFAULT_TXT2IMG_CFG)
    result = validate_txt2img(cfg)
    assert result.is_valid
    assert result.errors == {}


def test_validator_rejects_invalid_steps_and_cfg_scale():
    cfg = deepcopy(DEFAULT_TXT2IMG_CFG)
    cfg["steps"] = 0
    cfg["cfg_scale"] = 99
    result = validate_txt2img(cfg)
    assert not result.is_valid
    assert "steps" in result.errors
    assert "cfg_scale" in result.errors


def test_validator_rejects_invalid_dimensions_and_missing_strings():
    cfg = deepcopy(DEFAULT_TXT2IMG_CFG)
    cfg["width"] = 255
    cfg["height"] = 2000
    cfg["model"] = ""
    cfg["sampler_name"] = ""
    cfg["scheduler"] = ""
    cfg["vae"] = ""
    result = validate_txt2img(cfg)
    assert not result.is_valid
    assert "width" in result.errors
    assert "height" in result.errors
    assert "model" in result.errors
    assert "sampler_name" in result.errors
    assert "scheduler" in result.errors
    assert "vae" in result.errors


# --- GUI wiring tests -----------------------------------------------------


@pytest.mark.usefixtures("tk_root")
def test_run_button_disabled_when_invalid(gui_app_with_dummies):
    gui, controller, _ = gui_app_with_dummies
    gui.pipeline_panel_v2.txt2img_card.steps_var.set("0")
    gui.root.update_idletasks()

    assert str(gui.run_button["state"]).lower() == "disabled"
    assert "Config Error" in gui.status_bar_v2.status_label["text"]

    # Fix the value and ensure the status clears and button re-enables.
    gui.pipeline_panel_v2.txt2img_card.steps_var.set("10")
    gui.root.update_idletasks()
    assert str(gui.run_button["state"]).lower() == "normal"
    assert "Config Error" not in gui.status_bar_v2.status_label["text"]


@pytest.mark.usefixtures("tk_root")
def test_run_guard_blocks_invalid_config(gui_app_with_dummies, monkeypatch):
    gui, controller, _ = gui_app_with_dummies

    invoked = {"called": False}

    def fake_run(self):
        invoked["called"] = True

    monkeypatch.setattr(type(gui), "_run_full_pipeline_impl", fake_run, raising=False)

    gui.pipeline_panel_v2.txt2img_card.width_var.set("123")
    gui.root.update_idletasks()
    gui.run_button.invoke()

    assert invoked["called"] is False
    assert controller.start_calls == 0
    assert "Config Error" in gui.status_bar_v2.status_label["text"]

    gui.pipeline_panel_v2.txt2img_card.width_var.set("768")
    gui.root.update_idletasks()
    gui.run_button.invoke()

    assert str(gui.run_button["state"]).lower() == "normal"
    assert invoked["called"] is True
