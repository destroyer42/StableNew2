"""
MatrixSlotPickerDialog - Modal dialog for selecting matrix slot to insert.

Displays list of available matrix slots and inserts [[slot_name]] token
into the prompt editor at cursor position.
"""

import tkinter as tk
from tkinter import ttk
from collections.abc import Callable


class MatrixSlotPickerDialog(tk.Toplevel):
    """Dialog for picking which matrix slot to insert as [[token]]."""

    def __init__(
        self,
        parent,
        available_slots: list[str],
        on_select: Callable[[str], None],
    ):
        """
        Initialize slot picker dialog.

        Args:
            parent: Parent window
            available_slots: List of slot names from matrix config
            on_select: Callback with selected slot name
        """
        super().__init__(parent)
        self.available_slots = available_slots
        self.on_select = on_select

        self.title("Insert Matrix Slot")
        self.geometry("300x400")
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self) -> None:
        """Build listbox with slots and Insert/Cancel buttons."""
        # Label
        ttk.Label(
            self,
            text="Select slot to insert:",
            padding=10,
        ).pack(anchor="w")

        # Listbox with scrollbar
        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            selectmode="single",
        )
        scrollbar.config(command=self.listbox.yview)

        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Populate listbox
        for slot_name in self.available_slots:
            self.listbox.insert("end", slot_name)

        # Double-click to insert
        self.listbox.bind("<Double-Button-1>", lambda e: self._on_insert())

        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(
            button_frame,
            text="Insert",
            command=self._on_insert,
        ).pack(side="left", padx=5)

        ttk.Button(
            button_frame,
            text="Cancel",
            command=self.destroy,
        ).pack(side="left")

    def _on_insert(self) -> None:
        """Insert selected slot and close dialog."""
        selection = self.listbox.curselection()
        if not selection:
            return

        index = selection[0]
        slot_name = self.available_slots[index]
        self.on_select(slot_name)
        self.destroy()
