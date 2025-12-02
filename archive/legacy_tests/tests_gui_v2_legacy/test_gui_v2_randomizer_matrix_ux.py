from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.randomizer_panel_v2 import RandomizerPanelV2


def test_matrix_rows_add_clone_delete_and_enabled(monkeypatch):
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("Tkinter/Tcl not available")
    panel = RandomizerPanelV2(root)

    # disable first row, add values to second
    panel._rows[0].enabled_var.set(False)
    panel._rows[1].value_var.set("hn1, , hn2 ")
    panel._add_matrix_row(label="Style", values=" cinematic , ", enabled=True)
    options = panel.get_randomizer_options()
    # model row disabled -> no model_matrix
    assert "model_matrix" not in options
    assert options["hypernetworks"] == [{"name": "hn1", "strength": None}, {"name": "hn2", "strength": None}]
    assert options["matrix"]["style"] == ["cinematic"]

    # clone and delete
    orig_len = len(panel._rows)
    panel._clone_matrix_row(2)
    assert len(panel._rows) == orig_len + 1
    panel._delete_matrix_row(len(panel._rows) - 1)
    assert len(panel._rows) == orig_len

    root.destroy()
