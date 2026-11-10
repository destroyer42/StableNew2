"""PR-VID-UX-360: the task-first Video Workflow tab.

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording
``JobService`` stand-in from ``tests.helpers.make_video_313``.  No GPU, Comfy process, model or network.
"""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.views.video_workflow_task_panel_v2 import (
    PinTracker,
    SuggestedSettingsLine,
    WorkflowTaskSelector,
)
from tests.helpers.make_video_313 import ANIMATE2_ID, TI2V_ID, make_app, make_window

pytestmark = pytest.mark.gui


def _make_env(tk_root, tmp_path, *, rife: bool):
    app, controller, service = make_app(tmp_path)
    controller.rife_available = lambda: rife
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    return SimpleNamespace(
        app=app, controller=controller, service=service, tab=tab, root=tk_root, tmp=tmp_path
    )


@pytest.fixture
def env(tk_root, tmp_path):
    made = _make_env(tk_root, tmp_path, rife=True)
    yield made
    made.tab.destroy()


@pytest.fixture
def env_no_rife(tk_root, tmp_path):
    made = _make_env(tk_root, tmp_path, rife=False)
    yield made
    made.tab.destroy()


# ---------------------------------------------------------------- widgets


def test_selector_lists_four_tasks_and_reverts_on_refusal(tk_root):
    calls: list[str] = []

    def on_select(task_id: str) -> bool:
        calls.append(task_id)
        return task_id != "batch"

    sel = WorkflowTaskSelector(tk_root, on_select=on_select)
    assert list(sel.buttons) == ["animate", "follow_clip", "sequence", "batch"]
    sel.set_task("animate")
    sel.buttons["batch"].invoke()
    assert calls == ["batch"]
    assert sel.task_var.get() == "animate"
    sel.buttons["sequence"].invoke()
    assert sel.task_var.get() == "sequence"


def test_set_task_does_not_call_back(tk_root):
    calls: list[str] = []
    sel = WorkflowTaskSelector(tk_root, on_select=lambda t: calls.append(t) or True)
    sel.set_task("follow_clip")
    assert calls == [] and sel.task_var.get() == "follow_clip"


def test_unavailable_task_is_disabled_with_its_reason(tk_root):
    sel = WorkflowTaskSelector(tk_root, on_select=lambda t: True)
    sel.set_availability({"follow_clip": "No installed workflow supports this."})
    assert str(sel.buttons["follow_clip"].cget("state")) == "disabled"
    assert str(sel.buttons["animate"].cget("state")) != "disabled"
    sel.set_availability({})
    assert str(sel.buttons["follow_clip"].cget("state")) != "disabled"


def test_summary_line_joins_and_drops_empty_parts(tk_root):
    line = SuggestedSettingsLine(tk_root, on_change=lambda: None, on_reset=lambda: None)
    line.set_summary(["Engine X", "", "3.4 s", "smoothed"])
    assert line.summary_var.get() == "Engine X · 3.4 s · smoothed"
    line.set_notes(["one", "", "two"])
    assert line.notes_var.get() == "one\ntwo"


def test_summary_line_buttons_call_back(tk_root):
    calls: list[str] = []
    line = SuggestedSettingsLine(
        tk_root, on_change=lambda: calls.append("change"), on_reset=lambda: calls.append("reset")
    )
    line.change_button.invoke()
    line.reset_button.invoke()
    assert calls == ["change", "reset"]


def test_pin_tracker_pins_operator_writes_only(tk_root):
    var = tk.StringVar(master=tk_root)
    pins = PinTracker()
    pins.watch("seed", var)
    with pins.applying():
        var.set("1")
    assert pins.pinned == set()
    var.set("2")
    assert pins.pinned == {"seed"}
    pins.clear()
    assert pins.pinned == set()
    pins.pin_all(["seed", "smooth"])
    assert pins.pinned == {"seed", "smooth"}


# ---------------------------------------------------------------- the tab


def test_default_task_is_animate_with_the_recommended_engine(env):
    assert env.tab.current_task() == "animate"
    assert env.tab.workflow_var.get() == TI2V_ID
    assert env.tab.smooth_var.get() is True
    assert env.tab.task_selector.task_var.get() == "animate"


