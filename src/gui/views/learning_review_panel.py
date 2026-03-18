# Subsystem: Learning
# Role: Shows learning run results and feedback controls.

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.gui.learning_state import LearningVariant
from src.gui.ui_tokens import TOKENS
from src.learning.rating_schema import blend_rating, get_active_categories

try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


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
        self.preview_column.rowconfigure(0, weight=1)

        # Right: status / metadata / recommendations / rating stack
        self.side_column = ttk.Frame(self)
        self.side_column.grid(row=0, column=1, sticky="nsew", padx=(3, 5), pady=5)
        self.side_column.columnconfigure(0, weight=1)
        self.side_column.rowconfigure(0, weight=0)
        self.side_column.rowconfigure(1, weight=0)
        self.side_column.rowconfigure(2, weight=0)
        self.side_column.rowconfigure(3, weight=1)

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

        self.metadata_text = tk.Text(
            self.metadata_frame,
            height=4,
            width=32,
            state="disabled",
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
        )
        self.metadata_text.pack(fill="x")

        # Recommendations section
        self.recommendations_frame = ttk.LabelFrame(self.side_column, text="Recommended Settings", padding=5)
        self.recommendations_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self.recommendations_text = tk.Text(
            self.recommendations_frame,
            height=4,
            width=32,
            state="disabled",
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
        )
        self.recommendations_text.pack(fill="x")

        # Apply recommendations button
        button_frame = ttk.Frame(self.recommendations_frame)
        button_frame.pack(pady=(5, 0), fill="x")

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

        # Image display section
        self.image_frame = ttk.LabelFrame(self.preview_column, text="Images", padding=5)
        self.image_frame.grid(row=0, column=0, sticky="nsew")
        self.image_frame.columnconfigure(0, weight=1)
        self.image_frame.rowconfigure(1, weight=1)  # Thumbnail row gets weight

        # Import ImageThumbnail widget
        from src.gui.widgets.image_thumbnail import ImageThumbnail

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
            max_width=960,
            max_height=960,
        )
        self.image_thumbnail.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        self.image_thumbnail.clear()
        self.image_thumbnail.bind("<Double-Button-1>", self._on_open_selected_image)

        # Store full paths for loading images
        self._image_full_paths: list[str] = []
        self._viewer_window: tk.Toplevel | None = None
        self._viewer_canvas: tk.Canvas | None = None
        self._viewer_photo: Any = None
        self._viewer_image_id: int | None = None

        # Rating section
        self.rating_frame = ttk.LabelFrame(self.side_column, text="Rating", padding=5)
        self.rating_frame.grid(row=3, column=0, sticky="nsew")

        # Rating controls
        rating_frame = ttk.Frame(self.rating_frame)
        rating_frame.pack(fill="x")

        ttk.Label(rating_frame, text="Rating:").pack(side="left")
        self.rating_var = tk.IntVar(value=0)
        self.rating_buttons = []
        for i in range(1, 6):
            btn = ttk.Radiobutton(rating_frame, text=str(i), variable=self.rating_var, value=i)
            btn.pack(side="left")
            self.rating_buttons.append(btn)

        self.context_frame = ttk.LabelFrame(self.rating_frame, text="Context", padding=5)
        self.context_frame.pack(fill="x", pady=(8, 6))
        for index, (key, var) in enumerate(self._context_flag_vars.items()):
            ttk.Checkbutton(
                self.context_frame,
                text=key.replace("_", " ").title(),
                variable=var,
                command=self._rebuild_subscore_controls,
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 8), pady=2)

        self.subscore_frame = ttk.LabelFrame(self.rating_frame, text="Sub-scores", padding=5)
        self.subscore_frame.pack(fill="x", pady=(0, 6))
        self._rebuild_subscore_controls()

        # Notes
        ttk.Label(self.rating_frame, text="Notes:").pack(anchor="w")
        self.notes_text = tk.Text(
            self.rating_frame,
            height=3,
            width=40,
            bg=TOKENS.colors.surface_secondary,
            fg=TOKENS.colors.text_primary,
            insertbackground=TOKENS.colors.text_primary,
        )
        self.notes_text.pack(fill="x")

        # Rate button
        self.rate_button = ttk.Button(
            self.rating_frame, text="Submit Rating", command=self._submit_rating
        )
        self.rate_button.pack(pady=(5, 0))

        # Feedback label
        self.feedback_label = ttk.Label(self.rating_frame, text="")
        self.feedback_label.pack(pady=(2, 0))

    def display_variant_results(
        self, variant: LearningVariant, experiment: Any | None = None
    ) -> None:
        """Display results for a completed learning variant."""
        self.current_variant = variant
        self.current_experiment = experiment

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
                display = f"{i+1}. {filename} [{stars}]"
            else:
                display = f"{i+1}. {filename}"

            self.image_listbox.insert(tk.END, display)
            self._image_full_paths.append(image_ref)

        # Reset rating form
        self.rating_var.set(0)
        self.notes_text.delete(1.0, tk.END)
        self.feedback_label.config(text="")
        for var in self._subscore_vars.values():
            var.set(0)

        # Enable/disable rating controls based on status
        state = "normal" if variant.status == "completed" and variant.image_refs else "disabled"
        self.rate_button.config(state=state)
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

    def _update_metadata(self, variant: LearningVariant, experiment: Any | None) -> None:
        """Update the metadata display."""
        self.metadata_text.config(state="normal")
        self.metadata_text.delete(1.0, tk.END)

        if experiment:
            metadata = f"Experiment: {experiment.name}\n"
            metadata += f"Variable: {experiment.variable_under_test}\n"
            metadata += f"Value: {variant.param_value}\n"
            metadata += f"Stage: {getattr(experiment, 'stage', 'txt2img')}\n"
            metadata += f"Images: {variant.completed_images}/{variant.planned_images}\n"
            self.metadata_text.insert(tk.END, metadata)
        else:
            self.metadata_text.insert(tk.END, "No experiment data available")

        self.metadata_text.config(state="disabled")

    def _on_image_selected(self, event: tk.Event[tk.Listbox]) -> None:
        """Handle image selection from the list."""
        selection = self.image_listbox.curselection()
        if selection and hasattr(self, "_image_full_paths"):
            index = selection[0]
            if 0 <= index < len(self._image_full_paths):
                full_path = self._image_full_paths[index]
                # Load image into thumbnail
                self.image_thumbnail.load_image(full_path)
        else:
            self.image_thumbnail.clear()

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
        if not PIL_AVAILABLE:
            self.feedback_label.config(
                text="Full image viewer requires Pillow",
                foreground="red",
            )
            return

        path_obj = Path(image_path)
        if not path_obj.exists():
            self.feedback_label.config(
                text=f"Image not found: {path_obj.name}",
                foreground="red",
            )
            return

        try:
            with Image.open(path_obj) as image:
                image = image.convert("RGBA")
                image_width, image_height = image.size
                photo = ImageTk.PhotoImage(image)
        except Exception as exc:
            self.feedback_label.config(
                text=f"Failed to open image: {exc}",
                foreground="red",
            )
            return

        if self._viewer_window and self._viewer_window.winfo_exists():
            viewer = self._viewer_window
            for child in viewer.winfo_children():
                child.destroy()
        else:
            viewer = tk.Toplevel(self)
            self._viewer_window = viewer
            viewer.bind("<Destroy>", self._on_viewer_destroyed, add="+")

        viewer.title(f"Image Viewer - {path_obj.name}")
        viewer.transient(self.winfo_toplevel())
        viewer.resizable(True, True)

        frame = ttk.Frame(viewer, padding=6)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            frame,
            bg=TOKENS.colors.surface_secondary,
            highlightthickness=0,
        )
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self._viewer_canvas = canvas
        self._viewer_photo = photo
        self._viewer_image_id = canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, image_width, image_height))

        width, height = self._compute_viewer_window_size(
            image_width,
            image_height,
            viewer.winfo_screenwidth(),
            viewer.winfo_screenheight(),
        )
        viewer.geometry(f"{width}x{height}")

        status = ttk.Label(
            frame,
            text=f"{image_width} x {image_height}  |  Double-click another image to reuse this viewer",
        )
        status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        viewer.lift()
        viewer.focus_force()

    def _on_viewer_destroyed(self, _event: tk.Event | None = None) -> None:
        self._viewer_window = None
        self._viewer_canvas = None
        self._viewer_photo = None
        self._viewer_image_id = None

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

    def _submit_rating(self) -> None:
        """Submit the rating for the selected image."""
        if not self.current_variant:
            return

        rating = self.rating_var.get()
        notes = self.notes_text.get(1.0, tk.END).strip()
        details = self._build_rating_details(rating)

        if rating == 0:
            self.feedback_label.config(text="Please select a rating", foreground="red")
            return

        # Get selected image
        selection = self.image_listbox.curselection()
        if not selection:
            self.feedback_label.config(text="Please select an image to rate", foreground="red")
            return

        image_index = selection[0]
        if not hasattr(self, "_image_full_paths") or image_index >= len(self._image_full_paths):
            self.feedback_label.config(text="Invalid image selection", foreground="red")
            return

        image_ref = self._image_full_paths[image_index]

        # Check if already rated
        existing_rating = self._get_rating_for_image(image_ref)
        if existing_rating is not None:
            # Ask for confirmation to override
            from tkinter import messagebox
            if not messagebox.askyesno(
                "Override Rating",
                f"This image already has a rating of {existing_rating}.\nOverride with new rating?",
            ):
                return

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
                        self.display_variant_results(self.current_variant, self.current_experiment)
                    # Clear form
                    self.rating_var.set(0)
                    self.notes_text.delete(1.0, tk.END)
                except Exception as e:
                    self.feedback_label.config(text=f"Error saving rating: {e}", foreground="red")
            else:
                self.feedback_label.config(text="Rating system not available", foreground="red")
        else:
            self.feedback_label.config(text="Controller not available", foreground="red")

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
        self.recommendations_text.config(state="normal")
        self.recommendations_text.delete(1.0, tk.END)
        
        if not recommendations:
            self.recommendations_text.insert(tk.END, "No recommendations available yet.\n")
            self.recommendations_text.insert(tk.END, "\nRate more images to get personalized suggestions.")
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
            self.recommendations_text.insert(tk.END, "\nRate at least 3 images to generate suggestions.")
            self.recommendations_text.config(state="disabled")
            return
        
        lines.append("Recommended Settings\n")
        lines.append("-" * 30 + "\n\n")

        # PR-044: surface evidence tier and automation eligibility
        evidence_tier = getattr(recommendations, "evidence_tier", None)
        automation_eligible = getattr(recommendations, "automation_eligible", True)
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

        # PR-044/055: manual-only evidence can still be applied via the
        # confirm flow; only auto modes should enforce automation_eligible.
        if rec_list:
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
                    messagebox.showinfo(
                        "Applied",
                        "Recommendations applied to Pipeline settings."
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
            
            changes.append(f"  • {param} → {value}")
        
        if not changes:
            return False
        
        message = "Apply these settings to Pipeline?\n\n" + "\n".join(changes)
        return messagebox.askyesno("Confirm Apply", message)
    
    def _extract_rec_list(self, recommendations: Any) -> list:
        """Extract list of recommendations from various formats."""
        if hasattr(recommendations, "recommendations"):
            return recommendations.recommendations
        elif isinstance(recommendations, list):
            return recommendations
        return []
    
    def _get_learning_controller(self):
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
