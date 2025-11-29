from unittest.mock import MagicMock, patch

import pytest

from src.gui.controller import PipelineController
from src.gui.main_window import StableNewGUI
from src.gui.state import StateManager


@pytest.fixture
def mock_controller():
    controller = MagicMock()
    controller.stop_pipeline.return_value = True
    return controller


@pytest.fixture
def gui_stub(mock_controller):
    window = StableNewGUI.__new__(StableNewGUI)
    log_mock = MagicMock()
    window.controller = mock_controller
    window.log_message = log_mock
    return window, log_mock


def test_stop_execution_running(gui_stub, mock_controller):
    win, log_mock = gui_stub
    mock_controller.stop_pipeline.return_value = True

    win._stop_execution()

    mock_controller.stop_pipeline.assert_called_once_with()
    log_mock.assert_called_once_with("⏹️ Stop requested - cancelling pipeline...", "WARNING")


def test_stop_execution_when_idle(gui_stub, mock_controller):
    win, log_mock = gui_stub
    mock_controller.stop_pipeline.return_value = False

    win._stop_execution()

    mock_controller.stop_pipeline.assert_called_once_with()
    log_mock.assert_called_once_with("⏹️ No pipeline running", "INFO")


def test_stop_execution_handles_exception(gui_stub, mock_controller):
    win, log_mock = gui_stub
    mock_controller.stop_pipeline.side_effect = RuntimeError("boom")

    win._stop_execution()

    mock_controller.stop_pipeline.assert_called_once_with()
    log_mock.assert_called_once_with("⏹️ Stop failed: boom", "ERROR")


def test_stop_pipeline_duplicate_guard():
    log_mock = MagicMock()
    controller = PipelineController(StateManager())
    controller._log = log_mock
    controller.cancel_token = MagicMock()
    controller.report_progress = MagicMock()
    controller._terminate_subprocess = MagicMock()
    controller._sync_cleanup = True

    with patch.object(controller.state_manager, "can_stop", return_value=True), patch.object(
        controller.state_manager, "transition_to", return_value=True
    ):
        assert controller.stop_pipeline() is True
        log_mock.assert_any_call("Stop requested - cancelling pipeline...", "WARNING")

    log_mock.reset_mock()
    controller._stop_in_progress = True

    with patch.object(controller.state_manager, "can_stop", return_value=True):
        assert controller.stop_pipeline() is False
        log_mock.assert_called_once_with(
            "Cleanup already in progress; ignoring duplicate stop request", "DEBUG"
        )
