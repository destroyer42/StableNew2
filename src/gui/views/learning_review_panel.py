# Subsystem: Learning
# Role: Shows learning run results and feedback controls.

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from src.gui.learning_state import LearningVariant


class LearningReviewPanel(ttk.Frame):
    """Right panel for learning review and rating controls."""

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)

        # Current variant being reviewed
        self.current_variant: LearningVariant | None = None
        self.current_experiment = None

        # Configure layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Status section
        self.rowconfigure(1, weight=0)  # Metadata section
        self.rowconfigure(2, weight=0)  # Recommendations section
        self.rowconfigure(3, weight=1)  # Image display section
        self.rowconfigure(4, weight=0)  # Rating section

        # Status section
        self.status_frame = ttk.LabelFrame(self, text="Variant Status", padding=5)
        self.status_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.status_label = ttk.Label(self.status_frame, text="No variant selected")
        self.status_label.pack(anchor="w")

        self.progress_label = ttk.Label(self.status_frame, text="")
        self.progress_label.pack(anchor="w")

        # Metadata section
        self.metadata_frame = ttk.LabelFrame(self, text="Metadata", padding=5)
        self.metadata_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        self.metadata_text = tk.Text(self.metadata_frame, height=4, width=40, state="disabled")
        self.metadata_text.pack(fill="x")

        # Recommendations section
        self.recommendations_frame = ttk.LabelFrame(self, text="Recommended Settings", padding=5)
        self.recommendations_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        self.recommendations_text = tk.Text(
            self.recommendations_frame, height=6, width=40, state="disabled"
        )
        self.recommendations_text.pack(fill="x")

        # Image display section
        self.image_frame = ttk.LabelFrame(self, text="Images", padding=5)
        self.image_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)
        self.image_frame.columnconfigure(0, weight=1)
        self.image_frame.rowconfigure(1, weight=1)  # Thumbnail row gets weight

        # Import ImageThumbnail widget
        from src.gui.widgets.image_thumbnail import ImageThumbnail

        # Image list (top)
        self.image_listbox = tk.Listbox(self.image_frame, height=5)
        self.image_listbox.grid(row=0, column=0, sticky="ew")
        self.image_listbox.bind("<<ListboxSelect>>", self._on_image_selected)

        # Image thumbnail (bottom)
        self.image_thumbnail = ImageThumbnail(
            self.image_frame,
            max_width=250,
            max_height=250,
        )
        self.image_thumbnail.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        self.image_thumbnail.clear()

        # Store full paths for loading images
        self._image_full_paths: list[str] = []

        # Rating section
        self.rating_frame = ttk.LabelFrame(self, text="Rating", padding=5)
        self.rating_frame.grid(row=4, column=0, sticky="ew", padx=5, pady=5)

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

        # Notes
        ttk.Label(self.rating_frame, text="Notes:").pack(anchor="w")
        self.notes_text = tk.Text(self.rating_frame, height=3, width=40)
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

        # Enable/disable rating controls based on status
        state = "normal" if variant.status == "completed" and variant.image_refs else "disabled"
        self.rate_button.config(state=state)
        for btn in self.rating_buttons:
            btn.config(state=state)
        self.notes_text.config(state=tk.NORMAL if state == "normal" else tk.DISABLED)

    def _update_metadata(self, variant: LearningVariant, experiment: Any | None) -> None:
        """Update the metadata display."""
        self.metadata_text.config(state="normal")
        self.metadata_text.delete(1.0, tk.END)

        if experiment:
            metadata = f"Experiment: {experiment.name}\n"
            metadata += f"Variable: {experiment.variable_under_test}\n"
            metadata += f"Value: {variant.param_value}\n"
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

    def _extract_filename(self, path: str) -> str:
        """Extract filename from full path."""
        from pathlib import Path
        return Path(path).name

    def _get_rating_for_image(self, image_path: str) -> int | None:
        """Get rating for an image from the controller."""
        try:
            if hasattr(self.master, "learning_controller"):
                controller = self.master.learning_controller
                if hasattr(controller, "get_rating_for_image"):
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
        if hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "record_rating"):
                try:
                    controller.record_rating(image_ref, rating, notes)
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

    def update_recommendations(self, recommendations: Any) -> None:
        """Update the recommendations display with new data."""
        self.recommendations_text.config(state="normal")
        self.recommendations_text.delete(1.0, tk.END)

        if recommendations and hasattr(recommendations, "recommendations"):
            if recommendations.recommendations:
                # Sort recommendations by confidence (highest first)
                sorted_recs = sorted(
                    recommendations.recommendations, key=lambda r: r.confidence_score, reverse=True
                )

                for rec in sorted_recs[:5]:  # Show top 5 recommendations
                    line = f"{rec.parameter_name}: {rec.recommended_value} "
                    line += f"(confidence: {rec.confidence_score:.2f})\n"
                    self.recommendations_text.insert(tk.END, line)
            else:
                self.recommendations_text.insert(
                    tk.END,
                    "No recommendations available yet.\nRate some images to build recommendations.",
                )
        else:
            self.recommendations_text.insert(tk.END, "Recommendation system not available.")

        self.recommendations_text.config(state="disabled")
