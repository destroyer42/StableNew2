from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.randomizer_panel_v2 import RandomizerPanelV2


def test_preview_list_shows_variants(monkeypatch):
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    panel = RandomizerPanelV2(root)
    # set model entries to produce at least two variants
    panel._rows[0].value_var.set("m1, m2")
    panel.fanout_var.set("1")
    panel._refresh_preview()
    items = panel._preview_list.get_children() if panel._preview_list else []
    assert len(items) >= 1
    root.destroy()
