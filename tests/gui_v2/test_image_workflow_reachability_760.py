"""GUI-COMPLETE-760: controls in the primary image workflow stay reachable on narrow columns.

Real Tk widgets and fakes only; geometry is measured, no control is invoked.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.layout_v2 import measure_horizontal_extent
from src.gui.output_settings_panel_v2 import OutputSettingsPanelV2
from src.gui.widgets.flow_row_v2 import FlowRow
from src.state.output_routing import OUTPUT_ROUTE_TESTING
from tests.helpers.gui_harness_v2 import GuiV2Harness
from tests.helpers.reachability_760 import probe_notebook_pages

pytestmark = pytest.mark.gui


def _settle(root: tk.Misc, cycles: int = 6) -> None:
    for _ in range(cycles):
        root.update_idletasks()
        root.update()


def _host(root: tk.Tk, width: int) -> ttk.Frame:
    root.deiconify()
    root.geometry(f"{width + 40}x600+0+0")
    host = ttk.Frame(root, width=width, height=500)
    host.pack(side="left", anchor="nw")
    host.pack_propagate(False)
    _settle(root)
    return host


def _inside(widget: tk.Misc, container: tk.Misc) -> bool:
    return (
        widget.winfo_ismapped()
        and widget.winfo_rootx() >= container.winfo_rootx()
        and widget.winfo_rootx() + widget.winfo_width()
        <= container.winfo_rootx() + container.winfo_width()
        and widget.winfo_rooty() >= container.winfo_rooty()
        and widget.winfo_rooty() + widget.winfo_height()
        <= container.winfo_rooty() + container.winfo_height()
    )


def _flush(row: FlowRow, root: tk.Misc) -> None:
    _settle(root)
    row.reflow()
    _settle(root)


def test_flow_row_wraps_every_child_inside_a_narrow_width(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 260)
    row = FlowRow(host)
    row.pack(fill="x")
    buttons = [ttk.Button(row, text=f"Action number {index}") for index in range(6)]
    for button in buttons:
        row.add(button)
    _flush(row, tk_root)

    assert len(row.rows()) > 1
    assert all(_inside(button, host) for button in buttons)
    assert [b for line in row.rows() for b in line] == buttons  # order is preserved across rows


def test_flow_row_reflow_is_reversible_and_does_not_oscillate(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 700)
    row = FlowRow(host)
    row.pack(fill="x")
    for index in range(6):
        row.add(ttk.Button(row, text=f"Action number {index}"))
    _flush(row, tk_root)
    wide = [len(line) for line in row.rows()]

    host.configure(width=260)
    _flush(row, tk_root)
    narrow = [len(line) for line in row.rows()]
    host.configure(width=700)
    _flush(row, tk_root)
    again = [len(line) for line in row.rows()]
    _flush(row, tk_root)

    assert len(narrow) > len(wide)
    assert again == wide
    assert [len(line) for line in row.rows()] == wide  # no oscillation once settled


def test_flow_row_wraps_synchronously_when_its_width_changes(tk_root: tk.Tk) -> None:
    """The fit-driven Pipeline layout resizes columns and measures right after ``update_idletasks``."""

    host = _host(tk_root, 700)
    row = FlowRow(host)
    row.pack(fill="x")
    buttons = [ttk.Button(row, text=f"Action number {index}") for index in range(6)]
    for button in buttons:
        row.add(button)
    _flush(row, tk_root)
    wide_rows = len(row.rows())

    host.configure(width=260)
    tk_root.update_idletasks()  # no event pump and no waiting for the coalescing delay

    assert len(row.rows()) > wide_rows
    assert all(_inside(button, host) for button in buttons)


def test_flow_row_manual_reflow_leaves_no_stale_job_after_destroy(tk_root: tk.Tk) -> None:
    errors: list[object] = []
    tk_root.report_callback_exception = lambda *exc: errors.append(exc)  # type: ignore[method-assign]
    host = _host(tk_root, 400)
    row = FlowRow(host)
    row.pack(fill="x")
    row.add(ttk.Button(row, text="One"))
    row.add(ttk.Button(row, text="Two"))  # schedules a coalesced reflow
    row.reflow()  # a direct call must cancel it
    row.destroy()
    end = time.perf_counter() + 0.3
    while time.perf_counter() < end:
        tk_root.update()
        time.sleep(0.01)

    assert errors == []


def test_flow_row_self_schedules_after_a_child_changes_size(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 330)
    row = FlowRow(host)
    row.pack(fill="x")
    label = ttk.Button(row, text="Short")
    row.add(label)
    row.add(ttk.Button(row, text="Second action"))
    _flush(row, tk_root)
    before = len(row.rows())

    label.configure(text="A much longer caption that needs the whole row to itself")
    end = time.perf_counter() + 0.5
    while time.perf_counter() < end:  # only the real coalesced `after` can reflow here
        tk_root.update()
        time.sleep(0.01)

    assert len(row.rows()) > before
    assert _inside(label, host)


def test_flow_row_set_shown_keeps_order_and_unplaces_hidden_children(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 400)
    row = FlowRow(host)
    row.pack(fill="x")
    first, optional, last = (ttk.Button(row, text=text) for text in ("First", "Optional", "Last"))
    row.add(first)
    row.add(optional, shown=False)
    row.add(last)
    _flush(row, tk_root)
    assert optional.winfo_manager() == ""

    row.set_shown(optional, True)
    _flush(row, tk_root)
    assert [b for line in row.rows() for b in line] == [first, optional, last]
    assert _inside(optional, host)

    row.set_shown(optional, False)
    _flush(row, tk_root)
    assert optional.winfo_manager() == ""
    assert [b for line in row.rows() for b in line] == [first, last]


def test_extent_counts_a_control_clipped_by_a_narrower_container(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 700)
    content = ttk.Frame(host)
    content.pack(fill="both", expand=True)
    cell = ttk.Frame(content, width=80, height=40)
    cell.pack(anchor="w")
    cell.pack_propagate(False)
    wide = ttk.Button(cell, text="A control much wider than its container", width=36)
    wide.place(
        x=0, y=0
    )  # keeps its requested width inside the narrower cell (pack would shrink it)
    _settle(tk_root)
    viewport = wide.winfo_width() + 20  # the control alone would "fit" this viewport

    required, available = measure_horizontal_extent(content, viewport)

    assert wide.winfo_width() < viewport < required  # the width clipped away by the cell is counted
    assert available == viewport


def test_output_settings_row_wraps_so_every_option_is_reachable(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 230)
    panel = OutputSettingsPanelV2(host, embed_mode=True)
    panel.pack(fill="x")
    _flush(panel.controls_row, tk_root)

    controls = _descendants(panel.controls_row, ("TCombobox", "TSpinbox"))
    assert len(controls) == 4
    assert len(panel.controls_row.rows()) > 1
    assert all(_inside(control, host) for control in controls)
    panel.output_route_var.set(OUTPUT_ROUTE_TESTING)
    assert (
        panel.get_output_overrides()["output_route"] == OUTPUT_ROUTE_TESTING
    )  # wrapping never touches values


def _descendants(root: tk.Misc, classes: tuple[str, ...]) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    stack = list(root.winfo_children())
    while stack:
        node = stack.pop(0)
        if node.winfo_class() in classes:
            found.append(node)
        stack.extend(node.winfo_children())
    return found


class _NoopController:
    def refresh_job_history(self) -> None:
        return None


def test_job_history_actions_are_all_reachable_in_a_narrow_column(tk_root: tk.Tk) -> None:
    host = _host(tk_root, 330)
    panel = JobHistoryPanelV2(host, controller=_NoopController(), app_state=AppStateV2())
    panel.pack(fill="both", expand=True)
    _flush(panel._action_bar, tk_root)

    buttons = [
        panel.open_btn,
        panel.replay_btn,
        panel.iterate_btn,
        panel.svd_btn,
        panel.video_workflow_btn,
        panel.movie_clips_btn,
        panel.explain_btn,
        panel.review_btn,
        panel.browse_btn,
        panel.refresh_btn,
    ]
    assert all(_inside(button, host) for button in buttons)
    assert panel.refresh_btn is [b for line in panel._action_bar.rows() for b in line][-1]
    # a selection-dependent action keeps its state while wrapped (disabled until a job is chosen)
    assert str(panel.explain_btn.cget("state")) == "disabled"
    # sequence actions are not shown for an ordinary job
    assert panel.resume_sequence_btn.winfo_manager() == ""
    panel.destroy()


# -- primary journey in the real shell ---------------------------------------------------------------------------------

JOURNEY_TABS = ("prompt", "pipeline", "review")
# (realized client size, tk scaling multiplier): the minimum window, and 150% text at the 1366-wide laptop window
JOURNEY_VIEWPORTS = {"min-window": ("1280x680", 1.0), "1366-at-150pct-simulated": ("1342x680", 1.5)}


def _journey_settle(root: tk.Misc, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.01)


def _apply_geometry(root: tk.Tk, geometry: str) -> None:
    want = tuple(int(part) for part in geometry.split("x"))
    root.deiconify()
    for _ in range(3):
        root.geometry(f"{geometry}+0+0")
        _journey_settle(root, 0.5)
        if (root.winfo_width(), root.winfo_height()) == want:
            return
    pytest.fail(f"window did not realize {geometry}: {root.winfo_width()}x{root.winfo_height()}")


@pytest.mark.parametrize("viewport", list(JOURNEY_VIEWPORTS), ids=list(JOURNEY_VIEWPORTS))
def test_primary_image_journey_has_no_unreachable_control(tk_root: tk.Tk, viewport: str) -> None:
    geometry, factor = JOURNEY_VIEWPORTS[viewport]
    base = float(tk_root.tk.call("tk", "scaling"))
    harness = GuiV2Harness(tk_root)
    harness.controller.main_window = harness.window
    try:
        if factor != 1.0:
            tk_root.tk.call("tk", "scaling", base * factor)
        _apply_geometry(tk_root, geometry)
        for tab in JOURNEY_TABS:
            harness.window.select_tab(tab)
            _journey_settle(tk_root, 0.6)
            result = probe_notebook_pages(tk_root, harness.window.get_tab(tab))
            assert result.checked > 0
            assert [f.describe() for f in result.blocking] == [], f"{tab} at {viewport}"
    finally:
        harness.cleanup()
        tk_root.tk.call("tk", "scaling", base)


def test_pipeline_keyboard_focus_reaches_every_control_at_the_minimum_window(
    tk_root: tk.Tk,
) -> None:
    harness = GuiV2Harness(tk_root)
    harness.controller.main_window = harness.window
    try:
        _apply_geometry(tk_root, "1280x680")
        harness.window.select_tab("pipeline")
        _journey_settle(tk_root, 0.6)
        result = probe_notebook_pages(tk_root, harness.window.get_tab("pipeline"), keyboard=True)
        assert [f.describe() for f in result.blocking] == []
    finally:
        harness.cleanup()


def test_resizing_narrow_wide_narrow_keeps_state_and_layout_stable(tk_root: tk.Tk) -> None:
    harness = GuiV2Harness(tk_root)
    harness.controller.main_window = harness.window
    try:
        _apply_geometry(tk_root, "1280x680")
        harness.window.select_tab("pipeline")
        _journey_settle(tk_root, 0.6)
        pipeline = harness.window.get_tab("pipeline")
        history = next(
            n for n in _descendants(pipeline, ("TFrame",)) if isinstance(n, JobHistoryPanelV2)
        )
        before = len(history._action_bar.rows())

        _apply_geometry(tk_root, "1896x984")
        _journey_settle(tk_root, 0.8)
        wide = len(history._action_bar.rows())
        _apply_geometry(tk_root, "1280x680")
        _journey_settle(tk_root, 0.8)

        assert wide <= before
        assert len(history._action_bar.rows()) == before  # reversible
        assert harness.window._current_tab_id() == "pipeline"  # the selected tab never moved
        count = len(history._action_bar.rows())
        _journey_settle(tk_root, 0.8)
        assert len(history._action_bar.rows()) == count  # no oscillation once settled
    finally:
        harness.cleanup()
