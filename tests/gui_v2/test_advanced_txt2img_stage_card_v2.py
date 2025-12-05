"""Tests for AdvancedTxt2ImgStageCardV2."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2


@pytest.mark.gui
def test_advanced_txt2img_stage_card_creation(tk_root: tk.Tk) -> None:
    """Test that creating the card does not crash."""
    card = AdvancedTxt2ImgStageCardV2(tk_root, controller=None)
    assert card is not None
    assert card.winfo_exists()


@pytest.mark.gui
def test_advanced_txt2img_stage_card_refiner_slider_has_value_label(tk_root: tk.Tk) -> None:
    """Test that the refiner strength slider has an associated numeric label."""
    card = AdvancedTxt2ImgStageCardV2(tk_root, controller=None)

    # Check that _refiner_slider exists and is a LabeledSlider
    assert hasattr(card, "_refiner_slider")
    slider = card._refiner_slider

    # LabeledSlider should have a _value_label
    assert hasattr(slider, "_value_label")
    value_label = slider._value_label
    assert value_label.winfo_exists()

    # The label should show a percentage
    label_text = value_label.cget("text")
    assert "%" in label_text


@pytest.mark.gui
def test_advanced_txt2img_stage_card_refiner_slider_value_updates(tk_root: tk.Tk) -> None:
    """Test that updating the refiner slider variable causes the numeric label to change."""
    card = AdvancedTxt2ImgStageCardV2(tk_root, controller=None)

    slider = card._refiner_slider
    value_label = slider._value_label

    # Set initial value
    card.refiner_switch_var.set(50)
    tk_root.update_idletasks()

    label_text = value_label.cget("text")
    assert "50%" in label_text

    # Change value
    card.refiner_switch_var.set(75)
    tk_root.update_idletasks()

    label_text = value_label.cget("text")
    assert "75%" in label_text


@pytest.mark.gui
def test_advanced_txt2img_stage_card_hires_denoise_slider_has_value_label(tk_root: tk.Tk) -> None:
    """Test that the hires denoise slider has an associated numeric label."""
    card = AdvancedTxt2ImgStageCardV2(tk_root, controller=None)

    # Check that _hires_denoise_slider exists and is a LabeledSlider
    assert hasattr(card, "_hires_denoise_slider")
    slider = card._hires_denoise_slider

    # LabeledSlider should have a _value_label
    assert hasattr(slider, "_value_label")
    value_label = slider._value_label
    assert value_label.winfo_exists()


@pytest.mark.gui
def test_advanced_txt2img_stage_card_hires_denoise_slider_value_updates(tk_root: tk.Tk) -> None:
    """Test that updating the hires denoise slider variable causes the numeric label to change."""
    card = AdvancedTxt2ImgStageCardV2(tk_root, controller=None)

    slider = card._hires_denoise_slider
    value_label = slider._value_label

    # Set initial value
    card.hires_denoise_var.set(0.35)
    tk_root.update_idletasks()

    label_text = value_label.cget("text")
    assert "0.35" in label_text

    # Change value
    card.hires_denoise_var.set(0.70)
    tk_root.update_idletasks()

    label_text = value_label.cget("text")
    assert "0.70" in label_text
