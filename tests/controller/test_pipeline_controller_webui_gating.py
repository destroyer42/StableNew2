from unittest import mock

from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import WebUIConnectionState


def test_run_blocked_when_webui_not_ready(monkeypatch):
    controller = PipelineController()
    controller._webui_connection = mock.Mock()
    controller._webui_connection.ensure_connected.return_value = WebUIConnectionState.ERROR
    controller._build_pipeline_config_from_state = mock.Mock()

    result = controller.start_pipeline()

    assert result is False
    controller._build_pipeline_config_from_state.assert_not_called()


def test_run_allowed_when_webui_ready(monkeypatch):
    controller = PipelineController()
    controller._webui_connection = mock.Mock()
    controller._webui_connection.ensure_connected.return_value = WebUIConnectionState.READY
    controller._build_pipeline_config_from_state = mock.Mock(return_value=mock.Mock())
    controller._run_pipeline_job = mock.Mock(return_value={})

    # run payload immediately instead of async submission
    controller._job_controller.submit_pipeline_run = lambda fn: fn()

    result = controller.start_pipeline()

    assert result is True
    controller._build_pipeline_config_from_state.assert_called_once()
    controller._run_pipeline_job.assert_called_once()
