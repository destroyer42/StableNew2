"""Width-following label wrapping for responsive workspaces (PR-GUI-110). Presentation only; no state."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.gui.view_contracts.workspace_density_contract import (
    RESIZE_COALESCE_MS,
    WRAP_MIN,
    wrap_width,
)


def bind_wraplength(
    label: ttk.Label | tk.Label,
    *,
    minimum: int = WRAP_MIN,
    maximum: int | None = None,
) -> Callable[[], None]:
    """Keep ``label``'s ``wraplength`` equal to the width its geometry manager actually gives it.

    The label must be gridded/packed so that it stretches horizontally (``sticky="ew"`` / ``fill="x"``) inside a
    column the window can size; its own allotted width is then the real available width. Measuring the label
    itself (not a container) is what keeps this stable: the wrap tracks the allotment, so a wrap change can
    never feed back into a smaller allotment. Updates are coalesced and destroy-safe. Returns a ``refresh``
    callable that applies the current width immediately.
    """

    job: list[str | None] = [None]

    def owned_elsewhere() -> bool:
        """A surface that manages its own label wraps (the Pipeline's compact contract) opts out of this one."""

        node: tk.Misc | None = label
        while node is not None:
            if getattr(node, "manages_label_wraps", False):
                return True
            node = getattr(node, "master", None)
        return False

    def apply() -> None:
        job[0] = None
        try:
            if not label.winfo_exists() or owned_elsewhere():
                return
            width = wrap_width(label.winfo_width(), margin=0, minimum=minimum, maximum=maximum)
            if label.winfo_width() > 1 and int(str(label.cget("wraplength") or 0)) != width:
                label.configure(wraplength=width)
        except tk.TclError:
            return

    def schedule(_event: tk.Event | None = None) -> None:
        if job[0] is not None:
            return
        try:
            job[0] = label.after(RESIZE_COALESCE_MS, apply)
        except tk.TclError:
            job[0] = None

    def cleanup(event: tk.Event) -> None:
        if event.widget is not label or job[0] is None:
            return
        try:
            label.after_cancel(job[0])
        except tk.TclError:
            pass
        job[0] = None

    label.bind("<Configure>", schedule, add="+")
    label.bind("<Destroy>", cleanup, add="+")
    schedule()
    return apply


__all__ = ["bind_wraplength"]
