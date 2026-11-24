"""Storyboard tab layout: the viewer fits, the tree scrolls, the selection and Continue target are clear.

Design: docs/superpowers/specs/2026-11-24-storyboard-viewer-tree-layout-design.md
"""

from __future__ import annotations

from tkinter import ttk

import pytest

from src.gui import theme_v2
from src.gui.design_system_v2 import SELECTED_CARD_FRAME, Colors

pytestmark = pytest.mark.gui


# ---------------------------------------------------------------- Task 1: selected-card style


def test_selected_card_style_has_a_thick_accent_border(tk_root):
    style = theme_v2.apply_theme(tk_root)
    assert style.lookup(SELECTED_CARD_FRAME, "bordercolor") == Colors.PRIMARY_ACCENT
    assert int(style.lookup(SELECTED_CARD_FRAME, "borderwidth")) >= 3
    assert int(style.lookup("Card.TFrame", "borderwidth")) == 1
    assert isinstance(style, ttk.Style)


# ---------------------------------------------------------------- Task 2: the viewer fits its picture

import time  # noqa: E402

from PIL import Image  # noqa: E402

from src.gui.widgets.storyboard_viewer_v2 import MIN_IMAGE_HEIGHT, StoryboardViewerV2, fit_size  # noqa: E402


def _settle(root, seconds: float = 0.15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


def _viewer(root, width: int = 400, height: int = 300) -> StoryboardViewerV2:
    root.geometry(f"{width}x{height}")
    root.deiconify()  # a withdrawn window never maps its children, so no real sizes
    viewer = StoryboardViewerV2(
        root,
        on_frame=lambda _i: None,
        on_continue=lambda _i: None,
        readout=lambda i: f"frame {i + 1}",
    )
    viewer.pack(fill="both", expand=True)
    viewer.set_cut(5, (), 16)
    _settle(root)
    return viewer


def test_fit_size_keeps_aspect_and_never_upscales():
    assert fit_size((800, 400), (400, 400)) == (400, 200)
    assert fit_size((16, 8), (400, 400)) == (16, 8)


def test_fit_size_never_returns_zero():
    for source, box in (((800, 400), (0, 0)), ((0, 0), (10, 10)), ((800, 400), (-5, 3))):
        width, height = fit_size(source, box)
        assert width >= 1 and height >= 1


def test_viewer_picture_is_scaled_to_a_short_window(tk_root):
    viewer = _viewer(tk_root, 400, 300)
    viewer.show_image(Image.new("RGB", (800, 600)))
    _settle(tk_root)
    assert viewer._photo is not None
    assert viewer._photo.height() <= viewer.image_area.winfo_height()
    assert viewer._photo.width() <= viewer.image_area.winfo_width()
    for control in (viewer.slider, viewer.continue_button):
        assert control.winfo_ismapped()
        assert control.winfo_y() + control.winfo_height() <= viewer.winfo_height()


def test_viewer_keeps_controls_when_window_is_too_short_for_the_minimum(tk_root):
    viewer = _viewer(tk_root, 400, 120)
    viewer.show_image(Image.new("RGB", (800, 600)))
    _settle(tk_root)
    assert viewer.image_area.winfo_height() >= 1
    assert MIN_IMAGE_HEIGHT >= 100
    assert viewer.slider.winfo_ismapped() and viewer.continue_button.winfo_ismapped()


def test_viewer_rescales_when_resized(tk_root):
    viewer = _viewer(tk_root, 400, 300)
    viewer.show_image(Image.new("RGB", (800, 600)))
    _settle(tk_root)
    small = viewer._photo.height()
    tk_root.geometry("400x600")
    _settle(tk_root, 0.3)
    assert viewer._photo.height() > small


def test_hidden_viewer_drops_a_late_frame(tk_root):
    viewer = _viewer(tk_root)
    viewer.set_media_visible(False)
    viewer.show_image(Image.new("RGB", (8, 8)))
    assert viewer._photo is None
