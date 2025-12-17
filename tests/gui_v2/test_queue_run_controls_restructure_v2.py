"""PR-GUI-F1: Queue & Run Controls UI Restructure tests (V2.5).

These tests validate:
- PreviewPanelV2 has no queue/running job status labels
- QueuePanelV2 contains Pause Queue button and Auto-run checkbox
- Queue status label is in QueuePanelV2 with proper styling
- PipelineRunControlsV2 is not instantiated in the layout
"""

from __future__ import annotations

import pytest


def _skip_if_no_tk():
    """Helper to skip test if Tk is unavailable."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        return root
    except Exception as exc:
        pytest.skip(f"Tk not available: {exc}")


class TestPreviewPanelNoQueueStatus:
    """Test that PreviewPanelV2 has no queue/running-job status labels."""

    def test_preview_panel_no_queue_header(self):
        """PreviewPanelV2 should not have a Queue header label."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            # Verify no queue_header attribute
            assert not hasattr(panel, "queue_header"), "PreviewPanelV2 should not have queue_header"
        finally:
            root.destroy()

    def test_preview_panel_no_queue_status_label(self):
        """PreviewPanelV2 should not have a queue_status_label."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert not hasattr(panel, "queue_status_label"), (
                "PreviewPanelV2 should not have queue_status_label"
            )
        finally:
            root.destroy()

    def test_preview_panel_no_queue_items_text(self):
        """PreviewPanelV2 should not have a queue_items_text widget."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert not hasattr(panel, "queue_items_text"), (
                "PreviewPanelV2 should not have queue_items_text"
            )
        finally:
            root.destroy()

    def test_preview_panel_no_running_job_label(self):
        """PreviewPanelV2 should not have a running_job_label."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert not hasattr(panel, "running_job_label"), (
                "PreviewPanelV2 should not have running_job_label"
            )
        finally:
            root.destroy()

    def test_preview_panel_no_running_job_status_label(self):
        """PreviewPanelV2 should not have a running_job_status_label."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert not hasattr(panel, "running_job_status_label"), (
                "PreviewPanelV2 should not have running_job_status_label"
            )
        finally:
            root.destroy()

    def test_preview_panel_no_queue_controls_frame(self):
        """PreviewPanelV2 should not have a queue_controls_frame."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert not hasattr(panel, "queue_controls_frame"), (
                "PreviewPanelV2 should not have queue_controls_frame"
            )
        finally:
            root.destroy()

    def test_preview_panel_no_pause_button(self):
        """PreviewPanelV2 should not have a pause_button."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert not hasattr(panel, "pause_button"), "PreviewPanelV2 should not have pause_button"
        finally:
            root.destroy()

    def test_preview_panel_still_has_actions_frame(self):
        """PreviewPanelV2 should still have an actions_frame with Add to Queue button."""
        root = _skip_if_no_tk()
        try:
            from src.gui.preview_panel_v2 import PreviewPanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = PreviewPanelV2(root)
            panel.pack()

            assert hasattr(panel, "actions_frame"), "PreviewPanelV2 should have actions_frame"
            assert hasattr(panel, "add_to_queue_button"), (
                "PreviewPanelV2 should have add_to_queue_button"
            )
            assert hasattr(panel, "clear_draft_button"), (
                "PreviewPanelV2 should have clear_draft_button"
            )
        finally:
            root.destroy()


class TestQueuePanelHasControls:
    """Test that QueuePanelV2 contains queue controls."""

    def test_queue_panel_has_pause_resume_button(self):
        """QueuePanelV2 should have a Pause Queue button."""
        root = _skip_if_no_tk()
        try:
            from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = QueuePanelV2(root)
            panel.pack()

            assert hasattr(panel, "pause_resume_button"), (
                "QueuePanelV2 should have pause_resume_button"
            )
            # Verify it's a button
            from tkinter import ttk

            assert isinstance(panel.pause_resume_button, ttk.Button)
        finally:
            root.destroy()

    def test_queue_panel_has_auto_run_checkbox(self):
        """QueuePanelV2 should have an Auto-run queue checkbox."""
        root = _skip_if_no_tk()
        try:
            from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = QueuePanelV2(root)
            panel.pack()

            assert hasattr(panel, "auto_run_check"), "QueuePanelV2 should have auto_run_check"
            assert hasattr(panel, "auto_run_var"), "QueuePanelV2 should have auto_run_var"
        finally:
            root.destroy()

    def test_queue_panel_has_queue_status_label(self):
        """QueuePanelV2 should have a queue status label."""
        root = _skip_if_no_tk()
        try:
            from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = QueuePanelV2(root)
            panel.pack()

            assert hasattr(panel, "queue_status_label"), (
                "QueuePanelV2 should have queue_status_label"
            )
        finally:
            root.destroy()

    def test_queue_panel_status_label_updates(self):
        """Queue status label should update when update_queue_status is called."""
        root = _skip_if_no_tk()
        try:
            from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = QueuePanelV2(root)
            panel.pack()

            # Test status updates
            panel.update_queue_status("running")
            text = panel.queue_status_label.cget("text")
            assert "Running" in text

            panel.update_queue_status("paused")
            text = panel.queue_status_label.cget("text")
            assert "Paused" in text

            panel.update_queue_status("idle")
            text = panel.queue_status_label.cget("text")
            assert "Idle" in text
        finally:
            root.destroy()

    def test_queue_panel_pause_button_toggles_text(self):
        """Pause button should show 'Resume Queue' when paused."""
        root = _skip_if_no_tk()
        try:
            from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            panel = QueuePanelV2(root)
            panel.pack()

            # Initial state should be "Pause Queue"
            assert "Pause" in panel.pause_resume_button.cget("text")

            # Simulate paused state update
            class MockAppState:
                is_queue_paused = True
                auto_run_queue = False
                queue_items = []
                running_job = None

            panel.update_from_app_state(MockAppState())
            assert "Resume" in panel.pause_resume_button.cget("text")
        finally:
            root.destroy()


class TestNoRunControlsPanel:
    """Test that PipelineRunControlsV2 is not in the layout."""

    def test_pipeline_run_controls_import_removed(self):
        """PipelineRunControlsV2 should not be imported in pipeline_tab_frame_v2."""
        # This is a static check - verify the import is not there
        import ast
        from pathlib import Path

        path = Path("src/gui/views/pipeline_tab_frame_v2.py")
        if not path.exists():
            pytest.skip("File not found")

        content = path.read_text()
        tree = ast.parse(content)

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)

        assert "PipelineRunControlsV2" not in imports, (
            "PipelineRunControlsV2 should not be imported in pipeline_tab_frame_v2"
        )

    def test_run_controls_attribute_not_present(self):
        """PipelineTabFrame should not have run_controls attribute when instantiated."""
        root = _skip_if_no_tk()
        try:
            from src.gui.theme_v2 import apply_theme
            from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

            apply_theme(root)
            # PipelineTabFrame requires many dependencies, so we just check the class
            # doesn't reference run_controls in its __init__ anymore
            import inspect

            source = inspect.getsource(PipelineTabFrame.__init__)
            assert "self.run_controls = PipelineRunControlsV2" not in source, (
                "PipelineTabFrame should not create run_controls"
            )
        finally:
            root.destroy()
