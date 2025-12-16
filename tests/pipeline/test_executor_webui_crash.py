import pytest
from unittest.mock import Mock, patch

from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.pipeline.executor import Pipeline, PipelineStageError
from src.utils import StructuredLogger
from src.utils.error_envelope_v2 import get_attached_envelope


def test_pipeline_generates_diagnostics_bundle_on_webui_crash():
    diag_context = {
        "request_summary": {
            "endpoint": "/sdapi/v1/txt2img",
            "stage": "txt2img",
            "method": "POST",
            "status": 500,
            "session_id": 12345,
        },
        "webui_unavailable": True,
        "crash_suspected": True,
    }

    class StubClient:
        def generate_images(self, *, stage, payload, timings=None):
            return GenerateOutcome(
                error=GenerateError(
                    code=GenerateErrorCode.CONNECTION,
                    message="Simulated downstream failure",
                    stage=stage,
                    details={"diagnostics": diag_context},
                )
            )

    tail_payload = {
        "stdout_tail": "line1\nline2",
        "stderr_tail": "error line",
        "pid": 999,
        "running": False,
    }

    client = StubClient()
    pipeline = Pipeline(client, StructuredLogger(output_dir="tests/tmp_executor"))

    manager_stub = Mock()
    manager_stub.get_recent_output_tail.return_value = tail_payload

    service_stub = Mock()
    mock_build = service_stub.build_async
    with patch("src.pipeline.executor.get_global_webui_process_manager", return_value=manager_stub), patch(
        "src.pipeline.executor._get_diagnostics_service",
        return_value=service_stub,
    ):
        with pytest.raises(PipelineStageError) as excinfo:
            pipeline._generate_images("txt2img", {})

    envelope = get_attached_envelope(excinfo.value)
    assert envelope is not None
    context = envelope.context
    assert context["webui_stdout_tail"] == tail_payload["stdout_tail"]
    assert context["webui_stderr_tail"] == tail_payload["stderr_tail"]
    assert context["webui_pid"] == tail_payload["pid"]
    assert context["webui_running"] is False
    assert context["webui_session_id"] == 12345

    mock_build.assert_called_once()
    _, kwargs = mock_build.call_args
    assert kwargs["reason"] == "webui_crash_suspected"
    assert kwargs["extra_context"]["diagnostics"] == diag_context
    assert kwargs["webui_tail"] == tail_payload
