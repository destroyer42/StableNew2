"""Tests for PR-GUI-D: Layout & Column Scroll Normalization.

This module tests:
- Pipeline tab has three ScrollableFrame columns
- Each column has scrollable content
- Mouse wheel bindings work correctly per column
- Minimum window width is applied on first show
- Preview panel has no inner scrollbar (uses column scroll)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

# -----------------------------------------------------------------------------
# ScrollableFrame Tests
# -----------------------------------------------------------------------------


@pytest.mark.gui
def test_scrollable_frame_has_canvas_and_scrollbar() -> None:
    """ScrollableFrame should have a canvas and vertical scrollbar."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

        sf = ScrollableFrame(root)
        sf.pack(fill="both", expand=True)
        root.update_idletasks()

        # Should have _canvas and _vsb attributes
        assert hasattr(sf, "_canvas"), "ScrollableFrame should have _canvas"
        assert hasattr(sf, "_vsb"), "ScrollableFrame should have _vsb scrollbar"
        assert hasattr(sf, "inner"), "ScrollableFrame should have inner frame"

        # Canvas and scrollbar should exist
        assert sf._canvas.winfo_exists()
        assert sf._vsb.winfo_exists()
        assert sf.inner.winfo_exists()
    finally:
        root.destroy()


@pytest.mark.gui
def test_scrollable_frame_mousewheel_bindings() -> None:
    """ScrollableFrame should bind/unbind mouse wheel on enter/leave."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

        sf = ScrollableFrame(root)
        sf.pack(fill="both", expand=True)
        root.update_idletasks()

        # Initially wheel should not be bound
        assert sf._wheel_bound is False

        # Simulate enter event on canvas
        sf._canvas.event_generate("<Enter>")
        root.update_idletasks()
        assert sf._wheel_bound is True

        # Simulate leave event on canvas
        sf._canvas.event_generate("<Leave>")
        root.update_idletasks()
        assert sf._wheel_bound is False
    finally:
        root.destroy()


# -----------------------------------------------------------------------------
# Pipeline Tab Column Tests
# -----------------------------------------------------------------------------


@pytest.mark.gui
def test_pipeline_tab_has_three_scrollable_columns() -> None:
    """Pipeline tab should have three ScrollableFrame columns."""
    try:
        from src.app_factory import build_v2_app

        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter/app not available: {exc}")
        return

    try:
        from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

        pipeline_tab = getattr(window, "pipeline_tab", None)
        assert pipeline_tab is not None, "Pipeline tab should exist"

        # Check for left/center/right columns
        assert hasattr(pipeline_tab, "left_column")
        assert hasattr(pipeline_tab, "center_column")
        assert hasattr(pipeline_tab, "right_column")

        # Check for ScrollableFrame instances
        assert hasattr(pipeline_tab, "left_scroll"), "Should have left_scroll"
        assert hasattr(pipeline_tab, "stage_scroll"), "Should have stage_scroll (center)"
        assert hasattr(pipeline_tab, "right_scroll"), "Should have right_scroll"

        # Verify they are ScrollableFrame instances
        assert isinstance(pipeline_tab.left_scroll, ScrollableFrame)
        assert isinstance(pipeline_tab.stage_scroll, ScrollableFrame)
        assert isinstance(pipeline_tab.right_scroll, ScrollableFrame)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


@pytest.mark.gui
def test_pipeline_tab_columns_have_content() -> None:
    """Each pipeline column should have content inside its scroll frame."""
    try:
        from src.app_factory import build_v2_app

        root, app_state, controller, window = build_v2_app()
    except Exception as exc:
        pytest.skip(f"Tkinter/app not available: {exc}")
        return

    try:
        pipeline_tab = getattr(window, "pipeline_tab", None)
        assert pipeline_tab is not None

        # Left column should have sidebar
        left_inner = pipeline_tab.left_scroll.inner
        left_children = left_inner.winfo_children()
        assert len(left_children) > 0, "Left column should have content"

        # Center column should have stage cards
        center_inner = pipeline_tab.stage_scroll.inner
        center_children = center_inner.winfo_children()
        assert len(center_children) > 0, "Center column should have stage cards"

        # Right column should have preview/queue/history panels
        right_inner = pipeline_tab.right_scroll.inner
        right_children = right_inner.winfo_children()
        assert len(right_children) > 0, "Right column should have panels"
    finally:
        try:
            root.destroy()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Minimum Window Width Tests
# -----------------------------------------------------------------------------


@pytest.mark.gui
def test_pipeline_tab_has_min_width_constant() -> None:
    """Pipeline tab should define MIN_WINDOW_WIDTH constant."""
    from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

    assert hasattr(PipelineTabFrame, "MIN_WINDOW_WIDTH")
    assert PipelineTabFrame.MIN_WINDOW_WIDTH >= 1200  # Reasonable minimum


@pytest.mark.gui
def test_ensure_minimum_window_width_expands_narrow_window() -> None:
    """_ensure_minimum_window_width should expand a narrow window."""
    try:
        root = tk.Tk()
        root.geometry("800x600+100+100")
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        # Create pipeline tab with minimal mocks
        mock_controller = MagicMock()
        mock_controller.list_models.return_value = []
        mock_controller.list_vaes.return_value = []
        mock_controller.list_upscalers.return_value = []
        mock_controller.get_current_config.return_value = {}
        mock_controller.restore_last_run.return_value = None

        mock_app_state = MagicMock()
        mock_app_state.resources = {}
        mock_app_state.job_draft = None
        mock_app_state.queue_status = {}
        mock_app_state.subscribe = MagicMock()
        mock_app_state.add_resource_listener = MagicMock()

        pipeline_tab = PipelineTabFrame(
            root,
            app_controller=mock_controller,
            app_state=mock_app_state,
        )
        pipeline_tab.pack(fill="both", expand=True)
        root.update_idletasks()

        # Manually call the method
        pipeline_tab._ensure_minimum_window_width()
        root.update_idletasks()

        # Parse the new geometry
        geom = root.geometry()
        width_str = geom.split("x")[0]
        width = int(width_str)

        assert width >= PipelineTabFrame.MIN_WINDOW_WIDTH, (
            f"Window should be at least {PipelineTabFrame.MIN_WINDOW_WIDTH}px wide, got {width}"
        )
    finally:
        root.destroy()


@pytest.mark.gui
def test_ensure_minimum_window_width_preserves_large_window() -> None:
    """_ensure_minimum_window_width should not shrink a large window."""
    try:
        root = tk.Tk()
        root.geometry("1800x900+50+50")
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        mock_controller = MagicMock()
        mock_controller.list_models.return_value = []
        mock_controller.list_vaes.return_value = []
        mock_controller.list_upscalers.return_value = []
        mock_controller.get_current_config.return_value = {}
        mock_controller.restore_last_run.return_value = None

        mock_app_state = MagicMock()
        mock_app_state.resources = {}
        mock_app_state.job_draft = None
        mock_app_state.queue_status = {}
        mock_app_state.subscribe = MagicMock()
        mock_app_state.add_resource_listener = MagicMock()

        pipeline_tab = PipelineTabFrame(
            root,
            app_controller=mock_controller,
            app_state=mock_app_state,
        )
        pipeline_tab.pack(fill="both", expand=True)
        root.update_idletasks()

        # Get original width
        original_geom = root.geometry()
        original_width = int(original_geom.split("x")[0])

        # Call the method
        pipeline_tab._ensure_minimum_window_width()
        root.update_idletasks()

        # Width should remain unchanged
        new_geom = root.geometry()
        new_width = int(new_geom.split("x")[0])

        assert new_width >= original_width, (
            f"Window should not shrink (was {original_width}, now {new_width})"
        )
    finally:
        root.destroy()


# -----------------------------------------------------------------------------
# Preview Panel Tests (No Inner Scroll)
# -----------------------------------------------------------------------------


@pytest.mark.gui
def test_preview_panel_has_no_inner_scroll() -> None:
    """PreviewPanelV2 should not have an inner ScrollableFrame."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.preview_panel_v2 import PreviewPanelV2

        panel = PreviewPanelV2(root)
        panel.pack(fill="both", expand=True)
        root.update_idletasks()

        # Should NOT have _scroll attribute (removed in PR-GUI-D)
        assert not hasattr(panel, "_scroll"), (
            "PreviewPanelV2 should not have inner _scroll (removed in PR-GUI-D)"
        )

        # Should have direct body frame
        assert hasattr(panel, "body"), "PreviewPanelV2 should have body frame"
        assert isinstance(panel.body, ttk.Frame)
    finally:
        root.destroy()


