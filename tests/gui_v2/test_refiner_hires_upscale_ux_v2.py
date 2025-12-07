"""Tests for PR-GUI-E: Refiner/Hires Fix/Upscale UX Fixes.

This module tests:
- Refiner options visibility toggles with enable checkbox
- Hires Fix options visibility toggles with enable checkbox
- Hires Fix model selector with "Use base model" default
- Numeric indicators on sliders (LabeledSlider)
- Upscale final size calculation
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest


# -----------------------------------------------------------------------------
# Refiner Visibility Tests
# -----------------------------------------------------------------------------

@pytest.mark.gui
def test_refiner_options_hidden_when_disabled() -> None:
    """Refiner options frame should be hidden when refiner is disabled."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Disable refiner
        card.refiner_enabled_var.set(False)
        card._update_refiner_visibility()
        root.update_idletasks()

        # Options frame should be hidden
        assert hasattr(card, "_refiner_options_frame")
        assert card._refiner_options_frame.winfo_ismapped() == 0
    finally:
        root.destroy()


@pytest.mark.gui
def test_refiner_options_shown_when_enabled() -> None:
    """Refiner options frame should be visible when refiner is enabled."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Enable refiner
        card.refiner_enabled_var.set(True)
        card._update_refiner_visibility()
        root.update_idletasks()

        # Options frame should be visible
        assert card._refiner_options_frame.winfo_ismapped() == 1
    finally:
        root.destroy()


@pytest.mark.gui
def test_refiner_visibility_toggles_with_checkbox() -> None:
    """Toggling refiner checkbox should show/hide options."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Start disabled
        card.refiner_enabled_var.set(False)
        card._on_refiner_toggle()
        root.update_idletasks()
        assert card._refiner_options_frame.winfo_ismapped() == 0

        # Toggle to enabled
        card.refiner_enabled_var.set(True)
        card._on_refiner_toggle()
        root.update_idletasks()
        assert card._refiner_options_frame.winfo_ismapped() == 1

        # Toggle back to disabled
        card.refiner_enabled_var.set(False)
        card._on_refiner_toggle()
        root.update_idletasks()
        assert card._refiner_options_frame.winfo_ismapped() == 0
    finally:
        root.destroy()


# -----------------------------------------------------------------------------
# Hires Fix Visibility Tests
# -----------------------------------------------------------------------------

@pytest.mark.gui
def test_hires_options_hidden_when_disabled() -> None:
    """Hires options frame should be hidden when hires is disabled."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Disable hires
        card.hires_enabled_var.set(False)
        card._update_hires_visibility()
        root.update_idletasks()

        # Options frame should be hidden
        assert hasattr(card, "_hires_options_frame")
        assert card._hires_options_frame.winfo_ismapped() == 0
    finally:
        root.destroy()


@pytest.mark.gui
def test_hires_options_shown_when_enabled() -> None:
    """Hires options frame should be visible when hires is enabled."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Enable hires
        card.hires_enabled_var.set(True)
        card._update_hires_visibility()
        root.update_idletasks()

        # Options frame should be visible
        assert card._hires_options_frame.winfo_ismapped() == 1
    finally:
        root.destroy()


# -----------------------------------------------------------------------------
# Hires Model Selector Tests
# -----------------------------------------------------------------------------

@pytest.mark.gui
def test_hires_model_selector_exists() -> None:
    """Hires model selector should exist on the card."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Should have hires model var and combo
        assert hasattr(card, "hires_model_var")
        assert hasattr(card, "_hires_model_combo")
        assert isinstance(card._hires_model_combo, ttk.Combobox)
    finally:
        root.destroy()


@pytest.mark.gui
def test_hires_model_defaults_to_use_base_model() -> None:
    """Hires model selector should default to 'Use base model'."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

        card = AdvancedTxt2ImgStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # First value in combobox should be "Use base model"
        values = card._hires_model_combo["values"]
        assert len(values) > 0
        assert values[0] == card.USE_BASE_MODEL_LABEL
    finally:
        root.destroy()


@pytest.mark.gui
def test_hires_model_use_base_model_label_constant() -> None:
    """Card should define USE_BASE_MODEL_LABEL constant."""
    from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2

    assert hasattr(AdvancedTxt2ImgStageCardV2, "USE_BASE_MODEL_LABEL")
    assert AdvancedTxt2ImgStageCardV2.USE_BASE_MODEL_LABEL == "Use base model"


