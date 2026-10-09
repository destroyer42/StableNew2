"""PR-GUI-111: thumbnail request recovery, truncation-gated focus tooltips, experimental opt-in transitions."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from src.gui.tooltip import attach_tooltip, install_full_value_tooltips
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.widgets.thumbnail_widget_v2 import ThumbnailWidget

SPAWN = "src.utils.thread_registry.ThreadRegistry.spawn"


def _settle(root: tk.Tk, ms: int = 120) -> None:
    root.after(ms, root.quit)
    root.mainloop()


@pytest.fixture
def shown_root(tk_root: tk.Tk):
    tk_root.geometry("900x600+0+0")
    tk_root.deiconify()
    yield tk_root
    tk_root.withdraw()


def _image(tmp_path: Path, name: str = "a.png") -> Path:
    path = tmp_path / name
    Image.new("RGB", (64, 48), (10, 120, 200)).save(path)
    return path


# --- Scope A: thumbnail request recovery ----------------------------------------------------------------------------


def test_worker_start_failure_clears_the_inflight_marker_and_allows_a_retry(
    shown_root: tk.Tk, tmp_path: Path
) -> None:
    thumb = ThumbnailWidget(shown_root, width=200, height=200)
    thumb.pack()
    path = _image(tmp_path)
    try:
        with patch(SPAWN, side_effect=RuntimeError("cannot start worker")):
            thumb.set_image_from_path(path)  # must not raise into the Tk callback
        assert thumb._inflight_path is None  # no phantom decode is "running"
        assert thumb._current_path == str(path) and thumb._open_path == str(path)  # source stays selected/openable
        assert "Loading" not in str(thumb._placeholder_shown)  # a neutral failure state, not an endless spinner

        spawned: list[dict] = []
        with patch(SPAWN, side_effect=lambda **kw: spawned.append(kw)):
            thumb.set_image_from_path(path)  # the same path is retried normally
        assert len(spawned) == 1 and thumb._inflight_path == str(path)
    finally:
        thumb.destroy()


def test_worker_start_failure_of_an_old_request_never_clears_a_newer_one(
    shown_root: tk.Tk, tmp_path: Path
) -> None:
    thumb = ThumbnailWidget(shown_root, width=200, height=200)
    thumb.pack()
    first, second = _image(tmp_path, "one.png"), _image(tmp_path, "two.png")
    try:

        def start_then_supersede(**_kw):
            # While "starting" the first worker, a newer selection arrives and becomes the live request.
            with patch(SPAWN, side_effect=lambda **kw: None):
                thumb.set_image_from_path(second)
            raise RuntimeError("late start failure of the superseded request")

        with patch(SPAWN, side_effect=start_then_supersede):
            thumb.set_image_from_path(first)
        assert thumb._inflight_path == str(second)  # the newer request's marker is untouched
        assert thumb._current_path == str(second)
    finally:
        thumb.destroy()


def test_unexpected_decode_exception_resolves_to_a_recoverable_failure(shown_root: tk.Tk, tmp_path: Path) -> None:
    thumb = ThumbnailWidget(shown_root, width=200, height=200)
    thumb.pack()
    path = _image(tmp_path)
    try:
        with patch("src.utils.image_utils.load_image_thumbnail", side_effect=MemoryError("decode blew up")):
            thumb.set_image_from_path(path)
            deadline = 0
            while thumb._inflight_path is not None and deadline < 40:
                _settle(shown_root, 50)  # worker callbacks only land inside the real main loop
                deadline += 1
        assert thumb._inflight_path is None  # not stranded
        assert "Loading" not in str(thumb._placeholder_shown)
        spawned: list[dict] = []
        with patch(SPAWN, side_effect=lambda **kw: spawned.append(kw)):
            thumb.set_image_from_path(path)
        assert len(spawned) == 1  # recoverable: the same path decodes again
    finally:
        thumb.destroy()


def test_healthy_duplicate_requests_and_stale_results_keep_their_guards(shown_root: tk.Tk, tmp_path: Path) -> None:
    thumb = ThumbnailWidget(shown_root, width=200, height=200)
    thumb.pack()
    first, second = _image(tmp_path, "one.png"), _image(tmp_path, "two.png")
    spawned: list[dict] = []
    try:
        with patch(SPAWN, side_effect=lambda **kw: spawned.append(kw)):
            thumb.set_image_from_path(first)
            old_request = thumb._request_id
            thumb.set_image_from_path(first)  # a real decode is active: suppressed
            assert len(spawned) == 1
            thumb.set_image_from_path(second)
            assert len(spawned) == 2
        thumb._on_image_loaded(Image.new("RGB", (8, 8), "red"), old_request, str(first))
        assert thumb._photo_image is None  # the superseded result did not win
        pending = thumb._request_id
        thumb.destroy()
        thumb._on_image_loaded(Image.new("RGB", (8, 8), "red"), pending, str(second))  # after destroy: no-op
    finally:
        if thumb.winfo_exists():
            thumb.destroy()


# --- Scope B: focus tooltips only for truncated values --------------------------------------------------------------

LONG_VALUE = "a_very_long_checkpoint_identity_v1.0_final_pruned_fp16_ema.safetensors"


def _combos(root: tk.Tk):
    holder = ttk.Frame(root)
    holder.pack()
    narrow = ttk.Combobox(holder, values=[LONG_VALUE], width=10, state="readonly")
    narrow.set(LONG_VALUE)
    narrow.pack()
    wide = ttk.Combobox(holder, values=["x"], width=30, state="readonly")
    wide.set("x")
    wide.pack()
    attach_tooltip(wide, "Ordinary field help")
    attach_tooltip(narrow, "Model help")
    _settle(root, 80)
    install_full_value_tooltips(holder)
    return holder, narrow, wide


def test_keyboard_focus_on_a_fitting_value_does_not_schedule_a_tooltip(shown_root: tk.Tk) -> None:
    holder, narrow, wide = _combos(shown_root)
    try:
        wide.event_generate("<FocusIn>")
        assert wide.tooltip._after_id is None  # nothing to add: no unnecessary help popup on focus
        assert wide.tooltip._window is None
    finally:
        holder.destroy()


def test_keyboard_focus_on_a_truncated_value_shows_the_whole_value_and_help(shown_root: tk.Tk) -> None:
    holder, narrow, _wide = _combos(shown_root)
    try:
        narrow.event_generate("<FocusIn>")
        assert narrow.tooltip._after_id is not None  # scheduled because truncation warrants it
        narrow.tooltip.show()
        label_texts = [str(w.cget("text")) for w in narrow.tooltip._window.winfo_children()]
        assert LONG_VALUE in label_texts[0] and "Model help" in label_texts[0]
        narrow.event_generate("<FocusOut>")
        assert narrow.tooltip._window is None and narrow.tooltip._after_id is None
    finally:
        holder.destroy()


def test_pointer_hover_still_shows_ordinary_help_for_a_fitting_value(shown_root: tk.Tk) -> None:
    holder, _narrow, wide = _combos(shown_root)
    try:
        wide.event_generate("<Enter>")
        assert wide.tooltip._after_id is not None  # hover behaviour is unchanged
        assert wide.tooltip._display_text() == "Ordinary field help"
        wide.event_generate("<Leave>")
        assert wide.tooltip._after_id is None
    finally:
        holder.destroy()


def test_repeated_installation_adds_no_duplicate_handlers(shown_root: tk.Tk) -> None:
    holder, narrow, wide = _combos(shown_root)
    try:
        before = {seq: narrow.bind(seq) for seq in ("<FocusIn>", "<FocusOut>", "<<ComboboxSelected>>")}
        tooltip = narrow.tooltip
        assert install_full_value_tooltips(holder) == 0
        assert {seq: narrow.bind(seq) for seq in before} == before
        assert narrow.tooltip is tooltip
        narrow.event_generate("<FocusIn>")
        first_job = tooltip._after_id
        narrow.event_generate("<FocusIn>")  # a second focus event reschedules; it never stacks a second job
        assert tooltip._after_id != first_job and tooltip._after_id is not None
        narrow.event_generate("<FocusOut>")
        assert tooltip._after_id is None
    finally:
        holder.destroy()


# --- Scope C: experimental opt-in transitions -----------------------------------------------------------------------


class _Controller:
    SPECS = {
        "exp_a": True,
        "exp_b": True,
        "plain": False,
    }

    def __init__(self) -> None:
        self.submissions: list[dict[str, object]] = []

    def build_video_workflow_defaults(self) -> dict[str, object]:
        return {
            "workflow_id": "exp_a",
            "motion_profile": "gentle",
            "camera_intent": {"preset": "none", "strength": 0.35},
            "controlnet": {"model": "depth", "weight": 1.0, "guidance_start": 0.0, "guidance_end": 1.0},
            "depth_input": {"mode": "none", "path": ""},
            "output_route": "Reprocess",
        }

    def get_video_workflow_specs(self) -> list[dict[str, object]]:
        return [
            {
                "workflow_id": name,
                "workflow_version": "1",
                "backend_id": "comfy",
                "display_name": name,
                "experimental": experimental,
            }
            for name, experimental in self.SPECS.items()
        ]

    def submit_video_workflow_job(self, *, source_image_path: str, form_data: dict[str, object]) -> str:
        self.submissions.append(dict(form_data))
        return "job-1"


@pytest.fixture
def video_tab(shown_root: tk.Tk):
    controller = _Controller()
    tab = VideoWorkflowTabFrameV2(shown_root, app_controller=controller, app_state=SimpleNamespace())
    tab.pack(fill="both", expand=True)
    tab.source_image_var.set("C:/tmp/source.png")
    _settle(shown_root, 200)
    yield tab, controller
    tab.destroy()


def _opt_in_visible(tab: VideoWorkflowTabFrameV2) -> bool:
    return bool(tab.experimental_opt_in_check.winfo_ismapped())


def _select(tab: VideoWorkflowTabFrameV2, workflow: str, root: tk.Tk) -> None:
    tab.workflow_var.set(workflow)
    _settle(root, 80)


def test_opt_in_is_never_carried_across_workflow_switches(shown_root: tk.Tk, video_tab) -> None:
    tab, _controller = video_tab
    assert tab.workflow_var.get() == "exp_a"
    assert _opt_in_visible(tab) and tab.experimental_opt_in_var.get() is False  # visible, initially unchecked

    tab.experimental_opt_in_var.set(True)
    _select(tab, "plain", shown_root)
    assert not _opt_in_visible(tab) and tab.experimental_opt_in_var.get() is False  # hidden and cleared

    _select(tab, "exp_a", shown_root)
    assert _opt_in_visible(tab) and tab.experimental_opt_in_var.get() is False  # back again: still not authorised

    tab.experimental_opt_in_var.set(True)
    _select(tab, "exp_b", shown_root)  # experimental -> a different experimental workflow
    assert _opt_in_visible(tab) and tab.experimental_opt_in_var.get() is False


def test_ordinary_edits_do_not_revoke_a_deliberate_opt_in(shown_root: tk.Tk, video_tab) -> None:
    tab, _controller = video_tab
    tab.experimental_opt_in_var.set(True)
    tab.seed_var.set("1234")
    tab.motion_profile_var.set("dynamic")
    tab.output_route_var.set("Testing")
    tab.set_source_image_path("C:/tmp/other.png")
    _settle(shown_root, 120)
    assert tab.workflow_var.get() == "exp_a"
    assert tab.experimental_opt_in_var.get() is True  # same workflow identity: the choice stands


def test_submissions_carry_the_explicit_per_job_authorisation(shown_root: tk.Tk, video_tab) -> None:
    tab, controller = video_tab
    with patch("src.gui.views.video_workflow_tab_frame_v2.messagebox"):
        tab.experimental_opt_in_var.set(True)
        tab.queue_workflow_button.invoke()
        assert controller.submissions[-1]["workflow_id"] == "exp_a"
        assert controller.submissions[-1]["experimental_opt_in"] is True

        _select(tab, "exp_b", shown_root)  # switching clears it: the next job is not authorised by default
        tab.queue_workflow_button.invoke()
        assert controller.submissions[-1]["workflow_id"] == "exp_b"
        assert controller.submissions[-1]["experimental_opt_in"] is False

        tab.experimental_opt_in_var.set(True)
        tab.queue_workflow_button.invoke()
        assert controller.submissions[-1]["experimental_opt_in"] is True

        _select(tab, "plain", shown_root)
        tab.queue_workflow_button.invoke()
        assert controller.submissions[-1]["workflow_id"] == "plain"
        assert controller.submissions[-1]["experimental_opt_in"] is False
    assert len(controller.submissions) == 4  # one deliberate click, one existing callback each
