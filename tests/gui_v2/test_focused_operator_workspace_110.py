"""PR-GUI-110: focused operator workspace (real Tk, no backend, no generation).

Covers the compact Operator Log, progressive guidance, the responsive Review preview, the always-visible SVD /
Video Workflow primary actions and the collapsible Advanced Conditioning section.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from src.gui.app_state_v2 import AppStateV2
from src.gui.log_trace_panel_v2 import LogTracePanelV2
from src.gui.tooltip import install_full_value_tooltips
from src.gui.view_contracts.window_layout_contract import compute_window_layout
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerContent, ActionExplainerPanel
from src.gui.widgets.disclosure_section_v2 import DisclosureSection
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget
from src.utils import InMemoryLogHandler


def _settle(root: tk.Tk, ms: int = 160) -> None:
    """Run the real main loop briefly: coalesced `after` jobs and worker callbacks only land inside one."""

    root.after(ms, root.quit)
    root.mainloop()


def _is_under(widget: tk.Misc, ancestor: tk.Misc) -> bool:
    node: tk.Misc | None = widget
    while node is not None:
        if node is ancestor:
            return True
        node = getattr(node, "master", None)
    return False


def _rect(widget: tk.Misc) -> tuple[int, int, int, int]:
    return (
        widget.winfo_rootx(),
        widget.winfo_rooty(),
        widget.winfo_rootx() + widget.winfo_width(),
        widget.winfo_rooty() + widget.winfo_height(),
    )


@pytest.fixture
def laptop_root(tk_root: tk.Tk):
    layout = compute_window_layout(1366, 768)
    tk_root.geometry(f"{layout.width}x{layout.height}+0+0")
    tk_root.deiconify()
    yield tk_root
    tk_root.withdraw()


# --- Scope A: Operator Log ------------------------------------------------------------------------------------------


def test_operator_log_is_compact_by_default_and_keeps_details_on_demand(laptop_root: tk.Tk) -> None:
    handler = InMemoryLogHandler(max_entries=50)
    bundle = Mock()
    panel = LogTracePanelV2(laptop_root, handler, audience="operator", on_generate_bundle=bundle)
    panel.pack(fill="x")
    try:
        _settle(laptop_root, 60)
        assert panel.is_expanded() is False
        assert not panel._body.winfo_ismapped()  # the text area is not on screen
        assert not panel._level_combo.winfo_ismapped()  # filters belong to the details view
        assert panel._bundle_button is not None and panel._bundle_button.winfo_ismapped()
        compact_height = panel.winfo_height()

        panel._bundle_button.invoke()  # Crash Bundle works without opening the details
        bundle.assert_called_once()

        panel.show()
        _settle(laptop_root, 60)
        assert panel.is_expanded() is True
        assert panel._body.winfo_ismapped() and panel._level_combo.winfo_ismapped()
        assert panel.winfo_height() > compact_height
    finally:
        panel.destroy()


def test_trace_log_still_starts_expanded() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        panel = LogTracePanelV2(root, InMemoryLogHandler(max_entries=5), audience="trace")
        assert panel.is_expanded() is True
        panel.destroy()
    finally:
        root.destroy()


def test_log_toggle_never_changes_the_root_window_geometry(laptop_root: tk.Tk) -> None:
    panel = LogTracePanelV2(laptop_root, InMemoryLogHandler(max_entries=50), audience="operator")
    panel.pack(fill="both", expand=True)
    try:
        _settle(laptop_root, 60)
        before = laptop_root.geometry()
        for _ in range(3):
            panel.show()
            _settle(laptop_root, 40)
            assert laptop_root.geometry() == before
            panel._set_expanded(False)
            _settle(laptop_root, 40)
            assert laptop_root.geometry() == before
        assert not hasattr(panel, "_adjust_window_height")
    finally:
        panel.destroy()


def test_collapsed_log_reports_warnings_and_errors_without_hiding_them(laptop_root: tk.Tk) -> None:
    handler = InMemoryLogHandler(max_entries=50)
    logger = logging.getLogger("tests.gui110.log")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    panel = LogTracePanelV2(laptop_root, handler, audience="operator")
    panel.pack(fill="x")
    try:
        assert str(panel._severity_label.cget("text")) == ""  # nothing to report: nothing shown
        logger.info("routine message")
        logger.warning("first warning")
        logger.error("a real error")
        panel._refresh_severity()
        text = str(panel._severity_label.cget("text"))
        assert "1 error" in text and "1 warning" in text
        assert panel.is_expanded() is False  # reported, but the operator opens it deliberately

        panel._refresh_severity()  # unchanged log version: no second scan
        handler_calls = Mock(wraps=handler.get_entries)
        handler.get_entries = handler_calls  # type: ignore[method-assign]
        panel._refresh_severity()
        handler_calls.assert_not_called()

        snapshot = panel.get_diagnostics_snapshot()
        assert snapshot["warning_count"] == 1 and snapshot["error_count"] == 1
    finally:
        logger.removeHandler(handler)
        panel.destroy()


def test_log_panel_destroy_cancels_its_timers(laptop_root: tk.Tk) -> None:
    panel = LogTracePanelV2(laptop_root, InMemoryLogHandler(max_entries=5), audience="operator")
    panel.schedule_refresh_soon(10)
    assert panel._refresh_job is not None and panel._deferred_refresh_id is not None
    panel.destroy()
    assert panel._refresh_job is None and panel._deferred_refresh_id is None


# --- Scope B: progressive guidance ----------------------------------------------------------------------------------


def test_collapsed_overview_is_one_header_row_and_expands_with_full_content(laptop_root: tk.Tk) -> None:
    panel = TabOverviewPanel(laptop_root, content=get_tab_overview_content("review"))
    panel.pack(fill="x")
    try:
        _settle(laptop_root, 60)
        collapsed_height = panel.winfo_height()
        assert not panel.summary_label.winfo_ismapped() and not panel.details_label.winfo_ismapped()
        assert collapsed_height <= panel.toggle_button.winfo_reqheight() + 16  # one header row, not a wrapped block

        panel.toggle_button.invoke()
        _settle(laptop_root, 60)
        assert panel.summary_label.winfo_ismapped() and panel.details_label.winfo_ismapped()
        assert "Purpose:" in panel.details_label.cget("text")  # the complete explanation is intact
        assert panel.winfo_height() > collapsed_height
    finally:
        panel.destroy()


def test_action_explainer_collapses_but_can_keep_a_safety_summary_visible(laptop_root: tk.Tk) -> None:
    content = ActionExplainerContent(title="Danger", summary="This deletes data.", bullets=("a", "b"))
    plain = ActionExplainerPanel(laptop_root, content=content)
    safety = ActionExplainerPanel(laptop_root, content=content, summary_when_collapsed=True)
    plain.pack(fill="x")
    safety.pack(fill="x")
    try:
        _settle(laptop_root, 60)
        assert not plain.summary_label.winfo_ismapped()
        assert safety.summary_label.winfo_ismapped()  # a safety-critical notice never collapses away
        plain.toggle_button.invoke()
        _settle(laptop_root, 60)
        assert plain.summary_label.winfo_ismapped() and "- a" in plain.details_label.cget("text")
    finally:
        plain.destroy()
        safety.destroy()


def test_help_mode_still_forces_guidance_open_and_keyboard_activates_the_toggle(laptop_root: tk.Tk) -> None:
    state = AppStateV2()
    panel = ActionExplainerPanel(
        laptop_root,
        content=ActionExplainerContent(title="T", summary="S", bullets=("b",)),
        app_state=state,
    )
    panel.pack(fill="x")
    try:
        assert panel._on_return_key(SimpleNamespace()) == "break"  # Return activates like Space
        assert panel.is_expanded() is True
        panel.toggle_button.invoke()
        assert panel.is_expanded() is False
        state.set_help_mode_enabled(True)
        _settle(laptop_root, 60)
        assert panel.is_expanded() is True and panel.summary_label.winfo_ismapped()
    finally:
        panel.destroy()


def test_manual_disclosure_choice_survives_tab_switching_and_resizing(laptop_root: tk.Tk) -> None:
    from tkinter import ttk

    notebook = ttk.Notebook(laptop_root)
    notebook.pack(fill="both", expand=True)
    tab_a, tab_b = ttk.Frame(notebook), ttk.Frame(notebook)
    notebook.add(tab_a, text="A")
    notebook.add(tab_b, text="B")
    panel = TabOverviewPanel(tab_a, content=get_tab_overview_content("svd"))
    panel.pack(fill="x")
    try:
        panel.toggle_button.invoke()
        assert panel.is_expanded() is True
        for index in (1, 0, 1, 0):
            notebook.select(index)
            _settle(laptop_root, 30)
        laptop_root.geometry("1280x680+0+0")
        _settle(laptop_root, 60)
        laptop_root.geometry("1500x700+0+0")
        _settle(laptop_root, 60)
        assert panel.is_expanded() is True and panel.details_label.winfo_ismapped()
    finally:
        notebook.destroy()


def test_disclosure_section_keeps_body_widgets_and_values_while_collapsed(laptop_root: tk.Tk) -> None:
    from tkinter import ttk

    section = DisclosureSection(laptop_root, title="Advanced")
    section.pack(fill="x")
    variable = tk.StringVar(value="kept")
    entry = ttk.Entry(section.body, textvariable=variable)
    entry.pack()
    try:
        _settle(laptop_root, 60)
        assert not entry.winfo_ismapped() and section.is_expanded() is False
        variable.set("edited while collapsed")
        section.toggle_button.invoke()
        _settle(laptop_root, 60)
        assert entry.winfo_ismapped() and entry.get() == "edited while collapsed"
        section.set_status("ignored while expanded")
        assert "ignored" not in section.header_text()
        assert section._on_return(SimpleNamespace()) == "break" and section.is_expanded() is False
        section.set_status("2 edited", active=True)
        assert "2 edited" in section.header_text()
        assert str(section.toggle_button.cget("style")) == "DisclosureActive.TButton"
    finally:
        section.destroy()


def test_bind_wraplength_follows_the_allotted_width_and_cleans_up(laptop_root: tk.Tk) -> None:
    from tkinter import ttk

    frame = ttk.Frame(laptop_root)
    frame.pack(fill="x")
    frame.columnconfigure(0, weight=1)
    label = ttk.Label(frame, text="word " * 200)
    label.grid(row=0, column=0, sticky="ew")
    bind_wraplength(label, maximum=900)
    try:
        laptop_root.geometry("700x600+0+0")
        _settle(laptop_root, 200)
        narrow = int(str(label.cget("wraplength")))
        assert 160 <= narrow <= laptop_root.winfo_width()
        laptop_root.geometry("1100x600+0+0")
        _settle(laptop_root, 200)
        wide = int(str(label.cget("wraplength")))
        assert narrow < wide <= 900  # the old fixed value is now only an upper bound
    finally:
        frame.destroy()  # must not raise from a pending coalesced job
        _settle(laptop_root, 120)


# --- Scope C: responsive Review preview -----------------------------------------------------------------------------


def _image(tmp_path: Path, name: str = "a.png", size: tuple[int, int] = (768, 1024)) -> Path:
    path = tmp_path / name
    Image.new("RGB", size, (180, 70, 70)).save(path)
    return path


@pytest.mark.parametrize(("parent_width", "expected"), [(900, 620), (437, 437), (150, 200)])
def test_responsive_thumbnail_fits_its_parent_within_bounds(laptop_root: tk.Tk, parent_width: int, expected: int) -> None:
    from tkinter import ttk

    holder = ttk.Frame(laptop_root, width=parent_width, height=700)
    holder.pack(anchor="nw")
    holder.pack_propagate(False)
    holder.columnconfigure(0, weight=1)
    thumb = ThumbnailWidget(holder, width=620, height=620, responsive=True)
    thumb.pack(fill="x")
    try:
        _settle(laptop_root, 200)
        assert thumb.fitted_edge() == expected
        assert int(thumb._canvas.cget("width")) == expected
        assert thumb.winfo_width() <= max(parent_width, 200)  # never forces its parent wider
    finally:
        holder.destroy()


def test_responsive_thumbnail_preserves_aspect_and_rescales_without_decoding_again(laptop_root: tk.Tk) -> None:
    from tkinter import ttk

    holder = ttk.Frame(laptop_root, width=620, height=700)
    holder.pack(anchor="nw")
    holder.pack_propagate(False)
    thumb = ThumbnailWidget(holder, width=620, height=620, responsive=True)
    thumb.pack(fill="x")
    try:
        _settle(laptop_root, 200)
        thumb.set_image(Image.new("RGB", (620, 310), "navy"))  # 2:1 source
        assert thumb._photo_image.width() == 620 and thumb._photo_image.height() == 310

        with patch("src.utils.thread_registry.ThreadRegistry.spawn") as spawn:
            holder.configure(width=400)
            _settle(laptop_root, 250)
            assert thumb.fitted_edge() == 400
            ratio = thumb._photo_image.width() / thumb._photo_image.height()
            assert abs(ratio - 2.0) < 0.02  # aspect ratio preserved on the rescale
            spawn.assert_not_called()  # a resize never decodes the file again
    finally:
        holder.destroy()


def test_thumbnail_ignores_superseded_and_post_destroy_results(tmp_path: Path, laptop_root: tk.Tk) -> None:
    thumb = ThumbnailWidget(laptop_root, width=300, height=300, responsive=True)
    thumb.pack()
    first, second = _image(tmp_path, "one.png"), _image(tmp_path, "two.png")
    spawned: list[object] = []
    try:
        with patch("src.utils.thread_registry.ThreadRegistry.spawn", side_effect=lambda **kw: spawned.append(kw)):
            thumb.set_image_from_path(first)
            first_request = thumb._request_id
            thumb.set_image_from_path(first)  # identical decode already in flight: no duplicate work
            assert len(spawned) == 1 and thumb._request_id == first_request
            thumb.set_image_from_path(second)  # a newer selection supersedes it
            assert len(spawned) == 2 and thumb._request_id == first_request + 1

        stale = Image.new("RGB", (100, 100), "red")
        thumb._on_image_loaded(stale, first_request, str(first))
        assert thumb._source_image is None  # the stale result is discarded

        fresh = Image.new("RGB", (100, 100), "green")
        thumb._on_image_loaded(fresh, thumb._request_id, str(second))
        assert thumb._source_image is fresh and thumb._inflight_path is None

        pending = thumb._request_id
        thumb.destroy()
        thumb._on_image_loaded(fresh, pending, str(second))  # a late callback against a destroyed widget is a no-op
    finally:
        if thumb.winfo_exists():
            thumb.destroy()


def test_review_preview_and_metadata_stay_inside_the_viewport_at_laptop_and_increased_scaling(laptop_root: tk.Tk, tmp_path: Path) -> None:
    images = [_image(tmp_path, f"img{i}.png") for i in range(2)]
    base = float(laptop_root.tk.call("tk", "scaling"))
    for scaling in (base, base * 1.5):
        laptop_root.tk.call("tk", "scaling", scaling)
        tab = ReviewTabFrame(laptop_root)
        tab.pack(fill="both", expand=True)
        try:
            tab._set_selected_images(images)
            tab._show_image(images[0])
            _settle(laptop_root, 400)
            viewport = _rect(tab._workspace_scroll._canvas)
            for widget in (tab.preview, tab.meta_label):
                _left, _top, right, _bottom = _rect(widget)
                assert right <= viewport[2] + 1, f"{widget} leaks past the viewport at scaling {scaling}"
            assert tab.preview.fitted_edge() <= 620
            assert int(str(tab.meta_label.cget("wraplength"))) <= viewport[2] - viewport[0]
            assert tab.preview._source_image is not None  # the async decode landed (inside the real main loop)
        finally:
            tab.destroy()
            laptop_root.tk.call("tk", "scaling", base)


def test_review_selection_survives_a_resize(laptop_root: tk.Tk, tmp_path: Path) -> None:
    images = [_image(tmp_path, f"s{i}.png") for i in range(3)]
    tab = ReviewTabFrame(laptop_root)
    tab.pack(fill="both", expand=True)
    try:
        tab._set_selected_images(images)
        tab.images_list.selection_clear(0, "end")
        tab.images_list.selection_set(1)
        tab._on_image_select(SimpleNamespace())
        _settle(laptop_root, 200)
        laptop_root.geometry("1280x680+0+0")
        _settle(laptop_root, 200)
        laptop_root.geometry("1500x700+0+0")
        _settle(laptop_root, 200)
        assert tab.images_list.curselection() == (1,)
        assert tab._selected_image_path == images[1]
    finally:
        tab.destroy()


# --- Scope D: SVD and Video Workflow primary actions ----------------------------------------------------------------


def test_svd_animate_action_is_visible_without_scrolling_and_submits_once(laptop_root: tk.Tk) -> None:
    controller = Mock()
    controller.submit_svd_job.return_value = "job-svd-1"
    controller.get_supported_svd_models.return_value = ["stabilityai/stable-video-diffusion-img2vid-xt"]
    tab = SVDTabFrameV2(laptop_root, app_controller=controller)
    tab.pack(fill="both", expand=True)
    try:
        tab.source_image_var.set("C:/tmp/source.png")
        _settle(laptop_root, 250)
        scroll = tab._body_scroll
        assert not _is_under(tab.animate_btn, scroll.inner)  # not at the bottom of the scrolling settings
        scroll._canvas.yview_moveto(0.0)
        _settle(laptop_root, 60)
        _left, top, _right, bottom = _rect(tab.animate_btn)
        tab_rect = _rect(tab)
        assert tab.animate_btn.winfo_ismapped() and top >= tab_rect[1] and bottom <= tab_rect[3]

        with patch("src.gui.views.svd_tab_frame_v2.messagebox"):
            tab.animate_btn.invoke()  # one deliberate click ...
        controller.submit_svd_job.assert_called_once()  # ... one existing submission callback, nothing else
        assert controller.submit_svd_job.call_args.kwargs["source_image_path"] == "C:/tmp/source.png"
    finally:
        tab.destroy()


def test_svd_admission_blocker_stays_visible_and_the_action_stays_disabled(laptop_root: tk.Tk) -> None:
    controller = Mock()
    controller.get_supported_svd_models.return_value = ["stabilityai/stable-video-diffusion-img2vid-xt"]
    controller.get_svd_postprocess_capabilities.return_value = {
        "admission": {"available": False, "blocking_reasons": ["Select a source image."], "warnings": []}
    }
    tab = SVDTabFrameV2(laptop_root, app_controller=controller)
    tab.pack(fill="both", expand=True)
    try:
        _settle(laptop_root, 250)
        assert tab.admission_label.winfo_ismapped()
        assert "Select a source image." in tab.admission_label.cget("text")
        assert str(tab.animate_btn.cget("state")) == "disabled"
        assert not _is_under(tab.admission_label, tab._body_scroll.inner)  # the blocker is never scrolled away
    finally:
        tab.destroy()


class _VideoController:
    def __init__(self, experimental: bool) -> None:
        self.experimental = experimental
        self.submissions: list[dict[str, object]] = []

    def build_video_workflow_defaults(self) -> dict[str, object]:
        return {
            "workflow_id": "exp_wf",
            "motion_profile": "gentle",
            "camera_intent": {"preset": "none", "strength": 0.35},
            "controlnet": {"model": "depth", "weight": 1.0, "guidance_start": 0.0, "guidance_end": 1.0},
            "depth_input": {"mode": "none", "path": ""},
            "output_route": "Reprocess",
        }

    def get_video_workflow_specs(self) -> list[dict[str, object]]:
        return [
            {
                "workflow_id": "exp_wf",
                "workflow_version": "1",
                "backend_id": "comfy",
                "display_name": "Experimental WF",
                "experimental": self.experimental,
            }
        ]

    def submit_video_workflow_job(self, *, source_image_path: str, form_data: dict[str, object]) -> str:
        self.submissions.append(dict(form_data))
        return "job-video-1"


def test_video_workflow_action_and_experimental_opt_in_are_always_visible_and_associated(laptop_root: tk.Tk) -> None:
    controller = _VideoController(experimental=True)
    tab = VideoWorkflowTabFrameV2(laptop_root, app_controller=controller, app_state=SimpleNamespace())
    tab.pack(fill="both", expand=True)
    try:
        tab.source_image_var.set("C:/tmp/source.png")
        _settle(laptop_root, 250)
        scroll = tab._body_scroll
        for widget in (tab.queue_workflow_button, tab.experimental_opt_in_check):
            assert widget.winfo_ismapped()
            assert not _is_under(widget, scroll.inner)  # outside the scrolling form
        # The opt-in sits in the same row as the button it authorises.
        assert tab.experimental_opt_in_check.master is tab.queue_workflow_button.master
        assert abs(_rect(tab.experimental_opt_in_check)[1] - _rect(tab.queue_workflow_button)[1]) < 40

        scroll._canvas.yview_moveto(1.0)
        _settle(laptop_root, 60)
        assert tab.queue_workflow_button.winfo_ismapped() and tab.experimental_opt_in_check.winfo_ismapped()

        tab.experimental_opt_in_var.set(True)
        with patch("src.gui.views.video_workflow_tab_frame_v2.messagebox"):
            tab.queue_workflow_button.invoke()
        assert len(controller.submissions) == 1  # one click, one existing submission callback
        assert controller.submissions[0]["experimental_opt_in"] is True
    finally:
        tab.destroy()


def test_video_workflow_hides_the_opt_in_for_a_non_experimental_workflow(laptop_root: tk.Tk) -> None:
    tab = VideoWorkflowTabFrameV2(
        laptop_root, app_controller=_VideoController(experimental=False), app_state=SimpleNamespace()
    )
    tab.pack(fill="both", expand=True)
    try:
        _settle(laptop_root, 200)
        assert tab.queue_workflow_button.winfo_ismapped()
        assert not tab.experimental_opt_in_check.winfo_ismapped()
    finally:
        tab.destroy()


def test_video_workflow_status_and_source_identity_stay_visible_in_the_fixed_header(laptop_root: tk.Tk) -> None:
    tab = VideoWorkflowTabFrameV2(laptop_root, app_controller=_VideoController(True), app_state=SimpleNamespace())
    tab.pack(fill="both", expand=True)
    try:
        tab.set_source_image_path("C:/tmp/source.png", status_message="Video workflow queue failed: boom")
        _settle(laptop_root, 250)
        scroll = tab._body_scroll
        for label in (tab.status_label, tab.source_summary_label):
            assert label.winfo_ismapped() and not _is_under(label, scroll.inner)
        assert "boom" in tab.status_var.get()
        assert "source.png" in tab.source_summary_var.get()
        # Effective settings are condensed behind a disclosure but remain one click away and intact.
        section = tab.effective_settings_section
        assert not tab.effective_settings_label.winfo_ismapped()
        section.toggle_button.invoke()
        _settle(laptop_root, 60)
        assert tab.effective_settings_label.winfo_ismapped()
        assert tab.effective_settings_var.get().startswith("Effective settings:")
    finally:
        tab.destroy()


def test_advanced_conditioning_collapses_without_losing_values_and_flags_active_content(laptop_root: tk.Tk) -> None:
    tab = VideoWorkflowTabFrameV2(laptop_root, app_controller=_VideoController(True), app_state=SimpleNamespace())
    tab.pack(fill="both", expand=True)
    try:
        _settle(laptop_root, 200)
        section = tab.conditioning_section
        assert section.is_expanded() is False and not tab.conditioning_frame.winfo_ismapped()
        assert "active" not in section.header_text() and "edited" not in section.header_text()

        tab.camera_preset_var.set("dolly_in")
        tab.controlnet_weight_var.set("0.9")
        tab.depth_mode_var.set("upload")
        _settle(laptop_root, 60)
        header = section.header_text()
        assert "camera=dolly_in" in header and "depth=upload" in header  # hidden active controls announce themselves
        assert str(section.toggle_button.cget("style")) == "DisclosureActive.TButton"

        state = tab.get_video_workflow_state()
        assert state["camera_intent"]["preset"] == "dolly_in" and state["controlnet"]["weight"] == "0.9"

        section.toggle_button.invoke()  # expand, then collapse again: nothing is lost
        _settle(laptop_root, 60)
        assert tab.conditioning_frame.winfo_ismapped()
        section.toggle_button.invoke()
        assert tab.camera_preset_var.get() == "dolly_in" and tab.controlnet_weight_var.get() == "0.9"

        tab.camera_preset_var.set("none")
        tab.depth_mode_var.set("none")
        _settle(laptop_root, 60)
        assert "edited (inactive)" in section.header_text()  # a changed-but-inactive value is still disclosed
        tab.controlnet_weight_var.set("1.0")
        _settle(laptop_root, 60)
        assert "edited" not in section.header_text()  # back at the defaults: no accent
    finally:
        tab.destroy()


# --- Scope E: Pipeline readability ----------------------------------------------------------------------------------


def test_narrow_combobox_exposes_its_full_selected_value(laptop_root: tk.Tk) -> None:
    from tkinter import ttk

    holder = ttk.Frame(laptop_root)
    holder.pack()
    long_value = "a_very_long_checkpoint_identity_v1.0_final_pruned_fp16_ema.safetensors"
    combo = ttk.Combobox(holder, values=[long_value], width=10, state="readonly")
    combo.set(long_value)
    combo.pack()
    short = ttk.Combobox(holder, values=["x"], width=30, state="readonly")
    short.set("x")
    short.pack()
    try:
        _settle(laptop_root, 60)
        assert install_full_value_tooltips(holder) == 2
        assert install_full_value_tooltips(holder) == 0  # idempotent
        tooltip = combo.tooltip
        assert long_value in tooltip._display_text()  # truncated: the whole identity is available
        assert short.tooltip._display_text() == ""  # fits: nothing to add
        combo.set("other")
        assert combo.tooltip._display_text() == ""  # a short value fits: nothing to add
    finally:
        holder.destroy()


def test_preview_panel_gives_its_labels_the_width_until_thumbnails_are_requested(laptop_root: tk.Tk, tmp_path: Path) -> None:
    from src.gui.preview_panel_v2 import PreviewPanelV2

    with patch("src.gui.preview_panel_v2.PREVIEW_STATE_PATH", tmp_path / "preview_state.json"):
        panel = PreviewPanelV2(laptop_root, controller=Mock(), app_state=SimpleNamespace(preview_jobs=[]))
        holder_width = 440
        panel.pack(anchor="nw")
        panel.configure(width=holder_width)
        try:
            laptop_root.update_idletasks()
            _settle(laptop_root, 150)
            assert not panel.thumbnail_frame.winfo_ismapped()  # thumbnails are off by default: no 300 px column
            assert panel.model_label.winfo_ismapped()

            panel._show_preview_var.set(True)
            panel._on_preview_checkbox_changed()
            _settle(laptop_root, 150)
            assert panel.thumbnail_frame.winfo_ismapped()
            # Beside the info only when the labels keep their width; otherwise stacked under it.
            body_width = panel.body.winfo_width()
            side_by_side = int(panel.thumbnail_frame.grid_info()["column"]) == 1
            assert side_by_side == (body_width >= 300 + 8 + panel._preview_label_min_width())
        finally:
            panel.destroy()
