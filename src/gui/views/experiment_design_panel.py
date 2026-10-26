from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from src.gui.controllers.learning_controller import LearningController
from src.gui.models.prompt_metadata import build_prompt_metadata
from src.gui.models.prompt_pack_model import PromptPackModel, PromptSlot
from src.gui.ui_tokens import TOKENS
from src.gui.views.grid_design_frame import TwoAxisDesignFrame
from src.gui.views.learning_baseline_editor import LearningBaselineEditor
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.image_backends.model_policy import ModelPolicy
from src.learning import baseline_authoring as authoring
from src.learning.design_estimate import estimate_design
from src.learning.experiment_naming import build_experiment_identity
from src.learning.model_capabilities import (
    compatible_context,
    policy_context,
    project_learning_capabilities,
)
from src.learning.model_policy_service import live_capabilities, resolve_policy, selected_model
from src.learning.resource_access import get_resource_choices, resolve_app_state
from src.learning.stage_capabilities import (
    get_stage_capability,
    get_variables_for_stage,
    list_supported_stages,
)
from src.promptpacks.paths import resolve_prompt_pack_dir
from src.utils.embedding_prompt_utils import normalize_embedding_entries, render_embedding_reference
from src.utils.file_io import read_prompt_pack
from src.utils.prompt_packs import discover_packs


def _call(panel: Any, name: str, *args: Any) -> None:
    """Call an optional panel hook (the Preview path is also driven on stand-in panels in tests)."""
    method = getattr(panel, name, None)
    if callable(method):
        method(*args)


def _prompt_slot(panel: Any) -> bool:
    variable = getattr(panel, "study_type_var", None)
    return variable is not None and variable.get() == "Prompt Slot"


def _speak(panel: Any, text: str, *, ok: bool = False) -> None:
    panel.feedback_var.set(text)
    label = getattr(panel, "feedback_label", None)
    if label is not None:
        label.configure(foreground=TOKENS.colors.status_success if ok else TOKENS.colors.status_error)


STUDY_HINTS = {
    "Prompt Slot": "Compare alternatives for one named prompt slot with the other inputs fixed.",
    "Controlled Variable": "Test several values for one setting while keeping the other settings consistent.",
    "Model Comparison": (
        "Compare several models, each with its own validated settings and prompt. "
        "A preference between models, not a one-variable test."
    ),
    "Two-Axis Grid": (
        "Vary two settings together on one model and prompt. An exploratory comparison; "
        "its ratings never become recommendations."
    ),
}


