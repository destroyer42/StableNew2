from unittest import mock

from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import WebUIConnectionState
from src.queue.job_model import JobStatus


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


def test_on_set_auto_run_updates_job_service_and_starts_when_queued():
    controller = PipelineController()
    controller._app_state = mock.Mock()
    controller._app_state.is_queue_paused = False
    controller._job_controller = mock.Mock()
    controller._job_service = mock.Mock()
    controller._job_service.queue = mock.Mock()
    controller._job_service.queue.list_jobs.return_value = [mock.Mock(status=JobStatus.QUEUED)]

    controller.on_set_auto_run_v2(True)

    assert controller._job_service.auto_run_enabled is True
    controller._job_controller.set_auto_run_enabled.assert_called_once_with(True)
    controller._job_service.resume.assert_called_once()


def test_sync_auto_run_setting_reads_app_state_flag():
    controller = PipelineController()
    controller._job_service = mock.Mock()
    controller._app_state = mock.Mock()
    controller._app_state.auto_run_queue = True

    controller._sync_auto_run_setting()

    assert controller._job_service.auto_run_enabled is True


def test_sync_auto_run_setting_falls_back_to_job_controller_when_no_app_state():
    controller = PipelineController()
    controller._job_service = mock.Mock()
    controller._job_service.auto_run_enabled = False
    controller._app_state = None
    controller._job_controller = mock.Mock()
    controller._job_controller.auto_run_enabled = True

    controller._sync_auto_run_setting()

    assert controller._job_service.auto_run_enabled is True


def test_on_queue_remove_refreshes_app_state_when_job_removed():
    controller = PipelineController()
    controller._app_state = mock.Mock()
    controller._job_service = mock.Mock()
    controller._job_service.job_queue = mock.Mock()
    controller._job_service.job_queue.remove.return_value = object()
    controller._refresh_app_state_queue = mock.Mock()

    result = controller.on_queue_remove_job_v2("job-1")

    assert result is True
    controller._job_service.job_queue.remove.assert_called_once_with("job-1")
    controller._refresh_app_state_queue.assert_called_once()
