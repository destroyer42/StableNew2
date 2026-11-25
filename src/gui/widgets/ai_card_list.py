"""A scrollable list of AI Assist change cards (AI-230).

One card per :class:`~src.gui_v2.ai_changes.ProposedChange`: a check box and summary, a before/after preview, the effect line,
a few compiled examples, the model's rationale (labelled as its words) and one **Apply** button. A rejected card is greyed
with its reason and has no control; an applied card shows a tick. The widget never changes workspace state: **Apply** and
**Apply selected** call the callbacks the Prompt tab owner supplies, which run the stale-checked mutators.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk

from src.gui.scrolling import enable_mousewheel
from src.gui.theme_v2 import BACKGROUND_DARK, TEXT_DISABLED, TEXT_MUTED
from src.gui_v2.ai_changes import ProposedChange

_WRAP = 660


class AiCardList(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_apply: Callable[[str], None],
        height: int = 190,
        on_selection_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._on_apply = on_apply
        self._on_selection_changed = on_selection_changed
        self._cards: tuple[ProposedChange, ...] = ()
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self.apply_buttons: dict[str, ttk.Button] = {}
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bg=BACKGROUND_DARK)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)
        enable_mousewheel(self.canvas)

    # -- geometry -----------------------------------------------------------------------------------------------------------

    def _sync_region(self, _event: object = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    # -- content ------------------------------------------------------------------------------------------------------------

    @property
    def cards(self) -> tuple[ProposedChange, ...]:
        return self._cards

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self._cards = ()
        self.check_vars.clear()
        self.apply_buttons.clear()
        self.canvas.yview_moveto(0)

    def set_cards(self, cards: Sequence[ProposedChange]) -> None:
        """Replace the list. Offered cards start checked so **Apply selected** is live as soon as there is something to apply."""

        self.clear()
        self._cards = tuple(cards)
        for card in self._cards:
            if card.note:
                self._note_row(card)
            elif card.applied:
                self._applied_row(card)
            elif card.rejected:
                self._rejected_row(card)
            else:
                self._offered_row(card)
        self._changed()

    def _text_label(self, parent: tk.Misc, text: str, *, muted: bool = False) -> ttk.Label:
        label = ttk.Label(parent, text=text, wraplength=_WRAP, justify="left")
        if muted:
            label.configure(foreground=TEXT_MUTED)
        label.pack(fill="x", padx=(24, 4), anchor="w")
        return label

    def _offered_row(self, card: ProposedChange) -> None:
        frame = ttk.Frame(self.inner, relief="groove", borderwidth=1)
        frame.pack(fill="x", padx=2, pady=2)
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=4, pady=(2, 0))
        var = tk.BooleanVar(value=True)
        var.trace_add("write", lambda *_a: self._changed())
        self.check_vars[card.key] = var
        ttk.Checkbutton(top, text=card.title, variable=var).pack(side="left")
        button = ttk.Button(
            top, text="Apply", command=lambda key=card.key: self._on_apply(key), width=8
        )
        button.pack(side="right")
        self.apply_buttons[card.key] = button
        if card.before:
            self._text_label(frame, f"Before: {card.before}", muted=True)
        if card.after:
            self._text_label(frame, f"After:  {card.after}")
        if card.effect:
            self._text_label(frame, card.effect, muted=True)
        for example in card.examples:
            self._text_label(frame, f"Example: {example}", muted=True)
        if card.rationale:
            self._text_label(frame, f"Why (model's words): {card.rationale}", muted=True)

    def _rejected_row(self, card: ProposedChange) -> None:
        frame = ttk.Frame(self.inner)
        frame.pack(fill="x", padx=2, pady=1)
        label = ttk.Label(
            frame,
            text=f"Rejected: {card.title}. {card.detail}",
            wraplength=_WRAP,
            justify="left",
        )
        label.configure(foreground=TEXT_DISABLED)
        label.pack(fill="x", padx=4, anchor="w")

    def _note_row(self, card: ProposedChange) -> None:
        frame = ttk.Frame(self.inner)
        frame.pack(fill="x", padx=2, pady=1)
        ttk.Label(frame, text=card.title, wraplength=_WRAP, justify="left").pack(
            fill="x", padx=4, anchor="w"
        )
        if card.detail:
            label = ttk.Label(frame, text=card.detail, wraplength=_WRAP, justify="left")
            label.configure(foreground=TEXT_MUTED)
            label.pack(fill="x", padx=(24, 4), anchor="w")

    def _applied_row(self, card: ProposedChange) -> None:
        frame = ttk.Frame(self.inner)
        frame.pack(fill="x", padx=2, pady=1)
        label = ttk.Label(frame, text=f"Applied: {card.title}", wraplength=_WRAP, justify="left")
        label.configure(foreground=TEXT_MUTED)
        label.pack(fill="x", padx=4, anchor="w")

    # -- selection ----------------------------------------------------------------------------------------------------------

    def offered_keys(self) -> tuple[str, ...]:
        return tuple(card.key for card in self._cards if card.offered)

    def selected_keys(self) -> tuple[str, ...]:
        return tuple(
            card.key
            for card in self._cards
            if card.offered
            and self.check_vars.get(card.key) is not None
            and self.check_vars[card.key].get()
        )

    def _changed(self) -> None:
        if self._on_selection_changed is not None:
            self._on_selection_changed()


__all__ = ["AiCardList"]
