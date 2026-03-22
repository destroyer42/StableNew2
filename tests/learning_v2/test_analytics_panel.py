"""Tests for analytics panel GUI.

PR-LEARN-010: Analytics Dashboard
"""
from __future__ import annotations

import tkinter as tk

from src.gui.views.learning_analytics_panel import LearningAnalyticsPanel
from src.learning.learning_analytics import AnalyticsSummary, ExperimentSummary


def test_analytics_panel_creation():
    """Verify analytics panel can be created."""
    root = tk.Tk()
    try:
        panel = LearningAnalyticsPanel(root)
        assert panel.summary_text is not None
        assert panel.experiments_tree is not None
    finally:
        root.destroy()


def test_update_analytics_empty():
    """Verify display with no analytics."""
    root = tk.Tk()
    try:
        panel = LearningAnalyticsPanel(root)
        panel.update_analytics(None)

        content = panel.summary_text.get(1.0, tk.END)
        assert "No analytics" in content
    finally:
        root.destroy()


def test_update_analytics_with_data():
    """Verify display with analytics data."""
    root = tk.Tk()
    try:
        panel = LearningAnalyticsPanel(root)

        summary = AnalyticsSummary(
            total_experiments=2,
            total_ratings=10,
            avg_rating=4.2,
            experiments=[
                ExperimentSummary(
                    experiment_id="test_exp",
                    parameter_name="CFG Scale",
                    total_variants=3,
                    total_ratings=5,
                    best_value=7.5,
                    best_rating=4.8,
                    worst_value=5.0,
                    worst_rating=3.2,
                    completion_rate=1.0,
                )
            ],
            parameter_stats=[],
            evidence_class_counts={"controlled": 1, "observational": 2},
            decision_counts={"advanced_to_refine": 2},
            reason_tag_counts={"good_composition": 2, "bad_face": 1},
        )

        panel.update_analytics(summary)

        content = panel.summary_text.get(1.0, tk.END)
        assert "Total Experiments: 2" in content
        assert "Total Ratings: 10" in content
        assert "Evidence Classes: controlled=1, observational=2" in content
        assert "Decisions: advanced_to_refine=2" in content
        assert "Top Reason Tags: good_composition=2, bad_face=1" in content

        # Check tree has one item
        items = panel.experiments_tree.get_children()
        assert len(items) == 1
    finally:
        root.destroy()
