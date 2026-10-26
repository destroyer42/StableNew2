"""Application commands exercise a headless port, with no view/widget access."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.ports.presentation_actions import PresentationActions
from src.utils.error_envelope_v2 import wrap_exception


def make_controller():
    controller = AppController.__new__(AppController)
    controller.main_window = object()
    controller.presentation_actions = Mock(spec=PresentationActions)
    controller._append_log = Mock()
    return controller, controller.presentation_actions


def test_dialog_commands_pass_only_intent_and_payload():
    controller, actions = make_controller()
    envelope = wrap_exception(ValueError("boom"), subsystem="test")
    controller.open_debug_hub()
    controller.explain_job("")
    actions.explain_job.assert_not_called()
    controller.explain_job("job-1")
    controller._show_structured_error_modal(envelope)
    actions.open_debug_hub.assert_called_once_with()
    actions.explain_job.assert_called_once_with("job-1")
    actions.show_structured_error.assert_called_once_with(envelope)
    assert not hasattr(controller, "_error_modal")


def test_image_navigation_preserves_lineage_status_and_return(tmp_path):
    controller, actions = make_controller()
    path = tmp_path / "source.png"
    path.touch()
    lineage = {"source_job_id": "parent"}
    assert controller.send_image_to_video_workflow(path, lineage) == str(path)
    actions.image_to_video_workflow.assert_called_once_with(
        image_path=str(path),
        status_message="Loaded into Video Workflow tab: source.png",
        lineage=lineage,
    )
    with pytest.raises(FileNotFoundError):
        controller.send_image_to_video_workflow(tmp_path / "missing.png")


@pytest.mark.parametrize("destination", ["video", "movie"])
def test_history_bundle_and_image_fallback_preserve_results(destination):
    controller, actions = make_controller()
    controller._get_history_entry_by_job_id = Mock(return_value=object())
    bundle = {"primary_path": "clip.mp4", "frame_paths": ["b.png", "a.png"]}
    controller._get_history_video_bundle = Mock(return_value=bundle)
    controller._get_history_image_path = Mock(return_value="source.png")
    if destination == "video":
        actions.bundle_to_video_workflow.return_value = "b.png"
        assert controller.send_history_job_image_to_video_workflow("job-1") == "b.png"
        actions.bundle_to_video_workflow.assert_called_once_with(
            bundle=bundle,
            status_message="Loaded video output into Video Workflow tab.",
        )
        actions.bundle_to_video_workflow.return_value = None
        controller.send_image_to_video_workflow = Mock(return_value="source.png")
        assert controller.send_history_job_image_to_video_workflow("job-1") == "source.png"
        controller.send_image_to_video_workflow.assert_called_once_with(
            "source.png",
            {"source_job_id": "job-1"},
        )
    else:
        assert controller.send_history_job_to_movie_clips("job-1") == "clip.mp4"
        actions.bundle_to_movie_clips.assert_called_once_with(
            bundle=bundle,
            status_message="Loaded history output into Movie Clips.",
        )
        controller._get_history_video_bundle.return_value = None
        assert controller.send_history_job_to_movie_clips("job-1") == "source.png"
        actions.image_to_movie_clips.assert_called_once_with(
            image_path="source.png",
            status_message="Loaded source.png into Movie Clips.",
        )


def test_attachment_delegates_wiring_then_flushes_status():
    controller, actions = make_controller()
    calls = []
    controller.main_window = SimpleNamespace(
        attach_controller_actions=lambda ctrl: calls.append(ctrl) or actions,
    )
    controller._pending_status_text = "pending"
    controller._update_webui_state = lambda state: calls.append(state)
    controller._update_status = lambda text: calls.append(text)
    controller._attach_to_gui()
    assert calls == [controller, "disconnected", "pending"]
    assert controller.presentation_actions is actions
    controller.detach_presentation_actions()
    actions.detach.assert_called_once_with()
    with pytest.raises(RuntimeError, match="Presentation actions are not available"):
        controller._require_presentation_actions()


def test_replacing_or_detaching_window_fences_previous_attachment():
    controller, actions = make_controller()
    controller.app_state = None
    controller._projection_sink = Mock()
    controller.pipeline_controller = Mock()
    controller._job_lifecycle_logger = Mock()
    controller._update_status = Mock()
    controller.load_packs = Mock()
    controller.set_main_window(None)
    actions.detach.assert_called_once_with()
    assert controller.main_window is None
    assert controller.presentation_actions is None
    with pytest.raises(RuntimeError, match="Main window is not available"):
        controller._require_presentation_actions()
