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
# Responsive Pipeline layout (PR-GUI-100)
# -----------------------------------------------------------------------------

_ACTIONABLE_CLASSES = (ttk.Button, ttk.Combobox, ttk.Entry, ttk.Spinbox, ttk.Checkbutton, ttk.Radiobutton)


def _pipeline_tab_at_width(root: tk.Tk, width: int):
    from src.gui.app_state_v2 import AppStateV2
    from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

    root.geometry(f"{width}x800+0+0")
    root.deiconify()  # a withdrawn root never realizes its children's sizes
    tab = PipelineTabFrame(root, app_state=AppStateV2())
    tab.pack(fill="both", expand=True)
    root.update()
    root.update()
    return tab


def _descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


def _horizontally_clipped_controls(tab) -> list[str]:
    clipped: list[str] = []
    for scroll in (tab.left_scroll, tab.stage_scroll, tab.right_scroll):
        view_left = scroll._canvas.winfo_rootx()
        view_width = scroll._canvas.winfo_width()
        for widget in _descendants(scroll.inner):
            if not isinstance(widget, _ACTIONABLE_CLASSES) or not widget.winfo_ismapped():
                continue
            left = widget.winfo_rootx() - view_left
            if left < -1 or left + widget.winfo_width() > view_width + 1:
                clipped.append(f"{widget.winfo_class()} {widget}")
    return clipped


def _responsive_snapshot(tab) -> dict[tuple[str, str], int]:
    """Every grid-column minimum in the left/stage forms and every label wraplength the compact layout may change."""
    snapshot: dict[tuple[str, str], int] = {}
    for scroll in (tab.left_scroll, tab.stage_scroll, tab.right_scroll):
        for widget in [scroll, *_descendants(scroll)]:
            if widget.winfo_class() in ("TLabel", "Label"):
                snapshot[(str(widget), "wraplength")] = int(str(widget.cget("wraplength")) or 0)
            for index in range(int(widget.grid_size()[0])):
                snapshot[(str(widget), f"minsize{index}")] = int(widget.columnconfigure(index)["minsize"])
    return snapshot


def _adetailer_hand_pass_check(tab):
    return next(w._hand_pass_check for w in _descendants(tab) if hasattr(w, "_hand_pass_check"))


def _assert_responsive_layout_is_sound(tab) -> None:
    """Whatever presentation this Tk/font environment selects: it matches the measured fit and nothing is clipped."""
    assert tab._compact_layout is (not tab.normal_layout_fits()), "mode must agree with the measured fit"
    assert _horizontally_clipped_controls(tab) == []
    for scroll in (tab.left_scroll, tab.stage_scroll, tab.right_scroll):
        assert scroll.winfo_viewable()  # left, stage and right surfaces all stay reachable
    hand_pass = _adetailer_hand_pass_check(tab)  # the control the hosted Linux runner clipped
    assert hand_pass.winfo_ismapped()
    cell = hand_pass.grid_info()
    assert (int(cell["row"]), int(cell["column"])) == ((2, 1) if tab._compact_layout else (1, 3))


@pytest.mark.parametrize("width", [1280, 1342, 1500, 1896], ids=["min-window", "laptop-1366", "mid", "desktop-1920"])
def test_pipeline_controls_are_never_horizontally_clipped(width: int) -> None:
    """The normal presentation is used when it fits, the compact one otherwise; neither clips a control."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        tab = _pipeline_tab_at_width(root, width)
        _assert_responsive_layout_is_sound(tab)
    finally:
        root.destroy()


def test_pipeline_responsive_breakpoint_round_trip_is_lossless() -> None:
    """Compact -> normal -> compact -> normal keeps the same widgets, values, wheel routing and presentation."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        from src.gui.widgets.scrollable_frame_v2 import _WheelRouter

        tab = _pipeline_tab_at_width(root, 2600)
        panel = tab.sidebar.get_base_generation_panel()
        panel.seed_var.set("12345")
        widgets = {str(w) for w in _descendants(tab)}
        router_frames = _WheelRouter.for_widget(tab).frame_count
        assert tab._compact_layout is False  # 2600 px fits in any environment
        normal_snapshot = _responsive_snapshot(tab)

        for width in (1342, 2600, 1280, 2600):
            root.geometry(f"{width}x800+0+0")
            root.update()
            root.update()
            _assert_responsive_layout_is_sound(tab)
            assert {str(w) for w in _descendants(tab)} == widgets  # nothing orphaned, duplicated or rebuilt
            assert panel.seed_var.get() == "12345"
            assert _WheelRouter.for_widget(tab).frame_count == router_frames
            if width == 2600:
                assert tab._compact_layout is False
                assert _responsive_snapshot(tab) == normal_snapshot  # the normal layout is restored exactly
            else:
                assert tab._compact_layout is True  # 1280/1342 px never fit the normal forms
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
