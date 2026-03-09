# Subsystem: Learning
# Role: Renders a table of learning plans and planned runs.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from src.gui.learning_state import LearningVariant


class LearningPlanTable(ttk.Frame):
    """Center panel for learning plan table display."""

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)
        self._on_variant_selected: Callable[[int], None] | None = None
        self._stage_name: str = "txt2img"
        self._row_index_by_item: dict[str, int] = {}

        # Configure layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Create treeview for the plan table
        self._create_table()

    def _create_table(self) -> None:
        """Create the plan table treeview."""
        table_frame = ttk.Frame(self)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("variant", "param_value", "stage", "status", "images", "rating")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)

        self.tree.heading("variant", text="Variant #")
        self.tree.heading("param_value", text="Parameter Value")
        self.tree.heading("stage", text="Stage")
        self.tree.heading("status", text="Status")
        self.tree.heading("images", text="Images")
        self.tree.heading("rating", text="Avg Rating")

        self.tree.column("variant", width=80, anchor="center")
        self.tree.column("param_value", width=120, anchor="center")
        self.tree.column("stage", width=80, anchor="center")
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("images", width=80, anchor="center")
        self.tree.column("rating", width=80, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)

    def set_on_variant_selected(self, callback: Callable[[int], None] | None) -> None:
        """Set callback invoked when user selects a variant row."""
        self._on_variant_selected = callback

    def set_stage_name(self, stage_name: str) -> None:
        """Set stage label used for table rows."""
        stage = str(stage_name or "").strip().lower()
        self._stage_name = stage or "txt2img"

    def update_plan(self, plan: list[LearningVariant], stage_name: str | None = None) -> None:
        """Update the table with the current learning plan."""
        if stage_name is not None:
            self.set_stage_name(stage_name)

        for item in self.tree.get_children():
            self.tree.delete(item)
        self._row_index_by_item = {}

        for i, variant in enumerate(plan):
            item = self.tree.insert(
                "",
                "end",
                values=(
                    f"#{i + 1}",
                    str(variant.param_value),
                    self._stage_name,
                    variant.status.title(),
                    f"{variant.completed_images}/{variant.planned_images}",
                    "-",
                ),
            )
            self._row_index_by_item[item] = i

    def _on_row_selected(self, _event: Any) -> None:
        """Handle row selection in the table."""
        selection = self.tree.selection()
        if not selection:
            return
        row_index = self._row_index_by_item.get(selection[0])
        if row_index is not None:
            self._notify_row_selected(row_index)

    def _notify_row_selected(self, index: int) -> None:
        """Notify controller of row selection."""
        callback = self._on_variant_selected
        if callable(callback):
            callback(index)

    def update_row_status(self, index: int, status: str) -> None:
        """Update the status of a specific row."""
        try:
            item = self.tree.get_children()[index]
            current_values = list(self.tree.item(item, "values"))
            current_values[3] = status.title()
            self.tree.item(item, values=current_values)
        except (IndexError, TypeError):
            pass

    def update_row_images(self, index: int, completed: int, planned: int) -> None:
        """Update the images count of a specific row."""
        try:
            item = self.tree.get_children()[index]
            current_values = list(self.tree.item(item, "values"))
            current_values[4] = f"{completed}/{planned}"
            self.tree.item(item, values=current_values)
        except (IndexError, TypeError):
            pass

    def update_row_rating(self, index: int, avg_rating: float | None) -> None:
        """Update the average rating display for a row."""
        try:
            item = self.tree.get_children()[index]
            current_values = list(self.tree.item(item, "values"))

            if avg_rating is not None:
                if avg_rating >= 4.5:
                    rating_display = "*****"
                elif avg_rating >= 3.5:
                    rating_display = "****"
                elif avg_rating >= 2.5:
                    rating_display = "***"
                elif avg_rating >= 1.5:
                    rating_display = "**"
                else:
                    rating_display = "*"
            else:
                rating_display = "-"

            current_values[5] = rating_display
            self.tree.item(item, values=current_values)
        except (IndexError, TypeError):
            pass

    def highlight_row(self, index: int, highlight: bool = True) -> None:
        """Highlight or unhighlight a specific row."""
        try:
            item = self.tree.get_children()[index]
            if highlight:
                self.tree.item(item, tags=("highlight",))
            else:
                self.tree.item(item, tags=())
        except (IndexError, TypeError):
            pass

    def clear_highlights(self) -> None:
        """Clear all row highlights."""
        for item in self.tree.get_children():
            self.tree.item(item, tags=())
