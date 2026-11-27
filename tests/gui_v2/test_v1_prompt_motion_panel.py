"""V1-1: the prompt-only motion panel (presets, motion phrase, seconds-first duration, Advanced, summary line).

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording ``JobService``
stand-in from ``tests.helpers.make_video_313``.  No GPU, Comfy process, model or network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.pipeline.njr_core_v26 import thaw_json
from src.video.motion_intent import MOTION_INTENT_FIELD
from src.video.motion_presets import preset_by_id
from src.video.workflow_tasks import FIELD_LENGTH, TASKS
from tests.helpers.make_video_313 import RECOMMENDED_ID, TI2V_ID, make_app, make_image, make_window

pytestmark = pytest.mark.gui

PROMPT = "a woman on a balcony at dusk"


@pytest.fixture
def env(tk_root, tmp_path):
    app, controller, service = make_app(tmp_path)
    # Hermetic: no RIFE. With RIFE "found" the form suggests smoothing on, and admission then needs a real RIFE
    # executable, which this host may have and CI does not.
    controller.rife_available = lambda: False
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    tab.prompt_text.insert("1.0", PROMPT)
    tab.source_image_var.set(make_image(tmp_path / "source.png"))
    yield SimpleNamespace(app=app, controller=controller, service=service, tab=tab)
    tab.destroy()


def _stage(njr):
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


def _queue(env):
    count = len(env.service.submitted)
    env.tab._on_submit()
    assert len(env.service.submitted) == count + 1, env.tab.status_var.get()
    return env.service.submitted[-1]


def _frames(tab):
    return tab._frame_count_labels.get(tab.frame_count_var.get())


def test_the_tasks_read_as_intents_and_keep_their_ids():
    labels = {task.task_id: task.label for task in TASKS}
    assert labels["animate"] == "Prompt-only motion"
    assert labels["follow_clip"] == "Follow a driving video"


def test_an_untouched_form_submits_what_it_always_did(env):
    tab = env.tab
    assert tab.workflow_var.get() == RECOMMENDED_ID
    panel = tab.motion_intent_panel
    assert panel.preset_var.get() == "None" and panel.phrase_var.get() == ""
    assert panel.duration_var.get() == "5.1 s"
    assert panel.duration_line_var.get() == "5.1 s · 81 frames at 16 fps"
    assert panel.composed_var.get() == ""
    tab.seed_var.set("11")
    form = tab.get_video_workflow_state(for_submission=True)
    assert form["prompt"] == PROMPT and form["frame_count"] == 81
    record = form[MOTION_INTENT_FIELD]
    assert record["preset"] is None and record["duration"]["frames"] == 81
    assert record["basis"]["workflow_id"].startswith("Recommended")
    assert record["basis"][FIELD_LENGTH] == "The engine's default length."
    njr = _queue(env)
    assert njr.positive_prompt == PROMPT
    assert _stage(njr)["frame_count"] == 81
    assert njr.extra_metadata["video_workflow"][MOTION_INTENT_FIELD]["preset"] is None
    # The record is provenance only: without it the same form builds the same executable job.
    plain = {key: value for key, value in form.items() if key != MOTION_INTENT_FIELD}
    env.controller.submit_video_workflow_job(
        source_image_path=tab.source_image_var.get(), form_data=plain
    )
    without = env.service.submitted[-1]
    assert _stage(without) == _stage(njr) and without.positive_prompt == njr.positive_prompt


def test_a_preset_sets_duration_and_phrase_and_the_preview_is_what_is_sent(env):
    tab = env.tab
    panel = tab.motion_intent_panel
    panel.choose_preset("Walk")
    walk = preset_by_id("walk")
    assert panel.phrase_var.get() == walk.prompt_only.motion_phrase
    assert _frames(tab) == 81
    assert "untested" in panel.preset_status_var.get()
    assert "Walk" in tab.suggested_line.summary_var.get()
    composed = f"{PROMPT}, {walk.prompt_only.motion_phrase}"
    assert panel.composed_var.get() == f"Sends: {composed}"
    tab.seed_var.set("3")
    njr = _queue(env)
    assert njr.positive_prompt == composed
    assert njr.extra_metadata["video_workflow"][MOTION_INTENT_FIELD]["preset"] == {
        "id": "walk",
        "version": 1,
        "modified": False,
    }
    panel.choose_preset("Dance")
    assert _frames(tab) == 121
    assert "7.6 s" in panel.duration_var.get()


def test_typed_seconds_round_to_a_legal_length_and_pin_it(env):
    tab = env.tab
    panel = tab.motion_intent_panel
    panel.enter_duration("3")
    assert _frames(tab) == 49 and FIELD_LENGTH in tab._pins.pinned
    assert panel.duration_var.get() == "3.1 s"
    assert panel.duration_line_var.get() == "3.1 s · 49 frames at 16 fps"
    assert tab.get_video_workflow_state(for_submission=True)[MOTION_INTENT_FIELD]["duration"] == {
        "requested_seconds": 3.0,
        "frames": 49,
        "fps": 16,
    }
    panel.enter_duration("6")
    assert "Longer than 81 frames" in panel.duration_advisory_var.get()


def test_an_impossible_duration_changes_nothing(env):
    tab = env.tab
    tab.motion_intent_panel.enter_duration("fast")
    assert _frames(tab) == 81 and FIELD_LENGTH not in tab._pins.pinned
    assert "seconds" in tab.status_var.get()


def test_retyping_the_same_length_is_not_an_edit(env):
    tab = env.tab
    tab.motion_intent_panel.enter_duration("5")
    assert _frames(tab) == 81 and FIELD_LENGTH not in tab._pins.pinned


def test_edited_fields_survive_a_preset_change_and_reset_to_preset_restores_it(env):
    tab = env.tab
    panel = tab.motion_intent_panel
    panel.enter_duration("3")
    panel.choose_preset("Dance")
    assert _frames(tab) == 49  # the operator's length is kept
    assert panel.phrase_var.get() == preset_by_id("dance").prompt_only.motion_phrase
    assert "Dance (modified)" in tab.suggested_line.summary_var.get()
    assert panel.preset_status_var.get().startswith("Modified.")
    assert panel.reset_preset_button.winfo_manager()
    panel.reset_preset_button.invoke()
    assert _frames(tab) == 121
    assert "(modified)" not in tab.suggested_line.summary_var.get()
    assert not panel.reset_preset_button.winfo_manager()


def test_an_edited_phrase_is_pinned(env):
    tab = env.tab
    panel = tab.motion_intent_panel
    panel.phrase_var.set("turns slowly toward the camera")
    panel.choose_preset("Gesture")
    assert panel.phrase_var.get() == "turns slowly toward the camera"
    assert _frames(tab) == 49
    record = tab.get_video_workflow_state(for_submission=True)[MOTION_INTENT_FIELD]
    assert record["preset"]["modified"] is True
    assert record["basis"]["motion_phrase"] == "Your choice."


def test_choosing_no_preset_clears_an_unedited_phrase(env):
    panel = env.tab.motion_intent_panel
    panel.choose_preset("Subtle")
    assert panel.phrase_var.get()
    panel.choose_preset("None")
    assert panel.phrase_var.get() == "" and _frames(env.tab) == 81


def test_another_engine_resolves_the_same_preset_to_its_own_length(env):
    tab = env.tab
    tab.motion_intent_panel.choose_preset("Walk")
    tab.workflow_var.set(TI2V_ID)
    assert _frames(tab) == 81  # 5 s is longer than TI2V-5B allows: its longest
    assert tab.motion_intent_panel.duration_var.get() == "3.4 s (longest)"


def test_other_tasks_neither_show_nor_send_the_phrase(env):
    tab = env.tab
    tab.motion_intent_panel.choose_preset("Walk")
    assert tab.select_task("follow_clip")
    panel = tab.motion_intent_panel
    assert not panel.phrase_entry.winfo_manager() and not panel.preset_row.winfo_manager()
    form = tab.get_video_workflow_state(for_submission=True)
    assert form["prompt"] == PROMPT and MOTION_INTENT_FIELD not in form
    assert tab.select_task("animate")
    assert panel.phrase_entry.winfo_manager()


def test_saved_state_keeps_preset_and_phrase_and_a_submission_does_not(env):
    tab = env.tab
    tab.motion_intent_panel.choose_preset("Gesture")
    saved = tab.get_video_workflow_state()
    assert saved["motion_preset"] == "gesture" and saved["prompt"] == PROMPT
    assert saved["motion_phrase"] == preset_by_id("gesture").prompt_only.motion_phrase
    submitted = tab.get_video_workflow_state(for_submission=True)
    assert "motion_preset" not in submitted and "motion_phrase" not in submitted
    tab.motion_intent_panel.choose_preset("None")
    tab.restore_video_workflow_state(saved)
    assert tab.motion_intent_panel.preset_var.get() == "Gesture"
    assert tab.motion_intent_panel.phrase_var.get() == saved["motion_phrase"]
    assert _frames(tab) == 49
