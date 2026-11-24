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
