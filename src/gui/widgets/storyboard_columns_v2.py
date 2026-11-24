"""Shot columns with take cards for the Storyboard tab (PR-VID-STORY-380). Presentation only.

One column per tree depth, scrolling sideways and (when parallel takes stack taller than the strip) up and down:
the mouse wheel scrolls vertically and Shift+wheel sideways while the pointer is over the tree, and :meth:`see`
brings a take's card into view. The selected card has its own thick accent frame and a ``▶`` marker. Cards show a lazily loaded thumbnail, the label, a prompt excerpt, the
status and Keep ★ / Drop ✕ toggles. The widget holds no tree: the tab hands it :class:`Column` values and callbacks, and
supplies thumbnails (already loaded on a worker) through :meth:`set_thumbnail`. With thumbnails switched off
(:meth:`set_thumbnails_visible`) a card has no thumbnail widget at all, so its text and buttons take the space;
labels, excerpts, status, marks and actions are unchanged.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk
from typing import Any

from src.gui.design_system_v2 import SELECTED_CARD_FRAME
from src.gui.view_contracts.storyboard_tree_contract import Card, Column
from src.video.sequence_plan import ROOT_PARENT

CARD_WIDTH = 168
SCROLL_STEP_PX = 30  # one scroll "unit"; a wheel notch moves two
SEE_MARGIN = 4


class StoryboardColumnsV2(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select: Callable[[str], None],
        on_mark: Callable[[str, str], None],
        on_compare: Callable[[str], None] | None = None,
        on_resume: Callable[[str], None] | None = None,
        on_replay: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", **kwargs)
        self._on_select = on_select
        self._on_mark = on_mark
        self._on_compare = on_compare
        self._on_resume = on_resume
        self._on_replay = on_replay
        self.action_buttons: dict[tuple[str, str], ttk.Button] = {}
        self._columns: tuple[Column, ...] = ()
        self._photos: dict[str, Any] = {}
        self._thumb_labels: dict[str, ttk.Label] = {}
        self._mark_buttons: dict[str, tuple[ttk.Button, ttk.Button]] = {}
        self.compare_buttons: dict[str, ttk.Button] = {}
        self.card_frames: dict[str, ttk.Frame] = {}
        self._show_thumbnails = True
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._canvas = tk.Canvas(
            self,
            height=210,
            highlightthickness=0,
            xscrollincrement=SCROLL_STEP_PX,
            yscrollincrement=SCROLL_STEP_PX,
        )
        self._scroll = ttk.Scrollbar(self, orient="horizontal", command=self._canvas.xview)
        self._vscroll = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=self._scroll.set, yscrollcommand=self._vscroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")
        self._scroll.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._inner = ttk.Frame(self._canvas, style="Panel.TFrame")
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind(
            "<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )

    # ------------------------------------------------------------------ rendering

    def render(self, columns: tuple[Column, ...]) -> None:
        self._columns = columns
        for child in self._inner.winfo_children():
            child.destroy()
        self._thumb_labels.clear()
        self._mark_buttons.clear()
        self.compare_buttons.clear()
        self.action_buttons.clear()
        self.card_frames.clear()
        for position, column in enumerate(columns):
            holder = ttk.Frame(self._inner, style="Panel.TFrame", padding=(0, 0, 8, 0))
            holder.grid(row=0, column=position, sticky="n")
            ttk.Label(holder, text=column.title, style="Dark.TLabel").pack(anchor="w")
            for card in column.cards:
                self._build_card(holder, card)
            if sum(1 for card in column.cards if card.status_text.startswith("completed")) >= 2:
                button = ttk.Button(
                    holder,
                    text="Compare these side by side",
                    style="Dark.TButton",
                    command=partial(self._compare, column.title),
                )
                button.pack(fill="x", pady=(4, 0))
                self.compare_buttons[column.title] = button
        self._bind_wheel(self._inner)

    # ------------------------------------------------------------------ scrolling

    def _bind_wheel(self, widget: tk.Misc) -> None:
        """Route the wheel from every widget in the tree to :meth:`_on_wheel` (the canvas alone would miss cards)."""

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, self._on_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _on_wheel(self, event: Any) -> str | None:
        """Wheel scrolls up/down, Shift+wheel sideways; not consumed when there is nowhere to go (the page may scroll)."""

        number = getattr(event, "num", 0)
        delta = int(getattr(event, "delta", 0) or 0)
        if number == 4:
            delta = 120
        elif number == 5:
            delta = -120
        if not delta:
            return None
        direction = -1 if delta > 0 else 1
        sideways = bool(int(getattr(event, "state", 0) or 0) & 0x1)
        view = self._canvas.xview if sideways else self._canvas.yview
        first, last = view()
        if (direction < 0 and first <= 0.0) or (direction > 0 and last >= 1.0):
            return None
        (self._canvas.xview_scroll if sideways else self._canvas.yview_scroll)(
            direction * 2, "units"
        )
        return "break"

    def see(self, take_id: str) -> None:
        """Scroll just enough that the card is fully inside the strip, in both directions. Unknown id: nothing."""

        frame = self.card_frames.get(take_id)
        if frame is None or not frame.winfo_exists():
            return
        self.update_idletasks()
        region = self._canvas.bbox("all")
        if not region:
            return
        self._canvas.configure(scrollregion=region)
        canvas = self._canvas
        left = frame.winfo_rootx() - self._inner.winfo_rootx() + region[0]
        top = frame.winfo_rooty() - self._inner.winfo_rooty() + region[1]
        right, bottom = left + frame.winfo_width(), top + frame.winfo_height()
        view_left, view_top = canvas.canvasx(0), canvas.canvasy(0)
        view_w, view_h = canvas.winfo_width(), canvas.winfo_height()
        total_w, total_h = max(1, region[2] - region[0]), max(1, region[3] - region[1])
        if left < view_left or right > view_left + view_w:
            target = left - SEE_MARGIN if left < view_left else right + SEE_MARGIN - view_w
            canvas.xview_moveto(max(0.0, (target - region[0]) / total_w))
        if top < view_top or bottom > view_top + view_h:
            target = top - SEE_MARGIN if top < view_top else bottom + SEE_MARGIN - view_h
            canvas.yview_moveto(max(0.0, (target - region[1]) / total_h))

    @property
    def thumbnails_visible(self) -> bool:
        return self._show_thumbnails

    def set_thumbnails_visible(self, visible: bool) -> None:
        """Show or hide every card's thumbnail and re-render the cards in place (no state is lost)."""

        if visible == self._show_thumbnails:
            return
        self._show_thumbnails = visible
        if not visible:
            self._photos.clear()  # nothing hidden is kept alive, and nothing late can bring it back
        self.render(self._columns)

    def _build_card(self, holder: ttk.Frame, card: Card) -> None:
        if card.selected:
            style = SELECTED_CARD_FRAME
        else:
            style = "Card.TFrame" if card.on_path else "Panel.TFrame"
        frame = ttk.Frame(holder, style=style, padding=4)
        frame.pack(fill="x", pady=2)
        frame.configure(width=CARD_WIDTH)
        self.card_frames[card.take_id] = frame
        marker = "▶ " if card.selected else ""
        thumb: ttk.Label | None = None
        text_column = 0
        if self._show_thumbnails:
            thumb = ttk.Label(frame, text="…", width=14, anchor="center")
            thumb.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 6))
            self._thumb_labels[card.take_id] = thumb
            if card.take_id in self._photos:
                thumb.configure(image=self._photos[card.take_id], text="")
            text_column = 1
        ttk.Label(frame, text=f"{marker}{card.label}", style="Dark.TLabel").grid(
            row=0, column=text_column, sticky="w"
        )
        ttk.Label(
            frame, text=card.excerpt, style="Dark.TLabel", wraplength=110 if thumb else 190
        ).grid(row=1, column=text_column, sticky="w")
        ttk.Label(frame, text=card.status_text, style="Dark.TLabel").grid(
            row=2, column=text_column, sticky="w"
        )
        if card.take_id != ROOT_PARENT:
            keep = ttk.Button(
                frame,
                text="★" if card.mark == "kept" else "☆",
                width=3,
                command=lambda: self.toggle_keep(card.take_id),
            )
            drop = ttk.Button(
                frame,
                text="✕",
                width=3,
                command=lambda: self.toggle_drop(card.take_id),
            )
            keep.grid(row=0, column=text_column + 1, padx=2)
            drop.grid(row=1, column=text_column + 1, padx=2)
            self._mark_buttons[card.take_id] = (keep, drop)
        if card.can_resume and self._on_resume is not None:
            self._action(frame, card.take_id, "Resume", self._on_resume, 3, text_column)
        if card.can_replay and self._on_replay is not None:
            self._action(frame, card.take_id, "Replay", self._on_replay, 4, text_column)
        for widget in (frame, *frame.winfo_children()):
            if not isinstance(widget, ttk.Button):
                widget.bind("<Button-1>", partial(self._clicked, card.take_id))

    # ------------------------------------------------------------------ queries and actions

    def _action(
        self,
        frame: ttk.Frame,
        take_id: str,
        text: str,
        handler: Callable[[str], None],
        row: int,
        column: int = 1,
    ) -> None:
        button = ttk.Button(frame, text=text, command=partial(handler, take_id))
        button.grid(row=row, column=column, sticky="w")
        self.action_buttons[(take_id, text)] = button

    def _clicked(self, take_id: str, _event: Any) -> None:
        self._on_select(take_id)

    def column_titles(self) -> list[str]:
        return [column.title for column in self._columns]

    def card_take_ids(self) -> list[str]:
        return [card.take_id for column in self._columns for card in column.cards]

    def card_ids(self, title: str) -> list[str]:
        return [
            card.take_id
            for column in self._columns
            if column.title == title
            for card in column.cards
        ]

    def _find(self, take_id: str) -> Card | None:
        for column in self._columns:
            for card in column.cards:
                if card.take_id == take_id:
                    return card
        return None

    def toggle_keep(self, take_id: str) -> None:
        card = self._find(take_id)
        if card is not None:
            self._on_mark(take_id, "none" if card.mark == "kept" else "kept")

    def toggle_drop(self, take_id: str) -> None:
        card = self._find(take_id)
        if card is not None:
            self._on_mark(take_id, "none" if card.mark == "dropped" else "dropped")

    def select(self, take_id: str) -> None:
        self._on_select(take_id)

    def _compare(self, title: str) -> None:
        if self._on_compare is not None:
            self._on_compare(title)

    def set_thumbnail(self, take_id: str, photo: Any) -> None:
        if not self._show_thumbnails:
            return  # a late result must not bring a hidden thumbnail back
        self._photos[take_id] = photo
        label = self._thumb_labels.get(take_id)
        if label is not None and label.winfo_exists():
            label.configure(image=photo, text="")


__all__ = ["StoryboardColumnsV2"]
