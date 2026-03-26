from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.dialogs.multi_folder_selector import MultiFolderSelector
from src.gui.learning_review_dialog_v2 import LearningReviewDialogV2
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
def test_multi_folder_selector_uses_dark_theme(tk_root: tk.Tk) -> None:
    dialog = MultiFolderSelector(tk_root)
    try:
        assert dialog.cget("bg") == BACKGROUND_DARK
        assert dialog.folder_listbox.cget("bg") == BACKGROUND_ELEVATED
    finally:
        dialog.destroy()


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


@pytest.mark.gui
def test_learning_review_dialog_uses_dark_theme_when_empty(tk_root: tk.Tk) -> None:
    dialog = LearningReviewDialogV2(tk_root, controller=object(), records=[])
    try:
        assert dialog.cget("bg") == BACKGROUND_DARK
    finally:
        dialog.destroy()