class ExperimentDesignPanel(ttk.Frame):
    """Left panel for experiment design controls."""

    def __init__(
        self,
        master: tk.Misc,
        learning_controller: LearningController | None = None,
        prompt_workspace_state: Any | None = None,
        packs_dir: str | Path | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, *args, **kwargs)
        self.learning_controller = learning_controller
        self.prompt_workspace_state = prompt_workspace_state
        self._packs_dir = Path(packs_dir) if packs_dir is not None else None
        self._name_auto_generated = True
        self._description_auto_generated = True
        self._target_policy: ModelPolicy | None = None
        self._learning_capabilities = None
        self._suspend_identity_tracking = False
        self._comparison_readiness_busy = False
        self._comparison_evidence_task = None
        self._comparison_poll_id = None
        self._prompt_pack_paths: dict[str, Path] = {}
        self._prompt_option_payloads: dict[str, dict[str, Any]] = {}
        self._study_mode = "controlled"
        self._grid_preview_signature: Any = None
        # Signature of the inputs the current Preview was built from (None: unknown, e.g. built elsewhere).
        self._preview_signature: Any = None
        self._run_in_progress = False
        self._design_changed_callback: Any = None
        self._preview_built_callback: Any = None
        self._resource_state = resolve_app_state(self.learning_controller)
        if self._resource_state is not None and hasattr(self._resource_state, "add_resource_listener"):
            self._resource_state.add_resource_listener(self._on_resources_updated)

        # Configure layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Title
        self.rowconfigure(1, weight=0)  # Experiment Name
        self.rowconfigure(2, weight=0)  # Description
        self.rowconfigure(3, weight=0)  # Target Stage
        self.rowconfigure(4, weight=0)  # Input Image
        self.rowconfigure(5, weight=0)  # Variable Under Test
        self.rowconfigure(6, weight=0)  # Value Specification
        self.rowconfigure(7, weight=0)  # Images per Variant
        self.rowconfigure(8, weight=0)  # Prompt Source
        self.rowconfigure(9, weight=0)  # Buttons
        self.rowconfigure(10, weight=0)  # Feedback
        self.rowconfigure(12, weight=1)  # Spacer

        self._shown = False
        self._build_ui()
        for sequence in ("<Map>", "<Visibility>", "<Expose>"):
            self.bind(sequence, self._on_shown, add="+")
        if self._resource_state is not None and hasattr(self._resource_state, "subscribe"):
            self._resource_state.subscribe("content_visibility_mode", self._on_comparison_visibility_changed)

    def _build_ui(self) -> None:
        """Build the experiment design UI."""
        # Title
        title_label = ttk.Label(self, text="Experiment Design", font=("TkDefaultFont", 12, "bold"))
        title_label.grid(row=0, column=0, pady=(0, 10), sticky="w")

        self.stage_hint_var = tk.StringVar(value="")
        stage_hint = ttk.Label(
            self, textvariable=self.stage_hint_var, foreground=TOKENS.colors.text_muted
        )
        stage_hint.grid(row=0, column=0, sticky="e")

        # Experiment Name
        ttk.Label(self, text="Experiment Name:").grid(row=1, column=0, sticky="w", pady=(0, 2))
        self.name_var = tk.StringVar(value="")
        self.name_entry = ttk.Entry(self, textvariable=self.name_var)
        self.name_entry.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.name_var.trace_add("write", lambda *_: self._on_name_changed())

        # Description is optional context, so it lives behind a disclosure.
        self.details_section = DisclosureSection(self, title="Optional details", expanded=False)
        self.details_section.grid(row=3, column=0, rowspan=2, sticky="ew", pady=(0, 10))
        details = self.details_section.body
        details.columnconfigure(0, weight=1)
        ttk.Label(details, text="Description:").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.desc_var = tk.StringVar(value="")
        self.desc_entry = ttk.Entry(details, textvariable=self.desc_var)
        self.desc_entry.grid(row=1, column=0, sticky="ew")
        self.desc_var.trace_add("write", lambda *_: self._on_description_changed())

        # Target Stage
        study_frame = ttk.Frame(self)
        study_frame.grid(row=5, column=0, sticky="ew", pady=(0, 2))
        study_frame.columnconfigure(0, weight=1)
        # Controlled Variable is the ordinary experiment; the other studies are one disclosure away, not hidden.
        self.study_hint_var = tk.StringVar(value=STUDY_HINTS["Controlled Variable"])
        ttk.Label(
            study_frame, textvariable=self.study_hint_var, wraplength=360, justify="left",
            foreground=TOKENS.colors.text_muted,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.study_section = DisclosureSection(study_frame, title="Advanced study types", expanded=False)
        self.study_section.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        study_body = self.study_section.body
        study_body.columnconfigure(1, weight=1)
        ttk.Label(study_body, text="Study Type:").grid(row=0, column=0, sticky="w")
        self.study_type_var = tk.StringVar(value="Controlled Variable")
        self.study_type_combo = ttk.Combobox(study_body, textvariable=self.study_type_var,
                                             values=("Controlled Variable", "Prompt Slot", "Model Comparison", "Two-Axis Grid"), state="readonly")
        self.study_type_combo.grid(row=0, column=1, sticky="ew")
        self.study_type_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_study_type_changed())
        ttk.Button(study_frame, text="Prompt Slot Experiment", command=self._choose_prompt_slot).grid(row=0, column=1, padx=4)
        ttk.Label(study_frame, text="Target Stage:").grid(row=2, column=0, sticky="w")
        self.stage_var = tk.StringVar(value="txt2img")
        self.stage_combo = ttk.Combobox(
            self,
            textvariable=self.stage_var,
            values=list_supported_stages(),
            state="readonly",
        )
        self.stage_combo.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        self.stage_combo.bind("<<ComboboxSelected>>", self._on_stage_changed)

        self.input_image_frame = ttk.LabelFrame(self, text="Input Image", padding=5)
        self.input_image_frame.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        self.input_image_frame.columnconfigure(0, weight=1)
        self.input_image_var = tk.StringVar(value="")
        self.input_image_entry = ttk.Entry(
            self.input_image_frame,
            textvariable=self.input_image_var,
        )
        self.input_image_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.input_image_button = ttk.Button(
            self.input_image_frame,
            text="Browse",
            command=self._on_browse_input_image,
        )
        self.input_image_button.grid(row=0, column=1, sticky="e")

        # The experiment's own fixed settings.  Learning owns this baseline; the Pipeline is only ever copied in
        # on request, so a Pipeline edit can never change a Learning draft or Preview.
        self.baseline_section = DisclosureSection(self, title="Learning baseline (settings held fixed)", expanded=True)
        self.baseline_section.grid(row=8, column=0, sticky="ew", pady=(0, 10))
        self.baseline_editor = LearningBaselineEditor(
            self.baseline_section.body,
            self.learning_controller,
            stage_provider=lambda: self.stage_var.get(),
            variable_provider=lambda: self._safe_get(getattr(self, "variable_var", None), ""),
            input_image_provider=lambda: str(self._safe_get(getattr(self, "input_image_var", None), "")).strip(),
            policy_notes_provider=self._policy_notes,
            on_changed=self._on_baseline_changed,
        )
        self.baseline_editor.grid(row=0, column=0, sticky="ew")
        self.baseline_section.body.columnconfigure(0, weight=1)

        # Variable Under Test
        self.variable_label = ttk.Label(self, text="Variable Under Test:")
        self.variable_label.grid(row=9, column=0, sticky="w", pady=(0, 2))
        self.variable_var = tk.StringVar(value="")
        self.variable_combo = ttk.Combobox(
            self,
            textvariable=self.variable_var,
            values=get_variables_for_stage(self.stage_var.get()),
            state="readonly",
        )
        self.variable_combo.grid(row=10, column=0, sticky="ew", pady=(0, 10))

        # PR-LEARN-020: Bind variable selection to widget switcher
        self.variable_combo.bind("<<ComboboxSelected>>", self._on_variable_changed)

        # Value Specification Frame (numeric range)
        self.value_frame = ttk.LabelFrame(self, text="Value Specification", padding=5)
        self.value_frame.grid(row=11, column=0, sticky="ew", pady=(0, 10))
        self.value_frame.columnconfigure(0, weight=1)
        self.value_frame.columnconfigure(1, weight=1)
        self.value_frame.columnconfigure(2, weight=1)

        # Numeric range inputs
        ttk.Label(self.value_frame, text="Start:").grid(row=0, column=0, sticky="w", pady=2)
        self.start_var = tk.DoubleVar(value=1.0)
        self.start_spin = tk.Spinbox(
            self.value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.start_var
        )
        self.start_spin.grid(row=1, column=0, sticky="ew", padx=(0, 2))

        ttk.Label(self.value_frame, text="End:").grid(row=0, column=1, sticky="w", pady=2)
        self.end_var = tk.DoubleVar(value=10.0)
        self.end_spin = tk.Spinbox(
            self.value_frame, from_=0.1, to=100.0, increment=0.1, textvariable=self.end_var
        )
        self.end_spin.grid(row=1, column=1, sticky="ew", padx=2)

        ttk.Label(self.value_frame, text="Step:").grid(row=0, column=2, sticky="w", pady=2)
        self.step_var = tk.DoubleVar(value=1.0)
        self.step_spin = tk.Spinbox(
            self.value_frame, from_=0.1, to=10.0, increment=0.1, textvariable=self.step_var
        )
        self.step_spin.grid(row=1, column=2, sticky="ew", padx=(2, 0))

        # PR-LEARN-020: Build checklist frame (hidden by default)
        self.checklist_frame = ttk.LabelFrame(self, text="Select Items to Test", padding=5)
        self.checklist_canvas = tk.Canvas(self.checklist_frame, height=150)
        self.checklist_scrollbar = ttk.Scrollbar(
            self.checklist_frame, orient="vertical", command=self.checklist_canvas.yview
        )
        self.checklist_inner_frame = ttk.Frame(self.checklist_canvas)
        self.checklist_canvas.configure(yscrollcommand=self.checklist_scrollbar.set)
        self._bind_checklist_wheel(self.checklist_canvas)
        self._bind_checklist_wheel(self.checklist_inner_frame)

        self.checklist_scrollbar.pack(side="right", fill="y")
        self.checklist_canvas.pack(side="left", fill="both", expand=True)
        self.checklist_canvas.create_window((0, 0), window=self.checklist_inner_frame, anchor="nw")
        self.checklist_inner_frame.bind(
            "<Configure>",
            lambda e: self.checklist_canvas.configure(
                scrollregion=self.checklist_canvas.bbox("all")
            ),
        )

        # Initially hide checklist frame
        self.checklist_frame.grid_remove()

        # Store checkbox variables
        self.choice_vars: dict[str, tk.BooleanVar] = {}
        self._choice_display_map: dict[str, str] = {}

        # PR-LEARN-022: Build LoRA composite frame (hidden by default)
        self.lora_frame = ttk.LabelFrame(self, text="LoRA Configuration", padding=5)
        self.lora_frame.columnconfigure(0, weight=1)

        # Initially hide
        self.lora_frame.grid_remove()

        # Images per Variant
        images_row = ttk.Frame(self)
        images_row.grid(row=12, column=0, sticky="ew", pady=(0, 10))
        images_row.columnconfigure(1, weight=1)
        ttk.Label(images_row, text="Images per Variant:").grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        self.images_var = tk.IntVar(value=1)
        self.images_spin = tk.Spinbox(
            images_row, from_=1, to=10, textvariable=self.images_var, width=8
        )
        self.images_spin.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.estimate_var = tk.StringVar(value="")
        ttk.Label(
            images_row, textvariable=self.estimate_var, wraplength=360, justify="left",
            foreground=TOKENS.colors.text_muted,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.grid_frame = TwoAxisDesignFrame(
            self,
            on_change=self._on_grid_design_changed,
            lora_provider=self._grid_lora_choices,
            images_provider=lambda: int(self.images_var.get()),
        )
        self.grid_frame.grid(row=11, column=0, sticky="ew", pady=(0, 10))
        from src.gui.views.prompt_slot_design_frame import PromptSlotDesignFrame

        self.prompt_slot_frame = PromptSlotDesignFrame(
            self, template=self._get_prompt_preview_text, changed=self._notify_design_changed,
            visible=self._comparison_show_names)
        self.prompt_slot_frame.grid(row=11, column=0, sticky="ew", pady=(0, 10))
        self.prompt_slot_frame.grid_remove()
        self.grid_frame.grid_remove()
        self.images_var.trace_add("write", lambda *_: self._on_grid_design_changed())

        identity_actions = ttk.Frame(self)
        identity_actions.grid(row=13, column=0, sticky="e", pady=(0, 10))
        ttk.Button(
            identity_actions,
            text="Suggest Name",
            command=self._suggest_identity,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            identity_actions,
            text="Suggest Description",
            command=lambda: self._suggest_identity(name_only=False),
        ).pack(side="left")

        # Prompt Source
        prompt_frame = ttk.LabelFrame(self, text="Prompt Source", padding=5)
        prompt_frame.grid(row=14, column=0, sticky="ew", pady=(0, 10))
        prompt_frame.columnconfigure(1, weight=1)

        ttk.Label(prompt_frame, text="Source:").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.prompt_source_var = tk.StringVar(value="pack")
        self.prompt_source_combo = ttk.Combobox(
            prompt_frame,
            textvariable=self.prompt_source_var,
            values=["pack", "custom"],
            state="readonly",
        )
        self.prompt_source_combo.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.prompt_source_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_prompt_source_changed()
        )

        ttk.Label(prompt_frame, text="Prompt Pack:").grid(row=1, column=0, sticky="w", pady=(0, 2))
        self.prompt_pack_var = tk.StringVar(value="")
        self.prompt_pack_combo = ttk.Combobox(
            prompt_frame,
            textvariable=self.prompt_pack_var,
            state="readonly",
        )
        self.prompt_pack_combo.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self.prompt_pack_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_prompt_pack_selected()
        )

        ttk.Label(prompt_frame, text="Prompt:").grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.prompt_item_var = tk.StringVar(value="")
        self.prompt_item_combo = ttk.Combobox(
            prompt_frame,
            textvariable=self.prompt_item_var,
            state="readonly",
        )
        self.prompt_item_combo.grid(row=2, column=1, sticky="ew", pady=(0, 8))
        self.prompt_item_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_prompt_item_selected()
        )

        ttk.Label(prompt_frame, text="Custom prompt text:").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )

        self.custom_prompt_var = tk.StringVar(value="")
        self.custom_prompt_text = tk.Text(
            prompt_frame,
            height=3,
            wrap=tk.WORD,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
            highlightbackground=TOKENS.colors.border_subtle,
            highlightcolor=TOKENS.colors.accent_primary,
        )
        self.custom_prompt_text.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.custom_prompt_text.bind("<KeyRelease>", lambda _e: self._on_prompt_text_edited())

        self._refresh_prompt_pack_choices()
        self._on_prompt_source_changed()

        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.grid(row=15, column=0, sticky="ew", pady=(0, 10))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        self.build_button = ttk.Button(
            button_frame, text="Build Preview", command=self._on_build_preview
        )
        self.build_button.grid(row=0, column=0, columnspan=2, sticky="ew")

        # Run belongs to the Preview step (the guide bar). The button stays as the panel's own Run-readiness
        # state holder and is never shown here, so Design offers exactly one primary action.
        self.run_button = ttk.Button(
            button_frame, text="Run Experiment", command=self._on_run_experiment
        )

        # Feedback
        self.feedback_var = tk.StringVar(value="")
        self.feedback_label = ttk.Label(self, textvariable=self.feedback_var, foreground="red", wraplength=360)
        self.feedback_label.grid(row=16, column=0, sticky="w", pady=(0, 10))
        self.cancel_evidence_button = ttk.Button(
            button_frame, text="Cancel Evidence", state="disabled",
            command=self._cancel_comparison_evidence,
        )
        self.cancel_evidence_button.grid(row=1, column=0, columnspan=2)
        self.cancel_evidence_button.grid_remove()
        self.summary_var = tk.StringVar(value="")
        self.summary_label = ttk.Label(
            self,
            textvariable=self.summary_var,
            justify="left",
            foreground=TOKENS.colors.text_muted,
        )
        self.summary_label.grid(row=17, column=0, sticky="ew", pady=(0, 6))
        self.model_target_var = tk.StringVar(value="Learning Target: awaiting model policy")
        ttk.Label(self, textvariable=self.model_target_var, wraplength=360, justify="left").grid(
            row=18, column=0, sticky="ew", pady=(0, 6)
        )
        self._on_stage_changed()
        self._suggest_identity()
        for watched in (
            self.name_var, self.desc_var, self.stage_var, self.variable_var, self.start_var, self.end_var,
            self.step_var, self.images_var, self.prompt_source_var, self.prompt_pack_var, self.prompt_item_var,
            self.study_type_var,
        ):
            watched.trace_add("write", self._notify_design_changed)
        self.feedback_var.trace_add("write", lambda *_: self.feedback_label.configure(
            foreground=TOKENS.colors.status_error))
        self._built = True
        self._sync_study_presentation()
        self._refresh_estimate()

    def _on_prompt_source_changed(self) -> None:
        if getattr(self, "prompt_slot_frame", None) is not None:
            self.prompt_slot_frame.clear_frozen_source()
        use_pack = self.prompt_source_var.get() == "pack"
        self.prompt_pack_combo.config(state="readonly" if use_pack else "disabled")
        self.prompt_item_combo.config(state="readonly" if use_pack else "disabled")
        self.custom_prompt_text.config(state="disabled" if use_pack else "normal")

        if use_pack:
            selected = self._get_selected_prompt_payload()
            preview = selected.get("prompt_text") if selected else ""
            self.custom_prompt_text.config(state="normal")
            self.custom_prompt_text.delete("1.0", tk.END)
            self.custom_prompt_text.insert("1.0", preview or "(No prompt selected)")
            self.custom_prompt_text.config(state="disabled")

            variable_name = self.variable_var.get()
            if variable_name == "LoRA Strength" and self.lora_frame.winfo_manager() == "grid":
                self._build_lora_mode_content()
        self._refresh_identity_preview()
        self._on_grid_design_changed()

    def _is_model_comparison(self) -> bool:
        return self.study_type_var.get() == "Model Comparison"

    def _is_grid(self) -> bool:
        return self.study_type_var.get() == "Two-Axis Grid"

    def _is_prompt_slot(self) -> bool:
        return self.study_type_var.get() == "Prompt Slot"

    def _choose_prompt_slot(self) -> None:
        self.study_type_var.set("Prompt Slot")
        self._on_study_type_changed()

    def _grid_lora_choices(self) -> list[str]:
        known = getattr(self.learning_controller, "known_loras", None)
        return list(known()) if callable(known) else []

    def _grid_signature(self) -> tuple[Any, ...]:
        try:
            images = int(self.images_var.get())
        except (tk.TclError, ValueError):
            images = -1
        custom = self.custom_prompt_text.get("1.0", tk.END).strip() if self.prompt_source_var.get() == "custom" else ""
        return (
            self.grid_frame.signature(), images, self.prompt_source_var.get(), self.prompt_pack_var.get(),
            self.prompt_item_var.get(), custom, getattr(self, "_target_model", None),
        )

    def _current_experiment(self) -> Any:
        return getattr(getattr(self.learning_controller, "learning_state", None), "current_experiment", None)

    def _grid_preview_fresh(self) -> bool:
        experiment = self._current_experiment()
        return bool(
            getattr(experiment, "execution_snapshot_json", "")
            and self._grid_preview_signature is not None
            and self._grid_preview_signature == self._grid_signature()
        )

    def _on_grid_design_changed(self) -> None:
        if not hasattr(self, "run_button") or not self._is_grid():
            return
        had_preview = self._grid_preview_signature is not None
        self.grid_frame.refresh_summary()
        self._update_policy_buttons()
        if had_preview and not self._grid_preview_fresh():
            self.feedback_var.set("The grid design changed after Preview; Build Preview again before Run.")

    def _enter_grid_mode(self) -> None:
        self.stage_var.set("txt2img")
        self.stage_combo.configure(values=("txt2img",), state="disabled")
        self.input_image_frame.grid_remove()
        self.variable_label.grid_remove()
        self.variable_combo.grid_remove()
        self.variable_var.set("Two-Axis Grid")
        self.value_frame.grid_remove()
        self.checklist_frame.grid_remove()
        self.lora_frame.grid_remove()
        self.prompt_source_combo.configure(state="readonly")
        if self.prompt_source_var.get() not in ("pack", "custom"):
            self.prompt_source_var.set("pack")
        self._on_prompt_source_changed()
        self.grid_frame.grid()
        self.grid_frame.refresh_summary()
        self.model_target_var.set(
            "Two-Axis Grid: two settings vary together on one frozen prompt, model and seed set. Results are an "
            "exploratory comparison, not one-variable causal evidence."
        )

    def _on_study_type_changed(self) -> None:
        self._cancel_comparison_evidence()
        from src.learning.variable_metadata import get_variable_metadata

        previous = self._study_mode
        self._study_mode = "prompt_slot" if _prompt_slot(self) else "grid" if self._is_grid() else "comparison" if self._is_model_comparison() else "controlled"
        if self._study_mode != "prompt_slot":
            self.prompt_slot_frame.grid_remove()
            self.custom_prompt_text.tag_remove("slot_hidden", "1.0", tk.END)
        if self._study_mode != "grid":
            self.grid_frame.grid_remove()
        if previous == "controlled" and self._study_mode != "controlled":
            self._controlled_design = (self.stage_var.get(), self.variable_var.get(), self.prompt_source_var.get())
        if self._study_mode == "prompt_slot":
            self.stage_var.set("txt2img")
            self.stage_combo.configure(values=("txt2img",), state="disabled")
            self.input_image_frame.grid_remove()
            self.variable_label.grid_remove()
            self.variable_combo.grid_remove()
            self.variable_var.set("Prompt Slot")
            for frame in (self.value_frame, self.checklist_frame, self.lora_frame):
                frame.grid_remove()
            self.prompt_source_combo.configure(state="readonly")
            if self.prompt_source_var.get() not in ("pack", "custom"):
                self.prompt_source_var.set("custom")
            self.prompt_slot_frame.grid()
            self._on_prompt_source_changed()
            self.prompt_slot_frame.refresh_slots()
            self._on_comparison_visibility_changed()
            self.name_var.set("Prompt Slot experiment")
            self._name_auto_generated = False
            self.model_target_var.set("One prompt slot; registry-verified SDXL txt2img. Disable the prompt optimizer in the Learning baseline.")
        elif self._study_mode == "grid":
            self._enter_grid_mode()
        elif self._is_model_comparison():
            self.stage_var.set("txt2img")
            self.stage_combo.configure(values=("txt2img",), state="disabled")
            self.input_image_frame.grid_remove()
            self.variable_label.grid_remove()
            self.variable_combo.grid_remove()
            self.variable_var.set("Model Comparison")
            self.prompt_source_var.set("pack")
            self.prompt_source_combo.configure(state="disabled")
            self._on_prompt_source_changed()
            self._show_checklist_widget(get_variable_metadata("Model"))
            self.checklist_frame.configure(text="Models to Compare")
            self.model_target_var.set("Target-envelope comparison: each model uses its own validated settings and prompt adaptation. Requested seed and geometry are shared; this is not one-variable causal evidence.")
        else:
            self.stage_combo.configure(values=list_supported_stages(), state="readonly")
            self.prompt_source_combo.configure(state="readonly")
            self.variable_label.grid()
            self.variable_combo.grid()
            stage, variable, source = getattr(self, "_controlled_design", ("txt2img", "", "pack"))
            self.stage_var.set(stage)
            self.variable_var.set(variable)
            self.prompt_source_var.set(source)
            self._on_stage_changed()
            self._on_prompt_source_changed()
            self._on_variable_changed()
        self._update_policy_buttons()
        self._sync_study_presentation()
        self._notify_design_changed()

    def _resolve_packs_dir(self) -> Path:
        if self._packs_dir is not None:
            return self._packs_dir
        return resolve_prompt_pack_dir()

    def _refresh_prompt_pack_choices(self) -> None:
        self._prompt_pack_paths = {
            info.name: info.path for info in discover_packs(self._resolve_packs_dir())
        }
        pack_names = list(self._prompt_pack_paths.keys())
        self.prompt_pack_combo.configure(values=pack_names)

        current_name = self.prompt_pack_var.get().strip()
        if current_name not in self._prompt_pack_paths:
            workspace_name = ""
            if self.prompt_workspace_state:
                try:
                    workspace_name = self.prompt_workspace_state.get_current_pack_name()
                except Exception:
                    workspace_name = ""
            selected_name = (
                workspace_name
                if workspace_name in self._prompt_pack_paths
                else (pack_names[0] if pack_names else "")
            )
            self.prompt_pack_var.set(selected_name)

        self._refresh_prompt_choices()

    @staticmethod
    def _render_slot_positive_prompt(slot: PromptSlot) -> str:
        parts: list[str] = []
        embeds = normalize_embedding_entries(getattr(slot, "positive_embeddings", []))
        if embeds:
            parts.append(
                " ".join(render_embedding_reference(name, weight) for name, weight in embeds)
            )
        text = str(getattr(slot, "text", "") or "").strip()
        if text:
            parts.append(text)
        return "\n".join(parts).strip()

    @staticmethod
    def _render_slot_negative_prompt(slot: PromptSlot) -> str:
        parts: list[str] = []
        embeds = normalize_embedding_entries(getattr(slot, "negative_embeddings", []))
        if embeds:
            parts.append(
                " ".join(render_embedding_reference(name, weight) for name, weight in embeds)
            )
        text = str(getattr(slot, "negative", "") or "").strip()
        if text:
            parts.append(text)
        return "\n".join(parts).strip()

    def _load_prompt_payloads_for_pack(self, pack_path: Path) -> list[dict[str, Any]]:
        json_path = (
            pack_path if pack_path.suffix.lower() == ".json" else pack_path.with_suffix(".json")
        )
        payloads: list[dict[str, Any]] = []

        if json_path.exists():
            pack = PromptPackModel.load_from_file(json_path)
            for slot in pack.slots:
                slot_positive = self._render_slot_positive_prompt(slot)
                slot_negative = self._render_slot_negative_prompt(slot)
                if not (slot_positive or slot_negative or getattr(slot, "loras", [])):
                    continue
                preview = (
                    (str(getattr(slot, "text", "") or "") or slot_positive)
                    .strip()
                    .replace("\n", " ")
                )
                preview = preview[:48] + ("..." if len(preview) > 48 else "")
                label = f"Prompt {int(getattr(slot, 'index', 0)) + 1}"
                if preview:
                    label = f"{label}: {preview}"
                payloads.append(
                    {
                        "label": label,
                        "prompt_index": int(getattr(slot, "index", 0)),
                        "slot": slot,
                        "prompt_text": slot_positive,
                        "negative_prompt_text": slot_negative,
                        "loras": [
                            {"name": str(name), "weight": float(weight)}
                            for name, weight in list(getattr(slot, "loras", []) or [])
                            if str(name or "").strip()
                        ],
                    }
                )
            return payloads

        for index, prompt in enumerate(read_prompt_pack(pack_path)):
            positive = str(prompt.get("positive", "") or "").strip()
            negative = str(prompt.get("negative", "") or "").strip()
            if not (positive or negative):
                continue
            preview = positive.replace("\n", " ")
            preview = preview[:48] + ("..." if len(preview) > 48 else "")
            label = f"Prompt {index + 1}"
            if preview:
                label = f"{label}: {preview}"
            slot = PromptSlot(index=index, text=positive, negative=negative)
            payloads.append(
                {
                    "label": label,
                    "prompt_index": index,
                    "slot": slot,
                    "prompt_text": positive,
                    "negative_prompt_text": negative,
                    "loras": [],
                }
            )
        return payloads

    def _refresh_prompt_choices(self) -> None:
        self._prompt_option_payloads = {}
        selected_pack = self.prompt_pack_var.get().strip()
        pack_path = self._prompt_pack_paths.get(selected_pack)
        payloads = self._load_prompt_payloads_for_pack(pack_path) if pack_path else []
        if _prompt_slot(self) and not self._comparison_show_names():
            payloads = [{**payload, "label": f"Prompt {payload['prompt_index'] + 1}"} for payload in payloads]
        labels = [payload["label"] for payload in payloads]
        self._prompt_option_payloads = {payload["label"]: payload for payload in payloads}
        self.prompt_item_combo.configure(values=labels)

        current_label = self.prompt_item_var.get().strip()
        if current_label not in self._prompt_option_payloads:
            self.prompt_item_var.set(labels[0] if labels else "")

    def _get_selected_prompt_payload(self) -> dict[str, Any] | None:
        label = self.prompt_item_var.get().strip()
        payload = self._prompt_option_payloads.get(label)
        if not payload:
            return None
        pack_name = self.prompt_pack_var.get().strip()
        pack_path = self._prompt_pack_paths.get(pack_name)
        return {
            **payload,
            "prompt_pack_name": pack_name,
            "prompt_pack_path": str(pack_path) if pack_path else "",
        }

    def _build_selected_prompt_workspace_state(self) -> Any | None:
        payload = self._get_selected_prompt_payload()
        if not payload:
            return None
        slot = payload["slot"]
        positive = str(payload.get("prompt_text", "") or "")
        negative = str(payload.get("negative_prompt_text", "") or "")
        return type(
            "SelectedPromptWorkspaceState",
            (),
            {
                "get_current_slot": staticmethod(lambda: slot),
                "get_current_prompt_text": staticmethod(lambda: positive),
                "get_current_negative_text": staticmethod(lambda: negative),
                "get_current_prompt_metadata": staticmethod(
                    lambda: build_prompt_metadata(f"{positive}\n{negative}")
                ),
            },
        )()

    def _on_prompt_pack_selected(self) -> None:
        self._refresh_prompt_choices()
        self._on_prompt_item_selected()

    def _on_prompt_item_selected(self) -> None:
        self._on_prompt_source_changed()

    def _on_build_preview(self) -> None:
        """Handle build preview button click."""
        if getattr(self, "_comparison_readiness_busy", False):
            return
        if not _prompt_slot(self) and not self._is_model_comparison() and not self._is_grid() and self._learning_capabilities is not None:
            try:
                self._learning_capabilities.require(self.variable_var.get())
            except ValueError as exc:
                self.feedback_var.set(str(exc))
                return
        if not self.learning_controller:
            self.feedback_var.set("Learning controller not available")
            return
        # Pressing Build Preview means the operator is looking at this step: the one-time seed happens now at latest.
        self._shown = True
        ensure = getattr(self.learning_controller, "ensure_baseline", None)
        if callable(ensure):
            ensure(self.stage_var.get())

        # Collect form data
        experiment_data = {
            "study_type": "prompt_slot" if _prompt_slot(self) else "model_comparison" if self._is_model_comparison() else "two_axis_grid" if self._is_grid() else "controlled_variable",
            "prompt_slot": self.prompt_slot_frame.spec() if _prompt_slot(self) else None,
            "grid": self.grid_frame.spec() if self._is_grid() else None,
            "selected_models": [choice for choice, var in self.choice_vars.items() if var.get()] if self._is_model_comparison() else [],
            "name": self.name_var.get().strip(),
            "description": self.desc_var.get().strip(),
            "stage": self.stage_var.get(),
            "input_image_path": self.input_image_var.get().strip(),
            "variable_under_test": "" if self._is_grid() else self.variable_var.get(),
            "start_value": self.start_var.get(),
            "end_value": self.end_var.get(),
            "step_value": self.step_var.get(),
            "images_per_value": self.images_var.get(),
            "prompt_source": self.prompt_source_var.get(),
            "custom_prompt": self.custom_prompt_text.get("1.0", tk.END).strip()
            if self.prompt_source_var.get() == "custom"
            else "",
            "selected_prompt_text": "",
            "selected_negative_prompt": "",
            "selected_prompt_pack_name": "",
            "selected_prompt_pack_path": "",
            "selected_prompt_index": 0,
            "selected_prompt_label": "",
            "selected_prompt_loras": [],
            # PR-LEARN-020: Include selected items for discrete/resource variables
            "selected_items": [choice for choice, var in self.choice_vars.items() if var.get()]
            if hasattr(self, "choice_vars")
            else [],
            # PR-LEARN-022: LoRA metadata
            "lora_mode": self.lora_mode_var.get() if hasattr(self, "lora_mode_var") else "strength",
            "lora_name": self.lora_selector_var.get()
            if hasattr(self, "lora_selector_var")
            else None,
            "strength_start": self.lora_start_var.get() if hasattr(self, "lora_start_var") else 0.5,
            "strength_end": self.lora_end_var.get() if hasattr(self, "lora_end_var") else 1.5,
            "strength_step": self.lora_step_var.get() if hasattr(self, "lora_step_var") else 0.1,
            "comparison_mode": (self.lora_mode_var.get() == "comparison")
            if hasattr(self, "lora_mode_var")
            else False,
            "fixed_strength": self.lora_fixed_strength_var.get()
            if hasattr(self, "lora_fixed_strength_var")
            else 1.0,
            "selected_loras": [lora for lora, var in self.lora_choice_vars.items() if var.get()]
            if hasattr(self, "lora_choice_vars")
            else [],
        }

        if experiment_data["prompt_source"] == "pack":
            selected_prompt = self._get_selected_prompt_payload()
            if selected_prompt:
                experiment_data.update(
                    {
                        "selected_prompt_text": str(selected_prompt.get("prompt_text", "") or ""),
                        "selected_negative_prompt": str(
                            selected_prompt.get("negative_prompt_text", "") or ""
                        ),
                        "selected_prompt_pack_name": str(
                            selected_prompt.get("prompt_pack_name", "") or ""
                        ),
                        "selected_prompt_pack_path": str(
                            selected_prompt.get("prompt_pack_path", "") or ""
                        ),
                        "selected_prompt_index": int(selected_prompt.get("prompt_index", 0) or 0),
                        "selected_prompt_label": str(selected_prompt.get("label", "") or ""),
                        "selected_prompt_loras": list(selected_prompt.get("loras") or []),
                    }
                )

        # Validate
        validation_error = self._validate_experiment_data(experiment_data)
        if validation_error:
            _speak(self, f"Validation Error: {validation_error}")
            _call(self, "_mark_validation_failed", validation_error)
            return
        _call(self, "_mark_validation_failed", "")

        if self._is_model_comparison() and hasattr(self.learning_controller, "prepare_model_comparison_evidence"):
            self._start_comparison_evidence(experiment_data)
            return
        self._apply_experiment_preview(experiment_data)

    def _apply_experiment_preview(self, experiment_data, evidence=None) -> None:
        # Evidence readiness has no permission to mutate the plan; only the Tk
        # owner reaches this existing semantic freeze after selection checks.
        try:
            self.learning_controller.update_experiment_design(experiment_data)

            # Build the learning plan
            if self.learning_controller.learning_state.current_experiment:
                args = {"comparison_evidence": evidence} if evidence is not None else {}
                self.learning_controller.build_plan(
                    self.learning_controller.learning_state.current_experiment, **args
                )
                from src.learning.experiment_freeze import describe_matrix_freeze

                guidance = describe_matrix_freeze(
                    self.learning_controller.learning_state.current_experiment.metadata
                )
                _speak(
                    self,
                    guidance or "Experiment definition and plan built successfully. Nothing is queued yet.",
                    ok=True,
                )
                if self._is_model_comparison():
                    from src.learning.experiment_execution import thaw_snapshot
                    from src.learning.model_comparison import preview_summary

                    _speak(self, "Model Comparison preview ready", ok=True)
                    self.summary_var.set(preview_summary(thaw_snapshot(
                        self.learning_controller.learning_state.current_experiment.execution_snapshot_json),
                        show_names=self._comparison_show_names()))
                    self._update_policy_buttons()
                if self._is_grid():
                    from src.learning.experiment_execution import thaw_snapshot
                    from src.learning.two_axis_grid import preview_summary as grid_summary

                    _speak(self, "Two-Axis Grid preview ready; Run queues every cell once.", ok=True)
                    self.summary_var.set(grid_summary(thaw_snapshot(
                        self._current_experiment().execution_snapshot_json)))
                    self._grid_preview_signature = self._grid_signature()
                    self._update_policy_buttons()
                _call(self, "_mark_preview_built")
            else:
                self.feedback_var.set("Experiment definition updated successfully")
        except Exception as e:
            _speak(self, f"Error updating experiment: {str(e)}")
            self._preview_signature = None
            if self._is_grid():
                self._grid_preview_signature = None
                self._update_policy_buttons()
        _call(self, "_notify_design_changed")

    def _comparison_selection(self):
        from src.learning.resource_access import get_projected_resources

        return (self.study_type_var.get(), self.prompt_pack_var.get(), self.prompt_item_var.get(),
                tuple(name for name, var in self.choice_vars.items() if var.get()),
                repr(get_projected_resources(self.learning_controller).get("models", [])),
                self._comparison_show_names())

    def _comparison_show_names(self) -> bool:
        from src.gui.content_visibility import (
            ContentVisibilityMode,
            normalize_content_visibility_mode,
        )

        state = self._resource_state
        return normalize_content_visibility_mode(getattr(state, "content_visibility_mode", None)) is ContentVisibilityMode.NSFW

    def _on_comparison_visibility_changed(self) -> None:
        self._cancel_comparison_evidence()
        if _prompt_slot(self):
            current = self._get_selected_prompt_payload() or {}
            self.prompt_slot_frame.refresh_visibility()
            self.custom_prompt_text.tag_configure("slot_hidden", elide=not self._comparison_show_names())
            self.custom_prompt_text.tag_add("slot_hidden", "1.0", tk.END)
            self._refresh_prompt_choices()
            for label, payload in self._prompt_option_payloads.items():
                if payload.get("prompt_index") == current.get("prompt_index"):
                    self.prompt_item_var.set(label)
                    break
            return
        if not self._is_model_comparison():
            return
        self.feedback_var.set("Content visibility changed; rebuild Preview if evidence work was interrupted")
        experiment = self.learning_controller.learning_state.current_experiment
        if experiment is not None and experiment.execution_snapshot_json:
            from src.learning.experiment_execution import thaw_snapshot
            from src.learning.model_comparison import preview_summary

            snapshot = thaw_snapshot(experiment.execution_snapshot_json)
            if snapshot.get("study_type") == "model_comparison":
                self.summary_var.set(preview_summary(snapshot, show_names=self._comparison_show_names()))

    def _start_comparison_evidence(self, data):
        import copy

        from src.gui.model_comparison_readiness import ComparisonEvidenceTask
        from src.learning.resource_access import get_projected_resources

        selection = self._comparison_selection()
        resources = copy.deepcopy(get_projected_resources(self.learning_controller).get("models", []))
        prepare = self.learning_controller.prepare_model_comparison_evidence
        self._comparison_readiness_busy = True
        self.feedback_var.set("Checking selected checkpoint evidence; first use may read multi-GB files. Cancel Evidence stops this work.")
        self.cancel_evidence_button.configure(state="normal")
        self.cancel_evidence_button.grid()
        self._update_policy_buttons()
        show_names = self._comparison_show_names()
        task = ComparisonEvidenceTask(lambda **kwargs: prepare(data["selected_models"], resources, show_names=show_names, **kwargs))
        self._comparison_evidence_task = task

        def poll():
            import queue

            if self._comparison_selection() != selection:
                task.cancel()
            try:
                while True:
                    kind, value = task.messages.get_nowait()
                    if kind == "progress":
                        if not task.cancelled():
                            self.feedback_var.set(value)
                        continue
                    self._comparison_readiness_busy = False
                    self._comparison_evidence_task = None
                    self.cancel_evidence_button.configure(state="disabled")
                    self.cancel_evidence_button.grid_remove()
                    if task.cancelled():
                        self.feedback_var.set("Evidence work cancelled, timed out, or selection changed; rebuild Preview")
                    elif kind == "error":
                        self.feedback_var.set(value)
                    else:
                        self._apply_experiment_preview(data, evidence=value)
                    self._update_policy_buttons()
                    self._comparison_poll_id = None
                    return
            except queue.Empty:
                self._comparison_poll_id = self.after(50, poll)

        self._comparison_poll_id = self.after(50, poll)

    def _cancel_comparison_evidence(self):
        task = getattr(self, "_comparison_evidence_task", None)
        if task is not None:
            task.cancel()

    def destroy(self):
        self._cancel_comparison_evidence()
        if self._resource_state is not None and hasattr(self._resource_state, "unsubscribe"):
            self._resource_state.unsubscribe("content_visibility_mode", self._on_comparison_visibility_changed)
        poll_id = getattr(self, "_comparison_poll_id", None)
        if poll_id:
            self.after_cancel(poll_id)
        super().destroy()

    # -- guided-workflow support: stale Preview, estimate and honest feedback -------------------------------------

    def set_on_design_changed(self, callback: Any) -> None:
        """Register one callback fired when the design (or the readiness of its Preview) may have changed."""
        self._design_changed_callback = callback

    def _mark_preview_built(self) -> None:
        """Remember the inputs this Preview was built from, so a later edit can mark it out of date."""
        self._preview_signature = self.design_signature()
        built = self._preview_built_callback
        if callable(built):
            built()

    def _mark_validation_failed(self, error: str) -> None:
        self._blocker = (error, self.design_signature()) if error else None
        self._notify_design_changed()

    def set_on_preview_built(self, callback: Any) -> None:
        """Register one callback fired after a Preview was built successfully (nothing is queued by it)."""
        self._preview_built_callback = callback

    def _notify_design_changed(self, *_: Any) -> None:
        if not getattr(self, "_built", False):
            return
        self._refresh_estimate()
        callback = self._design_changed_callback
        if callable(callback):
            callback()

    @staticmethod
    def _safe_get(variable: Any, default: Any = None) -> Any:
        try:
            return variable.get()
        except (tk.TclError, ValueError, AttributeError):
            return default

    def design_signature(self) -> tuple[Any, ...]:
        """Every input a Preview is built from, so an edit after Preview can be detected for any study type."""
        get = self._safe_get
        custom = (
            self.custom_prompt_text.get("1.0", tk.END).strip()
            if self.prompt_source_var.get() == "custom"
            else ""
        )
        lora = tuple(
            get(getattr(self, name, None))
            for name in (
                "lora_mode_var", "lora_selector_var", "lora_start_var", "lora_end_var", "lora_step_var",
                "lora_fixed_strength_var",
            )
        )
        loras = tuple(sorted(name for name, var in getattr(self, "lora_choice_vars", {}).items() if get(var)))
        return (
            self.study_type_var.get(), self.name_var.get().strip(), self.desc_var.get().strip(),
            self.stage_var.get(), self.variable_var.get(), self.input_image_var.get().strip(),
            get(self.start_var), get(self.end_var), get(self.step_var), get(self.images_var),
            self.prompt_source_var.get(), self.prompt_pack_var.get(), self.prompt_item_var.get(), custom,
            tuple(sorted(name for name, var in self.choice_vars.items() if get(var))),
            lora, loras, self.grid_frame.signature() if self._is_grid() else None,
            self.prompt_slot_frame.signature() if _prompt_slot(self) else None,
            getattr(self, "_target_model", None), self._baseline_signature(),
        )

    def _baseline_signature(self) -> str:
        authored = getattr(self.learning_controller, "authoring_baseline", None)
        if not callable(authored):
            return ""
        return authoring.signature(authored(), self.stage_var.get())

    def preview_is_stale(self) -> bool:
        """True when a Preview exists but the design was edited after it was built.

        A Preview built elsewhere (no recorded signature) cannot be judged, so it is not called stale.
        """
        experiment = self._current_experiment()
        if not getattr(experiment, "execution_snapshot_json", "") or self._preview_signature is None:
            return False
        return bool(self._preview_signature != self.design_signature())

    def design_blocker(self) -> str:
        """The unresolved validation message for the design as it stands now (cleared once the form changes)."""
        recorded = getattr(self, "_blocker", None)
        if recorded and recorded[1] == self.design_signature():
            return str(recorded[0])
        return ""

    def can_run(self) -> bool:
        return str(self.run_button.cget("state")) != "disabled" and not self.preview_is_stale()

    def _refresh_estimate(self) -> None:
        from src.learning.variable_metadata import get_variable_metadata

        get = self._safe_get
        images = get(self.images_var, 1) or 1
        if _prompt_slot(self):
            count = len(self.prompt_slot_frame.spec()["candidates"])
            self.estimate_var.set(f"{count} candidates x {images} images = {count * int(images)} requested images (maximum 24)")
            self._update_policy_buttons()
            return
        grid_cells = None
        if self._is_grid():
            from src.learning.two_axis_grid import plan_summary

            try:
                grid_cells = plan_summary({"grid": self.grid_frame.spec()}, int(images))[0]
            except (ValueError, TypeError, KeyError):
                grid_cells = None
        meta = None if self._is_grid() or self._is_model_comparison() else get_variable_metadata(self.variable_var.get())
        selected = [name for name, var in self.choice_vars.items() if get(var)]
        estimate = estimate_design(
            study_type="model_comparison" if self._is_model_comparison() else "two_axis_grid" if self._is_grid() else "controlled_variable",
            value_type=meta.value_type if meta else "",
            images_per_value=int(images),
            start=float(get(self.start_var, 0.0) or 0.0),
            end=float(get(self.end_var, 0.0) or 0.0),
            step=float(get(self.step_var, 0.0) or 0.0),
            selected_items=selected,
            lora_comparison=get(getattr(self, "lora_mode_var", None)) == "comparison",
            selected_loras=[name for name, var in getattr(self, "lora_choice_vars", {}).items() if get(var)],
            strength_start=float(get(getattr(self, "lora_start_var", None), 0.0) or 0.0),
            strength_end=float(get(getattr(self, "lora_end_var", None), 0.0) or 0.0),
            strength_step=float(get(getattr(self, "lora_step_var", None), 0.0) or 0.0),
            selected_models=selected,
            grid_cells=grid_cells,
        )
        self.estimate_var.set(estimate.text())

    def _say(self, text: str, *, ok: bool = False) -> None:
        """Show feedback: errors in the error colour (the default), confirmations in the success colour."""
        self.feedback_var.set(text)
        self.feedback_label.configure(
            foreground=TOKENS.colors.status_success if ok else TOKENS.colors.status_error
        )

    def _sync_study_presentation(self) -> None:
        name = self.study_type_var.get()
        self.study_hint_var.set(STUDY_HINTS.get(name, ""))
        advanced = name != "Controlled Variable"
        if advanced:
            self.study_section.set_expanded(True)
        self.study_section.set_status(name if advanced else "", active=advanced)

    def request_run(self) -> int:
        """Send the frozen Preview to the queue once; returns how many jobs were newly admitted."""
        if self._run_in_progress:
            return 0
        if self.preview_is_stale():
            self._say("The design changed after Preview. Build Preview again before Run.")
            self._update_policy_buttons()
            self._notify_design_changed()
            return 0
        if self._is_grid() and not self._grid_preview_fresh():
            self._say("The grid design changed after Preview; Build Preview again before Run.")
            self._update_policy_buttons()
            return 0
        if not _prompt_slot(self) and not self._is_model_comparison() and not self._is_grid() and self._learning_capabilities is not None:
            try:
                self._learning_capabilities.require(self.variable_var.get())
            except ValueError as exc:
                self._say(str(exc))
                return 0
        controller = self.learning_controller
        if not controller:
            self._say("Learning controller not available")
            return 0

        def admitted() -> int:
            plan = getattr(controller.learning_state, "plan", [])
            return sum(bool(str(getattr(variant, "job_id", "") or "").strip()) for variant in plan)

        before = admitted()
        self._run_in_progress = True
        try:
            controller.run_plan()
        except Exception as e:
            self._say(f"Error running experiment: {str(e)}")
            return max(0, admitted() - before)
        finally:
            self._run_in_progress = False
            self._notify_design_changed()
        sent = admitted() - before
        if sent > 0:
            noun = "job" if sent == 1 else "jobs"
            self._say(f"Sent {sent} {noun} to the queue. Generation starts when the queue reaches them.", ok=True)
        else:
            self._say("Nothing new was queued. Build a Preview first, or the variants already have jobs.")
        return sent

    def _on_run_experiment(self) -> None:
        """Handle run experiment button click."""
        self.request_run()

    def _validate_experiment_data(self, data: dict[str, Any]) -> str | None:
        """Validate experiment data and return error message if invalid.

        PR-LEARN-020: Enhanced with discrete variable validation.
        """
        from src.learning.variable_metadata import get_variable_metadata

        if not data["name"]:
            return "Experiment name is required"

        if data.get("study_type") == "model_comparison":
            from src.learning.model_comparison import candidate_models

            if data.get("stage") != "txt2img":
                return "Model Comparison supports txt2img only"
            if data.get("prompt_source") != "pack" or not data.get("selected_prompt_pack_path"):
                return "Model Comparison requires a selected PromptPack row"
            if data.get("images_per_value", 0) < 1:
                return "Images per variant must be at least 1"
            try:
                candidate_models(data.get("selected_models"))
            except ValueError as exc:
                return str(exc)
            return None

        if data.get("study_type") == "prompt_slot":
            return self.prompt_slot_frame.validation_error(int(data.get("images_per_value", 0))) or None
        if data.get("study_type") == "two_axis_grid":
            from src.learning.two_axis_grid import plan_summary

            if data.get("prompt_source") == "pack" and not data.get("selected_prompt_pack_path"):
                return "Select a PromptPack row for the grid"
            if data.get("prompt_source") == "custom" and not data.get("custom_prompt"):
                return "Custom prompt text is required when using custom prompt source"
            try:
                plan_summary({"grid": data.get("grid")}, int(data.get("images_per_value", 0)))
            except (ValueError, TypeError) as exc:
                return str(exc)
            return None

        if not data["variable_under_test"]:
            return "Variable under test must be selected"

        capability = get_stage_capability(data.get("stage"))
        if capability.requires_input_image:
            input_image_path = str(data.get("input_image_path", "") or "").strip()
            if not input_image_path:
                return f"{capability.display_name} experiments require an input image"
            if not Path(input_image_path).exists():
                return "Selected input image does not exist"

        # Get metadata for variable
        meta = get_variable_metadata(data["variable_under_test"])

        if meta and meta.value_type in ["discrete", "resource"]:
            # Discrete/resource variable - validate selection
            selected = data.get("selected_items", [])
            if not selected:
                return f"At least one {meta.display_name} must be selected"
        elif meta and meta.value_type == "composite":
            # PR-LEARN-022: Composite LoRA validation
            comparison_mode = data.get("comparison_mode", False)

            if comparison_mode:
                # Mode 2: Comparison - require at least one LoRA selected
                selected_loras = data.get("selected_loras", [])
                if not selected_loras:
                    return "At least one LoRA must be selected for comparison mode"
            else:
                # Mode 1: Strength sweep - require LoRA selection
                lora_name = data.get("lora_name")
                if not lora_name:
                    return "LoRA must be selected for strength sweep mode"

                # Validate strength range
                start = data.get("strength_start", 0.0)
                end = data.get("strength_end", 1.0)
                step = data.get("strength_step", 0.1)

                if start >= end:
                    return "Start strength must be less than end strength"

                if step <= 0:
                    return "Strength step must be positive"
        else:
            # Numeric variable - validate range
            if data["start_value"] >= data["end_value"]:
                return "Start value must be less than end value"

            if data["step_value"] <= 0:
                return "Step value must be positive"

        if data["images_per_value"] < 1:
            return "Images per variant must be at least 1"

        if data["prompt_source"] == "custom" and not data["custom_prompt"]:
            return "Custom prompt text is required when using custom prompt source"
        if data["prompt_source"] == "pack":
            if not data.get("selected_prompt_pack_name"):
                return "Prompt pack must be selected"
            if not data.get("selected_prompt_text"):
                return "Prompt must be selected from the chosen prompt pack"

        return None

    def _on_variable_changed(self, event=None) -> None:
        """Handle variable selection change - show appropriate UI widget.

        PR-LEARN-020: Switches between range widget and checklist based on variable type.
        """
        from src.learning.variable_metadata import get_variable_metadata

        if _prompt_slot(self) or self._is_model_comparison() or self._is_grid():
            return

        variable_name = self.variable_var.get()
        self._update_policy_buttons()
        if not variable_name:
            return
        if self._learning_capabilities is not None and variable_name not in self._learning_capabilities.variables:
            self.feedback_var.set(f"{variable_name} is unavailable for this model/stage.")
            return

        # Look up metadata
        meta = get_variable_metadata(variable_name)
        if not meta:
            self._show_range_widget()
            return

        # Show appropriate widget based on ui_component
        if meta.ui_component == "range":
            self._show_range_widget()
        elif meta.ui_component == "checklist":
            self._show_checklist_widget(meta)
        elif meta.ui_component == "lora_composite":  # PR-LEARN-022
            self._show_lora_composite_widget(meta)
        else:
            self._show_range_widget()
        self._refresh_identity_preview()

    def _on_stage_changed(self, event=None) -> None:
        capability = get_stage_capability(self.stage_var.get())
        self.stage_hint_var.set(
            f"{capability.display_name}: requires an input image and stage-specific settings."
            if capability.requires_input_image
            else f"{capability.display_name}: generates directly from prompt with no source image."
        )
        if capability.requires_input_image:
            self.input_image_frame.grid()
        else:
            self.input_image_frame.grid_remove()
            self.input_image_var.set("")
        allowed_variables = get_variables_for_stage(self.stage_var.get())
        self.variable_combo.configure(values=allowed_variables)
        if self.variable_var.get() not in allowed_variables:
            self.variable_var.set("")
            self._show_range_widget()
        self._refresh_identity_preview()
        editor = getattr(self, "baseline_editor", None)
        if editor is not None:
            editor.rebuild()
        self._refresh_model_capabilities()

    def on_model_projection(self, projection) -> None:
        """Note the Pipeline's model policy; it never decides Learning's model, stages or variables.

        Learning's own baseline owns the model.  The Pipeline projection only keeps the "Copy Current Pipeline
        Settings" availability and the first-time seed of a brand-new experiment current.
        """
        self._pipeline_projection = projection
        self._ensure_baseline()
        self._refresh_model_capabilities()

    def _ensure_baseline(self) -> None:
        """Seed a brand-new experiment's baseline from the Pipeline once, with its origin shown.

        Only once the operator can see the Design step: a panel built at startup must not capture the Pipeline's
        startup defaults and present them as the experiment's settings.
        """
        ensure = getattr(self.learning_controller, "ensure_baseline", None)
        if callable(ensure) and getattr(self, "_shown", False):
            ensure(self.stage_var.get())

    def _on_selected_pages(self) -> bool:
        widget: tk.Misc | None = self
        while widget is not None:
            parent = getattr(widget, "master", None)
            if isinstance(parent, ttk.Notebook) and str(parent.tk.call(str(parent), "select")) != str(widget):
                return False
            widget = parent
        return True

    def _on_shown(self, _event: object = None) -> None:
        """First time the Design step is visible: take the one-time seed from the Pipeline as it is now."""
        # A hidden notebook page's children still receive <Map>; only a panel on the selected pages is displayed.
        if self._shown or not self._on_selected_pages():
            return
        self._shown = True
        self._ensure_baseline()
        editor = getattr(self, "baseline_editor", None)
        if editor is not None:
            editor.rebuild()
        self._refresh_model_capabilities()
        self._refresh_identity_preview()

    def _policy_notes(self) -> dict[str, str]:
        """Variables the Learning model's profile decides, for the editor's "fixed by profile" notes."""
        capability = self._learning_capabilities
        if capability is None:
            return {}
        return {name: reason for name, reason in capability.unavailable if reason in {"fixed", "unsupported"}}

    def _on_baseline_changed(self) -> None:
        self._refresh_model_capabilities()
        self._refresh_identity_preview()
        self._notify_design_changed()

    def _baseline_blockers(self) -> list[str]:
        editor = getattr(self, "baseline_editor", None)
        return editor.problems() if editor is not None else []

    def _sync_target_from_baseline(self) -> None:
        """Learning's model decides the policy: resolved from the Learning baseline, never the Pipeline."""
        controller = self.learning_controller
        authored = getattr(controller, "authoring_baseline", None)
        self._target_policy = None
        self._target_model = None
        if not callable(authored):
            return
        baseline = authored()
        model = selected_model(baseline, self.stage_var.get())
        if model:
            self._target_policy = resolve_policy(model, controller, baseline)
            self._target_model = model

    def _refresh_model_capabilities(self) -> None:
        if _prompt_slot(self):
            self._ensure_baseline()
            self._sync_target_from_baseline()
            self.baseline_editor.refresh()
            self._update_policy_buttons()
            return
        if self._is_grid():
            self._on_grid_design_changed()
            return
        if self._is_model_comparison():
            self._update_policy_buttons()
            return
        self._ensure_baseline()
        self._sync_target_from_baseline()
        editor = getattr(self, "baseline_editor", None)
        policy = self._target_policy
        stage = self.stage_var.get()
        controller = self.learning_controller
        if policy is None:
            self._learning_capabilities = None
            self.stage_combo.configure(values=list_supported_stages())
            self.variable_combo.configure(values=get_variables_for_stage(stage))
            self.model_target_var.set("Learning Target: choose a model in the Learning baseline")
            if editor is not None:
                editor.refresh()
            self._update_policy_buttons()
            return
        if controller is not None and callable(getattr(controller, "authoring_baseline", None)):
            capability = live_capabilities(
                controller, stage, policy=policy, model=self._target_model,
                baseline=controller.authoring_baseline(),
            )
        else:
            capability = project_learning_capabilities(policy, self._target_model, stage)
        self._learning_capabilities = capability
        if editor is not None:
            editor.refresh()
        stages = [s for s in list_supported_stages() if s in policy.stages and
                  (s not in {"adetailer", "upscale"} or policy.feature(s, s).supported)]
        self.stage_combo.configure(values=stages)
        self.variable_combo.configure(values=capability.variables)
        self.model_target_var.set(capability.target + ("\n" + capability.guidance if capability.guidance else ""))
        if self.variable_var.get() and self.variable_var.get() not in capability.variables:
            self.feedback_var.set(f"{self.variable_var.get()} is unavailable for this model/stage.")
            self.variable_var.set("")
        if not capability.stage_supported:
            self.feedback_var.set("Selected stage is unavailable for this model.")
        self._update_policy_buttons()
        if self.variable_var.get() == "Model":
            from src.learning.variable_metadata import get_variable_metadata
            selected = {name for name, value in self.choice_vars.items() if value.get()}
            self._populate_checklist(get_variable_metadata("Model"))
            for name, value in self.choice_vars.items():
                value.set(name in selected)
        elif self.variable_var.get() == "LoRA Strength" and policy.qualified:
            combo = getattr(self, "lora_selector_combo", None)
            if combo is not None:
                combo.configure(values=capability.lora_candidates)

    def _update_policy_buttons(self) -> None:
        if getattr(self, "_comparison_readiness_busy", False):
            self.build_button.configure(state="disabled")
            self.run_button.configure(state="disabled")
            return
        if _prompt_slot(self):
            from src.learning.prompt_slot_experiment import require_target

            try:
                policy = self._target_policy
                controller = self.learning_controller
                if policy is None or controller is None:
                    raise ValueError("Select a supported Learning baseline first")
                require_target(policy, controller.authoring_baseline())
                valid = not self.prompt_slot_frame.validation_error(int(self.images_var.get())) and not self._baseline_blockers()
            except (AttributeError, TypeError, ValueError, tk.TclError):
                valid = False
            self.build_button.configure(state="normal" if valid else "disabled")
            experiment = self._current_experiment()
            from src.learning.model_comparison import study_type

            frozen = bool(getattr(experiment, "execution_snapshot_json", "")) and study_type(experiment) == "prompt_slot"
            self.run_button.configure(state="normal" if frozen and not self.preview_is_stale() else "disabled")
            return
        if self._is_grid():
            self.build_button.configure(state="normal" if self.grid_frame.validation_error() is None else "disabled")
            self.run_button.configure(state="normal" if self._grid_preview_fresh() else "disabled")
            return
        if self._is_model_comparison():
            valid = sum(bool(var.get()) for var in self.choice_vars.values()) >= 2
            self.build_button.configure(state="normal" if valid else "disabled")
            experiment = getattr(getattr(self.learning_controller, "learning_state", None), "current_experiment", None)
            self.run_button.configure(state="normal" if getattr(experiment, "execution_snapshot_json", "") else "disabled")
            return
        capability = self._learning_capabilities
        if capability is None:
            if getattr(self, "baseline_editor", None) is not None and getattr(self, "_built", False):
                self.build_button.configure(state="disabled")
                self.run_button.configure(state="disabled")
            return
        valid = (
            capability.stage_supported
            and self.variable_var.get() in capability.variables
            and not self._baseline_blockers()
        )
        self.build_button.configure(state="normal" if valid else "disabled")
        self.run_button.configure(state="normal" if valid else "disabled")

    def _on_browse_input_image(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select Input Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All Files", "*.*")],
        )
        if selected:
            self.input_image_var.set(selected)
            self._refresh_identity_preview()

    def _show_range_widget(self) -> None:
        """Show numeric range widget (start/stop/step)."""
        # Show value frame
        self.value_frame.grid(row=11, column=0, sticky="ew", pady=(0, 10))

        # Hide checklist frame
        self.checklist_frame.grid_remove()
        self.lora_frame.grid_remove()

    def _show_checklist_widget(self, meta) -> None:
        """Show checklist widget for discrete choices.

        PR-LEARN-020: Displays checkboxes for discrete/resource variables.
        """
        # Hide value frame
        self.value_frame.grid_remove()
        self.lora_frame.grid_remove()

        # Show checklist frame at row 10
        self.checklist_frame.grid(row=11, column=0, sticky="ew", pady=(0, 10))

        # Update checklist label
        self.checklist_frame.config(text=f"Select {meta.display_name} to Test")

        # Populate checklist with choices
        self._populate_checklist(meta)

    def _populate_checklist(self, meta) -> None:
        """Populate checklist with choices from resources.

        PR-LEARN-020: Gets available choices from app_state resources.
        PR-LEARN-021: Added search/filter support.
        """
        # Clear existing checkboxes
        for widget in self.checklist_inner_frame.winfo_children():
            widget.destroy()

        self.choice_vars.clear()
        self._choice_display_map = {}

        # Get available choices from app_state
        choices = []
        if meta.resource_key and self.learning_controller:
            choices, mapping = get_resource_choices(self.learning_controller, meta.resource_key)
            self._choice_display_map = dict(mapping)
        if meta.name == "model" and self._target_policy is not None and not self._is_model_comparison():
            target = policy_context(self._target_policy, self._target_model, self.stage_var.get())
            choices = [choice for choice in choices if compatible_context(target, policy_context(
                resolve_policy(self._choice_display_map.get(choice, choice), self.learning_controller),
                self._choice_display_map.get(choice, choice), self.stage_var.get()))]

        if not choices:
            # No choices available
            ttk.Label(
                self.checklist_inner_frame,
                text=f"No {meta.display_name} available in WebUI",
                foreground="red",
            ).pack(anchor="w", pady=2)
            return

        # PR-LEARN-021: Add search/filter box for large resource lists
        if meta.constraints.get("supports_filter", False):
            search_frame = ttk.Frame(self.checklist_inner_frame)
            search_frame.pack(fill="x", pady=(0, 10))

            ttk.Label(search_frame, text="Search:").pack(side="left", padx=(0, 5))

            self.search_var = tk.StringVar()
            search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
            search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

            # Bind search to filter function
            self.search_var.trace_add("write", lambda *args: self._filter_checklist_items(meta))

            # Clear button
            clear_btn = ttk.Button(
                search_frame, text="Clear", width=8, command=lambda: self.search_var.set("")
            )
            clear_btn.pack(side="left", padx=(5, 0))

        # Add Select All / Clear All buttons
        button_frame = ttk.Frame(self.checklist_inner_frame)
        button_frame.pack(fill="x", pady=(0, 5))

        ttk.Button(
            button_frame, text="Select All", command=lambda: self._select_all_choices(True)
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            button_frame, text="Clear All", command=lambda: self._select_all_choices(False)
        ).pack(side="left")

        # Container for checkboxes (for filtering)
        self.checkbox_container = ttk.Frame(self.checklist_inner_frame)
        self.checkbox_container.pack(fill="both", expand=True)
        self._bind_checklist_wheel(self.checkbox_container)

        entries = [str(choice) for choice in choices]
        # Create checkboxes for each choice
        for choice in entries:
            internal_choice = self._choice_display_map.get(choice, choice)
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.checkbox_container, text=choice, variable=var)
            cb.pack(anchor="w", pady=2)
            self._bind_checklist_wheel(cb)
            self.choice_vars[internal_choice] = var

            # Bind checkbox changes to update count
            var.trace_add("write", lambda *args: self._update_choice_count())

        # Add count label
        self.choice_count_var = tk.StringVar(value="0 items selected")
        count_label = ttk.Label(
            self.checklist_inner_frame, textvariable=self.choice_count_var, foreground="blue"
        )
        count_label.pack(anchor="w", pady=(5, 0))

    def _on_resources_updated(self, _resources: dict[str, list[Any]] | None = None) -> None:
        """Refresh the active resource checklist from the current projection."""
        if not self.winfo_exists():
            return
        self._cancel_comparison_evidence()
        from src.learning.variable_metadata import get_variable_metadata
        if self._is_model_comparison():
            selected = {name for name, value in self.choice_vars.items() if value.get()}
            self._populate_checklist(get_variable_metadata("Model"))
            for name, value in self.choice_vars.items():
                value.set(name in selected)
            return
        self._ensure_baseline()
        self._refresh_model_capabilities()

        variable = self.variable_var.get().strip()
        if not variable:
            return
        meta = get_variable_metadata(variable)
        if meta is not None and meta.resource_key:
            self._populate_checklist(meta)

    def _select_all_choices(self, selected: bool) -> None:
        """Select or deselect all checkboxes."""
        for var in self.choice_vars.values():
            var.set(selected)

    def _bind_checklist_wheel(self, widget: tk.Misc) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, self._on_checklist_mousewheel, add="+")

    def _on_checklist_mousewheel(self, event: tk.Event) -> str:
        """Keep nested resource scrolling inside its bounded viewport."""
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = int(-1 * (getattr(event, "delta", 0) / 120)) or -1
        self.checklist_canvas.yview_scroll(delta, "units")
        return "break"

    def _update_choice_count(self) -> None:
        """Update the count label showing selected items."""
        self._cancel_comparison_evidence()
        count = sum(1 for var in self.choice_vars.values() if var.get())
        self.choice_count_var.set(f"{count} items selected")
        self._update_policy_buttons()
        self._notify_design_changed()

    def _on_name_changed(self) -> None:
        if self._suspend_identity_tracking:
            return
        current = self.name_var.get().strip()
        if current:
            self._name_auto_generated = False
        self._refresh_identity_preview()

    def _on_description_changed(self) -> None:
        if self._suspend_identity_tracking:
            return
        current = self.desc_var.get().strip()
        if current:
            self._description_auto_generated = False
        self._refresh_identity_preview()

    def _on_prompt_text_edited(self) -> None:
        if _prompt_slot(self):
            self.custom_prompt_text.tag_configure("slot_hidden", elide=not self._comparison_show_names())
            self.custom_prompt_text.tag_add("slot_hidden", "1.0", tk.END)
        self._refresh_identity_preview()
        self._on_grid_design_changed()
        self._notify_design_changed()

    def _get_prompt_preview_text(self) -> str:
        if self.prompt_source_var.get() == "custom":
            return self.custom_prompt_text.get("1.0", "end-1c") if _prompt_slot(self) else self.custom_prompt_text.get("1.0", tk.END).strip()
        selected_prompt = self._get_selected_prompt_payload()
        if selected_prompt:
            return str(selected_prompt.get("prompt_text", "") or "")
        return ""

    def _current_model_vae(self) -> tuple[str, str]:
        ctrl = self.learning_controller
        if ctrl and hasattr(ctrl, "authoring_baseline"):
            try:
                baseline = ctrl.authoring_baseline()
                txt2img = dict((baseline or {}).get("txt2img") or {})
                return (
                    str(txt2img.get("model") or ""),
                    str(txt2img.get("vae") or ""),
                )
            except Exception:
                return "", ""
        return "", ""

    def _refresh_identity_preview(self) -> None:
        if _prompt_slot(self):
            return
        model, vae = self._current_model_vae()
        identity = build_experiment_identity(
            stage=self.stage_var.get(),
            variable_label=self.variable_var.get(),
            prompt_text=self._get_prompt_preview_text(),
            model=model,
            vae=vae,
        )
        current_name = self.name_var.get().strip()
        current_desc = self.desc_var.get().strip()
        summary = identity["summary"]
        if current_name:
            summary = f"{summary}\nFolder: {current_name}"
        if current_desc:
            summary = f"{summary}\n{current_desc}"
        if hasattr(self, "summary_var"):
            self.summary_var.set(summary)

    def _suggest_identity(self, *, name_only: bool = True) -> None:
        model, vae = self._current_model_vae()
        identity = build_experiment_identity(
            stage=self.stage_var.get(),
            variable_label=self.variable_var.get(),
            prompt_text=self._get_prompt_preview_text(),
            model=model,
            vae=vae,
        )
        self._suspend_identity_tracking = True
        try:
            self._name_auto_generated = True
            self.name_var.set(identity["name"])
            if not name_only or not self.desc_var.get().strip() or self._description_auto_generated:
                self._description_auto_generated = True
                self.desc_var.set(identity["description"])
        finally:
            self._suspend_identity_tracking = False
        self._refresh_identity_preview()

    def _filter_checklist_items(self, meta) -> None:
        """Filter checklist items based on search text.

        PR-LEARN-021: Real-time filtering of resource lists.
        """
        if not hasattr(self, "search_var") or not hasattr(self, "checkbox_container"):
            return

        search_text = self.search_var.get().lower()

        # Show/hide checkboxes based on search
        for widget in self.checkbox_container.winfo_children():
            if isinstance(widget, ttk.Checkbutton):
                text = widget.cget("text").lower()
                if not search_text or search_text in text:
                    widget.pack(anchor="w", pady=2)
                else:
                    widget.pack_forget()

        # Update count
        self._update_choice_count()

    def _show_lora_composite_widget(self, meta) -> None:
        """Show LoRA composite widget (LoRA selector + strength range OR LoRA comparison).

        PR-LEARN-022: Supports two modes:
        - Mode 1: Single LoRA with strength sweep
        - Mode 2: Multiple LoRAs at fixed strength
        """
        # Hide other widgets
        try:
            self.value_frame.grid_remove()
        except Exception:
            pass
        self.checklist_frame.grid_remove()

        # Show LoRA frame at row 10
        self.lora_frame.grid(row=11, column=0, sticky="ew", pady=(0, 10))

        # Clear existing content
        for widget in self.lora_frame.winfo_children():
            widget.destroy()

        # Mode selector
        mode_frame = ttk.Frame(self.lora_frame)
        mode_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(mode_frame, text="Test Mode:", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w", pady=(0, 5)
        )

        self.lora_mode_var = tk.StringVar(value="strength")

        strength_mode_rb = ttk.Radiobutton(
            mode_frame,
            text="Test single LoRA at multiple strengths",
            variable=self.lora_mode_var,
            value="strength",
            command=self._on_lora_mode_changed,
        )
        strength_mode_rb.pack(anchor="w", pady=2)

        comparison_mode_rb = ttk.Radiobutton(
            mode_frame,
            text="Compare different LoRAs at fixed strength",
            variable=self.lora_mode_var,
            value="comparison",
            command=self._on_lora_mode_changed,
        )
        comparison_mode_rb.pack(anchor="w", pady=2)

        # Content frame (dynamic based on mode)
        self.lora_content_frame = ttk.Frame(self.lora_frame)
        self.lora_content_frame.pack(fill="both", expand=True)

        # Build initial content
        self._build_lora_mode_content()

    def _on_lora_mode_changed(self) -> None:
        """Handle LoRA mode selection change."""
        self._build_lora_mode_content()

    def _build_lora_mode_content(self) -> None:
        """Build content based on selected LoRA mode.

        PR-LEARN-022: Switches between strength sweep UI and LoRA comparison UI.
        """
        # Clear existing content
        for widget in self.lora_content_frame.winfo_children():
            widget.destroy()

        mode = self.lora_mode_var.get() if hasattr(self, "lora_mode_var") else "strength"

        if mode == "strength":
            self._build_strength_sweep_ui()
        else:
            self._build_lora_comparison_ui()

    def _build_strength_sweep_ui(self) -> None:
        """Build UI for single LoRA strength sweep.

        Shows: LoRA selector + strength range (start/stop/step)
        """
        # Get available LoRAs from controller
        available_loras = []
        if hasattr(self, "learning_controller") and self.learning_controller:
            try:
                override = (
                    self._build_selected_prompt_workspace_state()
                    if self.prompt_source_var.get() == "pack"
                    else None
                )
                loras = self.learning_controller._get_current_loras(
                    prompt_workspace_state_override=override
                )
                available_loras = [lora["name"] for lora in loras if self._learning_capabilities is None
                                   or not self._target_policy.qualified
                                   or lora["name"] in self._learning_capabilities.lora_candidates]
            except Exception:
                pass

        # LoRA selector
        lora_select_frame = ttk.Frame(self.lora_content_frame)
        lora_select_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(lora_select_frame, text="Select LoRA to test:").pack(anchor="w", pady=(0, 2))

        self.lora_selector_var = tk.StringVar()
        if available_loras:
            self.lora_selector_var.set(available_loras[0])

        lora_combo = ttk.Combobox(
            lora_select_frame,
            textvariable=self.lora_selector_var,
            values=available_loras,
            state="readonly",
        )
        lora_combo.pack(fill="x")
        self.lora_selector_combo = lora_combo

        if not available_loras:
            ttk.Label(
                lora_select_frame,
                text="No enabled LoRAs in current prompt or runtime config",
                foreground="red",
            ).pack(anchor="w", pady=(2, 0))

        # Strength range
        range_frame = ttk.LabelFrame(self.lora_content_frame, text="Strength Range", padding=5)
        range_frame.pack(fill="x")
        range_frame.columnconfigure(0, weight=1)
        range_frame.columnconfigure(1, weight=1)
        range_frame.columnconfigure(2, weight=1)

        # Start
        ttk.Label(range_frame, text="Start:").grid(row=0, column=0, sticky="w", pady=2)
        self.lora_start_var = tk.DoubleVar(value=0.5)
        start_spin = tk.Spinbox(
            range_frame, from_=0.0, to=2.0, increment=0.1, textvariable=self.lora_start_var
        )
        start_spin.grid(row=1, column=0, sticky="ew", padx=(0, 2))

        # End
        ttk.Label(range_frame, text="End:").grid(row=0, column=1, sticky="w", pady=2)
        self.lora_end_var = tk.DoubleVar(value=1.5)
        end_spin = tk.Spinbox(
            range_frame, from_=0.0, to=2.0, increment=0.1, textvariable=self.lora_end_var
        )
        end_spin.grid(row=1, column=1, sticky="ew", padx=2)

        # Step
        ttk.Label(range_frame, text="Step:").grid(row=0, column=2, sticky="w", pady=2)
        self.lora_step_var = tk.DoubleVar(value=0.1)
        step_spin = tk.Spinbox(
            range_frame, from_=0.05, to=1.0, increment=0.05, textvariable=self.lora_step_var
        )
        step_spin.grid(row=1, column=2, sticky="ew", padx=(2, 0))

        # Variant count estimate
        def update_variant_count(*args):
            try:
                start = self.lora_start_var.get()
                end = self.lora_end_var.get()
                step = self.lora_step_var.get()
                if step > 0 and end >= start:
                    count = int((end - start) / step) + 1
                    count_label.config(text=f"{count} variants will be generated")
                else:
                    count_label.config(text="Invalid range")
            except Exception:
                count_label.config(text="")

        self.lora_start_var.trace_add("write", update_variant_count)
        self.lora_end_var.trace_add("write", update_variant_count)
        self.lora_step_var.trace_add("write", update_variant_count)

        count_label = ttk.Label(self.lora_content_frame, text="", foreground="blue")
        count_label.pack(anchor="w", pady=(5, 0))
        update_variant_count()

    def _build_lora_comparison_ui(self) -> None:
        """Build UI for comparing different LoRAs at fixed strength.

        Shows: LoRA checklist + fixed strength input
        """
        # Get available LoRAs
        available_loras = []
        if hasattr(self, "learning_controller") and self.learning_controller:
            try:
                override = (
                    self._build_selected_prompt_workspace_state()
                    if self.prompt_source_var.get() == "pack"
                    else None
                )
                loras = self.learning_controller._get_current_loras(
                    prompt_workspace_state_override=override
                )
                available_loras = [lora["name"] for lora in loras if self._learning_capabilities is None
                                   or not self._target_policy.qualified
                                   or lora["name"] in self._learning_capabilities.lora_candidates]
            except Exception:
                pass

        # Fixed strength input
        strength_frame = ttk.Frame(self.lora_content_frame)
        strength_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(strength_frame, text="Fixed strength for all LoRAs:").pack(
            side="left", padx=(0, 5)
        )

        self.lora_fixed_strength_var = tk.DoubleVar(value=1.0)
        strength_spin = tk.Spinbox(
            strength_frame,
            from_=0.0,
            to=2.0,
            increment=0.1,
            textvariable=self.lora_fixed_strength_var,
            width=10,
        )
        strength_spin.pack(side="left")

        # LoRA checklist
        checklist_label = ttk.Label(self.lora_content_frame, text="Select LoRAs to compare:")
        checklist_label.pack(anchor="w", pady=(0, 5))

        # Scrollable checklist
        checklist_canvas = tk.Canvas(self.lora_content_frame, height=150)
        checklist_scrollbar = ttk.Scrollbar(
            self.lora_content_frame, orient="vertical", command=checklist_canvas.yview
        )
        checklist_inner = ttk.Frame(checklist_canvas)
        checklist_canvas.configure(yscrollcommand=checklist_scrollbar.set)

        checklist_scrollbar.pack(side="right", fill="y")
        checklist_canvas.pack(side="left", fill="both", expand=True)
        checklist_canvas.create_window((0, 0), window=checklist_inner, anchor="nw")
        checklist_inner.bind(
            "<Configure>",
            lambda e: checklist_canvas.configure(scrollregion=checklist_canvas.bbox("all")),
        )

        # Create checkboxes
        self.lora_choice_vars = {}

        if not available_loras:
            ttk.Label(
                checklist_inner,
                text="No enabled LoRAs in current prompt or runtime config",
                foreground="red",
            ).pack(anchor="w", pady=2)
        else:
            # Select All / Clear All
            button_frame = ttk.Frame(checklist_inner)
            button_frame.pack(fill="x", pady=(0, 5))

            ttk.Button(
                button_frame, text="Select All", command=lambda: self._select_all_lora_choices(True)
            ).pack(side="left", padx=(0, 5))

            ttk.Button(
                button_frame, text="Clear All", command=lambda: self._select_all_lora_choices(False)
            ).pack(side="left")

            # Checkboxes
            for lora in available_loras:
                var = tk.BooleanVar(value=False)
                cb = ttk.Checkbutton(checklist_inner, text=lora, variable=var)
                cb.pack(anchor="w", pady=2)
                self.lora_choice_vars[lora] = var

            # Count label
            self.lora_count_var = tk.StringVar(value="0 LoRAs selected")
            count_label = ttk.Label(
                checklist_inner, textvariable=self.lora_count_var, foreground="blue"
            )
            count_label.pack(anchor="w", pady=(5, 0))

            # Bind checkbox changes
            for var in self.lora_choice_vars.values():
                var.trace_add("write", lambda *args: self._update_lora_choice_count())

    def _select_all_lora_choices(self, selected: bool) -> None:
        """Select or deselect all LoRA checkboxes."""
        for var in self.lora_choice_vars.values():
            var.set(selected)

    def _update_lora_choice_count(self) -> None:
        """Update LoRA selection count."""
        count = sum(1 for var in self.lora_choice_vars.values() if var.get())
        self.lora_count_var.set(f"{count} LoRAs selected")
        self._notify_design_changed()

    def restore_state(self, experiment: Any) -> None:
        from src.learning.model_comparison import study_type

        self.study_type_var.set(
            {"model_comparison": "Model Comparison", "two_axis_grid": "Two-Axis Grid", "prompt_slot": "Prompt Slot"}.get(
                study_type(experiment), "Controlled Variable"
            )
        )
        self.name_var.set(str(getattr(experiment, "name", "") or ""))
        self.desc_var.set(str(getattr(experiment, "description", "") or ""))
        self.stage_var.set(str(getattr(experiment, "stage", "txt2img") or "txt2img"))
        self._on_stage_changed()
        self.input_image_var.set(str(getattr(experiment, "input_image_path", "") or ""))
        self.variable_var.set(str(getattr(experiment, "variable_under_test", "") or ""))
        metadata = dict(getattr(experiment, "metadata", {}) or {})
        self.start_var.set(float(metadata.get("start_value", self.start_var.get())))
        self.end_var.set(float(metadata.get("end_value", self.end_var.get())))
        self.step_var.set(float(metadata.get("step_value", self.step_var.get())))
        self.images_var.set(int(getattr(experiment, "images_per_value", 1) or 1))
        prompt_text = str(getattr(experiment, "prompt_text", "") or "")
        prompt_source = str(
            metadata.get("prompt_source", "custom" if prompt_text else "pack") or "pack"
        )
        self.prompt_source_var.set(prompt_source)
        selected_pack_name = str(metadata.get("selected_prompt_pack_name", "") or "")
        if selected_pack_name:
            self.prompt_pack_var.set(selected_pack_name)
        self._refresh_prompt_pack_choices()
        selected_prompt_index = metadata.get("selected_prompt_index")
        if selected_prompt_index is not None:
            for label, payload in self._prompt_option_payloads.items():
                if int(payload.get("prompt_index", -1)) == int(selected_prompt_index):
                    self.prompt_item_var.set(label)
                    break
        self._on_prompt_source_changed()
        self.custom_prompt_text.config(state="normal")
        self.custom_prompt_text.delete("1.0", tk.END)
        self.custom_prompt_text.insert("1.0", prompt_text)
        if self.prompt_source_var.get() == "pack":
            self._on_prompt_source_changed()
        self._on_variable_changed()
        if _prompt_slot(self) or self._is_model_comparison() or self._is_grid():
            self._on_study_type_changed()
        if _prompt_slot(self):
            from src.learning.experiment_execution import thaw_snapshot

            frozen = (thaw_snapshot(experiment.execution_snapshot_json).get("prompt_slot")
                      if getattr(experiment, "execution_snapshot_json", "") else None)
            spec = dict(metadata.get("prompt_slot") or {})
            if frozen:
                spec.update(slot=frozen["slot"], fixed_slots=frozen["fixed_slots"],
                            candidates=[candidate["value"] for candidate in frozen["candidates"]])
            self.prompt_slot_frame.load(spec, frozen_template=frozen["template"] if frozen and prompt_source == "pack" else None)
        if self._is_grid():
            self.grid_frame.load(metadata.get("grid"))
            self._grid_preview_signature = (
                self._grid_signature() if getattr(experiment, "execution_snapshot_json", "") else None
            )
            self._update_policy_buttons()
        selected_items = {str(item) for item in metadata.get("selected_models" if self._is_model_comparison() else "selected_items", [])}
        for item, var in self.choice_vars.items():
            var.set(item in selected_items)
        self._name_auto_generated = False
        self._description_auto_generated = False
        self.name_var.set(str(getattr(experiment, "name", "") or ""))
        self._refresh_model_capabilities()
        self._refresh_identity_preview()
        self._sync_study_presentation()
        self._preview_signature = (
            self.design_signature() if getattr(experiment, "execution_snapshot_json", "") else None
        )
        self._blocker = None
        self._notify_design_changed()
