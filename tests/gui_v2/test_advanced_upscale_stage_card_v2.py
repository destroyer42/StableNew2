"""Tests for AdvancedUpscaleStageCardV2."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2


@pytest.mark.gui
def test_advanced_upscale_stage_card_creation(tk_root: tk.Tk) -> None:
    """Test that creating the card does not crash."""
    card = AdvancedUpscaleStageCardV2(tk_root, controller=None)
    assert card is not None
    assert card.winfo_exists()


@pytest.mark.gui
def test_advanced_upscale_stage_card_final_size_not_zero(tk_root: tk.Tk) -> None:
    """Test that final size label is not '0x0' with valid dimensions."""
    card = AdvancedUpscaleStageCardV2(tk_root, controller=None)

    # Card initializes with 512x512 and factor 2.0
    # So final size should be 1024x1024
    assert card.final_dimensions_label is not None
    label_text = card.final_dimensions_label.cget("text")
    assert label_text != "0x0"
    assert "1024x1024" in label_text


@pytest.mark.gui
def test_advanced_upscale_stage_card_final_size_updates_on_scale_change(tk_root: tk.Tk) -> None:
    """Test that final size changes when the scale factor is changed."""
    card = AdvancedUpscaleStageCardV2(tk_root, controller=None)

    # Set base dimensions
    card.update_input_dimensions(512, 512)
    tk_root.update_idletasks()

    # Initial scale is 2.0, so final is 1024x1024
    label_text = card.final_dimensions_label.cget("text")
    assert "1024x1024" in label_text

    # Change scale to 3.0
    card.factor_var.set(3.0)
    tk_root.update_idletasks()

    # Final should be 1536x1536
    label_text = card.final_dimensions_label.cget("text")
    assert "1536x1536" in label_text


@pytest.mark.gui
def test_advanced_upscale_stage_card_final_size_updates_on_dimension_change(tk_root: tk.Tk) -> None:
    """Test that final size updates when input dimensions change."""
    card = AdvancedUpscaleStageCardV2(tk_root, controller=None)

    # Set scale
    card.factor_var.set(2.0)
    tk_root.update_idletasks()

    # Update input dimensions
    card.update_input_dimensions(768, 768)
    tk_root.update_idletasks()

    # Final should be 1536x1536
    label_text = card.final_dimensions_label.cget("text")
    assert "1536x1536" in label_text


@pytest.mark.gui
def test_advanced_upscale_stage_card_dark_mode_spinboxes(tk_root: tk.Tk) -> None:
    """Test that spinboxes use dark mode style."""
    card = AdvancedUpscaleStageCardV2(tk_root, controller=None)

    # Check that scale spinbox has dark style
    assert hasattr(card, "_scale_spinbox")
    spinbox = card._scale_spinbox
    # ttk.Spinbox should have Dark.TSpinbox style
    style = spinbox.cget("style")
    assert style == "Dark.TSpinbox"


@pytest.mark.gui
def test_advanced_upscale_stage_card_graceful_fallback_for_zero_dimensions(tk_root: tk.Tk) -> None:
    """Test that final size shows graceful fallback for zero dimensions."""
    card = AdvancedUpscaleStageCardV2(tk_root, controller=None)

    # Set zero dimensions
    card.update_input_dimensions(0, 0)
    tk_root.update_idletasks()

    # Final should show fallback, not "0x0"
    label_text = card.final_dimensions_label.cget("text")
    assert "0x0" not in label_text
    assert "—" in label_text or "x" in label_text
