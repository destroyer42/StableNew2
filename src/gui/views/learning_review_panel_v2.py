# Renamed from learning_review_panel.py to learning_review_panel_v2.py
# ...existing code...

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

        # Image list
        self.image_listbox = tk.Listbox(self.image_frame, height=8)
        self.image_listbox.pack(fill="both", expand=True)
        self.image_listbox.bind("<<ListboxSelect>>", self._on_image_selected)

        # Selected image display (placeholder for now)
        self.selected_image_label = ttk.Label(self.image_frame, text="Select an image above")
        self.selected_image_label.pack(pady=(5, 0))

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

        # Clear and populate image list
        self.image_listbox.delete(0, tk.END)
        for image_ref in variant.image_refs:
            self.image_listbox.insert(tk.END, image_ref)

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
        if selection:
            index = selection[0]
            image_path = self.image_listbox.get(index)
            self.selected_image_label.config(text=f"Selected: {image_path}")
            # TODO: In a real implementation, this would display the actual image
        else:
            self.selected_image_label.config(text="Select an image above")

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
        image_ref = self.image_listbox.get(image_index)

        # Call controller to record rating
        if hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "record_rating"):
                try:
                    controller.record_rating(image_ref, rating, notes)
                    self.feedback_label.config(
                        text="Rating saved successfully!", foreground="green"
                    )
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


LearningReviewPanel = LearningReviewPanel
