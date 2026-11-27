"""Motion preset, motion phrase and duration rows of the Video Workflow tab (V1-1).

Presentation only: the rows hold Tk variables and report the operator's choices through callbacks; the tab resolves
them with the pure ``src.video.motion_intent`` / ``src.video.motion_presets`` functions, writes the result into its
existing form fields and pins what the operator edited.  Nothing here reads a workflow record or builds a job.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from src.gui.tooltip import attach_tooltip
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.video.motion_presets import NO_PRESET_LABEL, preset_labels

PHRASE_HELP = (
    "Words added to the end of your prompt to describe the movement. A preset fills this in; you can edit it, "
    "and the text that is sent is shown below."
)
PRESET_HELP = (
    "A starting point for the movement: it sets the duration and the motion words. Presets are untested "
    "wording; values beyond the engine's defaults were observed once, not qualified."
)
DURATION_HELP = (
    "How long the clip runs. Pick one or type seconds; it is rounded to the nearest length the engine can make, "
    "and the frame count shown is exactly what is queued."
)


class MotionIntentPanel(ttk.Frame):
    """Three rows: Motion (the phrase), Preset (with its status and Reset to preset) and Duration."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_preset: Callable[[str], None],
        on_reset_preset: Callable[[], None],
        on_duration: Callable[[str], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._on_preset = on_preset
        self._on_duration = on_duration
        self.columnconfigure(1, weight=1)
        self.phrase_var = tk.StringVar(master=self, value="")
        self.preset_var = tk.StringVar(master=self, value=NO_PRESET_LABEL)
        self.preset_status_var = tk.StringVar(master=self, value="")
        self.composed_var = tk.StringVar(master=self, value="")
        self.duration_var = tk.StringVar(master=self, value="")
        self.duration_line_var = tk.StringVar(master=self, value="")
        self.duration_advisory_var = tk.StringVar(master=self, value="")

        self.phrase_label = ttk.Label(self, text="Motion", style="Dark.TLabel")
        self.phrase_label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        self.phrase_entry = ttk.Entry(self, textvariable=self.phrase_var, style="Dark.TEntry")
        self.phrase_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 4))
        attach_tooltip(self.phrase_entry, PHRASE_HELP)
        attach_tooltip(self.phrase_label, PHRASE_HELP)
        self.composed_label = ttk.Label(
            self, textvariable=self.composed_var, style="Muted.TLabel", justify="left"
        )
        self.composed_label.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(0, 4))
        bind_wraplength(self.composed_label)

        self.preset_label = ttk.Label(self, text="Preset", style="Dark.TLabel")
        self.preset_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        preset_row = ttk.Frame(self, style="Panel.TFrame")
        preset_row.grid(row=2, column=1, columnspan=3, sticky="ew", pady=(0, 4))
        preset_row.columnconfigure(1, weight=1)
        self.preset_row = preset_row
        self.preset_combo = ttk.Combobox(
            preset_row,
            textvariable=self.preset_var,
            values=list(preset_labels()),
            state="readonly",
            style="Dark.TCombobox",
            width=14,
        )
        self.preset_combo.grid(row=0, column=0, sticky="w")
        self.preset_combo.bind("<<ComboboxSelected>>", self._preset_chosen, add="+")
        attach_tooltip(self.preset_combo, PRESET_HELP)
        self.preset_status_label = ttk.Label(
            preset_row, textvariable=self.preset_status_var, style="Muted.TLabel", justify="left"
        )
        self.preset_status_label.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        bind_wraplength(self.preset_status_label)
        self.reset_preset_button = ttk.Button(
            preset_row, text="Reset to preset", style="Dark.TButton", command=on_reset_preset
        )
        self.reset_preset_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.reset_preset_button.grid_remove()

        self.duration_label = ttk.Label(self, text="Duration", style="Dark.TLabel")
        self.duration_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        duration_row = ttk.Frame(self, style="Panel.TFrame")
        duration_row.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(0, 4))
        duration_row.columnconfigure(1, weight=1)
        self.duration_row = duration_row
        self.duration_combo = ttk.Combobox(
            duration_row,
            textvariable=self.duration_var,
            values=[],
            style="Dark.TCombobox",
            width=16,
        )
        self.duration_combo.grid(row=0, column=0, sticky="w")
        for sequence in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
            self.duration_combo.bind(sequence, self._duration_entered, add="+")
        attach_tooltip(self.duration_combo, DURATION_HELP)
        attach_tooltip(self.duration_label, DURATION_HELP)
        ttk.Label(duration_row, textvariable=self.duration_line_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        self.duration_advisory_label = ttk.Label(
            duration_row,
            textvariable=self.duration_advisory_var,
            style="Dark.TLabel",
            justify="left",
        )
        self.duration_advisory_label.grid(row=1, column=0, columnspan=2, sticky="ew")
        bind_wraplength(self.duration_advisory_label)

    # ------------------------------------------------------------------ operator events

    def _preset_chosen(self, _event: Any = None) -> None:
        self._on_preset(self.preset_var.get())

    def _duration_entered(self, _event: Any = None) -> None:
        self._on_duration(self.duration_var.get())

    def enter_duration(self, text: str) -> None:
        """Type ``text`` into Duration and commit it, as the operator would."""

        self.duration_var.set(text)
        self._duration_entered()

    def choose_preset(self, label: str) -> None:
        """Pick ``label`` in the preset list, as the operator would."""

        self.preset_var.set(label)
        self._preset_chosen()

    # ------------------------------------------------------------------ what the tab shows

    def show_mode(self, *, phrase: bool, preset: bool) -> None:
        """The Motion row belongs to prompt-only motion; the Preset row and the "Sends:" line to it and to following
        a driver."""

        rows: Sequence[tuple[bool, Sequence[tk.Widget]]] = (
            (phrase, (self.phrase_label, self.phrase_entry)),
            (preset, (self.composed_label, self.preset_label, self.preset_row)),
        )
        for shown, widgets in rows:
            for widget in widgets:
                if shown:
                    widget.grid()
                else:
                    widget.grid_remove()

    def show_duration(self, shown: bool) -> None:
        for widget in (self.duration_label, self.duration_row):
            if shown:
                widget.grid()
            else:
                widget.grid_remove()

    def set_duration(self, text: str, line: str, advisory: str, options: Sequence[str]) -> None:
        self.duration_combo["values"] = list(options)
        self.duration_var.set(text)
        self.duration_line_var.set(line)
        self.duration_advisory_var.set(advisory)

    def set_preset(self, label: str, status: str, *, modified: bool) -> None:
        self.preset_var.set(label)
        self.preset_status_var.set(status)
        if modified:
            self.reset_preset_button.grid()
        else:
            self.reset_preset_button.grid_remove()

    def set_composed(self, text: str) -> None:
        self.composed_var.set(f"Sends: {text}" if text else "")


__all__ = ["MotionIntentPanel"]
