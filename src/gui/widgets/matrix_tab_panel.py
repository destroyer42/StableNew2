"""
MatrixTabPanel v2.6 - Matrix configuration editor for Prompt Tab.

Provides UI for defining matrix dimensions (name + values) for Cartesian prompt expansion. The panel owns no
combination algorithm: counts, the limit in effect and the bounded examples are a projection of
``MatrixExpansionPlan`` (``src/pipeline/matrix_expansion_plan.py``), the same plan the PromptPack compiler expands
with (see ``src/gui_v2/matrix_editor_view.py``). Inspecting, loading or scrolling never changes the pack; only an
explicit edit calls ``on_matrix_changed``.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.controller.content_visibility_resolver import ContentVisibilityResolver
from src.gui.models.prompt_pack_model import MatrixConfig, MatrixSlot
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui_v2.matrix_editor_view import (
    STARTER_DIMENSIONS,
    TOKEN_HELP,
    MatrixEditorView,
    build_matrix_editor_view,
    parse_seed_entry,
)
from src.utils.prompt_pack_utils import normalize_matrix_slot_name

_MODES = ["fanout", "sequential", "random"]
_HELP_WRAP = 560


def _values_text(values: list[Any]) -> str:
    return ",".join(str(value) for value in values)


class MatrixTabPanel(ttk.Frame):
    """Matrix configuration editor panel."""

    _PREVIEW_DEBOUNCE_MS = 200

    def __init__(
        self,
        parent,
        workspace_state: PromptWorkspaceState,
        on_matrix_changed: Callable[[], None],
        visibility_mode_provider: Callable[[], str] | None = None,
    ):
        """
        Initialize matrix editor panel.

        Args:
            parent: Parent widget
            workspace_state: Access to current pack and matrix config
            on_matrix_changed: Callback when matrix config changes (for dirty tracking)
            visibility_mode_provider: Returns the content-visibility mode used to redact example prompts
        """
        super().__init__(parent)
        self.workspace_state = workspace_state
        self.on_matrix_changed = on_matrix_changed
        self._visibility_mode_provider = visibility_mode_provider
        self._preview_refresh_after_id: str | None = None
        self._destroyed = False

        # Matrix slot entry widgets (list of tuples: name_entry, values_entry, delete_button)
        self.slot_widgets: list[tuple[tk.Entry, tk.Entry, ttk.Button]] = []
        self.last_view: MatrixEditorView | None = None

        self._build_ui()
        self._update_preview()

    def _build_ui(self) -> None:
        """Build matrix editor UI components."""
        self._scroll = ScrollableFrame(self)
        self._scroll.pack(fill="both", expand=True)
        container = ttk.Frame(self._scroll.inner, padding=10)
        container.pack(fill="both", expand=True)

        self._build_header(container)
        self._build_guidance(container)

        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=10)
        self._build_slots_editor(container)

        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=10)
        self._build_summary(container)
        self._build_preview(container)

    def _build_header(self, parent: ttk.Frame) -> None:
        """Build enable checkbox, mode selector, limit spinbox and the optional sample seed."""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill="x", pady=(0, 6))

        # Enable checkbox
        self.enable_var = tk.BooleanVar(value=False)
        self.enable_check = ttk.Checkbutton(
            header_frame,
            text="Enable Matrix",
            variable=self.enable_var,
            command=self._on_enable_changed,
        )
        self.enable_check.pack(side="left", padx=(0, 20))

        # Mode label + combobox. The stored values stay fanout / sequential / random.
        ttk.Label(header_frame, text="Mode:").pack(side="left", padx=(0, 5))
        self.mode_var = tk.StringVar(value="fanout")
        self.mode_combo = ttk.Combobox(
            header_frame,
            textvariable=self.mode_var,
            values=_MODES,
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
        self.limit_spin.bind("<KeyRelease>", lambda e: self._on_limit_typed())
        self.limit_spin.bind("<FocusOut>", lambda e: self._on_limit_typed())

        # Sample seed: shown only for random mode.
        self.seed_frame = ttk.Frame(parent)
        ttk.Label(self.seed_frame, text="Sample seed (optional):").pack(side="left", padx=(0, 5))
        self.seed_var = tk.StringVar(value="")
        self.seed_entry = ttk.Entry(self.seed_frame, textvariable=self.seed_var, width=14)
        self.seed_entry.pack(side="left")
        self.seed_entry.bind("<KeyRelease>", lambda e: self._on_seed_typed())
        self.seed_entry.bind("<FocusOut>", lambda e: self._on_seed_typed())
        self.seed_error_var = tk.StringVar(value="")
        ttk.Label(self.seed_frame, textvariable=self.seed_error_var, foreground="#b00020").pack(
            side="left", padx=(8, 0)
        )

    def _build_guidance(self, parent: ttk.Frame) -> None:
        self.mode_help_var = tk.StringVar(value="")
        self.mode_help_label = ttk.Label(
            parent, textvariable=self.mode_help_var, wraplength=_HELP_WRAP, justify="left"
        )
        self.mode_help_label.pack(anchor="w", pady=(0, 4))
        self.seed_help_var = tk.StringVar(value="")
        self.seed_help_label = ttk.Label(
            parent, textvariable=self.seed_help_var, wraplength=_HELP_WRAP, justify="left"
        )
        self.token_help_label = ttk.Label(
            parent, text=TOKEN_HELP, wraplength=_HELP_WRAP, justify="left"
        )
        self.token_help_label.pack(anchor="w", pady=(0, 4))

    def _build_slots_editor(self, parent: ttk.Frame) -> None:
        """Build slots table with scrollable frame."""
        ttk.Label(parent, text="Matrix Dimensions:", font=("TkDefaultFont", 9, "bold")).pack(
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

        # Add Slot button + starter examples (each adds one new dimension; nothing is overwritten)
        add_btn_frame = ttk.Frame(parent)
        add_btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(add_btn_frame, text="+ Add Slot", command=self._on_slot_added).pack(side="left")
        ttk.Label(add_btn_frame, text="Starter example:").pack(side="left", padx=(16, 5))
        self.example_var = tk.StringVar(value=STARTER_DIMENSIONS[0].label)
        self.example_combo = ttk.Combobox(
            add_btn_frame,
            textvariable=self.example_var,
            values=[item.label for item in STARTER_DIMENSIONS],
            state="readonly",
            width=22,
        )
        self.example_combo.pack(side="left")
        ttk.Button(add_btn_frame, text="Add example", command=self._on_example_added).pack(
            side="left", padx=(5, 0)
        )
        self.example_message_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.example_message_var).pack(anchor="w")

    def _build_summary(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Counts:", font=("TkDefaultFont", 9, "bold")).pack(
            anchor="w", pady=(0, 3)
        )
        self.summary_var = tk.StringVar(value="")
        self.summary_label = ttk.Label(
            parent, textvariable=self.summary_var, wraplength=_HELP_WRAP, justify="left"
        )
        self.summary_label.pack(anchor="w")
        self.warning_var = tk.StringVar(value="")
        self.warning_label = ttk.Label(
            parent,
            textvariable=self.warning_var,
            wraplength=_HELP_WRAP,
            justify="left",
            foreground="#8a4b00",
        )
        self.warning_label.pack(anchor="w", pady=(4, 0))

    def _build_preview(self, parent: ttk.Frame) -> None:
        """Build the bounded examples panel."""
        self.preview_heading_var = tk.StringVar(value="Examples")
        ttk.Label(
            parent, textvariable=self.preview_heading_var, font=("TkDefaultFont", 9, "bold")
        ).pack(anchor="w", pady=(8, 5))

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
        self.preview_text.insert("1.0", "Examples will appear here when the Matrix has dimensions.")
        self.preview_text.config(state="disabled")

    def destroy(self) -> None:
        """Cancel the pending debounced update so a stale callback never touches a dead widget."""
        self._destroyed = True
        self._cancel_pending_preview()
        super().destroy()

    def refresh(self) -> None:
        """Reload matrix config from workspace state. Never marks the pack dirty."""
        matrix_config = self.workspace_state.get_matrix_config()

        # Update header controls
        self.enable_var.set(matrix_config.enabled)
        self.mode_var.set(matrix_config.mode)
        self.limit_var.set(matrix_config.limit)
        self.seed_var.set(
            "" if matrix_config.sample_seed is None else str(matrix_config.sample_seed)
        )
        self.seed_error_var.set("")
        self.example_message_var.set("")

        # Clear existing slot widgets
        for name_entry, values_entry, delete_btn in self.slot_widgets:
            name_entry.destroy()
            values_entry.destroy()
            delete_btn.destroy()
        self.slot_widgets.clear()

        # Rebuild slot rows
        for i, slot in enumerate(matrix_config.slots):
            self._add_slot_row(i + 1, slot.name, _values_text(slot.values))

        self._schedule_preview_update(immediate=True)

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
        values_entry.bind("<KeyRelease>", lambda e, idx=row_index - 1: self._on_slot_changed(idx))

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
        self._schedule_preview_update(immediate=True)

    def _on_mode_changed(self) -> None:
        """Update matrix mode."""
        mode = self.mode_var.get()
        matrix_config = self.workspace_state.get_matrix_config()
        if mode != matrix_config.mode or "mode" in matrix_config.preserved:
            matrix_config.mode = mode
            matrix_config.clear_preserved("mode")
            self.on_matrix_changed()
        self._schedule_preview_update(immediate=True)

    def _on_limit_changed(self) -> None:
        """Spinbox arrow: apply the new limit."""
        self._apply_limit_text(self.limit_spin.get())

    def _on_limit_typed(self) -> None:
        """Typed limit: apply it once it is a positive whole number; anything else leaves the stored limit alone."""
        self._apply_limit_text(self.limit_spin.get())

    def _apply_limit_text(self, text: str) -> None:
        cleaned = str(text or "").strip()
        matrix_config = self.workspace_state.get_matrix_config()
        if not cleaned.isascii() or not cleaned.isdigit() or int(cleaned) <= 0:
            self._schedule_preview_update()
            return
        limit = int(cleaned)
        if limit != matrix_config.limit or "limit" in matrix_config.preserved:
            matrix_config.limit = limit
            matrix_config.clear_preserved("limit")
            self.on_matrix_changed()
        self._schedule_preview_update(immediate=True)

    def _on_seed_typed(self) -> None:
        """Apply the sample seed when valid; an invalid entry is reported and the stored seed is left untouched."""
        seed, error = parse_seed_entry(self.seed_var.get())
        self.seed_error_var.set(error)
        if error:
            return
        matrix_config = self.workspace_state.get_matrix_config()
        if seed != matrix_config.sample_seed or "sample_seed" in matrix_config.preserved:
            matrix_config.sample_seed = seed
            matrix_config.clear_preserved("sample_seed")
            self.on_matrix_changed()
        self._schedule_preview_update()

    def _on_slot_added(self) -> None:
        """Add new empty slot row."""
        matrix_config = self.workspace_state.get_matrix_config()
        new_slot = MatrixSlot(name="", values=[])
        matrix_config.slots.append(new_slot)

        # Add UI row
        row_index = len(self.slot_widgets) + 1
        self._add_slot_row(row_index, "", "")

        self.on_matrix_changed()
        self._schedule_preview_update(immediate=True)

    def _on_example_added(self) -> None:
        """Add the chosen starter dimension as a new row. An existing dimension of that name is never touched."""
        choice = next(
            (item for item in STARTER_DIMENSIONS if item.label == self.example_var.get()), None
        )
        if choice is None:
            return
        matrix_config = self.workspace_state.get_matrix_config()
        wanted = normalize_matrix_slot_name(choice.name)
        if any(normalize_matrix_slot_name(slot.name) == wanted for slot in matrix_config.slots):
            self.example_message_var.set(
                f"A dimension named '{choice.name}' already exists, so nothing was added."
            )
            return
        matrix_config.slots.append(MatrixSlot(name=choice.name, values=list(choice.values)))
        self._add_slot_row(
            len(self.slot_widgets) + 1, choice.name, _values_text(list(choice.values))
        )
        self.example_message_var.set(
            f"Added '{choice.name}'. Use [[{choice.name}]] in a prompt, and turn Matrix on to use it."
        )
        self.on_matrix_changed()
        self._schedule_preview_update(immediate=True)

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
        self._schedule_preview_update(immediate=True)

    def _on_slot_changed(self, index: int) -> None:
        """Update slot name/values when user types. A key release that changes nothing is not an edit."""
        if index < 0 or index >= len(self.slot_widgets):
            return

        name_entry, values_entry, _ = self.slot_widgets[index]
        name = name_entry.get().strip()
        values_text = values_entry.get().strip()
        matrix_config = self.workspace_state.get_matrix_config()

        if index < len(matrix_config.slots):
            slot = matrix_config.slots[index]
            if name == slot.name.strip() and values_text == _values_text(slot.values).strip():
                return
        # Parse values (comma-separated)
        values = [v.strip() for v in values_text.split(",") if v.strip()]

        # Update matrix config
        if index < len(matrix_config.slots):
            matrix_config.slots[index].name = name
            matrix_config.slots[index].values = values
            matrix_config.slots[index].preserved.pop("__item__", None)
            for key in ("name", "values"):
                matrix_config.slots[index].preserved.pop(key, None)
        else:
            # Shouldn't happen, but handle gracefully
            matrix_config.slots.append(MatrixSlot(name=name, values=values))

        self.on_matrix_changed()
        self._schedule_preview_update()

    def _cancel_pending_preview(self) -> None:
        if self._preview_refresh_after_id is not None:
            try:
                self.after_cancel(self._preview_refresh_after_id)
            except Exception:
                pass
            self._preview_refresh_after_id = None

    def _schedule_preview_update(self, *, immediate: bool = False) -> None:
        if self._destroyed:
            return
        self._cancel_pending_preview()

        if immediate:
            self._update_preview()
            return

        self._preview_refresh_after_id = self.after(
            self._PREVIEW_DEBOUNCE_MS,
            self._run_scheduled_preview_update,
        )

    def _run_scheduled_preview_update(self) -> None:
        self._preview_refresh_after_id = None
        if self._destroyed:
            return
        self._update_preview()

    def _pack_batch_factors(self) -> tuple[int | None, int | None]:
        """``(loop_count, images_per_prompt)`` saved with the current pack, when they are plain numbers."""
        pack = self.workspace_state.current_pack
        preset = getattr(pack, "preset_data", None) if pack is not None else None
        pipeline = preset.get("pipeline") if isinstance(preset, dict) else None
        if not isinstance(pipeline, dict):
            return None, None

        def positive(key: str) -> int | None:
            value = pipeline.get(key)
            return (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value > 0
                else None
            )

        return positive("loop_count"), positive("images_per_prompt")

    def _redact(self, text: str) -> str:
        provider = self._visibility_mode_provider
        mode = str(provider() or "nsfw") if provider is not None else "nsfw"
        return ContentVisibilityResolver(mode).redact_text(text)

    def build_view(self) -> MatrixEditorView:
        """Project the current editor state (no side effects)."""
        matrix_config = self.workspace_state.get_matrix_config()
        current_slot = self.workspace_state.get_current_slot()
        prompt_text = current_slot.text if current_slot else ""
        loop_count, images_per_prompt = self._pack_batch_factors()
        return build_matrix_editor_view(
            matrix_config,
            prompt_text,
            batch_runs=loop_count,
            images_per_prompt=images_per_prompt,
        )

    def _update_preview(self) -> None:
        """Render the projection: guidance, counts, warnings and bounded examples."""
        if self._destroyed:
            return
        view = self.build_view()
        self.last_view = view

        self.mode_help_var.set(f"{view.mode_title}: {view.mode_help}")
        if view.show_seed:
            if not self.seed_frame.winfo_manager():
                self.seed_frame.pack(fill="x", pady=(0, 6), before=self.mode_help_label)
            self.seed_help_var.set(view.seed_help)
            if not self.seed_help_label.winfo_manager():
                self.seed_help_label.pack(anchor="w", pady=(0, 4), before=self.token_help_label)
            if view.seed_error:
                self.seed_error_var.set(view.seed_error)
        else:
            self.seed_frame.pack_forget()
            self.seed_help_label.pack_forget()

        self.summary_var.set("\n".join((*view.count_lines, *view.multiplicity_lines)))
        self.warning_var.set("\n".join(view.warnings))
        self.preview_heading_var.set(view.examples_heading)

        lines = [self._redact(row) for row in view.example_rows]
        if not lines:
            lines = [
                "No examples yet: enable Matrix, add dimensions, and write a prompt using [[name]] tokens."
            ]
        if view.examples_footer:
            lines.extend(["", view.examples_footer])

        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", "\n".join(lines))
        self.preview_text.config(state="disabled")

    def get_matrix_config(self) -> MatrixConfig:
        """Return current matrix configuration."""
        return self.workspace_state.get_matrix_config()
