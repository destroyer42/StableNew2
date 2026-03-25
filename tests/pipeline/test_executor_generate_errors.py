from __future__ import annotations

import json
from typing import Any

import pytest

from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.pipeline.executor import Pipeline, PipelineStageError
from src.utils import StructuredLogger
from unittest.mock import patch


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
