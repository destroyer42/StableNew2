"""Analytics display panel for learning system.

PR-LEARN-010: Shows experiment statistics, trends, and summaries.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any


class LearningAnalyticsPanel(ttk.Frame):
    """Panel displaying learning analytics and statistics."""

    def __init__(self, master: tk.Misc, *args, **kwargs) -> None:
        super().__init__(master, *args, **kwargs)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)  # Summary section
        self.rowconfigure(1, weight=1)  # Experiments table
        self.rowconfigure(2, weight=0)  # Export section

        # Summary section
        self.summary_frame = ttk.LabelFrame(self, text="Overall Statistics", padding=5)
        self.summary_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.summary_text = tk.Text(self.summary_frame, height=6, width=40, state="disabled")
        self.summary_text.pack(fill="x")

        # Experiments table
        self.experiments_frame = ttk.LabelFrame(self, text="Experiment History", padding=5)
        self.experiments_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        columns = ("Parameter", "Variants", "Ratings", "Best Value", "Best Rating")
        self.experiments_tree = ttk.Treeview(
            self.experiments_frame,
            columns=columns,
            show="tree headings",
            selectmode="browse",
        )

        for col in columns:
            self.experiments_tree.heading(col, text=col)
            self.experiments_tree.column(col, width=100)

        self.experiments_tree.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            self.experiments_frame,
            orient="vertical",
            command=self.experiments_tree.yview,
        )
        scrollbar.pack(side="right", fill="y")
        self.experiments_tree.config(yscrollcommand=scrollbar.set)

        self.export_frame = ttk.LabelFrame(self, text="Export", padding=5)
        self.export_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        export_button_frame = ttk.Frame(self.export_frame)
        export_button_frame.pack(fill="x")

        ttk.Button(
            export_button_frame,
            text="Export to JSON",
            command=self._on_export_json,
        ).pack(side="left", padx=2)

        ttk.Button(
            export_button_frame,
            text="Export to CSV",
            command=self._on_export_csv,
        ).pack(side="left", padx=2)

        ttk.Button(
            export_button_frame,
            text="Refresh",
            command=self._on_refresh,
        ).pack(side="left", padx=2)

    def update_analytics(self, analytics_summary: Any) -> None:
        """Update the display with new analytics data."""
        self.summary_text.config(state="normal")
        self.summary_text.delete(1.0, tk.END)

        if not analytics_summary:
            self.summary_text.insert(tk.END, "No analytics data available.")
            self.summary_text.config(state="disabled")
            return

        lines = [
            f"Total Experiments: {analytics_summary.total_experiments}\n",
            f"Total Ratings: {analytics_summary.total_ratings}\n",
            f"Average Rating: {analytics_summary.avg_rating:.2f}\n",
        ]
        evidence_counts = getattr(analytics_summary, "evidence_class_counts", {}) or {}
        if evidence_counts:
            evidence_parts = [f"{key}={value}" for key, value in sorted(evidence_counts.items())]
            lines.append(f"Evidence Classes: {', '.join(evidence_parts)}\n")
        decision_counts = getattr(analytics_summary, "decision_counts", {}) or {}
        if decision_counts:
            decision_parts = [f"{key}={value}" for key, value in sorted(decision_counts.items())]
            lines.append(f"Decisions: {', '.join(decision_parts)}\n")
        reason_tag_counts = getattr(analytics_summary, "reason_tag_counts", {}) or {}
        if reason_tag_counts:
            top_tags = sorted(reason_tag_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
            tag_parts = [f"{tag}={count}" for tag, count in top_tags]
            lines.append(f"Top Reason Tags: {', '.join(tag_parts)}\n")

        self.summary_text.insert(tk.END, "".join(lines))
        self.summary_text.config(state="disabled")

        self.experiments_tree.delete(*self.experiments_tree.get_children())
        for exp in analytics_summary.experiments:
            self.experiments_tree.insert(
                "",
                "end",
                text=exp.experiment_id,
                values=(
                    exp.parameter_name or "N/A",
                    exp.total_variants,
                    exp.total_ratings,
                    exp.best_value or "N/A",
                    f"{exp.best_rating:.2f}",
                ),
            )

    def _on_export_json(self) -> None:
        """Handle JSON export button."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )

        if file_path and hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "export_analytics_json"):
                try:
                    controller.export_analytics_json(file_path)
                    messagebox.showinfo("Export", f"Analytics exported to {file_path}")
                except Exception as e:
                    messagebox.showerror("Export Error", str(e))

    def _on_export_csv(self) -> None:
        """Handle CSV export button."""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

        if file_path and hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "export_analytics_csv"):
                try:
                    controller.export_analytics_csv(file_path)
                    messagebox.showinfo("Export", f"Analytics exported to {file_path}")
                except Exception as e:
                    messagebox.showerror("Export Error", str(e))

    def _on_refresh(self) -> None:
        """Handle refresh button."""
        if hasattr(self.master, "learning_controller"):
            controller = self.master.learning_controller
            if hasattr(controller, "refresh_analytics"):
                controller.refresh_analytics()
