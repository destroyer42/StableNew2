"""VID-FINISH: the per-clip finishing options in the Video Workflow tab's Advanced section.

Presentation only: it holds the operator's choice and hands it to the form as plain values. Everything is off by
default and is not saved with the form, so a new session never loops, trims or upscales a clip by itself.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Mapping
from tkinter import ttk
from typing import Any

from src.video.clip_finishing import LOOP_CROSSFADE, LOOP_OFF, LOOP_PING_PONG

_LOOP_LABELS = {
    LOOP_OFF: "No loop",
    LOOP_PING_PONG: "Ping-pong (forward, back)",
    LOOP_CROSSFADE: "Crossfade end into start",
}
_NOTE = (
    "Off by default. Trim and loop apply after smoothing; the untrimmed clip is kept. The upscale runs before "
    "smoothing and needs model files StableNew does not download: Queue says what is missing."
)


class FinishOptionsPanel(ttk.Frame):
    def __init__(self, parent: Any, *, on_change: Callable[[], None]) -> None:
        super().__init__(parent, style="Panel.TFrame")
        self._on_change = on_change
        self.loop_var = tk.StringVar(master=self, value=_LOOP_LABELS[LOOP_OFF])
        self.trim_start_var = tk.StringVar(master=self, value="")
        self.trim_end_var = tk.StringVar(master=self, value="")
        self.upscale_var = tk.BooleanVar(master=self, value=False)

        row = ttk.Frame(self, style="Panel.TFrame")
        row.grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="Loop", style="Dark.TLabel").pack(side="left", padx=(0, 8))
        self.loop_combo = ttk.Combobox(
            row,
            textvariable=self.loop_var,
            values=list(_LOOP_LABELS.values()),
            state="readonly",
            style="Dark.TCombobox",
            width=24,
        )
        self.loop_combo.pack(side="left")
        ttk.Label(row, text="Trim from (s)", style="Dark.TLabel").pack(side="left", padx=(12, 6))
        self.trim_start_entry = ttk.Entry(
            row, textvariable=self.trim_start_var, style="Dark.TEntry", width=6
        )
        self.trim_start_entry.pack(side="left")
        ttk.Label(row, text="to (s)", style="Dark.TLabel").pack(side="left", padx=6)
        self.trim_end_entry = ttk.Entry(
            row, textvariable=self.trim_end_var, style="Dark.TEntry", width=6
        )
        self.trim_end_entry.pack(side="left")

        self.upscale_check = ttk.Checkbutton(
            self,
            text="Upscale 2x with SeedVR2 (experimental, unrated)",
            variable=self.upscale_var,
            style="Dark.TCheckbutton",
        )
        self.upscale_check.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(self, text=_NOTE, style="Muted.TLabel", wraplength=520, justify="left").grid(
            row=2, column=0, sticky="w", pady=(2, 0)
        )
        for variable in (self.loop_var, self.trim_start_var, self.trim_end_var, self.upscale_var):
            variable.trace_add("write", lambda *_args: self._on_change())

    def _loop_mode(self) -> str:
        chosen = self.loop_var.get()
        return next((mode for mode, label in _LOOP_LABELS.items() if label == chosen), LOOP_OFF)

    def upscale_selected(self) -> bool:
        return bool(self.upscale_var.get())

    def value(self) -> dict[str, Any] | None:
        """The form's ``finishing`` block, or ``None`` when nothing is chosen. Text is validated by the builder."""

        data: dict[str, Any] = {}
        if self._loop_mode() != LOOP_OFF:
            data["loop_mode"] = self._loop_mode()
        for key, variable in (
            ("trim_start_seconds", self.trim_start_var),
            ("trim_end_seconds", self.trim_end_var),
        ):
            text = variable.get().strip()
            if text:
                data[key] = text
        if self.upscale_selected():
            data["upscale"] = True
        return data or None

    def restore(self, value: Any) -> None:
        data = value if isinstance(value, Mapping) else {}
        mode = str(data.get("loop_mode") or LOOP_OFF)
        self.loop_var.set(_LOOP_LABELS.get(mode, _LOOP_LABELS[LOOP_OFF]))
        for key, variable in (
            ("trim_start_seconds", self.trim_start_var),
            ("trim_end_seconds", self.trim_end_var),
        ):
            number = data.get(key)
            variable.set("" if number in (None, "") else str(number))
        self.upscale_var.set(bool(data.get("upscale")))

    def summary(self) -> list[str]:
        parts: list[str] = []
        if self.trim_start_var.get().strip() or self.trim_end_var.get().strip():
            parts.append("trimmed")
        if self._loop_mode() != LOOP_OFF:
            parts.append(
                "ping-pong loop" if self._loop_mode() == LOOP_PING_PONG else "crossfade loop"
            )
        if self.upscale_selected():
            parts.append("upscaled 2x (experimental)")
        return parts


__all__ = ["FinishOptionsPanel"]
