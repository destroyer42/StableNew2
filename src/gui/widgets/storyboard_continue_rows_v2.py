"""The Continue panel's rows for the Storyboard tab (PR-VID-STORY-IMPORT). Presentation only.

One grid owns the persistent header row and every Continue row, so a header and its column can never drift apart when rows
are added, removed or the window is resized. The two prompt columns share the spare width; the number, seed and remove
columns keep their natural size. The seed control is Random or Fixed: Random needs no number (a seed is drawn when the row
is queued) and Fixed enables a whole-number entry. The widget owns no validation and builds no request; the tab reads
each row's variables and the contract judges them.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from src.gui.tooltip import attach_tooltip
from src.gui.view_contracts.storyboard_tree_contract import (
    ROW_HEADERS,
    ROW_TIPS,
    SEED_FIXED,
    SEED_RANDOM,
    SEED_TIPS,
)
from src.gui.widgets.mirrored_text_v2 import MirroredText
from src.video.storyboard_tree import MAX_ROWS

PROMPT_MINSIZE = 140
SEED_CHOICES = (SEED_RANDOM, SEED_FIXED)


class ContinueRowFields:
    """One row: number, Positive Prompt, Negative Prompt, the seed control and a remove button."""

    def __init__(
        self,
        parent: ttk.Frame,
        number: int,
        prompt: str,
        negative: str,
        seed_mode: str,
        seed: str,
        *,
        on_remove: Callable[[ContinueRowFields], None],
        on_change: Callable[[], None],
    ) -> None:
        self.prompt_var = tk.StringVar(value=prompt)
        self.negative_var = tk.StringVar(value=negative)
        self.seed_mode_var = tk.StringVar(
            value=seed_mode if seed_mode in SEED_CHOICES else SEED_RANDOM
        )
        #: The Fixed seed's text; it is only sent when the mode is Fixed.
        self.seed_var = tk.StringVar(value=seed)
        self.number_label = ttk.Label(parent, text=str(number), width=2, anchor="e")
        #: Word-wrapped multi-line fields that mirror the variables above (a long prompt never scrolls sideways).
        self.prompt_entry = MirroredText(parent, self.prompt_var)
        self.negative_entry = MirroredText(parent, self.negative_var)
        self.seed_frame = ttk.Frame(parent, style="Panel.TFrame")
        self.seed_box = ttk.Combobox(
            self.seed_frame,
            textvariable=self.seed_mode_var,
            values=SEED_CHOICES,
            state="readonly",
            width=7,
        )
        self.seed_entry = ttk.Entry(self.seed_frame, textvariable=self.seed_var, width=11)
        self.seed_box.pack(side="left")
        self.seed_entry.pack(side="left", padx=(3, 0))
        self.remove_button = ttk.Button(parent, text="✕", width=3, command=lambda: on_remove(self))
        attach_tooltip(self.prompt_entry, ROW_TIPS["Positive Prompt"])
        attach_tooltip(self.negative_entry, ROW_TIPS["Negative Prompt"])
        attach_tooltip(self.seed_box, ROW_TIPS["Seed"])
        self.seed_tip = attach_tooltip(self.seed_entry, SEED_TIPS[SEED_FIXED])
        self.seed_mode_var.trace_add("write", lambda *_: self._mode_changed(on_change))
        self.sync_seed()

    @property
    def seed_mode(self) -> str:
        return SEED_FIXED if self.seed_mode_var.get() == SEED_FIXED else SEED_RANDOM

    def _mode_changed(self, on_change: Callable[[], None]) -> None:
        self.sync_seed()
        on_change()

    def sync_seed(self) -> None:
        """Random: no number is needed, so the entry is disabled; Fixed enables it."""

        fixed = self.seed_mode == SEED_FIXED
        self.seed_entry.configure(state="normal" if fixed else "disabled")
        self.seed_box.tooltip.text = SEED_TIPS[self.seed_mode]  # type: ignore[attr-defined]

    def widgets(self) -> tuple[ttk.Widget, ...]:
        return (
            self.number_label,
            self.prompt_entry,
            self.negative_entry,
            self.seed_frame,
            self.remove_button,
        )

    def place(self, grid_row: int, number: int) -> None:
        self.number_label.configure(text=str(number))
        # A row's cells hang from its top, so they stay put when a prompt field grows.
        sticky = ("ne", "new", "new", "nw", "n")
        for column, (widget, edge) in enumerate(zip(self.widgets(), sticky, strict=True)):
            widget.grid(row=grid_row, column=column, sticky=edge, padx=2, pady=1)

    def destroy(self) -> None:
        for widget in self.widgets():
            widget.destroy()


class ContinueRowsV2(ttk.Frame):
    """The header row and the 1-6 Continue rows on one grid."""

    def __init__(self, master: tk.Misc, *, on_change: Callable[[], None] = lambda: None) -> None:
        super().__init__(master, style="Panel.TFrame")
        self._on_change = on_change
        self.rows: list[ContinueRowFields] = []
        self.header_labels: dict[str, ttk.Label] = {}
        self.hint_var = tk.StringVar(value="")
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=3, minsize=PROMPT_MINSIZE, uniform="prompts")
        self.columnconfigure(2, weight=3, minsize=PROMPT_MINSIZE, uniform="prompts")
        self.columnconfigure(3, weight=0)
        self.columnconfigure(4, weight=0)
        for column, text in enumerate(ROW_HEADERS):
            label = ttk.Label(self, text=text, style="Dark.TLabel", anchor="w" if column else "e")
            label.grid(row=0, column=column, sticky="ew", padx=2)
            attach_tooltip(label, ROW_TIPS[text])
            self.header_labels[text] = label
        self.hint = ttk.Label(self, textvariable=self.hint_var, style="Dark.TLabel", wraplength=420)
        self.hint.grid(row=MAX_ROWS + 1, column=0, columnspan=len(ROW_HEADERS), sticky="w")
        self.bind("<Configure>", self._rewrap, add="+")

    # ------------------------------------------------------------------ rows

    def add_row(
        self, prompt: str = "", negative: str = "", seed_mode: str = SEED_RANDOM, seed: str = ""
    ) -> ContinueRowFields | None:
        if len(self.rows) >= MAX_ROWS:
            return None
        row = ContinueRowFields(
            self,
            len(self.rows) + 1,
            prompt,
            negative,
            seed_mode,
            seed,
            on_remove=self.remove_row,
            on_change=self._on_change,
        )
        self.rows.append(row)
        self._layout()
        return row

    def remove_row(self, row: ContinueRowFields) -> None:
        if len(self.rows) <= 1 or row not in self.rows:
            return
        self.rows.remove(row)
        row.destroy()
        self._layout()

    def _layout(self) -> None:
        """Re-seat every row under the headers (rows 1..n), renumber, and enable Remove only while there are 2+."""

        for position, row in enumerate(self.rows, start=1):
            row.place(position, position)
            row.remove_button.configure(state="normal" if len(self.rows) > 1 else "disabled")
        self._on_change()

    def _rewrap(self, event: tk.Event) -> None:
        self.hint.configure(wraplength=max(200, int(event.width) - 8))

    # ------------------------------------------------------------------ reading

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def full(self) -> bool:
        return len(self.rows) >= MAX_ROWS


__all__ = ["ContinueRowFields", "ContinueRowsV2"]
