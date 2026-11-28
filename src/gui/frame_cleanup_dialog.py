"""The one-time confirmation before the first video frame cleanup (VID-FRAME, KEEP-SPACE).

Not modal and not blocking: the window can be left open, closing it means Not now, and nothing is moved until Move now
is chosen. The figures come from a dry run of the same sweep. When the Recycle Bin cannot take the frames, the window
explains why and offers no Move now.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk

from src.app.frame_retention_service import (
    CHOICE_MOVE_NOW,
    CHOICE_NOT_NOW,
    CHOICE_TURN_OFF,
)
from src.video.frame_retention import FrameSweep

TITLE = "Move old video frames to the Recycle Bin?"
BLOCKED_TITLE = "Old video frames were not moved"
STOPPED_TITLE = "The video frame cleanup stopped"
KEPT = (
    "Kept: every video clip, each clip's first and last frame, anything a job records as an output, frames a "
    "Storyboard uses, multi-segment sequences, evaluations and archived files."
)
CONSEQUENCE = (
    "Frames can be restored from the Recycle Bin until it is emptied, and disk space is freed only then. Windows "
    "permanently deletes items too large for the Recycle Bin's size limit, so nothing is moved unless it all fits. "
    "If you choose Move now, later cleanups run by themselves while the queue is empty. You can turn them off in "
    "Engine Settings."
)
NOT_NOW = "Not now: nothing is moved or deleted by this cleanup. It looks again later."
THE_REST = "The rest stay where they are. The cleanup looks again later."


def summary_text(preview: FrameSweep) -> str:
    return (
        f"{preview.frames:,} PNG frames ({preview.bytes / 1e9:.1f} GB) from {preview.runs:,} clips made more than "
        "7 days ago can be moved to the Recycle Bin."
    )


def paragraphs(preview: FrameSweep) -> list[str]:
    """What the window says: what would happen, or why the Recycle Bin cannot take the frames."""

    if not preview.bin_refusal:
        room = [preview.bin_room] if preview.bin_room else []
        return [summary_text(preview), *room, KEPT, CONSEQUENCE]
    if preview.stopped:
        moved = f"{preview.frames:,} PNG frames ({preview.bytes / 1e9:.1f} GB) moved to the Recycle Bin first."
        return [moved, preview.bin_refusal, THE_REST]
    due = []
    if preview.frames:
        due.append(
            f"{preview.frames:,} PNG frames ({preview.bytes / 1e9:.1f} GB) from {preview.runs:,} clips made more "
            "than 7 days ago are due."
        )
    return [*due, preview.bin_refusal, NOT_NOW]


def ask_with_dialog(parent: tk.Misc) -> Callable[[FrameSweep, Callable[[str], None]], None]:
    """The ``ask`` the retention scheduler takes: show the dialog over ``parent``."""

    def ask(preview: FrameSweep, choose: Callable[[str], None]) -> None:
        show_frame_cleanup_dialog(parent, preview, choose)

    return ask


def show_frame_cleanup_dialog(
    parent: tk.Misc, preview: FrameSweep, choose: Callable[[str], None]
) -> tk.Toplevel:
    window = tk.Toplevel(parent)
    refused = STOPPED_TITLE if preview.stopped else BLOCKED_TITLE
    window.title(refused if preview.bin_refusal else TITLE)
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=16)
    frame.grid(sticky="nsew")
    texts = paragraphs(preview)
    for row, text in enumerate(texts):
        ttk.Label(frame, text=text, wraplength=460, justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )

    def finish(choice: str) -> None:
        window.destroy()
        choose(choice)

    buttons = [("Not now", CHOICE_NOT_NOW), ("Turn off", CHOICE_TURN_OFF)]
    if not preview.bin_refusal:
        buttons.insert(0, ("Move now", CHOICE_MOVE_NOW))
    for column, (label, choice) in enumerate(buttons):
        ttk.Button(frame, text=label, command=partial(finish, choice)).grid(
            row=len(texts), column=column, sticky="w", padx=(0, 8)
        )
    window.protocol("WM_DELETE_WINDOW", lambda: finish(CHOICE_NOT_NOW))
    return window


__all__ = ["ask_with_dialog", "paragraphs", "show_frame_cleanup_dialog", "summary_text"]
