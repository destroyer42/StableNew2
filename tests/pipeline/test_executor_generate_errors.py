from __future__ import annotations

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
