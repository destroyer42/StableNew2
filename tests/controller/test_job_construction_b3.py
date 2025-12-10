from __future__ import annotations

import pytest

from src.controller.pipeline_controller import PipelineController
from src.gui.state import StateManager
from src.pipeline.job_models_v2 import NormalizedJobRecord


def _make_test_record() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="b3-test-job",
        config={"prompt": "test", "model": "sdxl"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=12345,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=1000.0,
    )


def test_to_queue_job_requires_normalized_record() -> None:
    controller = PipelineController(state_manager=StateManager())
    with pytest.raises(ValueError, match="NormalizedJobRecord"):
        controller._to_queue_job(None)  # type: ignore[arg-type]


def test_to_queue_job_creates_njr_only_job() -> None:
    controller = PipelineController(state_manager=StateManager())
    record = _make_test_record()
    job = controller._to_queue_job(record)
    assert hasattr(job, "_normalized_record")
    assert job._normalized_record is record
    assert job.pipeline_config is None
