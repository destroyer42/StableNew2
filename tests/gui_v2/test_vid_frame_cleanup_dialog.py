"""VID-FRAME: the first cleanup's confirmation shows the dry-run figures and reports the operator's choice."""

from __future__ import annotations

from tkinter import ttk

import pytest

from src.app.frame_retention_service import CHOICE_MOVE_NOW, CHOICE_NOT_NOW, CHOICE_TURN_OFF
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
        ("Move now", CHOICE_MOVE_NOW),
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
    assert "restored from the Recycle Bin" in text and "permanently deletes" in text
    assert window.grab_current() is None
    next(b for b in _widgets(window, ttk.Button) if b.cget("text") == label).invoke()

    assert chosen == [choice] and not window.winfo_exists()


def test_a_bin_that_cannot_take_them_offers_no_move(tk_root) -> None:
    chosen: list[str] = []
    window = show_frame_cleanup_dialog(
        tk_root,
        FrameSweep(frames=10, bytes=2_000_000_000, runs=1, bin_refusal="The bin has 1.0 GB free."),
        chosen.append,
    )

    text = " ".join(str(item.cget("text")) for item in _widgets(window, ttk.Label))
    labels = [button.cget("text") for button in _widgets(window, ttk.Button)]
    assert "1.0 GB free" in text and "Not now" in text and "can be moved" not in text
    assert labels == ["Not now", "Turn off"]
    window.destroy()


def test_a_stopped_cleanup_says_what_did_move(tk_root) -> None:
    window = show_frame_cleanup_dialog(
        tk_root,
        FrameSweep(frames=7, bytes=7_000_000, runs=1, bin_refusal="It stopped.", stopped=True),
        lambda _choice: None,
    )

    text = " ".join(str(item.cget("text")) for item in _widgets(window, ttk.Label))
    assert "7 PNG frames" in text and "moved to the Recycle Bin first" in text
    assert "are due" not in text and "nothing is moved" not in text
    window.destroy()