def test_default_task_hides_everything_it_does_not_need(env):
    tab = env.tab
    for widget in (tab.follow_clip_frame, tab.sequence_panel, tab.batch_panel):
        assert not widget.winfo_manager()
    assert tab.motion_library_panel.master is tab.follow_clip_tools
    for section in (
        tab.advanced_section,
        tab.keyframes_section,
        tab.compare_section,
        tab.details_section,
    ):
        assert not section.is_expanded()


def test_summary_line_names_the_engine_and_what_was_set(env):
    summary = env.tab.suggested_line.summary_var.get()
    assert "smoothed" in summary and "random seed" in summary
    assert env.tab.workflow_label_var.get() in summary


def test_change_button_opens_the_settings_editor(env):
    env.tab.suggested_line.change_button.invoke()
    assert env.tab.advanced_section.is_expanded()
    assert str(env.tab.suggested_line.change_button.cget("text")) == "Hide"
    assert env.tab.workflow_combo.winfo_manager()


def test_engine_picker_offers_only_engines_for_the_task(env):
    labels = list(env.tab.workflow_combo["values"])
    ids = [env.tab._workflow_label_to_id[label] for label in labels]
    assert TI2V_ID in ids and ANIMATE2_ID not in ids
    env.tab.select_task("follow_clip")
    ids = [env.tab._workflow_label_to_id[label] for label in env.tab.workflow_combo["values"]]
    assert ANIMATE2_ID in ids and TI2V_ID not in ids


def test_follow_clip_selects_a_driving_engine_and_shows_its_inputs(env):
    assert env.tab.select_task("follow_clip")
    assert env.tab.workflow_var.get() == ANIMATE2_ID
    assert env.tab.follow_clip_frame.winfo_manager()
    assert env.tab.pose_video_frame.winfo_manager()
    assert env.tab.experimental_opt_in_var.get() is False  # never ticked for the operator
    assert str(env.tab.queue_workflow_button.cget("state")) == "disabled"


def test_task_follows_an_engine_chosen_some_other_way(env):
    env.tab.workflow_var.set(ANIMATE2_ID)
    assert env.tab.current_task() == "follow_clip"
    assert env.tab.follow_clip_frame.winfo_manager()


def test_sequence_turns_smoothing_off_and_shows_the_shot_list(env):
    assert env.tab.select_task("sequence")
    assert env.tab.smooth_var.get() is False
    assert env.tab.sequence_panel.winfo_manager()
    assert env.tab.select_task("animate")
    assert env.tab.smooth_var.get() is True
    assert not env.tab.sequence_panel.winfo_manager()


def test_operator_edits_survive_a_task_switch(env):
    env.tab.seed_var.set("42")
    env.tab.smooth_var.set(False)
    env.tab.select_task("batch")
    env.tab.select_task("animate")
    assert env.tab.seed_var.get() == "42"
    assert env.tab.smooth_var.get() is False


def test_reset_to_suggested_clears_pins(env):
    env.tab.smooth_var.set(False)
    env.tab.seed_var.set("7")
    env.tab.suggested_line.reset_button.invoke()
    assert env.tab.smooth_var.get() is True
    assert env.tab.seed_var.get() == ""


def test_batch_task_shows_the_source_strip(env):
    assert env.tab.select_task("batch")
    assert env.tab.batch_panel.winfo_manager()
    assert env.tab.select_task("animate")
    assert not env.tab.batch_panel.winfo_manager()


def test_task_switch_refused_while_a_batch_step_runs(env):
    env.tab.select_task("batch")
    env.tab._batch_session.sources = [object()]
    env.tab._batch_session.busy = "preview"
    assert env.tab.select_task("animate") is False
    assert env.tab.current_task() == "batch"
    assert env.tab.task_selector.task_var.get() == "batch"
    env.tab._batch_session.busy = None
    env.tab._batch_session.sources = []


def test_leaving_follow_clip_drops_driving_state(env, tmp_path):
    env.tab.select_task("follow_clip")
    env.tab.pose_video_var.set(str(tmp_path / "m.mp4"))
    env.tab._library_binding = {"sha256": "x"}
    env.tab._library_bound_path = str(tmp_path / "m.mp4")
    env.tab.select_task("animate")
    assert env.tab.pose_video_var.get() == ""
    assert env.tab._library_binding is None and env.tab._library_bound_path == ""
    assert "pose_video_path" not in env.tab.get_video_workflow_state(for_submission=True)


def test_smoothing_is_suggested_off_when_rife_is_missing(env_no_rife):
    assert env_no_rife.tab.smooth_var.get() is False
    assert "interpolation" not in env_no_rife.tab.get_video_workflow_state(for_submission=True)


