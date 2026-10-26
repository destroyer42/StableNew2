# Subsystem: Learning
# Role: Shows learning run results and feedback controls.

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.gui.learning_state import LearningVariant
from src.gui.theme_v2 import PRIMARY_BUTTON_STYLE
from src.gui.ui_tokens import TOKENS
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.media_inspector import MediaInspector as ImageThumbnail
from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame
from src.gui_v2.recommendation_targets import describe_apply_changes
from src.learning.controlled_study_display import DISPLAYED_STUDIES, visibility_prompt
from src.learning.guided_workflow import RatingProgress, build_rating_progress
from src.learning.rating_schema import blend_rating, get_active_categories
from src.learning.recommendation_summary import build_recommendation_summary
from src.learning.review_workspace import build_review_projection
from src.learning.two_axis_grid import variant_label


class LearningReviewPanel(ttk.Frame):
    """Image-first learning review surface with side controls."""

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)
        self.learning_controller = None

        # Current variant being reviewed
        self.current_variant: LearningVariant | None = None
        self.current_experiment = None
        self._context_flag_vars: dict[str, tk.BooleanVar] = {
            "people": tk.BooleanVar(value=True),
            "animals": tk.BooleanVar(value=False),
            "landscape": tk.BooleanVar(value=False),
            "architecture": tk.BooleanVar(value=False),
            "close_up": tk.BooleanVar(value=False),
        }
        self._subscore_vars: dict[str, tk.IntVar] = {}

        # Configure layout
        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(0, weight=1)

        # Left: image-first review workspace
        self.preview_column = ttk.Frame(self)
        self.preview_column.grid(row=0, column=0, sticky="nsew", padx=(5, 3), pady=5)
        self.preview_column.columnconfigure(0, weight=1)
        self.preview_column.rowconfigure(0, weight=0)
        self.preview_column.rowconfigure(1, weight=1)

        # Experiment-wide review workspace.  The existing per-variant viewer
        # remains the detail surface; this layer makes the durable experiment
        # the navigation/comparison unit.
        self.experiment_workspace = ttk.LabelFrame(
            self.preview_column, text="Experiment Review", padding=5
        )
        self.experiment_workspace.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.experiment_workspace.columnconfigure(0, weight=1)
        self.experiment_workspace.columnconfigure(1, weight=0)
        self.workspace_status_var = tk.StringVar(value="No experiment selected")
        ttk.Label(
            self.experiment_workspace,
            textvariable=self.workspace_status_var,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.variant_summary_list = tk.Listbox(
            self.experiment_workspace,
            height=4,
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        self.variant_summary_list.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.variant_summary_list.bind("<<ListboxSelect>>", self._on_workspace_variant_selected)
        workspace_actions = ttk.Frame(self.experiment_workspace)
        workspace_actions.grid(row=1, column=1, sticky="ns", padx=(6, 0), pady=(4, 0))
        self.next_unrated_button = ttk.Button(
            workspace_actions, text="Next Unrated", command=self._on_next_unrated
        )
        self.next_unrated_button.pack(fill="x")
        self.compare_button = ttk.Button(
            workspace_actions, text="Compare Selected", command=self._on_compare_selected
        )
        self.compare_button.pack(fill="x", pady=(4, 0))

        # Right: rating first. Status and metadata describe the variant while comparing; the recommendations
        # are the outcome of the ratings and sit below them.
        self.side_column = ttk.Frame(self)
        self.side_column.grid(row=0, column=1, sticky="nsew", padx=(3, 5), pady=5)
        self.side_column.columnconfigure(0, weight=1)
        self.side_column.rowconfigure(0, weight=0)
        self.side_column.rowconfigure(1, weight=0)
        self.side_column.rowconfigure(3, weight=1)
        self._mode = "rate"

        # Status section
        self.status_frame = ttk.LabelFrame(self.side_column, text="Variant Status", padding=5)
        self.status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.status_label = ttk.Label(self.status_frame, text="No variant selected")
        self.status_label.pack(anchor="w")

        self.progress_label = ttk.Label(self.status_frame, text="")
        self.progress_label.pack(anchor="w")

        # Metadata section
        self.metadata_frame = ttk.LabelFrame(self.side_column, text="Metadata", padding=5)
        self.metadata_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.metadata_text = ScrolledText(
            self.metadata_frame,
            height=4,
            width=32,
            state="disabled",
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
        )
        self.metadata_text.pack(fill="x")

        # Recommendations section: a plain-language summary first, the evidence one disclosure away.
        self.recommendations_frame = ttk.LabelFrame(self.side_column, text="Recommendations", padding=5)
        self.recommendations_frame.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.recommendations_frame.columnconfigure(0, weight=1)
        self.recommendation_summary_var = tk.StringVar(
            value="No recommendation yet. Rate results to build evidence."
        )
        self.recommendation_summary_label = ttk.Label(
            self.recommendations_frame,
            textvariable=self.recommendation_summary_var,
            wraplength=340,
            justify="left",
        )
        self.recommendation_summary_label.grid(row=0, column=0, sticky="ew")
        self.recommendation_scope_var = tk.StringVar(value="")
        ttk.Label(
            self.recommendations_frame,
            textvariable=self.recommendation_scope_var,
            wraplength=340,
            justify="left",
            foreground=TOKENS.colors.text_muted,
        ).grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.mode_host = ttk.Frame(self.recommendations_frame)
        self.mode_host.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self.recommendation_details = DisclosureSection(
            self.recommendations_frame, title="Evidence and details", expanded=False
        )
        self.recommendation_details.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.recommendations_text = tk.Text(
            self.recommendation_details.body,
            height=6,
            width=32,
            state="disabled",
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
        )
        self.recommendations_text.pack(fill="x")

        self.apply_note_var = tk.StringVar(value="")
        ttk.Label(
            self.recommendations_frame,
            textvariable=self.apply_note_var,
            wraplength=340,
            justify="left",
            foreground=TOKENS.colors.text_muted,
        ).grid(row=4, column=0, sticky="ew", pady=(6, 0))

        # Apply recommendations button
        button_frame = ttk.Frame(self.recommendations_frame)
        button_frame.grid(row=5, column=0, sticky="ew", pady=(5, 0))

        self.apply_button = ttk.Button(
            button_frame,
            text="Apply to Pipeline",
            command=self._on_apply_recommendations,
            state="disabled",
        )
        self.apply_button.pack(side="left", padx=2)

        # Analytics button
        self.analytics_button = ttk.Button(
            button_frame,
            text="View Analytics",
            command=self._on_view_analytics,
        )
        self.analytics_button.pack(side="left", padx=2)
        self.slot_conclusion_text = ScrolledText(self.recommendations_frame, height=5, wrap="word", state="disabled")
        self.slot_conclusion_text.grid(row=7, column=0, sticky="ew", pady=4)
        self.slot_conclusion_text.grid_remove()

        from src.gui.views.learning_profile_publication import LearningProfilePublicationPanel

        self.profile_publication = LearningProfilePublicationPanel(
            self.recommendations_frame, controller_getter=lambda: self.learning_controller
        )
        self.profile_publication.grid(row=6, column=0, sticky="ew", pady=(6, 0))

        # Image display section
        self.image_frame = ttk.LabelFrame(self.preview_column, text="Images", padding=5)
        self.image_frame.grid(row=1, column=0, sticky="nsew")
        self.image_frame.columnconfigure(0, weight=1)
        self.image_frame.rowconfigure(1, weight=1)  # Thumbnail row gets weight

        # Image list (top)
        self.image_listbox = tk.Listbox(
            self.image_frame,
            height=4,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            selectbackground=TOKENS.colors.accent_primary,
            selectforeground=TOKENS.colors.text_primary,
            exportselection=False,
        )
        self.image_listbox.grid(row=0, column=0, sticky="ew")
        self.image_listbox.bind("<<ListboxSelect>>", self._on_image_selected)
        self.image_listbox.bind("<Double-Button-1>", self._on_open_selected_image)

        # Image thumbnail (bottom)
        self.image_thumbnail = ImageThumbnail(
            self.image_frame,
            allow_original=False,
            max_width=960,
            max_height=960,
            fit_to_widget=True,
        )
        self.image_thumbnail.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        self.image_thumbnail.clear()
        self.image_thumbnail.bind("<Double-Button-1>", self._on_open_selected_image)

        # Store full paths for loading images
        self._image_full_paths: list[str] = []
        self._workspace_syncing = False
        self._active_image_ref: str | None = None

        # Rating section: the image, the 1-5 choice and Save & Next come first; the detailed evidence fields
        # (context, sub-scores, notes) stay available under "Rating details".
        self.rating_frame = ttk.LabelFrame(self.side_column, text="Rating", padding=5)
        self.rating_frame.grid(row=3, column=0, sticky="nsew")
        self.rating_details_scroll = ScrollableFrame(self.rating_frame)
        self.rating_details_scroll.pack(fill="both", expand=True)
        rating_details = self.rating_details_scroll.inner
        rating_details.columnconfigure(0, weight=1)

        self.rating_context_var = tk.StringVar(value="")
        ttk.Label(
            rating_details, textvariable=self.rating_context_var, wraplength=340, justify="left"
        ).pack(fill="x")
        self.rating_status_var = tk.StringVar(value="")
        self.rating_status_label = ttk.Label(rating_details, textvariable=self.rating_status_var)
        self.rating_status_label.pack(fill="x", pady=(2, 6))

        # Rating controls
        rating_frame = ttk.Frame(rating_details)
        rating_frame.pack(fill="x")

        ttk.Label(rating_frame, text="Overall (1 poor - 5 excellent):").pack(side="left")
        self.rating_var = tk.IntVar(value=0)
        self.rating_buttons = []
        for i in range(1, 6):
            btn = ttk.Radiobutton(
                rating_frame,
                text=str(i),
                variable=self.rating_var,
                value=i,
                style="Page.TRadiobutton",
            )
            btn.pack(side="left")
            self.rating_buttons.append(btn)
        self.rating_var.trace_add("write", lambda *_: self._update_rating_status())

        self.rating_details_section = DisclosureSection(
            rating_details, title="Rating details", expanded=False
        )
        self.rating_details_section.pack(fill="x", pady=(8, 0))
        details_body = self.rating_details_section.body

        self.context_frame = ttk.LabelFrame(details_body, text="Context", padding=5)
        self.context_frame.pack(fill="x", pady=(0, 6))
        for index, (key, var) in enumerate(self._context_flag_vars.items()):
            ttk.Checkbutton(
                self.context_frame,
                text=key.replace("_", " ").title(),
                variable=var,
                command=self._rebuild_subscore_controls,
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 8), pady=2)

        self.subscore_frame = ttk.LabelFrame(details_body, text="Sub-scores", padding=5)
        self.subscore_frame.pack(fill="x", pady=(0, 6))
        self._rebuild_subscore_controls()

        # Notes
        ttk.Label(details_body, text="Notes:").pack(anchor="w")
        self.notes_text = tk.Text(
            details_body,
            height=3,
            width=40,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
        )
        self.notes_text.pack(fill="x")

        # Feedback label
        self.feedback_label = ttk.Label(rating_details, text="", wraplength=340, justify="left")
        self.feedback_label.pack(pady=(4, 0), fill="x")

        # This strip stays outside the scrollable/detail stack so persistence
        # is reachable at constrained review-pane heights.
        self.rating_action_strip = ttk.Frame(self.side_column, padding=(0, 5))
        self.rating_action_strip.grid(row=4, column=0, sticky="ew")
        self.save_next_button = ttk.Button(
            self.rating_action_strip,
            text="Save & Next",
            style=PRIMARY_BUTTON_STYLE,
            command=self._save_and_next,
        )
        self.save_next_button.pack(side="left")
        self.rate_button = ttk.Button(
            self.rating_action_strip, text="Save Rating", command=self._submit_rating
        )
        self.rate_button.pack(side="left", padx=(4, 0))
        self.discard_draft_button = ttk.Button(
            self.rating_action_strip, text="Discard Draft", command=self._discard_draft
        )
        self.discard_draft_button.pack(side="left", padx=(4, 0))
        self.save_all_drafts_button = ttk.Button(
            self.rating_action_strip, text="Save All Drafts", command=self._save_all_drafts
        )
        self.save_all_drafts_button.pack(side="left", padx=(4, 0))
        self.send_to_curation_button = ttk.Button(
            self.rating_action_strip,
            text="Send Selected to Curation",
            command=self._send_selected_to_curation,
        )
        self.send_to_curation_button.pack(side="right")

    # -- guided workflow support ------------------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """``compare``: look at results with their frozen context. ``rate``: image, rating and recommendations."""
        rate = mode == "rate"
        self._mode = "rate" if rate else "compare"
        if rate:
            self.variant_summary_list.grid_remove()
            self.compare_button.pack_forget()
            self.status_frame.grid_remove()
            self.metadata_frame.grid_remove()
            self.rating_frame.grid()
            self.rating_action_strip.grid()
            self.recommendations_frame.grid()
        else:
            self.variant_summary_list.grid()
            if not self.compare_button.winfo_ismapped():
                self.compare_button.pack(fill="x", pady=(4, 0))
            self.status_frame.grid()
            self.metadata_frame.grid()
            self.rating_frame.grid_remove()
            self.rating_action_strip.grid_remove()
            self.recommendations_frame.grid_remove()

    def show_results(self) -> None:
        """Bring the current experiment's results into view (the guide opened Compare or Rate).

        Background completion deliberately does not repaint review, so on arrival the workspace is refreshed
        and, when no variant is showing, the selected (else first completed) one is displayed. Read-only.
        """
        controller = self._get_learning_controller()
        state = getattr(controller, "learning_state", None)
        experiment = getattr(state, "current_experiment", None)
        variants = list(getattr(state, "plan", []) or [])
        showing = getattr(self, "current_variant", None)
        if showing is not None and showing in variants:
            self._refresh_experiment_workspace(experiment)
            return
        selected = getattr(state, "selected_variant", None)
        target = selected if selected in variants else None
        if target is None:
            target = next((v for v in variants if v.status == "completed" and v.image_refs), None)
        if target is None:
            self._refresh_experiment_workspace(experiment)
            return
        if state is not None:
            state.selected_variant = target
        self.display_variant_results(target, experiment)

    def save_and_next(self) -> None:
        """Public route for the guide's primary action."""
        self._save_and_next()

    def show_recommendations(self) -> None:
        self.recommendation_details.set_expanded(True)
        self.recommendations_frame.focus_set()

    @staticmethod
    def _image_available(image_ref: str) -> bool:
        try:
            return Path(str(image_ref)).is_file()
        except (OSError, ValueError):
            return False

    def _rating_progress(self, variants: list[Any] | None = None) -> RatingProgress:
        controller = self._get_learning_controller()
        plan = list(variants if variants is not None else getattr(self, "_workspace_variants", []) or [])
        if controller is None:
            return build_rating_progress(plan, is_saved=lambda _ref: False, has_draft=lambda _ref: False)
        return build_rating_progress(
            plan,
            is_saved=lambda ref: controller.get_rating_for_image(ref) is not None,
            has_draft=lambda ref: controller.get_review_draft(ref) is not None,
            exists=self._image_available,
        )

    @staticmethod
    def _unresolved_text(progress: RatingProgress) -> str:
        parts = []
        if progress.missing:
            parts.append(f"{progress.missing} unavailable")
        if progress.awaiting:
            parts.append(f"{progress.awaiting} still generating")
        if progress.uncontrolled:
            parts.append(f"{progress.uncontrolled} uncontrolled (not ratable here)")
        return " / " + " / ".join(parts) if parts else ""

    def _update_rating_status(self) -> None:
        """Say plainly whether the selected result is unrated, an unsaved choice, a draft or saved."""
        if not hasattr(self, "rating_status_var"):
            return
        image_ref = getattr(self, "_active_image_ref", None)
        variant = self.current_variant
        experiment = self.current_experiment
        if variant is not None and experiment is not None:
            images = len(getattr(variant, "image_refs", []) or [])
            position = (
                f" | image {self._image_full_paths.index(image_ref) + 1} of {images}"
                if image_ref in getattr(self, "_image_full_paths", [])
                else ""
            )
            self.rating_context_var.set(
                f"{getattr(experiment, 'variable_under_test', 'Value')} = {variant_label(variant.param_value)}"
                f"{position}"
            )
        else:
            self.rating_context_var.set("Select a result to rate.")
        controller = self._get_learning_controller()
        chosen = int(self.rating_var.get() or 0)
        saved = controller.get_rating_for_image(image_ref) if controller is not None and image_ref else None
        draft = controller.get_review_draft(image_ref) if controller is not None and image_ref else None
        if image_ref and not self._image_available(image_ref):
            text, color = "This image file is unavailable; it stays unrated.", TOKENS.colors.status_warning
        elif saved is not None and chosen == saved and not draft:
            text, color = f"Saved: {saved} of 5.", TOKENS.colors.status_success
        elif saved is not None and chosen != saved:
            text, color = (
                f"Saved as {saved}; {chosen or 'no'} selected is not saved yet.",
                TOKENS.colors.status_warning,
            )
        elif chosen:
            text, color = (
                f"Rating {chosen} selected - not saved yet. Press Save & Next.",
                TOKENS.colors.status_warning,
            )
        elif draft:
            text, color = "Unsaved draft (no overall rating).", TOKENS.colors.status_warning
        else:
            text, color = "Unrated.", TOKENS.colors.text_muted
        self.rating_status_var.set(text)
        self.rating_status_label.configure(foreground=color)

    def _stage_cards(self) -> Any:
        controller = self._get_learning_controller()
        return getattr(getattr(controller, "pipeline_controller", None), "stage_cards_panel", None)

    def _render_recommendation_summary(self, recommendations: Any) -> None:
        """Plain-language recommendation summary, evidence progress and what Apply would do (read-only)."""
        if getattr(self, "recommendation_summary_var", None) is None:
            return
        controller = self._get_learning_controller()
        mode = controller.get_automation_mode() if controller is not None else "suggest_only"
        progress_getter = getattr(controller, "get_evidence_progress", None)
        evidence = progress_getter().message() if callable(progress_getter) else ""
        rec_list = self._extract_rec_list(recommendations) if recommendations else []
        changes: list[tuple[str, Any, Any]] = []
        note = ""
        if rec_list:
            changes, note = describe_apply_changes(
                self._stage_cards(), str(getattr(recommendations, "stage", "txt2img") or "txt2img"), rec_list
            )
        summary = build_recommendation_summary(
            recommendations, mode=mode, evidence_message=evidence, changes=changes, changes_note=note
        )
        self.recommendation_summary_var.set(summary.headline)
        scope = [summary.tier_label] if summary.has_recommendations else []
        if summary.applies_to:
            scope.append(f"Applies to {summary.applies_to}")
        self.recommendation_scope_var.set(" | ".join(scope))
        change_text = "".join(f"\n{line}" for line in summary.changes)
        self.apply_note_var.set(summary.apply_note + change_text)
        self.apply_button.config(state="normal" if summary.apply_enabled else "disabled")

    def display_variant_results(
        self, variant: LearningVariant, experiment: Any | None = None
    ) -> None:
        """Display results for a completed learning variant."""
        self._capture_current_draft()
        self.current_variant = variant
        self.current_experiment = experiment
        self._refresh_experiment_workspace(experiment)

        # Update status
        self.status_label.config(text=f"Status: {variant.status.title()}")
        self.progress_label.config(text=f"Images: {variant.completed_images} completed")

        # Update metadata
        self._update_metadata(variant, experiment)

        # Clear and populate image list with rating indicators
        self.image_listbox.delete(0, tk.END)
        self._image_full_paths = []
        for i, image_ref in enumerate(variant.image_refs):
            filename = self._extract_filename(image_ref)
            rating = self._get_rating_for_image(image_ref)

            if rating:
                # Show rating indicator
                stars = "⭐" * rating
                display = f"{i + 1}. {filename} [{stars}]"
            else:
                display = f"{i + 1}. {filename}"
            if not self._image_available(image_ref):
                display += " [file unavailable]"

            self.image_listbox.insert(tk.END, display)
            self._image_full_paths.append(image_ref)

        self.feedback_label.config(text="")

        # Enable/disable rating controls based on status
        state = "normal" if variant.status == "completed" and variant.image_refs else "disabled"
        self.rate_button.config(state=state)
        self.save_next_button.config(state=state)
        self.discard_draft_button.config(state=state)
        self.send_to_curation_button.config(state=state)
        for btn in self.rating_buttons:
            btn.config(state=state)
        self.notes_text.config(state=tk.NORMAL if state == "normal" else tk.DISABLED)
        for child in self.context_frame.winfo_children():
            try:
                child.configure(state=state)
            except Exception:
                continue
        for child in self.subscore_frame.winfo_children():
            try:
                child.configure(state=state)
            except Exception:
                continue

        # Preserve the review target across refreshes while still making the
        # current image available for deterministic rate-and-next navigation.
        selected_image_index = int(
            getattr(getattr(self, "learning_controller", None), "learning_state", None)
            and getattr(
                getattr(self.learning_controller, "learning_state", None),
                "selected_image_index",
                0,
            )
            or 0
        )
        if self._image_full_paths:
            selected_image_index = max(0, min(selected_image_index, len(self._image_full_paths) - 1))
            self.image_listbox.selection_set(selected_image_index)
            self.image_listbox.activate(selected_image_index)
            self._on_image_selected(None)

    def _refresh_experiment_workspace(self, experiment: Any | None = None) -> None:
        controller = self._get_learning_controller()
        state = getattr(controller, "learning_state", None) if controller is not None else None
        variants = list(getattr(state, "plan", []) or [])
        if experiment is None:
            experiment = getattr(state, "current_experiment", None)
        self._workspace_variants = variants
        projection = build_review_projection(variants, self._get_rating_for_image)
        self._review_projection = projection
        if not hasattr(self, "variant_summary_list"):
            return
        self.variant_summary_list.delete(0, tk.END)
        progress = self._rating_progress(variants)
        counts = {"saved": progress.saved, "draft": progress.drafts, "unrated": progress.unrated}
        for summary in projection.variants:
            label = (
                f"{getattr(experiment, 'variable_under_test', 'Value')}="
                f"{variant_label(summary.value)} | {summary.status.title()} | "
                f"{summary.rated_count}/{summary.sample_count} rated"
            )
            self.variant_summary_list.insert(tk.END, label)
        state_label = (
            "complete"
            if projection.review_complete
            else ("ready to review" if projection.execution_complete else "in progress")
        )
        name = str(getattr(experiment, "name", "experiment") or "experiment")
        progress_getter = getattr(controller, "get_evidence_progress", None)
        progress_text = f" | {progress_getter().message()}" if callable(progress_getter) else ""
        self.workspace_status_var.set(
            f"{name} | {getattr(experiment, 'variable_under_test', 'value')} | "
            f"{counts['saved']} saved / {counts['draft']} draft / {counts['unrated']} unrated"
            f"{self._unresolved_text(progress)} | "
            f"Experiment {state_label}{progress_text}"
        )
        self._update_rating_status()
        selected = getattr(state, "selected_variant", None) if state is not None else None
        if selected in variants:
            self._workspace_syncing = True
            try:
                self.variant_summary_list.selection_clear(0, tk.END)
                self.variant_summary_list.selection_set(variants.index(selected))
                self.variant_summary_list.see(variants.index(selected))
            finally:
                self._workspace_syncing = False

    def _on_workspace_variant_selected(self, _event: tk.Event | None = None) -> None:
        if getattr(self, "_workspace_syncing", False):
            return
        selection = self.variant_summary_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if index < 0 or index >= len(getattr(self, "_workspace_variants", [])):
            return
        variant = self._workspace_variants[index]
        controller = self._get_learning_controller()
        if controller is not None and hasattr(controller, "on_variant_selected"):
            controller.on_variant_selected(index)
        else:
            self.display_variant_results(variant, self.current_experiment)

    def _on_next_unrated(self, position: tuple[str, str | None] | None = None) -> None:
        """Select the next unrated sample after the current one, in stable variant/sample identity order.

        Results whose file is unavailable cannot be reviewed; they are skipped here but stay counted as
        unavailable, never as rated.
        """
        variants = list(getattr(self, "_workspace_variants", []) or [])
        controller = self._get_learning_controller()
        projection = build_review_projection(variants, self._get_rating_for_image)
        if position is None:
            position = (
                str(getattr(self.current_variant, "variant_id", "") or ""),
                self._selected_image_ref(),
            )
        sample = projection.next_unrated_after(
            position[0], position[1], reviewable=lambda item: self._image_available(item.image_ref)
        )
        if sample is not None:
            variant = variants[sample.variant_index]
            if controller is not None:
                state = getattr(controller, "learning_state", None)
                if state is not None:
                    state.selected_variant = variant
                    state.selected_image_index = sample.image_index
            self.display_variant_results(variant, self.current_experiment)
            return
        progress = self._rating_progress(variants)
        if progress.to_rate or progress.missing or progress.awaiting:
            self.feedback_label.config(
                text=f"Nothing else can be rated right now: {progress.describe()}.", foreground="orange"
            )
        else:
            self.feedback_label.config(text="All completed samples are rated", foreground="green")

    def _on_compare_selected(self) -> None:
        """Open a bounded side-by-side comparison for selected variant samples."""
        selected = self.variant_summary_list.curselection()
        variants = list(getattr(self, "_workspace_variants", []) or [])
        chosen = [variants[index] for index in selected if 0 <= index < len(variants)]
        if not chosen and self.current_variant is not None:
            chosen = [self.current_variant]
        image_paths = [str(ref) for variant in chosen for ref in (getattr(variant, "image_refs", []) or [])]
        image_paths = image_paths[:4]
        if not image_paths:
            self.feedback_label.config(text="No completed samples to compare", foreground="red")
            return
        window = tk.Toplevel(self)
        window.title("Learning Experiment Comparison")
        window.geometry("1100x700")
        window.minsize(520, 360)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        columns = 2 if len(image_paths) > 1 else 1
        for column in range(columns):
            window.columnconfigure(column, weight=1)
        for row in range((len(image_paths) + columns - 1) // columns):
            window.rowconfigure(row, weight=1)
        for column, image_path in enumerate(image_paths):
            frame = ttk.Frame(window, padding=4)
            row, grid_column = divmod(column, columns)
            frame.grid(row=row, column=grid_column, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)
            try:
                ttk.Label(frame, text=Path(image_path).name).grid(row=0, column=0, sticky="w")
                thumbnail = ImageThumbnail(
                    frame,
                    allow_original=False,
                    max_width=1600,
                    max_height=1600,
                    fit_to_widget=True,
                )
                thumbnail.grid(row=1, column=0, sticky="nsew")
                thumbnail.set_image_reference(image_path, subject={
                    "name": image_path,
                    "prompt": visibility_prompt(self.current_experiment),
                })
            except Exception as exc:
                ttk.Label(frame, text=f"Unable to load\n{Path(image_path).name}\n{exc}").grid(
                    row=1, column=0, sticky="nsew"
                )

    def _update_metadata(self, variant: LearningVariant, experiment: Any | None) -> None:
        """Update the metadata display."""
        self.metadata_text.config(state="normal")
        self.metadata_text.delete(1.0, tk.END)

        if experiment:
            metadata = f"Experiment: {experiment.name}\n"
            metadata += f"Variable: {experiment.variable_under_test}\n"
            metadata += f"Value: {variant_label(variant.param_value)}\n"
            metadata += f"Stage: {getattr(experiment, 'stage', 'txt2img')}\n"
            metadata += f"Images: {variant.completed_images}/{variant.planned_images}\n"
            self.metadata_text.insert(tk.END, metadata)
            study = (getattr(experiment, "metadata", {}) or {}).get("study_type")
            if study in DISPLAYED_STUDIES:
                from src.learning.controlled_study_display import candidate_caption
                from src.learning.resource_access import resolve_app_state
                from src.state.content_visibility import (
                    ContentVisibilityMode,
                    normalize_content_visibility_mode,
                )

                state = resolve_app_state(self._get_learning_controller())
                visible = normalize_content_visibility_mode(getattr(state, "content_visibility_mode", None)) is ContentVisibilityMode.NSFW
                self.metadata_text.insert(tk.END, candidate_caption(study, experiment, variant.param_value, visible=visible) + "\n")
        else:
            self.metadata_text.insert(tk.END, "No experiment data available")

        self.metadata_text.config(state="disabled")

    def _on_image_selected(self, event: tk.Event[tk.Listbox]) -> None:
        """Handle image selection from the list."""
        self._capture_current_draft()
        selection = self.image_listbox.curselection()
        if selection and hasattr(self, "_image_full_paths"):
            index = selection[0]
            if 0 <= index < len(self._image_full_paths):
                controller = self._get_learning_controller()
                state = getattr(controller, "learning_state", None) if controller else None
                if state is not None:
                    state.selected_image_index = int(index)
                full_path = self._image_full_paths[index]
                # Load image into thumbnail
                self.image_thumbnail.load_image(full_path)
                self._active_image_ref = full_path
                self._load_review_state(full_path)
        else:
            self.image_thumbnail.clear()
            self._active_image_ref = None

    def _on_open_selected_image(self, _event: tk.Event | None = None) -> None:
        """Open the currently selected image in a resizable viewer."""
        image_path = self._get_selected_image_path()
        if image_path:
            self._open_image_viewer(image_path)

    def _get_selected_image_path(self) -> str | None:
        selection = self.image_listbox.curselection()
        if not selection or not hasattr(self, "_image_full_paths"):
            return None
        index = selection[0]
        if index < 0 or index >= len(self._image_full_paths):
            return None
        return self._image_full_paths[index]

    @staticmethod
    def _compute_viewer_window_size(
        image_width: int,
        image_height: int,
        screen_width: int,
        screen_height: int,
    ) -> tuple[int, int]:
        max_width = max(640, int(screen_width * 0.9))
        max_height = max(480, int(screen_height * 0.9))
        desired_width = min(max_width, image_width + 40)
        desired_height = min(max_height, image_height + 80)
        return max(480, desired_width), max(360, desired_height)

    def _open_image_viewer(self, image_path: str) -> None:
        self.image_thumbnail.set_image_reference(image_path)
        self.image_thumbnail.detach()

    def _current_visibility_subject(self) -> dict[str, str]:
        return {
            "name": self._get_selected_image_path() or "",
            "prompt": visibility_prompt(self.current_experiment),
        }

    def on_content_visibility_mode_changed(self, _mode: Any = None) -> None:
        if self.current_variant is not None:
            self._update_metadata(self.current_variant, self.current_experiment)

    def set_prompt_slot_conclusion(self, result: dict[str, Any]) -> None:
        self.slot_conclusion_text.configure(state="normal")
        self.slot_conclusion_text.delete("1.0", tk.END)
        if result.get("study_type") in DISPLAYED_STUDIES:
            self.slot_conclusion_text.grid()
            named = result["study_type"] != "prompt_slot"
            from src.learning.controlled_study_display import candidate_label_text
            from src.learning.resource_access import resolve_app_state
            from src.state.content_visibility import (
                ContentVisibilityMode,
                normalize_content_visibility_mode,
            )

            state = resolve_app_state(self._get_learning_controller())
            visible = normalize_content_visibility_mode(getattr(state, "content_visibility_mode", None)) is ContentVisibilityMode.NSFW
            self.slot_conclusion_text.insert("1.0", result["message"] + "\n" + "\n".join(
                f"Candidate {row['value']}"
                + (f" ({candidate_label_text(result['study_type'], self.current_experiment, row['value'], visible=visible)})" if named else "")
                + f": {row['sample_count']} completed, {row['saved_count']} valid rated; "
                f"mean {row['average_overall']}, variability {row['rating_stddev']}; "
                + ("controlled" if row["controlled"] else "uncontrolled/unverified") for row in result["values"]))
        else:
            self.slot_conclusion_text.grid_remove()
        self.slot_conclusion_text.configure(state="disabled")


    def _extract_filename(self, path: str) -> str:
        """Extract filename from full path."""
        from pathlib import Path

        return Path(path).name

    def _get_rating_for_image(self, image_path: str) -> int | None:
        """Get rating for an image from the controller."""
        try:
            controller = self._get_learning_controller()
            if controller and hasattr(controller, "get_rating_for_image"):
                return controller.get_rating_for_image(image_path)
        except Exception:
            pass
        return None

    def _capture_current_draft(self) -> None:
        """Checkpoint editable review controls before changing the current artifact."""
        image_ref = self._active_image_ref
        controller = self._get_learning_controller()
        if not image_ref or controller is None or not hasattr(controller, "save_review_draft"):
            return
        rating = int(self.rating_var.get() or 0)
        notes = self.notes_text.get("1.0", tk.END).strip()
        details = self._build_rating_details(rating)
        if self._matches_saved_rating(controller, image_ref, rating, notes, details):
            return
        # Untouched controls (the default context flags only) are not a draft: merely viewing an image must not
        # leave one behind.
        touched = details["context_flags"] != {key: key == "people" for key in details["context_flags"]}
        if rating or notes or details["subscores"] or touched:
            controller.save_review_draft(
                image_ref,
                {
                    "overall_rating": rating,
                    "notes": notes,
                    "context_flags": details["context_flags"],
                    "subscores": details["subscores"],
                    "dirty": True,
                },
            )
            self._commit_draft_on_navigation(controller, image_ref)

    @staticmethod
    def _matches_saved_rating(
        controller: Any, image_ref: str, rating: int, notes: str, details: dict[str, Any]
    ) -> bool:
        """True when the controls still show exactly the saved rating, so there is nothing to draft."""
        getter = getattr(controller, "get_rating_details_for_image", None)
        saved = getter(image_ref) if callable(getter) else None
        if not saved:
            return False
        return (
            int(saved.get("overall_rating") or 0) == rating
            and str(saved.get("notes") or "") == notes
            and dict(saved.get("subscores") or {}) == details["subscores"]
            and dict(saved.get("context_flags") or {}) == details["context_flags"]
        )

    def _commit_draft_on_navigation(self, controller: Any, image_ref: str) -> None:
        """Leaving an image saves its rated draft; one that cannot be saved stays a draft."""
        committer = getattr(controller, "commit_review_draft", None)
        if not callable(committer):
            return
        try:
            saved = committer(image_ref)
        except (OSError, RuntimeError, ValueError):
            return  # not storable now; it stays a draft and Save All Drafts reports it
        if saved:
            self.feedback_label.config(text="Draft saved as a rating", foreground="green")
            self._refresh_experiment_workspace(self.current_experiment)

    def _load_review_state(self, image_ref: str) -> None:
        controller = self._get_learning_controller()
        draft = (
            controller.get_review_draft(image_ref)
            if controller is not None and hasattr(controller, "get_review_draft")
            else None
        )
        saved = (
            controller.get_rating_details_for_image(image_ref)
            if controller is not None and hasattr(controller, "get_rating_details_for_image")
            else None
        )
        payload = dict(draft or saved or {})
        self.rating_var.set(int(payload.get("overall_rating", 0) or 0))
        context = dict(payload.get("context_flags") or {})
        for key, var in self._context_flag_vars.items():
            var.set(bool(context.get(key, key == "people" and not payload)))
        self._rebuild_subscore_controls()
        for key, value in dict(payload.get("subscores") or {}).items():
            if key in self._subscore_vars:
                self._subscore_vars[key].set(int(value or 0))
        self.notes_text.config(state=tk.NORMAL)
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", str(payload.get("notes") or ""))
        if draft:
            self.feedback_label.config(text="Unsaved draft", foreground="orange")
        self._update_rating_status()

    def _selected_image_ref(self) -> str | None:
        selection = self.image_listbox.curselection()
        if not selection or not hasattr(self, "_image_full_paths"):
            return None
        index = int(selection[0])
        if not 0 <= index < len(self._image_full_paths):
            return None
        return str(self._image_full_paths[index])

    def _submit_rating(self) -> bool:
        """Persist the selected artifact's rating and its complete detail payload."""
        if not self.current_variant:
            return False

        rating = self.rating_var.get()
        notes = self.notes_text.get(1.0, tk.END).strip()
        details = self._build_rating_details(rating)

        if rating == 0:
            self.feedback_label.config(text="Please select a rating", foreground="red")
            return False

        # Get selected image
        image_ref = self._selected_image_ref()
        if not image_ref:
            self.feedback_label.config(text="Please select an image to rate", foreground="red")
            return False

        # Check if already rated
        existing_rating = self._get_rating_for_image(image_ref)
        if existing_rating is not None:
            controller = self._get_learning_controller()
            if controller is not None and self._matches_saved_rating(controller, image_ref, rating, notes, details):
                # Already stored exactly as shown: appending again would only duplicate the record.
                self.feedback_label.config(text="Already saved - no change.", foreground="green")
                self._update_rating_status()
                return True
            # Ask for confirmation to override
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Override Rating",
                f"This image already has a rating of {existing_rating}.\nOverride with new rating?",
            ):
                return False

        # Call controller to record rating
        controller = self._get_learning_controller()
        if controller:
            if hasattr(controller, "record_rating"):
                try:
                    controller.record_rating(image_ref, rating, notes, details)
                    self.feedback_label.config(
                        text="Rating saved successfully!", foreground="green"
                    )
                    # Refresh display to show new rating indicator
                    if self.current_variant and self.current_experiment:
                        self._active_image_ref = None
                        self.display_variant_results(self.current_variant, self.current_experiment)
                    return True
                except Exception as e:
                    self.feedback_label.config(text=f"Error saving rating: {e}", foreground="red")
            else:
                self.feedback_label.config(text="Rating system not available", foreground="red")
        else:
            self.feedback_label.config(text="Controller not available", foreground="red")
        return False

    def _save_and_next(self) -> None:
        # Remember where we are before a successful save refreshes the lists; advance only after it succeeded.
        position = (
            str(getattr(self.current_variant, "variant_id", "") or ""),
            self._selected_image_ref(),
        )
        if self._submit_rating():
            self._on_next_unrated(position)

    def _save_all_drafts(self) -> None:
        """Save every rated draft of this experiment as a rating (images already rated are left alone)."""
        controller = self._get_learning_controller()
        committer = getattr(controller, "commit_review_drafts", None)
        if not callable(committer):
            self.feedback_label.config(text="Rating system not available", foreground="red")
            return
        self._capture_current_draft()
        counts_getter = getattr(controller, "get_review_counts", None)
        drafts = int(counts_getter().get("draft", 0)) if callable(counts_getter) else 0
        if drafts:
            from tkinter import messagebox

            if not messagebox.askyesno(
                "Save All Drafts",
                f"Save {drafts} draft(s) as ratings?\n\nDrafts without an overall rating, and images that "
                "already have a saved rating, are left as drafts.",
            ):
                return
        try:
            summary = committer()
        except (OSError, RuntimeError, ValueError) as exc:
            self.feedback_label.config(text=f"Error saving drafts: {exc}", foreground="red")
            return
        self._active_image_ref = None
        if self.current_variant and self.current_experiment:
            self.display_variant_results(self.current_variant, self.current_experiment)
        # After the redisplay, which resets the label.
        self.feedback_label.config(
            text=summary.describe(), foreground="green" if summary.committed and not summary.failed else "orange"
        )

    def _discard_draft(self) -> None:
        image_ref = self._selected_image_ref()
        controller = self._get_learning_controller()
        if not image_ref or controller is None:
            return
        discard = getattr(controller, "discard_review_draft", None)
        if callable(discard):
            discard(image_ref)
        self._load_review_state(image_ref)
        self.feedback_label.config(text="Draft discarded", foreground="green")
        self._refresh_experiment_workspace(self.current_experiment)

    def _send_selected_to_curation(self) -> None:
        image_ref = self._selected_image_ref()
        controller = self._get_learning_controller()
        sender = getattr(controller, "send_controlled_artifacts_to_staged_curation", None)
        if not image_ref or not callable(sender):
            return
        group_id = sender([image_ref])
        if group_id:
            self.feedback_label.config(
                text=f"Sent to Staged Curation ({group_id[-6:]})", foreground="green"
            )
        else:
            self.feedback_label.config(text="Unable to create curation workset", foreground="red")

    def _rebuild_subscore_controls(self) -> None:
        for child in self.subscore_frame.winfo_children():
            child.destroy()
        self._subscore_vars = {}
        categories = get_active_categories(self._current_context_flags())
        for row, category in enumerate(categories):
            ttk.Label(self.subscore_frame, text=f"{category.label}:").grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )
            var = tk.IntVar(value=0)
            self._subscore_vars[category.key] = var
            for idx in range(1, 6):
                ttk.Radiobutton(
                    self.subscore_frame,
                    text=str(idx),
                    variable=var,
                    value=idx,
                ).grid(row=row, column=idx, sticky="w", padx=2)

    def _current_context_flags(self) -> dict[str, bool]:
        vars_map = getattr(self, "_context_flag_vars", {}) or {}
        return {key: bool(var.get()) for key, var in vars_map.items()}

    def _build_rating_details(self, overall_rating: int) -> dict[str, Any]:
        subscores = {
            key: int(var.get())
            for key, var in (getattr(self, "_subscore_vars", {}) or {}).items()
            if int(var.get() or 0) > 0
        }
        return {
            "context_flags": self._current_context_flags(),
            "subscores": subscores,
            "blended_rating": blend_rating(overall_rating, subscores),
        }

    def update_recommendations(self, recommendations: Any) -> None:
        """Update the recommendations display with new data."""
        self._write_recommendation_text(recommendations)
        self._render_recommendation_summary(recommendations)

    def _write_recommendation_text(self, recommendations: Any) -> None:
        self.recommendations_text.config(state="normal")
        self.recommendations_text.delete(1.0, tk.END)

        if not recommendations:
            self.recommendations_text.insert(tk.END, "No recommendations available yet.\n")
            self.recommendations_text.insert(
                tk.END, "\nRate more images to get personalized suggestions."
            )
            self.recommendations_text.config(state="disabled")
            return

        # Format recommendations for display
        lines = []

        # Check if it's a RecommendationSet or list of recommendations
        if hasattr(recommendations, "recommendations"):
            rec_list = recommendations.recommendations
        elif isinstance(recommendations, list):
            rec_list = recommendations
        else:
            rec_list = []

        if not rec_list:
            self.recommendations_text.insert(tk.END, "Insufficient data for recommendations.\n")
            self.recommendations_text.insert(
                tk.END, "\nRate at least 3 images to generate suggestions."
            )
            self.recommendations_text.config(state="disabled")
            return

        lines.append("Recommended Settings\n")
        lines.append("-" * 30 + "\n\n")

        # PR-044: surface evidence tier and automation eligibility
        evidence_tier = getattr(recommendations, "evidence_tier", None)
        if evidence_tier and evidence_tier != "experiment_strong":
            tier_labels = {
                "experiment_sparse_plus_review": "Evidence: sparse experiment + review (manual-only)",
                "review_only": "Evidence: review feedback only (manual-only)",
                "no_evidence": "Evidence: none",
            }
            tier_label = tier_labels.get(evidence_tier, f"Evidence tier: {evidence_tier}")
            lines.append(f"[{tier_label}]\n\n")
        elif evidence_tier == "experiment_strong":
            lines.append("[Evidence: experiment (auto-eligible)]\n\n")

        for rec in rec_list[:5]:
            # Handle both dataclass and dict formats
            if hasattr(rec, "parameter_name"):
                param = rec.parameter_name
                value = rec.recommended_value
                confidence = rec.confidence_score
                samples = rec.sample_count
                mean_rating = rec.mean_rating
                rationale = getattr(rec, "confidence_rationale", "")
                context = getattr(rec, "context_key", "")
            elif isinstance(rec, dict):
                param = rec.get("parameter", "Unknown")
                value = rec.get("value", "?")
                confidence = rec.get("confidence", 0)
                samples = rec.get("samples", 0)
                mean_rating = rec.get("mean_rating", 0)
                rationale = rec.get("rationale", "")
                context = rec.get("context", "")
            else:
                continue

            # Format confidence as percentage
            conf_pct = f"{confidence * 100:.0f}%"

            # Format mean rating as stars
            stars = "*" * int(round(mean_rating))

            lines.append(f"{param}: {value}\n")
            lines.append(f"  Avg Rating: {stars or '-'} ({mean_rating:.1f})\n")
            lines.append(f"  Confidence: {conf_pct} ({samples} samples)\n")
            because_parts = []
            if rationale:
                because_parts.append(str(rationale))
            if context:
                because_parts.append(f"context={context}")
            if because_parts:
                lines.append(f"  Because: {'; '.join(because_parts)}\n")
            lines.append("\n")

        self.recommendations_text.insert(tk.END, "".join(lines))
        self.recommendations_text.config(state="disabled")

        # suggest_only is deliberately display-only.  Do not expose an
        # enabled interaction that the controller must silently reject.
        controller = self._get_learning_controller()
        mode = (
            controller.get_automation_mode()
            if controller is not None and hasattr(controller, "get_automation_mode")
            else "suggest_only"
        )
        if rec_list and mode != "suggest_only":
            self.apply_button.config(state="normal")
        else:
            self.apply_button.config(state="disabled")

    def _on_apply_recommendations(self) -> None:
        """Handle apply recommendations button click."""
        # Get controller
        controller = self._get_learning_controller()
        if not controller:
            return

        # Get current recommendations
        recs = getattr(controller, "get_recommendations_for_current_prompt", None)
        if not callable(recs):
            return

        recommendations = recs()
        if not recommendations:
            return

        # Show confirmation dialog
        if self._confirm_apply(recommendations):
            apply_fn = getattr(controller, "apply_recommendations_to_pipeline", None)
            if callable(apply_fn):
                success = apply_fn(recommendations)
                if success:
                    from tkinter import messagebox

                    messagebox.showinfo("Applied", "Recommendations applied to Pipeline settings.")
                else:
                    self.feedback_label.config(
                        text=(
                            "Nothing was changed. Apply is refused when the current model or stage does not match "
                            "the evidence, a setting has no matching control, or the mode does not allow it."
                        ),
                        foreground="red",
                    )

    def _confirm_apply(self, recommendations: Any) -> bool:
        """Show confirmation dialog with proposed changes."""
        from tkinter import messagebox

        # Format changes for display
        changes = []
        rec_list = self._extract_rec_list(recommendations)

        for rec in rec_list:
            if hasattr(rec, "parameter_name"):
                param = rec.parameter_name
                value = rec.recommended_value
            elif isinstance(rec, dict):
                param = rec.get("parameter", "?")
                value = rec.get("value", "?")
            else:
                continue

            changes.append((param, value))

        if not changes:
            return False

        current, _reason = describe_apply_changes(
            self._stage_cards(), str(getattr(recommendations, "stage", "txt2img") or "txt2img"), rec_list
        )
        old_values = {name: old for name, old, _new in current}
        lines = [
            f"  • {param}: {old_values[param]} → {value}" if param in old_values else f"  • {param} → {value}"
            for param, value in changes
        ]
        message = (
            "Apply these settings to the current Pipeline settings?\n\n"
            + "\n".join(lines)
            + "\n\nPast jobs, prompts and results are not changed."
        )
        return messagebox.askyesno("Confirm Apply", message)

    def _extract_rec_list(self, recommendations: Any) -> list:
        """Extract list of recommendations from various formats."""
        if hasattr(recommendations, "recommendations"):
            return recommendations.recommendations
        elif isinstance(recommendations, list):
            return recommendations
        return []

    def _get_learning_controller(self) -> Any:
        """Get the learning controller from parent chain."""
        try:
            controller = getattr(self, "learning_controller", None)
            if controller is not None:
                return controller
            if hasattr(self.master, "learning_controller"):
                return self.master.learning_controller
            parent = getattr(self.master, "master", None)
            if parent is not None and hasattr(parent, "learning_controller"):
                return parent.learning_controller
        except Exception:
            pass
        return None

    def _on_view_analytics(self) -> None:
        """Open analytics window."""
        controller = self._get_learning_controller()
        if not controller:
            return

        # Create analytics window
        analytics_window = tk.Toplevel(self.master)
        analytics_window.title("Learning Analytics")
        analytics_window.geometry("800x600")

        from src.gui.views.learning_analytics_panel import LearningAnalyticsPanel

        analytics_panel = LearningAnalyticsPanel(analytics_window)
        analytics_panel.pack(fill="both", expand=True)

        # Store reference for refresh
        controller._analytics_panel = analytics_panel

        # Pass controller to panel for export functions
        analytics_window.learning_controller = controller

        # Load initial data
        controller.refresh_analytics()
