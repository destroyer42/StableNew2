"""VID-FINISH in the Video Workflow tab: off by default, per job, warned beside Queue.

Real Tk widgets, the production controller and builder, a recording stand-in for ``JobService``. No GPU, ComfyUI or
weights.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from tests.helpers.make_video_313 import make_app, make_image

pytestmark = pytest.mark.gui


@pytest.fixture
def tab(tk_root, tmp_path):
    app, _controller, _service = make_app(tmp_path)
    frame = VideoWorkflowTabFrameV2(tk_root, app_controller=app, app_state=SimpleNamespace())
    frame.source_image_var.set(str(make_image(tmp_path / "src.png")))
    yield frame
    frame.destroy()


def test_finishing_is_off_by_default_and_sends_nothing(tab) -> None:
    assert tab.finish_panel.value() is None
    assert "finishing" not in tab.get_video_workflow_state(for_submission=True)
    assert "experimental" not in tab.queue_block_reason_var.get().lower()


def test_the_chosen_options_are_sent_with_the_job_but_not_saved_with_the_form(tab) -> None:
    tab.finish_panel.loop_var.set("Ping-pong (forward, back)")
    tab.finish_panel.trim_start_var.set("0.5")

    expected = {"loop_mode": "ping_pong", "trim_start_seconds": "0.5"}
    assert tab.get_video_workflow_state(for_submission=True)["finishing"] == expected
    assert "finishing" not in tab.get_video_workflow_state()
    assert tab.finish_panel.summary() == ["trimmed", "ping-pong loop"]


def test_ticking_the_upscale_warns_beside_queue_without_blocking_it(tab) -> None:
    tab.finish_panel.upscale_var.set(True)

    assert "SeedVR2 upscale is experimental" in tab.queue_block_reason_var.get()
    assert str(tab.queue_workflow_button.cget("state")) == "normal"

    tab.finish_panel.upscale_var.set(False)
    assert "SeedVR2" not in tab.queue_block_reason_var.get()


def test_a_restored_form_takes_its_own_finishing_or_none(tab) -> None:
    tab.restore_video_workflow_state({"finishing": {"loop_mode": "crossfade", "upscale": True}})
    assert tab.finish_panel.value() == {"loop_mode": "crossfade", "upscale": True}

    tab.restore_video_workflow_state({"prompt": "a saved form never carries finishing"})
    assert tab.finish_panel.value() is None


def test_make_video_starts_with_everything_off(tab) -> None:
    tab.finish_panel.upscale_var.set(True)
    tab.finish_panel.trim_end_var.set("2")

    tab.apply_make_video_defaults()

    assert tab.finish_panel.value() is None
