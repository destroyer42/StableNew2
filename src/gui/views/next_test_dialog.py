"""Compact "What Should I Test Next?" dialog.

Renders a prepared ``NextTestView``: one recommended action, a few alternatives, a short explanation and
optional evidence details. It owns no worker, timer or navigation: choosing an action calls back into the
owning Model Evidence window, which revalidates against current evidence and uses existing workflows.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.gui_v2.next_test_view import NextTestCard, NextTestView


class NextTestDialog(tk.Toplevel):
    def __init__(
        self,
        owner: Any,
        view: NextTestView,
        *,
        on_open: Callable[[str], None],
        on_refresh: Callable[[], None],
    ) -> None:
        super().__init__(owner)
        self.title("What Should I Test Next?")
        self.geometry(
            f"{min(760, self.winfo_screenwidth() - 24)}x{min(560, self.winfo_screenheight() - 96)}"
        )
        self.minsize(420, 320)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._on_open, self._on_refresh = on_open, on_refresh
        self.view = view
        self.cards: list[NextTestCard] = [c for c in (view.primary, *view.alternatives) if c]
        self._closed = False
        self._stale = False
        self.status = tk.StringVar(value=view.status)
        self.message = tk.StringVar(value=view.notice)
        ttk.Label(
            self, text=view.headline, font=("TkDefaultFont", 11, "bold"), padding=(10, 8, 10, 0)
        ).grid(row=0, column=0, sticky="ew")
        self._labels: list[ttk.Label] = []
        for row, variable in enumerate((self.status, self.message), start=1):
            label = ttk.Label(self, textvariable=variable, padding=(10, 2), justify="left")
            label.grid(row=row, column=0, sticky="ew")
            self._labels.append(label)
        body = ttk.Frame(self, padding=(10, 4))
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        self.choices = ttk.Treeview(
            body,
            columns=(),
            show="tree",
            selectmode="browse",
            height=min(4, max(1, len(self.cards))),
        )
        self.choices.grid(row=0, column=0, sticky="ew")
        for index, card in enumerate(self.cards):
            prefix = "Recommended: " if index == 0 else ""
            self.choices.insert("", "end", iid=str(index), text=prefix + card.title)
        self.choices.bind("<<TreeviewSelect>>", lambda _event: self._render_card())
        self.choices.bind("<Return>", lambda _event: self._open())
        self.card_text = tk.Text(body, height=9, wrap="word", state="disabled", relief="flat")
        self.card_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.details = ScrolledText(self, height=10, wrap="word", state="disabled")
        self.details_shown = False
        actions = ttk.Frame(self, padding=10)
        actions.grid(row=5, column=0, sticky="ew")
        self.open_button = ttk.Button(actions, text="Open", command=self._open, state="disabled")
        self.open_button.pack(side="left")
        ttk.Button(actions, text="Refresh", command=self._refresh).pack(side="left", padx=6)
        self.details_button = ttk.Button(
            actions, text="Show evidence details", command=self.toggle_details
        )
        self.details_button.pack(side="left")
        ttk.Button(actions, text="Close", command=self.close).pack(side="right")
        self.bind("<Escape>", lambda _event: self.close())
        self.bind("<Configure>", self._rewrap, add="+")
        self.bind("<Destroy>", self._destroyed, add="+")
        self.protocol("WM_DELETE_WINDOW", self.close)
        if self.cards:
            self.choices.selection_set("0")
            self.choices.focus("0")
        else:
            self._set_card_text("No suggestion is available.")
        self.choices.focus_set()

    def _destroyed(self, event: Any) -> None:
        if event.widget is self:
            self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.destroy()

    def _rewrap(self, _event: Any = None) -> None:
        width = max(240, self.winfo_width() - 40)
        for label in self._labels:
            label.configure(wraplength=width)

    def _selected(self) -> NextTestCard | None:
        selection = self.choices.selection()
        return self.cards[int(selection[0])] if selection else None

    def _set_card_text(self, text: str) -> None:
        self.card_text.configure(state="normal")
        self.card_text.delete("1.0", "end")
        self.card_text.insert("1.0", text)
        self.card_text.configure(state="disabled")

    def _render_card(self) -> None:
        card = self._selected()
        if card is None:
            return
        lines = [card.purpose, "", card.readiness]
        if card.workload:
            lines.append(f"Workload: {card.workload}")
        lines.append(f"Reduces uncertainty about: {card.addresses}")
        if card.step:
            lines.append(f"Your next step: {card.step}")
        lines.extend(f"- {reason}" for reason in card.reasons)
        lines.extend(f"Blocked: {blocker}" for blocker in card.blockers)
        lines.append("No improvement is promised; this asks a question.")
        self._set_card_text("\n".join(lines))
        self.open_button.configure(
            text=card.button or "Open",
            state="normal" if card.button and not self._stale else "disabled",
        )

    def _open(self) -> None:
        card = self._selected()
        if card is not None and card.button and not self._stale and not self._closed:
            self._on_open(card.action_id)

    def _refresh(self) -> None:
        if not self._closed:
            self._on_refresh()

    def toggle_details(self) -> None:
        self.details_shown = not self.details_shown
        if self.details_shown:
            self.details.configure(state="normal")
            self.details.delete("1.0", "end")
            self.details.insert("1.0", self.view.details)
            self.details.configure(state="disabled")
            self.details.grid(row=4, column=0, sticky="nsew", padx=10)
            self.rowconfigure(4, weight=1)
            self.details_button.configure(text="Hide evidence details")
        else:
            self.details.grid_remove()
            self.rowconfigure(4, weight=0)
            self.details_button.configure(text="Show evidence details")

    def show_message(self, text: str) -> None:
        if not self._closed:
            self.message.set(text)

    def mark_stale(self, text: str) -> None:
        """The evidence changed under this suggestion: keep it readable, but make it inert."""
        self._stale = True
        self.show_message(text)
        self.open_button.configure(state="disabled")
