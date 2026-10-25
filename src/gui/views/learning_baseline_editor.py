"""Editor for Learning's own experiment baseline (the fixed settings every variant shares).

A view over ``LearningController``'s baseline draft: it renders the stage's authorable settings from
``src.learning.baseline_authoring`` and writes each edit back through the controller.  It never reads a Pipeline
card; the single place Pipeline settings enter is the explicit "Copy Current Pipeline Settings" action.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from src.gui.ui_tokens import TOKENS
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.learning import baseline_authoring as authoring
from src.learning.model_capabilities import variable_name
from src.learning.resource_access import get_projected_resources

NOTE_VARIABLE = "set by this experiment's sweep"
NOTE_MODEL = "fixed by the model profile"


def _confirm_replace(parent: tk.Misc) -> bool:
    return bool(
        messagebox.askyesno(
            "Copy Pipeline settings",
            "Replace the Learning baseline with the Pipeline's current settings?\n\n"
            "Only the editable baseline changes. Any Preview already built becomes out of date.",
            parent=parent,
        )
    )


class LearningBaselineEditor(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        controller: Any,
        *,
        stage_provider: Callable[[], str],
        variable_provider: Callable[[], str],
        input_image_provider: Callable[[], str],
        policy_notes_provider: Callable[[], dict[str, str]] | None = None,
        on_changed: Callable[[], None] | None = None,
        confirm: Callable[[tk.Misc], bool] = _confirm_replace,
    ) -> None:
        super().__init__(master)
        self._controller = controller
        self._stage_provider = stage_provider
        self._variable_provider = variable_provider
        self._input_image_provider = input_image_provider
        self._policy_notes_provider = policy_notes_provider or (lambda: {})
        self._on_changed = on_changed
        self._confirm = confirm
        self._loading = False
        self._stage = ""
        self._vars: dict[str, tk.StringVar] = {}
        self._widgets: dict[str, ttk.Widget] = {}
        self._notes: dict[str, tk.StringVar] = {}
        self.columnconfigure(0, weight=1)

        self.origin_var = tk.StringVar(value="")
        ttk.Label(
            self,
            textvariable=self.origin_var,
            wraplength=360,
            justify="left",
            foreground=TOKENS.colors.text_muted,
        ).grid(row=0, column=0, sticky="ew")
        self.copy_button = ttk.Button(
            self, text="Copy Current Pipeline Settings", command=self.copy_from_pipeline
        )
        self.copy_button.grid(row=1, column=0, sticky="w", pady=(4, 6))
        self.essential = ttk.Frame(self)
        self.essential.grid(row=2, column=0, sticky="ew")
        self.essential.columnconfigure(1, weight=1)
        self.advanced_section = DisclosureSection(
            self, title="Advanced baseline settings", expanded=False
        )
        self.advanced_section.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.advanced = self.advanced_section.body
        self.advanced.columnconfigure(1, weight=1)
        self.problems_var = tk.StringVar(value="")
        ttk.Label(
            self,
            textvariable=self.problems_var,
            wraplength=360,
            justify="left",
            foreground=TOKENS.colors.status_error,
        ).grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.rebuild(refresh=False)

    # -- structure ---------------------------------------------------------------------------------------------

    def rebuild(self, *, refresh: bool = True) -> None:
        """Recreate the field rows for the current target stage."""
        stage = self._stage_provider() or "txt2img"
        try:
            specs = authoring.fields_for_stage(stage)
        except ValueError:
            specs = ()
        self._stage = stage
        for frame in (self.essential, self.advanced):
            for child in frame.winfo_children():
                child.destroy()
        self._vars.clear()
        self._widgets.clear()
        self._notes.clear()
        rows = {id(self.essential): 0, id(self.advanced): 0}
        has_advanced = False
        for spec in specs:
            parent = self.advanced if spec.advanced else self.essential
            has_advanced = has_advanced or spec.advanced
            row = rows[id(parent)]
            rows[id(parent)] += 1
            ttk.Label(parent, text=spec.label + ":").grid(
                row=row, column=0, sticky="w", pady=1, padx=(0, 6)
            )
            var = tk.StringVar(value="")
            if spec.kind in {"resource", "choice"}:
                widget: ttk.Widget = ttk.Combobox(parent, textvariable=var, state="normal")
            else:
                widget = ttk.Entry(parent, textvariable=var, width=12)
            widget.grid(row=row, column=1, sticky="ew", pady=1)
            note = tk.StringVar(value="")
            ttk.Label(parent, textvariable=note, foreground=TOKENS.colors.text_muted).grid(
                row=row, column=2, sticky="w", padx=(6, 0)
            )
            var.trace_add("write", lambda *_a, name=spec.name: self._on_edit(name))
            self._vars[spec.name] = var
            self._widgets[spec.name] = widget
            self._notes[spec.name] = note
        if has_advanced:
            self.advanced_section.grid()
        else:
            self.advanced_section.grid_remove()
        if refresh:
            self.refresh()

    # -- state -------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the draft: values, resource choices, ownership notes and what is still missing."""
        stage = self._stage_provider() or "txt2img"
        if stage != self._stage:
            self.rebuild()
            return
        controller = self._controller
        config = controller.authoring_baseline() if controller is not None else {}
        resources = get_projected_resources(controller) if controller is not None else {}
        variable = variable_name(self._variable_provider() or "")
        notes = self._policy_notes_provider()
        self._loading = True
        try:
            for spec in authoring.fields_for_stage(stage):
                var = self._vars.get(spec.name)
                if var is None:
                    continue
                value = authoring.read_field(config, spec)
                text = "" if value is None else str(value)
                widget = self._widgets[spec.name]
                if spec.resource and isinstance(widget, ttk.Combobox):
                    names = authoring.resource_names(resources, spec.resource)
                    widget.configure(values=names)
                if var.get() != text:
                    var.set(text)
                owner = authoring.field_ownership(spec, variable=variable)
                note = ""
                state = "normal"
                if owner == authoring.OWNERSHIP_VARIABLE:
                    note, state = NOTE_VARIABLE, "disabled"
                elif spec.variable and notes.get(spec.variable) not in (None, ""):
                    note = NOTE_MODEL
                widget["state"] = state
                self._notes[spec.name].set(note)
        finally:
            self._loading = False
        record = controller.baseline_authoring_record() if controller is not None else {}
        self.origin_var.set("Baseline: " + authoring.origin_text(record or None))
        self.copy_button.configure(
            state="normal"
            if controller is not None and controller.pipeline_settings_available()
            else "disabled"
        )
        problems = self.problems()
        self.problems_var.set(("Still needed: " + "; ".join(problems)) if problems else "")

    def problems(self) -> list[str]:
        if self._controller is None:
            return []
        return list(
            self._controller.baseline_blockers(
                self._stage_provider() or "txt2img", self._input_image_provider()
            )
        )

    # -- edits -------------------------------------------------------------------------------------------------

    def _on_edit(self, name: str) -> None:
        if self._loading or self._controller is None:
            return
        try:
            self._controller.update_baseline_field(self._stage, name, self._vars[name].get())
        except ValueError as exc:
            self.problems_var.set(str(exc))
            return
        self._after_change()

    def _after_change(self) -> None:
        self.refresh()
        if callable(self._on_changed):
            self._on_changed()

    def copy_from_pipeline(self, *, confirmed: bool | None = None) -> bool:
        """The one deliberate path from the Pipeline into Learning; replaces only the editable baseline."""
        controller = self._controller
        if controller is None:
            return False
        has_edits = bool(controller.baseline_authoring_record().get("edited")) or bool(
            controller.authoring_baseline()
        )
        if has_edits:
            approved = self._confirm(self) if confirmed is None else confirmed
            if not approved:
                return False
        try:
            controller.copy_pipeline_settings(self._stage_provider() or "txt2img")
        except ValueError as exc:
            self.problems_var.set(str(exc))
            return False
        self._after_change()
        return True
