# Renamed from learning_plan_table.py to learning_plan_table_v2.py
# ...existing code...

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.learning_state import LearningVariant


class LearningPlanTable(ttk.Frame):
    """Center panel for learning plan table display."""

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)

        # Configure layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Create treeview for the plan table
        self._create_table()

    def _create_table(self) -> None:
        """Create the plan table treeview."""
        # Frame for the table
        table_frame = ttk.Frame(self)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        # Treeview with columns
        columns = ("variant", "param_value", "stage", "status", "images")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)

        # Define headings
        self.tree.heading("variant", text="Variant #")
        self.tree.heading("param_value", text="Parameter Value")
        self.tree.heading("stage", text="Stage")
        self.tree.heading("status", text="Status")
        self.tree.heading("images", text="Images")

        # Define column widths
        self.tree.column("variant", width=80, anchor="center")
        self.tree.column("param_value", width=120, anchor="center")
        self.tree.column("stage", width=80, anchor="center")
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("images", width=80, anchor="center")

        # Add scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        # Grid the treeview and scrollbar
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Add selection binding
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)

    def update_plan(self, plan: list[LearningVariant]) -> None:
        """Update the table with the current learning plan."""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Add variants to the table
        for i, variant in enumerate(plan, 1):
            self.tree.insert(
                "",
                "end",
                values=(
                    f"#{i + 1}",
                    str(variant.param_value),
                    "txt2img",  # TODO: Get from experiment stage
                    variant.status.title(),
                    f"{variant.completed_images}/{variant.planned_images}",
                ),
            )

    def _on_row_selected(self, event: Any) -> None:
        """Handle row selection in the table."""
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            # Get the row index (variant number - 1)
            values = self.tree.item(item, "values")
            if values:
                try:
                    variant_num = int(values[0].replace("#", ""))
                    self._notify_row_selected(variant_num - 1)  # Convert to 0-based index
                except (ValueError, IndexError):
                    pass

    def _notify_row_selected(self, index: int) -> None:
        """Notify controller of row selection."""
        # This will be called by the controller to handle selection
        if hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "on_variant_selected"):
                controller.on_variant_selected(index)

    def update_row_status(self, index: int, status: str) -> None:
        """Update the status of a specific row."""
        try:
            item = self.tree.get_children()[index]
            current_values = list(self.tree.item(item, "values"))
            current_values[3] = status.title()  # Status column is index 3
            self.tree.item(item, values=current_values)
        except (IndexError, TypeError):
            # Row doesn't exist or invalid data
            pass

    def update_row_images(self, index: int, completed: int, planned: int) -> None:
        """Update the images count of a specific row."""
        try:
            item = self.tree.get_children()[index]
            current_values = list(self.tree.item(item, "values"))
            current_values[4] = f"{completed}/{planned}"  # Images column is index 4
            self.tree.item(item, values=current_values)
        except (IndexError, TypeError):
            # Row doesn't exist or invalid data
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
            # Row doesn't exist
            pass

    def clear_highlights(self) -> None:
        """Clear all row highlights."""
        for item in self.tree.get_children():
            self.tree.item(item, tags=())


LearningPlanTable = LearningPlanTable
