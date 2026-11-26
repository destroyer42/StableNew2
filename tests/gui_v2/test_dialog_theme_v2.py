from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.theme_v2 import BACKGROUND_DARK, BACKGROUND_ELEVATED
from src.gui.widgets.matrix_helper_widget import MatrixHelperDialog
from src.gui.widgets.matrix_slot_picker import MatrixSlotPickerDialog


@pytest.fixture
def tk_root() -> tk.Tk:
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter unavailable: {exc}")
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.gui
def test_matrix_dialogs_use_dark_theme(tk_root: tk.Tk) -> None:
    picker = MatrixSlotPickerDialog(tk_root, ["hair", "lighting"], lambda _slot: None)
    helper = MatrixHelperDialog(tk_root)
    try:
        assert picker.cget("bg") == BACKGROUND_DARK
        assert picker.listbox.cget("bg") == BACKGROUND_ELEVATED
        assert helper.cget("bg") == BACKGROUND_DARK
        assert helper.text.cget("bg") == BACKGROUND_DARK
    finally:
        picker.destroy()
        helper.destroy()