def test_pinned_smoothing_without_rife_is_warned_not_flipped(env_no_rife):
    tab = env_no_rife.tab
    tab.smooth_var.set(True)
    tab.select_task("batch")
    tab.select_task("animate")
    assert tab.smooth_var.get() is True
    assert "Smoothing cannot run" in tab.suggested_line.notes_var.get()


def test_submitted_form_carries_no_task_and_the_same_fields(env):
    form = env.tab.get_video_workflow_state(for_submission=True)
    assert "task" not in form
    assert form["workflow_id"] == TI2V_ID
    assert form["interpolation"] == {"enabled": True}
    assert form["experimental_opt_in"] is False


def test_keyframes_section_is_hidden_when_the_engine_declares_none(env):
    visible = env.tab._workflow_map[TI2V_ID]["form_visibility"]
    declares = any(
        visible.get(key)
        for key in ("end_anchor", "mid_anchors", "camera_intent", "depth_conditioning")
    )
    assert bool(env.tab.keyframes_section.winfo_manager()) is declares


def test_default_task_fits_the_minimum_window(env):
    env.root.deiconify()
    env.root.geometry("1280x680")
    env.tab.pack(fill="both", expand=True)
    env.root.update()
    line = env.tab.suggested_line
    assert line.winfo_ismapped()
    assert line.winfo_rooty() + line.winfo_height() <= env.root.winfo_rooty() + 680
    env.root.withdraw()


# ---------------------------------------------------------------- saved state and handoffs


def test_saved_state_carries_the_task_but_a_submission_does_not(env):
    env.tab.select_task("sequence")
    assert env.tab.get_video_workflow_state()["task"] == "sequence"
    assert "task" not in env.tab.get_video_workflow_state(for_submission=True)


def test_state_round_trip_keeps_task_and_pins_everything(env):
    env.tab.select_task("follow_clip")
    env.tab.smooth_var.set(False)
    saved = env.tab.get_video_workflow_state()
    assert saved["task"] == "follow_clip"
    env.tab.suggested_line.reset_button.invoke()
    env.tab.select_task("animate")
    assert env.tab.smooth_var.get() is True
    env.tab.restore_video_workflow_state(saved)
    assert env.tab.current_task() == "follow_clip"
    assert env.tab.workflow_var.get() == ANIMATE2_ID
    assert env.tab.smooth_var.get() is False
    env.tab.select_task("follow_clip")
    assert env.tab.smooth_var.get() is False  # restored values are the operator's, not suggestions


def test_old_state_without_task_infers_it(env):
    env.tab.restore_video_workflow_state({"workflow_id": ANIMATE2_ID})
    assert env.tab.current_task() == "follow_clip"
    env.tab.restore_video_workflow_state({"workflow_id": TI2V_ID})
    assert env.tab.current_task() == "animate"


def test_restore_without_task_keeps_a_task_the_engine_can_serve(env):
    # The sequence panel restores a form snapshot (no task key) while its own task is selected.
    env.tab.select_task("sequence")
    env.tab.restore_video_workflow_state({"workflow_id": TI2V_ID})
    assert env.tab.current_task() == "sequence"


def test_unknown_task_falls_back_and_a_retired_workflow_is_shown_not_swapped(env):
    env.tab.restore_video_workflow_state({"workflow_id": TI2V_ID, "task": "nonsense"})
    assert env.tab.current_task() == "animate"
    env.tab.select_task("follow_clip")
    env.tab.restore_video_workflow_state({"workflow_id": "gone_v9", "task": "follow_clip"})
    assert env.tab.current_task() == "animate"
    assert env.tab.workflow_var.get() == "gone_v9"  # never silently replaced by another engine
    assert env.tab.select_task("animate")  # choosing the task again picks an installed engine
    assert env.tab.workflow_var.get() == TI2V_ID


def test_make_video_selects_animate(env):
    env.tab.select_task("follow_clip")
    assert env.tab.apply_make_video_defaults() == TI2V_ID
    assert env.tab.current_task() == "animate"


def test_batch_handoff_selects_batch_and_a_single_image_returns_to_animate(env, tmp_path):
    from tests.helpers.make_video_313 import make_image

    first = make_image(tmp_path / "a.png")
    second = make_image(tmp_path / "b.png", color="maroon")
    assert env.tab.set_source_batch([first, second])
    assert env.tab.current_task() == "batch"
    env.tab.apply_make_video_defaults()
    assert env.tab.current_task() == "batch"  # the Review handoff calls both; batch must stand
    env.tab.set_source_image_path(first)
    assert env.tab.current_task() == "animate"
    assert env.tab.source_image_var.get() == first


