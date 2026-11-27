"""N13: the Video Workflow engine picker's Show experimental switch (real Tk, production controller, no Comfy)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from tests.helpers.make_video_313 import ANIMATE2_ID, RECOMMENDED_ID, make_app, make_window

pytestmark = pytest.mark.gui

PROMPT_MODE = "wan_animate2_prompt_i2v_v1"
CK_ARM = "wan22_i2v_a14b_4step_ck_v1"
HUNYUAN_8 = "hunyuan_video15_i2v_480p_8step_v1"


@pytest.fixture
def tab(tk_root, tmp_path):
    app, _controller, _service = make_app(tmp_path)
    frame = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(frame)
    yield frame
    frame.destroy()


def _offered(tab) -> list[str]:
    return [tab._workflow_label_to_id[label] for label in tab.workflow_combo["values"]]


def test_show_experimental_is_off_and_the_arms_and_prompt_mode_are_not_offered(tab) -> None:
    assert tab.show_experimental_var.get() is False
    assert str(tab.show_experimental_check.cget("text")) == "Show experimental"
    offered = _offered(tab)
    assert RECOMMENDED_ID in offered
    assert CK_ARM not in offered and HUNYUAN_8 not in offered and PROMPT_MODE not in offered


def test_turning_it_on_offers_the_unrated_arms_but_never_prompt_mode(tab) -> None:
    tab.show_experimental_var.set(True)
    offered = _offered(tab)
    assert CK_ARM in offered and HUNYUAN_8 in offered
    assert PROMPT_MODE not in offered
    tab.show_experimental_var.set(False)
    assert CK_ARM not in _offered(tab)


def test_driving_clip_engines_stay_offered_without_the_switch(tab) -> None:
    assert tab.select_task("follow_clip")
    assert ANIMATE2_ID in _offered(tab)
    assert tab.workflow_var.get() == ANIMATE2_ID


def test_a_restored_hidden_engine_stays_selected_and_offered(tab) -> None:
    state = tab.get_video_workflow_state()
    tab.restore_video_workflow_state({**state, "workflow_id": CK_ARM})
    assert tab.workflow_var.get() == CK_ARM
    assert CK_ARM in _offered(tab)
    assert "CK attention" in tab.workflow_label_var.get()
    # A retired engine named by stored state still loads (nothing is refused), labelled as before.
    tab.restore_video_workflow_state({**state, "workflow_id": PROMPT_MODE})
    assert tab.workflow_var.get() == PROMPT_MODE
    assert "Wan-Animate-2" in tab.workflow_label_var.get()


def test_the_switch_is_saved_with_the_form_and_restored(tab) -> None:
    assert tab.get_video_workflow_state()["show_experimental"] is False
    tab.show_experimental_var.set(True)
    state = tab.get_video_workflow_state()
    assert state["show_experimental"] is True
    assert "show_experimental" not in tab.get_video_workflow_state(for_submission=True)
    tab.show_experimental_var.set(False)
    tab.restore_video_workflow_state(state)
    assert tab.show_experimental_var.get() is True
    assert CK_ARM in _offered(tab)
