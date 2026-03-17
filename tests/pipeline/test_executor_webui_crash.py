from unittest.mock import Mock, patch

import pytest

from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome, GenerateResult
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
    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "_check_webui_health_before_stage", return_value=None),
        patch("src.pipeline.executor.get_global_webui_process_manager", return_value=manager_stub),
        patch(
            "src.pipeline.executor._get_diagnostics_service",
            return_value=service_stub,
        ),
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


def test_pipeline_retries_once_after_executor_local_webui_recovery():
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
        "error_message": "Internal server error",
    }

    class StubClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_images(self, *, stage, payload, timings=None):
            self.calls += 1
            if self.calls == 1:
                return GenerateOutcome(
                    error=GenerateError(
                        code=GenerateErrorCode.CONNECTION,
                        message="Simulated downstream failure",
                        stage=stage,
                        details={"diagnostics": diag_context},
                    )
                )
            return GenerateOutcome(
                result=GenerateResult(
                    images=["img"],
                    info={},
                    stage=stage,
                    timings=None,
                )
            )

    client = StubClient()
    pipeline = Pipeline(client, StructuredLogger(output_dir="tests/tmp_executor"))
    manager_stub = Mock()
    manager_stub.restart_webui.return_value = True

    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "_check_webui_health_before_stage", return_value=None),
        patch("src.pipeline.executor.get_global_webui_process_manager", return_value=manager_stub),
    ):
        result = pipeline._generate_images("txt2img", {})

    assert result is not None
    assert result["images"] == ["img"]
    assert client.calls == 2
    manager_stub.restart_webui.assert_called_once()
