"""Tests for PR-GUI-D: Layout & Column Scroll Normalization.

This module tests:
- Pipeline tab has three ScrollableFrame columns
- Each column has scrollable content
- Mouse wheel bindings work correctly per column
- Pipeline never resizes the root window (PR-GUI-100)
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
def test_scrollable_frame_wheel_router_is_shared_scoped_and_cleaned_up() -> None:
    """One interpreter-wide wheel router serves every ScrollableFrame and removes only its own binding (PR-GUI-100)."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame, _WheelRouter

        root.geometry("900x300+50+50")  # wide enough that both frames are visible
        first = ScrollableFrame(root)
        second = ScrollableFrame(root)
        # place() gives each frame a fixed half of the window regardless of the canvases' requested widths
        first.place(relx=0.0, rely=0.0, relwidth=0.5, relheight=1.0)
        second.place(relx=0.5, rely=0.0, relwidth=0.5, relheight=1.0)
        combo = ttk.Combobox(first.inner, values=["a", "b"])
        combo.pack()
        for frame in (first, second):
            for index in range(60):
                ttk.Label(frame.inner, text=f"row {index}").pack()
        root.deiconify()
        # winfo_containing() is z-order based: keep the test window above other desktop windows
        root.attributes("-topmost", True)
        root.lift()
        root.update()

        router = _WheelRouter.for_widget(root)
        base = router.frame_count - 2  # frames other tests in this process may still hold on the shared interpreter
        assert router.installed and router.frame_count == base + 2
        # Enter/Leave no longer toggle anything: nothing can steal or disable another frame's wheel.
        first._canvas.event_generate("<Enter>")
        first._canvas.event_generate("<Leave>")
        root.update()
        assert router.installed

        def wheel_over(widget, delta=-120):
            widget.event_generate(
                "<MouseWheel>", delta=delta, rootx=widget.winfo_rootx() + 5, rooty=widget.winfo_rooty() + 5
            )
            root.update()

        assert first.has_scroll_overflow() and second.has_scroll_overflow()
        wheel_over(first._canvas)
        assert first._canvas.yview()[0] > 0.0  # the region under the pointer scrolled...
        assert second._canvas.yview()[0] == 0.0  # ...and only that region
        before = first._canvas.yview()[0]
        wheel_over(combo)
        assert first._canvas.yview()[0] == before  # a combobox keeps its own wheel behavior
        wheel_over(second.inner)
        assert second._canvas.yview()[0] > 0.0

        # No overflow -> nothing to scroll, harmlessly.
        short = ScrollableFrame(root)
        assert not short.has_scroll_overflow()
        short.destroy()
        assert router.installed and router.frame_count == base + 2

        first.destroy()
        assert router.installed and router.frame_count == base + 1
        second.destroy()
        assert router.frame_count == base
        if base == 0:
            assert not router.installed
            assert str(root.tk.call("bind", "all", "<MouseWheel>")).strip() == ""  # no stale global handler
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
# Root window size ownership (PR-GUI-100)
# -----------------------------------------------------------------------------


@pytest.mark.gui
def test_pipeline_tab_never_resizes_the_root_window() -> None:
    """The shared screen-aware window layout is the only root-size authority; Pipeline no longer forces a width."""
    try:
        root = tk.Tk()
        root.geometry("800x600+100+100")
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.app_state_v2 import AppStateV2
        from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

        assert not hasattr(PipelineTabFrame, "MIN_WINDOW_WIDTH")
        assert not hasattr(PipelineTabFrame, "_ensure_minimum_window_width")
        pipeline_tab = PipelineTabFrame(root, app_state=AppStateV2(), pipeline_controller=MagicMock())
        pipeline_tab.pack(fill="both", expand=True)
        root.update()
        pipeline_tab._on_first_map()
        root.update()
        assert root.geometry().startswith("800x600")
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
