"""PR-GUI-111: truncation-gated focus tooltips, experimental opt-in transitions."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace

import pytest
from PIL import Image

from src.gui.tooltip import attach_tooltip, install_full_value_tooltips
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2

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


def _select(tab: VideoWorkflowTabFrameV2, workflow: str, root: tk.Tk) -> None:
    tab.workflow_var.set(workflow)
    _settle(root, 80)


def _opt_in(tab: VideoWorkflowTabFrameV2) -> bool:
    return bool(tab.get_video_workflow_state(for_submission=True)["experimental_opt_in"])


def test_the_opt_in_follows_the_selected_workflow_and_is_never_carried_to_an_approved_one(
    shown_root: tk.Tk, video_tab
) -> None:
    # N1 (warn, don't block): Queue on the warned header is the opt-in; it follows the workflow shown at Queue.
    tab, _controller = video_tab
    assert tab.workflow_var.get() == "exp_a"
    assert _opt_in(tab) is True  # an experimental workflow is warned, not gated
    _select(tab, "plain", shown_root)
    assert _opt_in(tab) is False  # an approved workflow never carries an opt-in
    _select(tab, "exp_b", shown_root)
    assert _opt_in(tab) is True


def test_ordinary_edits_keep_the_warning_and_the_opt_in(shown_root: tk.Tk, video_tab) -> None:
    tab, _controller = video_tab
    tab.seed_var.set("1234")
    tab.motion_profile_var.set("dynamic")
    tab.output_route_var.set("Testing")
    tab.set_source_image_path("C:/tmp/other.png")
    _settle(shown_root, 120)
    assert tab.workflow_var.get() == "exp_a"
    assert _opt_in(tab) is True
    assert "experimental" in tab.queue_block_reason_var.get()


def test_submissions_carry_the_per_job_authorisation_of_the_workflow_queued(shown_root: tk.Tk, video_tab) -> None:
    tab, controller = video_tab
    tab.queue_workflow_button.invoke()
    assert controller.submissions[-1]["workflow_id"] == "exp_a"
    assert controller.submissions[-1]["experimental_opt_in"] is True

    _select(tab, "exp_b", shown_root)
    assert str(tab.queue_workflow_button.cget("state")) == "normal"  # warned, not gated
    tab.queue_workflow_button.invoke()
    assert controller.submissions[-1]["workflow_id"] == "exp_b"
    assert controller.submissions[-1]["experimental_opt_in"] is True

    _select(tab, "plain", shown_root)
    tab.queue_workflow_button.invoke()
    assert controller.submissions[-1]["workflow_id"] == "plain"
    assert controller.submissions[-1]["experimental_opt_in"] is False
    assert len(controller.submissions) == 3  # one deliberate click, one existing callback each


# --- N1 (replaces PR-VID-GOV-316's gate): Queue shows the experimental warning beside an enabled button -------------


def _queue_state(tab: VideoWorkflowTabFrameV2) -> str:
    return str(tab.queue_workflow_button.cget("state"))


def test_an_experimental_workflow_shows_its_warning_inline_beside_an_enabled_queue(
    shown_root: tk.Tk, video_tab
) -> None:
    tab, _controller = video_tab
    assert tab.workflow_var.get() == "exp_a"
    assert _queue_state(tab) == "normal"
    assert "exp_a is experimental" in tab.queue_block_reason_var.get()
    assert "Queue runs it anyway" in tab.queue_block_reason_var.get()
    assert tab.queue_block_label.winfo_ismapped()  # the warning is visible, not only a tooltip
    assert tab.queue_block_label.master is tab.queue_workflow_button.master  # same row as the button


def test_an_approved_workflow_shows_no_warning_and_queue_stays_enabled(shown_root: tk.Tk, video_tab) -> None:
    tab, _controller = video_tab
    _select(tab, "plain", shown_root)
    assert _queue_state(tab) == "normal"
    assert tab.queue_block_reason_var.get() == "" and not tab.queue_block_label.winfo_ismapped()

    _select(tab, "exp_b", shown_root)  # back to an experimental workflow: warned again, still enabled
    assert _queue_state(tab) == "normal" and tab.queue_block_label.winfo_ismapped()
    _select(tab, "plain", shown_root)
    assert _queue_state(tab) == "normal" and not tab.queue_block_label.winfo_ismapped()


def test_a_restored_experimental_workflow_is_warned_and_saved_state_never_carries_the_opt_in(
    shown_root: tk.Tk, video_tab
) -> None:
    tab, _controller = video_tab
    tab.restore_video_workflow_state({"workflow_id": "exp_b", "experimental_opt_in": True})
    _settle(shown_root, 60)
    assert _queue_state(tab) == "normal"
    assert "exp_b is experimental" in tab.queue_block_reason_var.get()
    assert "experimental_opt_in" not in tab.get_video_workflow_state()  # not part of saved state


def test_batch_mode_still_disables_queue_independently_of_the_opt_in(
    shown_root: tk.Tk, video_tab
) -> None:
    tab, _controller = video_tab
    _select(tab, "plain", shown_root)
    tab._on_batch_mode_change(True)
    assert _queue_state(tab) == "disabled"
    assert tab.queue_block_reason_var.get() == ""  # the batch panel explains this one
    tab._on_batch_mode_change(False)
    assert _queue_state(tab) == "normal"

    _select(tab, "exp_a", shown_root)
    tab._on_batch_mode_change(True)
    assert _queue_state(tab) == "disabled"  # a warned workflow does not lift the batch-mode disable
    tab._on_batch_mode_change(False)
    assert _queue_state(tab) == "normal"
