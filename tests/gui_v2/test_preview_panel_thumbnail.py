"""Tests for preview panel thumbnail functionality."""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.gui.preview_panel_v2 import PreviewPanelV2
from tests.gui_v2.tk_test_utils import get_shared_tk_root


class TestPreviewPanelThumbnail(unittest.TestCase):
    """Test preview panel thumbnail widget and loading."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.root = get_shared_tk_root()
        if not self.root:
            self.skipTest("Tk not available")

        self.controller = Mock()
        self.app_state = Mock()
        # Configure app_state.preview_jobs as empty list
        self.app_state.preview_jobs = []
        self.panel = PreviewPanelV2(
            self.root, controller=self.controller, app_state=self.app_state
        )

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        if hasattr(self, "panel"):
            try:
                self.panel.destroy()
            except Exception:
                pass

    def test_preview_panel_has_thumbnail(self) -> None:
        """Test that preview panel includes thumbnail widget."""
        assert hasattr(self.panel, "thumbnail")
        assert hasattr(self.panel, "thumbnail_frame")
        assert hasattr(self.panel, "preview_checkbox")

    def test_preview_checkbox_default_state(self) -> None:
        """Test that preview checkbox is enabled by default."""
        assert self.panel._show_preview_var.get() is True

    def test_thumbnail_clears_when_no_job(self) -> None:
        """Test that thumbnail is cleared when no job is selected."""
        with patch.object(self.panel.thumbnail, "clear") as mock_clear:
            self.panel.set_job_summaries([])
            mock_clear.assert_called()

    def test_find_recent_thumbnail_returns_none_when_no_output(self) -> None:
        """Test that _find_recent_thumbnail returns None when output dir doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            job = Mock()
            result = self.panel._find_recent_thumbnail(job)
            assert result is None

    def test_update_thumbnail_respects_checkbox(self) -> None:
        """Test that thumbnail update respects checkbox state."""
        job = Mock()

        # Disable checkbox
        self.panel._show_preview_var.set(False)

        with patch.object(self.panel.thumbnail, "clear") as mock_clear:
            self.panel._update_thumbnail(job, pack_name="test", show_preview=True)
            mock_clear.assert_called()

    def test_checkbox_handler_updates_thumbnail(self) -> None:
        """Test that checkbox handler triggers thumbnail update."""
        # Set up a mock job with required attributes
        mock_job = Mock()
        self.panel._job_summaries = [mock_job]
        self.panel._current_preview_job = mock_job
        self.panel._current_pack_name = "test_pack"
        self.panel._current_show_preview = True

        with patch.object(self.panel, "_update_thumbnail") as mock_update:
            # Enable checkbox (should call _update_thumbnail)
            self.panel._show_preview_var.set(True)
            self.panel._on_preview_checkbox_changed()

            mock_update.assert_called_with(mock_job, "test_pack", True)

    def test_pack_show_preview_flag_updates_checkbox(self) -> None:
        """Test that pack show_preview flag updates checkbox state."""
        from types import SimpleNamespace

        # Create summary with show_preview=False
        summary = SimpleNamespace(
            job_id="test-1",
            label="test_model",
            positive_preview="test prompt",
            negative_preview="test negative",
            stages_display="txt2img",
            sampler_name="Euler a",
            steps=20,
            cfg_scale=7.0,
            seed=-1,
            show_preview=False,
        )

        self.panel._render_summary(summary, 1)

        # Checkbox should be updated to False
        assert self.panel._show_preview_var.get() is False
