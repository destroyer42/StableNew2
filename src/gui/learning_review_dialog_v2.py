# Subsystem: Learning
# Role: Presents recent learning runs for review and rating.

"""Simple dialog for reviewing recent learning runs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import apply_toplevel_theme, style_canvas_widget
from src.gui_v2.adapters.learning_adapter_v2 import LearningRecordSummary
from src.learning.learning_record import LearningRecord


class LearningReviewDialogV2(tk.Toplevel):
    """Dialog that lists recent LearningRecords and allows rating/tag edits."""

    def __init__(
        self,
        parent: tk.Misc,
        controller: Any,
        records: Iterable[LearningRecordSummary] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Review Recent Runs")
        apply_toplevel_theme(self)
        self.geometry("940x540")
        self.minsize(720, 360)
        self.controller = controller
        self._rows: list[tuple[LearningRecordSummary, tk.StringVar, tk.StringVar]] = []
        self._body_canvas: tk.Canvas | None = None
        self._build_ui(records or [])
        self.grab_set()

    def _build_ui(self, records: Iterable[LearningRecord]) -> None:
        container = ttk.Frame(self, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Label(container, text="Recent Runs", style="Dark.TLabel")
        header.grid(row=0, column=0, sticky="w", pady=(0, 6))

        records_list = list(records)
        if not records_list:
            ttk.Label(
                container,
                text="No learning data yet. Enable learning and run a few pipelines.",
                style="Dark.TLabel",
            ).grid(row=1, column=0, sticky="w", pady=(0, 6))
            ttk.Button(container, text="Close", command=self.destroy).grid(
                row=2, column=0, sticky="e"
            )
            return

        body = ttk.Frame(container)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        canvas = tk.Canvas(body, highlightthickness=0)
        style_canvas_widget(canvas, elevated=True)
        canvas.grid(row=0, column=0, sticky="nsew")
        self._body_canvas = canvas
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        table = ttk.Frame(canvas, padding=(0, 0, 8, 0))
        table.columnconfigure(1, weight=1)
        table.columnconfigure(3, weight=1)
        window_id = canvas.create_window((0, 0), window=table, anchor="nw")

        def _sync_scrollregion(_event: tk.Event[tk.Misc] | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_inner_width(event: tk.Event[tk.Misc]) -> None:
            canvas.itemconfigure(window_id, width=max(0, event.width))

        table.bind("<Configure>", _sync_scrollregion)
        canvas.bind("<Configure>", _sync_inner_width)

        ttk.Label(table, text="Timestamp").grid(row=0, column=0, sticky=tk.W, padx=4)
        ttk.Label(table, text="Prompt/Model").grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Label(table, text="Rating").grid(row=0, column=2, sticky=tk.W, padx=4)
        ttk.Label(table, text="Tags").grid(row=0, column=3, sticky=tk.W, padx=4)

        for idx, record in enumerate(records_list, start=1):
            rating_value = getattr(record, "rating", None)
            tags_value = getattr(record, "tags", [])
            if hasattr(record, "metadata"):
                meta = getattr(record, "metadata", {}) or {}
                if rating_value is None:
                    rating_value = meta.get("rating")
                if not tags_value:
                    tags_val = meta.get("tags", "")
                    tags_value = (
                        tags_val if isinstance(tags_val, list) else str(tags_val).split(",")
                    )
            rating_var = tk.StringVar(value=str(rating_value or ""))
            tags_str = (
                ",".join(tags_value) if isinstance(tags_value, list) else str(tags_value or "")
            )
            tags_var = tk.StringVar(value=tags_str)
            summary = getattr(record, "prompt_summary", "") or getattr(record, "run_id", "")
            model = getattr(record, "pipeline_summary", "") or getattr(record, "primary_model", "")
            ttk.Label(table, text=record.timestamp).grid(
                row=idx, column=0, sticky=tk.W, padx=4, pady=2
            )
            ttk.Label(
                table,
                text=f"{summary} / {model}",
                justify=tk.LEFT,
                wraplength=420,
            ).grid(
                row=idx, column=1, sticky="ew", padx=4, pady=2
            )
            rating_spin = ttk.Spinbox(table, from_=1, to=5, textvariable=rating_var, width=4)
            rating_spin.grid(row=idx, column=2, sticky=tk.W, padx=4, pady=2)
            tags_entry = ttk.Entry(table, textvariable=tags_var, width=24)
            tags_entry.grid(row=idx, column=3, sticky="ew", padx=4, pady=2)
            self._rows.append((record, rating_var, tags_var))

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Save", command=self._on_save).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(actions, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _on_save(self) -> None:
        for record, rating_var, tags_var in self._rows:
            try:
                rating = int(rating_var.get())
            except Exception:
                rating = 0
            tags = tags_var.get().strip()
            if hasattr(self.controller, "save_feedback"):
                try:
                    self.controller.save_feedback(record, rating, tags)
                except Exception:
                    continue

    def run_modal(self) -> None:
        """Convenience to start modal loop in tests."""

        try:
            self.wait_window(self)
        except Exception:
            pass
