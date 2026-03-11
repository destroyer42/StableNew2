# Subsystem: Learning / GUI
# Role: Compact image comparison table for a discovered-review group.

"""DiscoveredReviewTable — shows all items in a discovered group for comparison."""

from __future__ import annotations

from tkinter import ttk
from typing import Any, Callable

import tkinter as tk

from src.gui.theme_v2 import BODY_LABEL_STYLE, SURFACE_FRAME_STYLE
from src.learning.discovered_review_models import (
    RATING_MAX,
    RATING_MIN,
    RATING_UNRATED,
    DiscoveredReviewItem,
)


_RATING_LABELS = {
    RATING_UNRATED: "—",
    1: "★",
    2: "★★",
    3: "★★★",
    4: "★★★★",
    5: "★★★★★",
}


class DiscoveredReviewTable(ttk.Frame):
    """Item comparison table for a single discovered-review group.

    Displays each artifact as a row.  Allows per-item rating selection.

    Callbacks
    ---------
    on_rate_item(item_id, rating):
        Called when the user changes a rating.
    on_item_selected(item_id):
        Called when a row is focused.
    """

    def __init__(
        self,
        master: tk.Misc,
        on_rate_item: Callable[[str, int], None] | None = None,
        on_item_selected: Callable[[str], None] | None = None,
        varying_fields: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_rate_item = on_rate_item
        self._on_item_selected = on_item_selected
        self._varying_fields = varying_fields or []
        self._items: list[DiscoveredReviewItem] = []
        self._rating_vars: dict[str, tk.IntVar] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # header label
        self._header_label = ttk.Label(
            self,
            text="No group loaded",
            style=BODY_LABEL_STYLE,
            font=("TkDefaultFont", 10, "bold"),
        )
        self._header_label.grid(row=0, column=0, sticky="w", padx=4, pady=(4, 2))

        # table frame
        table_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE, padding=2)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=2)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        fixed_cols = ("rating", "stage", "model", "sampler", "steps", "cfg")
        varying_cols = tuple(self._varying_fields)
        all_cols = fixed_cols + varying_cols + ("path",)

        self._tree = ttk.Treeview(
            table_frame,
            columns=all_cols,
            show="headings",
            selectmode="browse",
        )
        # Fixed column headings
        self._tree.heading("rating", text="Rating")
        self._tree.heading("stage", text="Stage")
        self._tree.heading("model", text="Model")
        self._tree.heading("sampler", text="Sampler")
        self._tree.heading("steps", text="Steps")
        self._tree.heading("cfg", text="CFG")
        self._tree.column("rating", width=70, anchor="center")
        self._tree.column("stage", width=70, anchor="center")
        self._tree.column("model", width=160, anchor="w")
        self._tree.column("sampler", width=90, anchor="center")
        self._tree.column("steps", width=50, anchor="center")
        self._tree.column("cfg", width=50, anchor="center")
        # Varying column headings
        for v in varying_cols:
            self._tree.heading(v, text=v)
            self._tree.column(v, width=80, anchor="center")
        # Path column
        self._tree.heading("path", text="File")
        self._tree.column("path", width=200, anchor="w")

        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # rating control strip
        rating_bar = ttk.Frame(self, style=SURFACE_FRAME_STYLE, padding=(4, 2))
        rating_bar.grid(row=2, column=0, sticky="ew")
        ttk.Label(rating_bar, text="Rate selected:", style=BODY_LABEL_STYLE).pack(
            side="left", padx=(0, 4)
        )
        for r in range(RATING_MIN, RATING_MAX + 1):
            ttk.Button(
                rating_bar,
                text=f"{r}★",
                width=4,
                command=lambda rv=r: self._apply_rating(rv),
            ).pack(side="left", padx=1)
        ttk.Button(
            rating_bar,
            text="Clear",
            width=5,
            command=lambda: self._apply_rating(RATING_UNRATED),
        ).pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_items(
        self,
        items: list[DiscoveredReviewItem],
        varying_fields: list[str] | None = None,
        group_display_name: str = "",
    ) -> None:
        """Populate the table with *items*."""
        self._items = list(items)
        if varying_fields is not None:
            self._varying_fields = varying_fields
        if group_display_name:
            self._header_label.configure(text=group_display_name)
        self._render_items()

    def refresh_item_rating(self, item_id: str, rating: int) -> None:
        """Update the displayed rating for a single item without full reload."""
        label = _RATING_LABELS.get(rating, "—")
        try:
            self._tree.set(item_id, "rating", label)
        except Exception:
            pass

    def get_selected_item_id(self) -> str | None:
        sel = self._tree.selection()
        return sel[0] if sel else None

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _render_items(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for item in self._items:
            rating_label = _RATING_LABELS.get(item.rating, "—")
            fixed_values = (
                rating_label,
                item.stage,
                _truncate(item.model, 24),
                item.sampler,
                item.steps,
                f"{item.cfg_scale:.1f}",
            )
            varying_values = tuple(
                str(item.extra_fields.get(f, getattr(item, f, "—")) or "—")
                for f in self._varying_fields
            )
            path_value = (_truncate(item.artifact_path, 40),)
            self._tree.insert(
                "",
                "end",
                iid=item.item_id,
                values=fixed_values + varying_values + path_value,
            )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_tree_select(self, _event: Any = None) -> None:
        item_id = self.get_selected_item_id()
        if item_id and self._on_item_selected:
            self._on_item_selected(item_id)

    def _apply_rating(self, rating: int) -> None:
        item_id = self.get_selected_item_id()
        if not item_id:
            return
        self.refresh_item_rating(item_id, rating)
        if self._on_rate_item:
            self._on_rate_item(item_id, rating)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return "…" + text[-(max_len - 1):]
