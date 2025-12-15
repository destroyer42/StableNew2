from unittest import mock

from src.controller.app_controller import AppController
from src.controller.webui_connection_controller import WebUIConnectionState
from src.queue.job_model import Job


def test_queue_job_fails_when_webui_not_ready():
    controller = AppController.__new__(AppController)
    controller.pipeline_controller = mock.Mock()
    controller.webui_connection_controller = mock.Mock()
    controller.webui_connection_controller.is_webui_ready_strict.return_value = False
    controller.webui_connection_controller.get_state.return_value = WebUIConnectionState.READY
    controller.webui_connection_controller.last_readiness_error = "not listening"
    controller._append_log = lambda *args, **kwargs: None

    job = Job(job_id="ph-001")
    job._normalized_record = {"dummy": True}

    result = controller._execute_job(job)

    assert not result["success"]
    assert result["metadata"]["execution_path"] == "ready_gate"
    assert "WebUI not ready" in (result.get("error") or "")
    controller.pipeline_controller._run_job.assert_not_called()

