"""VID-FRAME: the first cleanup's confirmation shows the dry-run figures and reports the operator's choice."""

from __future__ import annotations

from tkinter import ttk

import pytest

from src.app.frame_retention_service import CHOICE_DELETE_NOW, CHOICE_NOT_NOW, CHOICE_TURN_OFF
from src.gui.frame_cleanup_dialog import show_frame_cleanup_dialog
from src.video.frame_retention import FrameSweep

pytestmark = pytest.mark.gui


def _widgets(window, kind):
    found = []
    for child in window.winfo_children():
        found.extend([child] if isinstance(child, kind) else [])
        found.extend(_widgets(child, kind))
    return found


@pytest.mark.parametrize(
    ("label", "choice"),
    [
        ("Delete now", CHOICE_DELETE_NOW),
        ("Not now", CHOICE_NOT_NOW),
        ("Turn off", CHOICE_TURN_OFF),
    ],
)
def test_each_button_reports_its_choice_without_a_grab(tk_root, label, choice) -> None:
    chosen: list[str] = []
    window = show_frame_cleanup_dialog(
        tk_root, FrameSweep(frames=100_268, bytes=64_600_000_000, runs=1_232), chosen.append
    )

    text = " ".join(str(item.cget("text")) for item in _widgets(window, ttk.Label))
    assert "100,268" in text and "64.6 GB" in text and "first and last frame" in text
    assert window.grab_current() is None
    next(b for b in _widgets(window, ttk.Button) if b.cget("text") == label).invoke()

    assert chosen == [choice] and not window.winfo_exists()