@pytest.mark.gui
def test_preview_panel_body_is_direct_child() -> None:
    """PreviewPanelV2 body should be a direct child, not inside a scroll frame."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.preview_panel_v2 import PreviewPanelV2

        panel = PreviewPanelV2(root)
        panel.pack(fill="both", expand=True)
        root.update_idletasks()

        # Body's parent should be the panel itself (after removing inner scroll)
        body_parent = panel.body.master
        assert body_parent == panel, "Body frame should be direct child of PreviewPanelV2"
    finally:
        root.destroy()


# -----------------------------------------------------------------------------
# Validation Placeholder Removal Tests
# -----------------------------------------------------------------------------


@pytest.mark.gui
def test_pipeline_config_panel_no_validation_label() -> None:
    """PipelineConfigPanel should not have legacy validation label."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

        panel = PipelineConfigPanel(root)
        panel.pack(fill="both", expand=True)
        root.update_idletasks()

        # Should NOT have _validation_message_var or _validation_label
        assert not hasattr(panel, "_validation_message_var"), (
            "PipelineConfigPanel should not have legacy _validation_message_var"
        )
        assert not hasattr(panel, "_validation_label"), (
            "PipelineConfigPanel should not have legacy _validation_label"
        )
        assert not hasattr(panel, "queue_label_var"), (
            "PipelineConfigPanel should not have legacy queue_label_var"
        )
    finally:
        root.destroy()


@pytest.mark.gui
def test_set_validation_message_is_noop() -> None:
    """set_validation_message should be a no-op stub."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.panels_v2.pipeline_config_panel_v2 import PipelineConfigPanel

        panel = PipelineConfigPanel(root)
        panel.pack(fill="both", expand=True)

        # Should not raise an error
        panel.set_validation_message("test message")
        panel.set_validation_message("")
    finally:
        root.destroy()
