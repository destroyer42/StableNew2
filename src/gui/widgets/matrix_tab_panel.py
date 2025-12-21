"""
MatrixTabPanel v2.6 - Matrix configuration editor for Prompt Tab.

v2.6 Changes:
- Added 'random' mode for true per-slot independent randomization
- Each slot randomly picks a value independently per run
- Random mode provides equal probability for all combinations

Provides UI for defining matrix slots (name + values) for Cartesian
prompt expansion, with real-time preview of combinations.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot
from src.gui.prompt_workspace_state import PromptWorkspaceState


class MatrixTabPanel(ttk.Frame):
    """Matrix configuration editor panel."""

    def __init__(
        self,
        parent,
        workspace_state: PromptWorkspaceState,
        on_matrix_changed: Callable[[], None],
    ):
        """
        Initialize matrix editor panel.

        Args:
            parent: Parent widget
            workspace_state: Access to current pack and matrix config
            on_matrix_changed: Callback when matrix config changes (for dirty tracking)
        """
        super().__init__(parent)
        self.workspace_state = workspace_state
        self.on_matrix_changed = on_matrix_changed

        # Matrix slot entry widgets (list of tuples: name_entry, values_entry, delete_button)
        self.slot_widgets: list[tuple[tk.Entry, tk.Entry, ttk.Button]] = []

        self._build_ui()

    def _build_ui(self) -> None:
        """Build matrix editor UI components."""
        # Main container with padding
        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        # Header frame (enable + mode + limit)
        self._build_header(container)

        # Separator
        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=10)

        # Slots editor frame
        self._build_slots_editor(container)

        # Separator
        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=10)

        # Preview frame (will be populated by Day 3)
        self._build_preview(container)

    def _build_header(self, parent: ttk.Frame) -> None:
        """Build enable checkbox, mode selector, limit spinbox."""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill="x", pady=(0, 10))

        # Enable checkbox
        self.enable_var = tk.BooleanVar(value=False)
        self.enable_check = ttk.Checkbutton(
            header_frame,
            text="Enable Matrix",
            variable=self.enable_var,
            command=self._on_enable_changed,
        )
        self.enable_check.pack(side="left", padx=(0, 20))

        # Mode label + combobox
        ttk.Label(header_frame, text="Mode:").pack(side="left", padx=(0, 5))
        self.mode_var = tk.StringVar(value="fanout")
        self.mode_combo = ttk.Combobox(
            header_frame,
            textvariable=self.mode_var,
            values=["fanout", "sequential", "random"],
            state="readonly",
            width=12,
        )
        self.mode_combo.pack(side="left", padx=(0, 20))
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self._on_mode_changed())

        # Limit label + spinbox
        ttk.Label(header_frame, text="Limit:").pack(side="left", padx=(0, 5))
        self.limit_var = tk.IntVar(value=8)
        self.limit_spin = ttk.Spinbox(
            header_frame,
            from_=1,
            to=100,
            textvariable=self.limit_var,
            width=8,
            command=self._on_limit_changed,
        )
        self.limit_spin.pack(side="left")

    def _build_slots_editor(self, parent: ttk.Frame) -> None:
        """Build slots table with scrollable frame."""
        # Label
        ttk.Label(parent, text="Matrix Slots:", font=("TkDefaultFont", 9, "bold")).pack(
            anchor="w", pady=(0, 5)
        )

        # Scrollable container for slot rows
        slots_container = ttk.Frame(parent)
        slots_container.pack(fill="both", expand=True)

        # Canvas + scrollbar for scrolling
        canvas = tk.Canvas(slots_container, height=200)
        scrollbar = ttk.Scrollbar(slots_container, orient="vertical", command=canvas.yview)
        self.slots_frame = ttk.Frame(canvas)

        self.slots_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.slots_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Header row
        header_frame = ttk.Frame(self.slots_frame)
        header_frame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 5))
        ttk.Label(header_frame, text="Name", width=15).grid(row=0, column=0, padx=5)
        ttk.Label(header_frame, text="Values (comma-separated)", width=40).grid(
            row=0, column=1, padx=5
        )
        ttk.Label(header_frame, text="", width=5).grid(row=0, column=2)

        # Add Slot button
        add_btn_frame = ttk.Frame(parent)
        add_btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(add_btn_frame, text="+ Add Slot", command=self._on_slot_added).pack(
            anchor="w"
        )

    def _build_preview(self, parent: ttk.Frame) -> None:
        """Build preview panel (Day 3 will populate with combinations)."""
        ttk.Label(parent, text="Preview:", font=("TkDefaultFont", 9, "bold")).pack(
            anchor="w", pady=(0, 5)
        )

        # Preview text area (read-only)
        preview_frame = ttk.Frame(parent)
        preview_frame.pack(fill="both", expand=True)

        self.preview_text = tk.Text(
            preview_frame, height=10, wrap="word", state="disabled", bg="#f0f0f0"
        )
        preview_scrollbar = ttk.Scrollbar(
            preview_frame, orient="vertical", command=self.preview_text.yview
        )
        self.preview_text.configure(yscrollcommand=preview_scrollbar.set)

        self.preview_text.pack(side="left", fill="both", expand=True)
        preview_scrollbar.pack(side="right", fill="y")

        # Initial message
        self.preview_text.config(state="normal")
        self.preview_text.insert("1.0", "Preview will appear here when matrix is enabled.")
        self.preview_text.config(state="disabled")

    def refresh(self) -> None:
        """Reload matrix config from workspace state."""
        matrix_config = self.workspace_state.get_matrix_config()

        # Update header controls
        self.enable_var.set(matrix_config.enabled)
        self.mode_var.set(matrix_config.mode)
        self.limit_var.set(matrix_config.limit)

        # Clear existing slot widgets
        for name_entry, values_entry, delete_btn in self.slot_widgets:
            name_entry.destroy()
            values_entry.destroy()
            delete_btn.destroy()
        self.slot_widgets.clear()

        # Rebuild slot rows
        for i, slot in enumerate(matrix_config.slots):
            self._add_slot_row(i + 1, slot.name, ",".join(slot.values))

        # Update preview (Day 3)
        # self._update_preview()

    def _add_slot_row(self, row_index: int, name: str = "", values_text: str = "") -> None:
        """Add a slot row to the editor."""
        # Name entry
        name_entry = ttk.Entry(self.slots_frame, width=15)
        name_entry.grid(row=row_index, column=0, padx=5, pady=2, sticky="ew")
        name_entry.insert(0, name)
        name_entry.bind("<KeyRelease>", lambda e, idx=row_index - 1: self._on_slot_changed(idx))

        # Values entry
        values_entry = ttk.Entry(self.slots_frame, width=40)
        values_entry.grid(row=row_index, column=1, padx=5, pady=2, sticky="ew")
        values_entry.insert(0, values_text)
        values_entry.bind(
            "<KeyRelease>", lambda e, idx=row_index - 1: self._on_slot_changed(idx)
        )

        # Delete button
        delete_btn = ttk.Button(
            self.slots_frame,
            text="X",
            width=3,
            command=lambda idx=row_index - 1: self._on_slot_deleted(idx),
        )
        delete_btn.grid(row=row_index, column=2, padx=5, pady=2)

        self.slot_widgets.append((name_entry, values_entry, delete_btn))

    def _on_enable_changed(self) -> None:
        """Enable/disable matrix and update preview."""
        enabled = self.enable_var.get()
        matrix_config = self.workspace_state.get_matrix_config()
        matrix_config.enabled = enabled
        self.on_matrix_changed()
        self._update_preview()

    def _on_mode_changed(self) -> None:
        """Update matrix mode."""
        mode = self.mode_var.get()
        matrix_config = self.workspace_state.get_matrix_config()
        matrix_config.mode = mode
        self.on_matrix_changed()
        self._update_preview()

    def _on_limit_changed(self) -> None:
        """Update matrix limit."""
        try:
            limit = self.limit_var.get()
            matrix_config = self.workspace_state.get_matrix_config()
            matrix_config.limit = limit
            self.on_matrix_changed()
            self._update_preview()
        except tk.TclError:
            pass  # Invalid input, ignore

    def _on_slot_added(self) -> None:
        """Add new empty slot row."""
        matrix_config = self.workspace_state.get_matrix_config()
        new_slot = MatrixSlot(name="", values=[])
        matrix_config.slots.append(new_slot)

        # Add UI row
        row_index = len(self.slot_widgets) + 1
        self._add_slot_row(row_index, "", "")

        self.on_matrix_changed()
        self._update_preview()

    def _on_slot_deleted(self, index: int) -> None:
        """Remove slot at index."""
        if index < 0 or index >= len(self.slot_widgets):
            return

        matrix_config = self.workspace_state.get_matrix_config()
        if index < len(matrix_config.slots):
            del matrix_config.slots[index]

        # Refresh UI
        self.refresh()
        self.on_matrix_changed()
        self._update_preview()

    def _on_slot_changed(self, index: int) -> None:
        """Update slot name/values when user types."""
        if index < 0 or index >= len(self.slot_widgets):
            return

        name_entry, values_entry, _ = self.slot_widgets[index]
        name = name_entry.get().strip()
        values_text = values_entry.get().strip()

        # Parse values (comma-separated)
        values = [v.strip() for v in values_text.split(",") if v.strip()]

        # Update matrix config
        matrix_config = self.workspace_state.get_matrix_config()
        if index < len(matrix_config.slots):
            matrix_config.slots[index].name = name
            matrix_config.slots[index].values = values
        else:
            # Shouldn't happen, but handle gracefully
            matrix_config.slots.append(MatrixSlot(name=name, values=values))

        self.on_matrix_changed()
        self._update_preview()

    def _update_preview(self) -> None:
        """Generate and display preview of expanded combinations (full prompts, no truncation)."""
        matrix_config = self.workspace_state.get_matrix_config()

        # Clear preview
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")

        # Check if disabled or no slots
        if not matrix_config.enabled or not matrix_config.slots:
            self.preview_text.insert("1.0", "Matrix disabled or no slots defined.")
            self.preview_text.config(state="disabled")
            return

        # Get current prompt text (with [[tokens]])
        current_slot = self.workspace_state.get_current_slot()
        if not current_slot or not current_slot.text.strip():
            self.preview_text.insert("1.0", "No prompt text in current slot to preview.")
            self.preview_text.config(state="disabled")
            return

        prompt_text = current_slot.text

        # Build combinations using Cartesian product
        combinations = self._build_combinations(matrix_config)

        # Apply limit if configured
        limit = matrix_config.limit if matrix_config.limit and matrix_config.limit > 0 else len(combinations)
        limited_combinations = combinations[:limit]

        # Apply combinations to prompt
        expanded_prompts = []
        for combo in limited_combinations:
            expanded = prompt_text
            for slot_name, slot_value in combo.items():
                token = f"[[{slot_name}]]"
                expanded = expanded.replace(token, slot_value)
            expanded_prompts.append(expanded)

        # Display preview (NO TRUNCATION - show full prompts)
        total = len(combinations)
        displayed = len(expanded_prompts)
        preview_lines = [f"Preview ({displayed} of {total} combinations):"]
        preview_lines.append("")

        for i, prompt in enumerate(expanded_prompts, start=1):
            # NO truncation - show full prompt
            preview_lines.append(f"{i}. {prompt}")
            preview_lines.append("")  # Blank line between prompts for readability

        if total > displayed:
            preview_lines.append(f"━━━ {total - displayed} more combinations not shown (limit={limit}) ━━━")

        self.preview_text.insert("1.0", "\n".join(preview_lines))
        self.preview_text.config(state="disabled")

    def _build_combinations(self, matrix_config: MatrixConfig) -> list[dict[str, str]]:
        """Build Cartesian product of all slot values."""
        if not matrix_config.slots:
            return []

        # Filter slots that have name and values
        valid_slots = [s for s in matrix_config.slots if s.name and s.values]
        if not valid_slots:
            return []

        # Build Cartesian product
        combinations = []
        limit = matrix_config.limit if matrix_config.limit > 0 else 9999

        def backtrack(slot_index: int, current_combo: dict[str, str]) -> None:
            if len(combinations) >= limit:
                return
            if slot_index == len(valid_slots):
                combinations.append(current_combo.copy())
                return

            slot = valid_slots[slot_index]
            for value in slot.values:
                current_combo[slot.name] = value
                backtrack(slot_index + 1, current_combo)
                if len(combinations) >= limit:
                    break

        backtrack(0, {})
        return combinations

    def get_matrix_config(self) -> MatrixConfig:
        """Return current matrix configuration."""
        return self.workspace_state.get_matrix_config()