def test_library_handoff_selects_follow_clip(env, tmp_path):
    from src.video.motion_library.handoff import HandoffPlan

    clip = tmp_path / "walk.mp4"
    clip.write_bytes(b"x")
    version = env.tab._workflow_map[ANIMATE2_ID]["workflow_version"]
    plan = HandoffPlan(
        ok=True,
        asset_id="asset-1",
        path=str(clip),
        sha256="ab" * 32,
        workflow_id=ANIMATE2_ID,
        workflow_version=version,
    )
    env.tab._apply_library_handoff(plan)
    assert env.tab.current_task() == "follow_clip"
    assert env.tab.workflow_var.get() == ANIMATE2_ID
    assert env.tab.pose_video_var.get() == str(clip)


# ---------------------------------------------------------------- whole-branch review fixes

PROMPT_ENGINE_ID = "wan_animate2_prompt_i2v_v1"


def test_many_images_can_share_one_driving_clip(env, tmp_path):
    # Reachable before the task-first form: a batch whose engine follows a driving clip.
    from tests.helpers.make_video_313 import make_image

    tab = env.tab
    assert tab.select_task("follow_clip")
    assert tab.batch_panel.winfo_manager() == "grid"
    tab.pose_video_var.set(str(tmp_path / "walk.mp4"))
    engine = tab.workflow_var.get()
    first = make_image(tmp_path / "a.png")
    second = make_image(tmp_path / "b.png", color="maroon")
    assert tab.set_source_batch([first, second])
    assert tab.current_task() == "follow_clip"
    assert tab.workflow_var.get() == engine
    assert tab.pose_video_var.get() == str(tmp_path / "walk.mp4")


def test_source_preview_and_guidance_are_not_tied_to_the_driving_clip_task(env):
    tab = env.tab
    assert tab.current_task() == "animate"
    panel = tab.motion_readiness_panel
    widget = panel
    while widget is not None and widget is not tab:
        assert widget is not tab.follow_clip_frame
        widget = widget.master
    assert tab.select_task("follow_clip")
    assert tab.pose_video_frame.winfo_manager() == "grid"
    assert tab.follow_clip_tools.winfo_manager() == "grid"


def test_a_storyboard_restore_shows_the_storyboard(env):
    # Job History "open as Storyboard" restores the form through the sequence panel from any task.
    tab = env.tab
    assert tab.current_task() == "animate"
    tab._restore_form_for_storyboard({"workflow_id": TI2V_ID})
    assert tab.current_task() == "sequence"
    assert tab.sequence_panel.winfo_manager() == "grid"


def test_the_operators_engine_choice_survives_a_task_round_trip(env):
    tab = env.tab
    tab.workflow_var.set(PROMPT_ENGINE_ID)  # an operator pick in "Animate an image"
    assert tab.current_task() == "animate"
    assert tab.select_task("follow_clip")
    assert tab.workflow_var.get() != PROMPT_ENGINE_ID
    assert tab.select_task("animate")
    assert tab.workflow_var.get() == PROMPT_ENGINE_ID
    tab.suggested_line.reset_button.invoke()
    assert tab.workflow_var.get() == TI2V_ID
    assert tab.select_task("follow_clip") and tab.select_task("animate")
    assert tab.workflow_var.get() == TI2V_ID


def test_browsing_a_single_image_leaves_the_batch_task(env, tmp_path, monkeypatch):
    from tests.helpers.make_video_313 import make_image

    image = make_image(tmp_path / "one.png")
    assert env.tab.select_task("batch")
    monkeypatch.setattr(
        "src.gui.views.video_workflow_tab_frame_v2.filedialog.askopenfilename",
        lambda **_kwargs: image,
    )
    env.tab._on_browse_source()
    assert env.tab.current_task() == "animate"
    assert env.tab.source_image_var.get() == image


def test_a_restore_without_a_workflow_keeps_task_and_engine_consistent(env):
    tab = env.tab
    assert tab.select_task("follow_clip")
    engine = tab.workflow_var.get()
    tab.restore_video_workflow_state({})
    assert tab.current_task() == "follow_clip"
    assert tab.workflow_var.get() == engine
