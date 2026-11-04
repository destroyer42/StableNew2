"""PR-GUI-RELIABILITY-831 (findings F1 and F7): the Learning review sections stay reachable in a short pane.

The review panel's two columns used a fixed grid, which squeezed the weighted row (Rating on the right, Images on the
left) to nothing when the pane was shorter than its neighbours.  They now scroll as one body, and a taller pane still
stretches the weighted row.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from src.gui.views.learning_review_panel import LearningReviewPanel
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from tests.gui_v2.tk_test_utils import get_shared_tk_root

#: The Rating box must keep room for its title, context lines and the 1-5 choice.
MINIMUM_RATING_HEIGHT = 150
MINIMUM_IMAGES_HEIGHT = 120


@pytest.fixture
def shown_root():
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    root.geometry("1300x900+20+20")
    root.deiconify()
    root.update()
    yield root
    root.withdraw()


def _panel(root: tk.Tk, mode: str, height: int) -> LearningReviewPanel:
    panel = LearningReviewPanel(root)
    panel.set_mode(mode)
    panel.place(x=0, y=0, width=1200, height=height)
    root.update_idletasks()
    root.update()
    return panel


@pytest.mark.parametrize("height", [900, 600, 420, 300, 160])
def test_rate_mode_keeps_the_rating_box_and_the_save_strip_at_every_height(shown_root, height):
    panel = _panel(shown_root, "rate", height)
    try:
        assert panel.rating_frame.winfo_ismapped()
        assert panel.rating_frame.winfo_height() >= MINIMUM_RATING_HEIGHT
        assert panel.rating_action_strip.winfo_ismapped()
        assert panel.rating_action_strip.winfo_height() > 1
        assert (
            panel.rating_action_strip.winfo_rooty() + panel.rating_action_strip.winfo_height()
            <= (panel.winfo_rooty() + height + 1)
        )
    finally:
        panel.destroy()


@pytest.mark.parametrize("height", [900, 600, 420, 300, 160])
def test_compare_mode_keeps_the_images_list_at_every_height(shown_root, height):
    panel = _panel(shown_root, "compare", height)
    try:
        assert panel.image_frame.winfo_height() >= MINIMUM_IMAGES_HEIGHT
        assert panel.image_listbox.winfo_height() > 1
    finally:
        panel.destroy()


def test_a_short_pane_scrolls_and_a_tall_pane_stretches(shown_root):
    short = _panel(shown_root, "rate", 300)
    try:
        assert short.side_scroll.has_scroll_overflow()
        assert short.preview_scroll.has_scroll_overflow()
        natural_rating = short.rating_frame.winfo_height()
    finally:
        short.destroy()
    tall = _panel(shown_root, "rate", 900)
    try:
        assert not tall.side_scroll.has_scroll_overflow()
        assert (
            tall.rating_frame.winfo_height() > natural_rating
        )  # the weighted row uses the extra height
        assert tall.image_frame.winfo_height() > MINIMUM_IMAGES_HEIGHT * 3
    finally:
        tall.destroy()


def test_fill_height_stretches_a_weighted_row_and_scrolls_when_the_viewport_is_short(shown_root):
    frame = ScrollableFrame(shown_root, fill_height=True)
    frame.place(x=0, y=0, width=400, height=500)
    frame.inner.columnconfigure(0, weight=1)
    frame.inner.rowconfigure(1, weight=1)
    ttk.Label(frame.inner, text="header").grid(row=0, column=0)
    body = ttk.Frame(frame.inner, height=100)
    body.grid(row=1, column=0, sticky="nsew")
    shown_root.update()
    try:
        assert body.winfo_height() > 300 and not frame.has_scroll_overflow()

        frame.place_configure(height=60)
        shown_root.update()

        assert body.winfo_height() >= 100 and frame.has_scroll_overflow()
    finally:
        frame.destroy()


def test_a_plain_scrollable_frame_is_unchanged_without_fill_height(shown_root):
    frame = ScrollableFrame(shown_root)
    try:
        assert frame._ruler is None  # noqa: SLF001
        assert frame.inner.grid_slaves() == []
    finally:
        frame.destroy()