# -----------------------------------------------------------------------------
# LabeledSlider Numeric Indicator Tests
# -----------------------------------------------------------------------------

@pytest.mark.gui
def test_labeled_slider_shows_numeric_value() -> None:
    """LabeledSlider should display a numeric value label."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.components import LabeledSlider

        var = tk.DoubleVar(value=0.5)
        slider = LabeledSlider(root, variable=var, from_=0.0, to=1.0)
        slider.pack()
        root.update_idletasks()

        # Should have a value label
        assert hasattr(slider, "_value_label")
        assert slider._value_label.winfo_exists()

        # Label text should reflect the variable value
        label_text = slider._value_label.cget("text")
        assert "0.50" in label_text or "0.5" in label_text
    finally:
        root.destroy()


@pytest.mark.gui
def test_labeled_slider_updates_on_change() -> None:
    """LabeledSlider label should update when variable changes."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.components import LabeledSlider

        var = tk.DoubleVar(value=0.5)
        slider = LabeledSlider(root, variable=var, from_=0.0, to=1.0)
        slider.pack()
        root.update_idletasks()

        # Change the variable
        var.set(0.75)
        root.update_idletasks()

        # Label should update
        label_text = slider._value_label.cget("text")
        assert "0.75" in label_text
    finally:
        root.destroy()


@pytest.mark.gui
def test_labeled_slider_shows_percent() -> None:
    """LabeledSlider with show_percent=True should display percentage."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.components import LabeledSlider

        var = tk.DoubleVar(value=50)
        slider = LabeledSlider(root, variable=var, from_=0, to=100, show_percent=True)
        slider.pack()
        root.update_idletasks()

        # Label should show percentage
        label_text = slider._value_label.cget("text")
        assert "50%" in label_text
    finally:
        root.destroy()


# -----------------------------------------------------------------------------
# Upscale Final Size Calculation Tests
# -----------------------------------------------------------------------------

@pytest.mark.gui
def test_upscale_final_size_not_zero() -> None:
    """Upscale final size should not show 0x0 when dimensions are set."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2

        card = AdvancedUpscaleStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Set input dimensions
        card.update_input_dimensions(1024, 1024)
        root.update_idletasks()

        # Final size label should not show 0x0
        label_text = card.final_dimensions_label.cget("text")
        assert "0x0" not in label_text
        assert "0 x 0" not in label_text
    finally:
        root.destroy()


@pytest.mark.gui
def test_upscale_final_size_calculates_correctly() -> None:
    """Upscale final size should correctly calculate width * scale."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2

        card = AdvancedUpscaleStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Set input dimensions and scale
        card.update_input_dimensions(1024, 1024)
        card.factor_var.set(2.0)
        card._update_final_dimensions_display()
        root.update_idletasks()

        # Final size should be 2048x2048
        label_text = card.final_dimensions_label.cget("text")
        assert "2048" in label_text
    finally:
        root.destroy()


@pytest.mark.gui
def test_upscale_final_size_updates_on_scale_change() -> None:
    """Upscale final size should update when scale factor changes."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2

        card = AdvancedUpscaleStageCardV2(root, controller=None)
        card.pack(fill="both", expand=True)
        root.update_idletasks()

        # Set initial dimensions
        card.update_input_dimensions(1024, 1024)
        card.factor_var.set(2.0)
        root.update_idletasks()

        # Change scale
        card.factor_var.set(1.5)
        root.update_idletasks()

        # Final size should update to 1536x1536
        label_text = card.final_dimensions_label.cget("text")
        assert "1536" in label_text
    finally:
        root.destroy()


@pytest.mark.gui
def test_upscale_card_has_update_input_dimensions_method() -> None:
    """Upscale card should have update_input_dimensions method."""
    from src.gui.stage_cards_v2.advanced_upscale_stage_card_v2 import AdvancedUpscaleStageCardV2

    assert hasattr(AdvancedUpscaleStageCardV2, "update_input_dimensions")
    assert callable(AdvancedUpscaleStageCardV2.update_input_dimensions)
