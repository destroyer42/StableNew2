from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
import requests

from src.api.client import SDWebUIClient
from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.pipeline.executor import Pipeline, PipelineStageError
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils import StructuredLogger
from tests.helpers.njr_factory import make_queue_job


class DummyClient:
    def __init__(self, outcome: GenerateOutcome) -> None:
        self.outcome = outcome

    def generate_images(self, *, stage: str, payload: dict[str, Any]) -> GenerateOutcome:
        return self.outcome


def test_generate_outcome_error_raises_pipeline_stage_error():
    outcome = GenerateOutcome(
        error=GenerateError(
            code=GenerateErrorCode.INVALID_MODEL, message="bad model", stage="txt2img"
        )
    )
    client = DummyClient(outcome)
    pipeline = Pipeline(client, StructuredLogger())

    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "_check_webui_health_before_stage", return_value=None),
        pytest.raises(PipelineStageError) as excinfo,
    ):
        pipeline._generate_images("txt2img", {})

    assert excinfo.value.error.code == GenerateErrorCode.INVALID_MODEL
    assert excinfo.value.error.stage == "txt2img"


def test_generate_images_does_not_restart_on_structured_http_500_inference_error():
    outcome = GenerateOutcome(
        error=GenerateError(
            code=GenerateErrorCode.UNKNOWN,
            message="NansException: A tensor with NaNs was produced in Unet.",
            stage="adetailer",
            details={
                "diagnostics": {
                    "request_summary": {
                        "status": 500,
                        "response_snippet": json.dumps(
                            {
                                "error": "NansException",
                                "errors": "A tensor with NaNs was produced in Unet.",
                            }
                        ),
                    }
                }
            },
        )
    )
    client = DummyClient(outcome)
    pipeline = Pipeline(client, StructuredLogger())

    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "_check_webui_health_before_stage", return_value=None),
        patch.object(
            pipeline,
            "_attempt_webui_recovery",
            side_effect=lambda **_kwargs: pytest.fail(
                "recovery should not run for structured inference failures"
            ),
        ),
        pytest.raises(PipelineStageError) as excinfo,
    ):
        pipeline._generate_images("adetailer", {})

    assert excinfo.value.error.code == GenerateErrorCode.UNKNOWN
    assert "NansException" in excinfo.value.error.message


def test_generate_images_still_attempts_restart_on_opaque_http_500():
    outcome = GenerateOutcome(
        error=GenerateError(
            code=GenerateErrorCode.UNKNOWN,
            message="500 Server Error: Internal Server Error",
            stage="adetailer",
            details={
                "diagnostics": {
                    "request_summary": {
                        "status": 500,
                        "response_snippet": "Internal Server Error",
                    }
                }
            },
        )
    )
    client = DummyClient(outcome)
    pipeline = Pipeline(client, StructuredLogger())

    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "_check_webui_health_before_stage", return_value=None),
        patch.object(pipeline, "_attempt_webui_recovery", return_value=False) as mock_recovery,
        pytest.raises(PipelineStageError),
    ):
        pipeline._generate_images("adetailer", {})

    mock_recovery.assert_called_once_with(
        stage="adetailer",
        reason="request_http_500",
    )


def test_ambiguous_generation_fails_canonical_job_without_replay(monkeypatch):
    """Client, executor, and queue preserve one POST and a failed job."""
    post_methods: list[str] = []

    def _fake_request(self, method: str, url: str, **kwargs: object):
        post_methods.append(method)
        raise requests.ReadTimeout("response lost after dispatch")

    monkeypatch.setattr("src.api.client.requests.Session.request", _fake_request)
    client = SDWebUIClient()
    pipeline = Pipeline(client, StructuredLogger())
    pipeline._true_ready_gated = True
    queue = JobQueue()
    job = make_queue_job("ambiguous-generation")
    queue.submit(job)
    runner = SingleNodeJobRunner(
        job_queue=queue,
        run_callable=lambda _job: pipeline._generate_images("txt2img", {"prompt": "test"}),
    )

    with (
        patch.object(pipeline, "_ensure_webui_true_ready", return_value=None),
        patch.object(pipeline, "_check_webui_health_before_stage", return_value=None),
        patch.object(pipeline, "_attempt_webui_recovery", return_value=True) as recovery,
    ):
        with pytest.raises(PipelineStageError):
            runner.run_once(job)

    stored = queue.get_job(job.job_id)
    assert post_methods == ["POST"]
    assert recovery.call_count == 1
    assert pipeline._true_ready_gated is False
    assert stored is not None
    assert stored.status == JobStatus.FAILED
    assert stored.result is None
    assert "may have executed" in (stored.error_message or "")
