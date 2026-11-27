"""The one-time confirmation before the first video frame cleanup (VID-FRAME).

Not modal and not blocking: the window can be left open, closing it means Not now, and nothing is removed until
Delete now is chosen. The figures come from a dry run of the same sweep.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from src.app.frame_retention_service import (
    CHOICE_DELETE_NOW,
    CHOICE_NOT_NOW,
    CHOICE_TURN_OFF,
)
from src.video.frame_retention import FrameSweep

TITLE = "Delete old video frames?"
KEPT = (
    "Kept: every video clip, each clip's first and last frame, anything a job records as an output, frames a "
    "Storyboard uses, multi-segment sequences, evaluations and archived files."
)
CONSEQUENCE = (
    "Deleting cannot be undone. If you choose Delete now, later cleanups run by themselves while the queue is empty. "
    "You can turn them off in Engine Settings."
)


def summary_text(preview: FrameSweep) -> str:
    return (
        f"{preview.frames:,} PNG frames ({preview.bytes / 1e9:.1f} GB) from {preview.runs:,} clips made more than "
        "a day ago can be deleted."
    )


def ask_with_dialog(parent: tk.Misc) -> Callable[[FrameSweep, Callable[[str], None]], None]:
    """The ``ask`` the retention scheduler takes: show the dialog over ``parent``."""

    def ask(preview: FrameSweep, choose: Callable[[str], None]) -> None:
        show_frame_cleanup_dialog(parent, preview, choose)

    return ask


def show_frame_cleanup_dialog(
    parent: tk.Misc, preview: FrameSweep, choose: Callable[[str], None]
) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    window.title(TITLE)
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=16)
    frame.grid(sticky="nsew")
    for row, text in enumerate((summary_text(preview), KEPT, CONSEQUENCE)):
        ttk.Label(frame, text=text, wraplength=460, justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )

    def finish(choice: str) -> None:
        window.destroy()
        choose(choice)

    for column, (label, choice) in enumerate(
        (
            ("Delete now", CHOICE_DELETE_NOW),
            ("Not now", CHOICE_NOT_NOW),
            ("Turn off", CHOICE_TURN_OFF),
        )
    ):
        ttk.Button(frame, text=label, command=partial(finish, choice)).grid(
            row=3, column=column, sticky="w", padx=(0, 8)
        )
    window.protocol("WM_DELETE_WINDOW", lambda: finish(CHOICE_NOT_NOW))
    return window


__all__ = ["ask_with_dialog", "show_frame_cleanup_dialog", "summary_text"]
