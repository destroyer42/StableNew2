"""V1 end frame: the "Start and end image" task of the Video Workflow tab.

Real Tk widgets; the production ``VideoWorkflowController`` and NJR builder sit behind the recording ``JobService``
stand-in from ``tests.helpers.make_video_313``.  No GPU, Comfy process, model or network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.pipeline.njr_core_v26 import thaw_json
from src.video.driver_intent import DEFAULT_BETWEEN_PROMPT
from src.video.workflow_catalog_wan_a14b import WAN_A14B_FLF_ID
from tests.helpers.make_video_313 import RECOMMENDED_ID, make_app, make_image, make_window

pytestmark = pytest.mark.gui


@pytest.fixture
def env(tk_root, tmp_path, monkeypatch):
    app, controller, service = make_app(tmp_path)
    controller.rife_available = lambda: False
    tab = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    app.main_window = make_window(tab)
    start = make_image(tmp_path / "start.png", size=(480, 832))
    end = make_image(tmp_path / "end.png", size=(960, 1664), color="maroon")
    monkeypatch.setattr(
        "src.gui.views.video_workflow_tab_frame_v2.filedialog.askopenfilename",
        lambda **_kwargs: end,
    )
    yield SimpleNamespace(tab=tab, service=service, start=start, end=end, tmp=tmp_path)
    tab.destroy()


def _queue(env):
    count = len(env.service.submitted)
    env.tab._on_submit()
    assert len(env.service.submitted) == count + 1, env.tab.status_var.get()
    return env.service.submitted[-1]


def _stage(njr):
    return thaw_json(next(s for s in njr.stage_chain if s.stage_type == "video_workflow").extra)


def test_a_clip_between_two_images_is_queued_with_the_experimental_engine(env):
    tab = env.tab
    assert tab.select_task("between_images")
    assert tab.workflow_var.get() == WAN_A14B_FLF_ID
    assert tab.end_image_frame.winfo_manager()
    assert not tab.advanced_section.is_expanded() and not tab.keyframes_section.winfo_manager()
    assert "experimental" in tab.queue_block_reason_var.get().lower()
    tab.source_image_var.set(env.start)
    tab._on_browse_end_anchor()
    assert tab.motion_intent_panel.composed_var.get() == f"Sends: {DEFAULT_BETWEEN_PROMPT}"
    tab.motion_intent_panel.enter_duration("3")
    njr = _queue(env)
    stage = _stage(njr)
    assert stage["workflow_id"] == WAN_A14B_FLF_ID and stage["frame_count"] == 49
    assert njr.positive_prompt == DEFAULT_BETWEEN_PROMPT
    assert stage["end_anchor_path"] != env.end and stage["end_anchor_sha256"]
    assert njr.extra_metadata["video_workflow"]["experimental_opt_in"] is True


def test_queue_without_an_end_image_says_what_is_missing(env):
    tab = env.tab
    assert tab.select_task("between_images")
    tab.source_image_var.set(env.start)
    tab._on_submit()
    assert env.service.submitted == []
    assert "end anchor image" in tab.status_var.get()


def test_a_wider_end_image_is_warned_about_beside_queue(env):
    tab = env.tab
    assert tab.select_task("between_images")
    tab.source_image_var.set(env.start)
    wide = make_image(env.tmp / "wide.png", size=(1280, 720))
    tab.end_anchor_var.set(wide)
    tab._refresh_queue_gate()
    assert "end picture is cut away" in tab.queue_block_reason_var.get()
    assert str(tab.queue_workflow_button.cget("state")) == "normal"


def test_leaving_the_task_returns_to_the_approved_engine_without_the_end_image(env):
    tab = env.tab
    assert tab.select_task("between_images")
    tab.source_image_var.set(env.start)
    tab._on_browse_end_anchor()
    assert tab.select_task("animate")
    assert tab.workflow_var.get() == RECOMMENDED_ID
    assert not tab.end_image_frame.winfo_manager()
    form = tab.get_video_workflow_state(for_submission=True)
    assert form["end_anchor_path"] == "" and form["experimental_opt_in"] is False


def test_choosing_the_engine_another_way_brings_the_task(env):
    env.tab.workflow_var.set(WAN_A14B_FLF_ID)
    assert env.tab.current_task() == "between_images"
    assert env.tab.end_image_frame.winfo_manager()
