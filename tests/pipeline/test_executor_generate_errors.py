from __future__ import annotations

import pytest

from typing import Any

from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome
from src.pipeline.executor import Pipeline, PipelineStageError
from src.utils import StructuredLogger


class DummyClient:
    def __init__(self, outcome: GenerateOutcome) -> None:
        self.outcome = outcome

    def generate_images(self, *, stage: str, payload: dict[str, Any]) -> GenerateOutcome:
        return self.outcome


def test_generate_outcome_error_raises_pipeline_stage_error():
    outcome = GenerateOutcome(
        error=GenerateError(code=GenerateErrorCode.INVALID_MODEL, message="bad model", stage="txt2img")
    )
    client = DummyClient(outcome)
    pipeline = Pipeline(client, StructuredLogger())

    with pytest.raises(PipelineStageError) as excinfo:
        pipeline._generate_images("txt2img", {})

    assert excinfo.value.error.code == GenerateErrorCode.INVALID_MODEL
    assert excinfo.value.error.stage == "txt2img"
