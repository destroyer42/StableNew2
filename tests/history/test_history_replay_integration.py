from __future__ import annotations

import time

from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_history_service import JobHistoryService
from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION, validate_entry
from src.pipeline.job_models_v2 import JobView, NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_pipeline_njr


def test_replay_invokes_njr_path() -> None:
    captured: dict[str, NormalizedJobRecord] = {}

    def execute_njr(record: NormalizedJobRecord) -> dict:
        captured["record"] = record
        return {"status": "ok"}

    controller = JobExecutionController(execute_job=execute_njr)
    njr = make_pipeline_njr(
        job_id="replay-001", positive_prompt="castle", base_model="v1-5", seed=123
    )
    record = HistoryRecord(
        id=njr.job_id,
        njr_snapshot={"normalized_job": njr.to_dict()},
        timestamp="2025-01-01T00:00:00Z",
        status="completed",
        history_schema=HISTORY_SCHEMA_VERSION,
        metadata={},
        runtime={},
        result=PipelineRunResult(
            run_id=njr.job_id,
            success=True,
            error=None,
            variants=[],
            learning_records=[],
            metadata={},
        ).to_dict(),
        ui_summary={},
    )

    ok, errors = validate_entry(record.to_dict())
    assert ok, errors

    replay_job_id = controller.replay(record)
    deadline = time.monotonic() + 2.0
    while "record" not in captured and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert "record" in captured
    assert captured["record"].job_id == replay_job_id
    assert captured["record"].job_id != njr.job_id
    assert captured["record"].source.parent_job_id == njr.job_id


def test_history_record_summary_returns_job_view(tmp_path) -> None:
    store = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=store)
    service = JobHistoryService(queue, store)

    njr = make_pipeline_njr(
        job_id="replay-002", positive_prompt="forest", base_model="v1-5", seed=456
    )
    record = HistoryRecord(
        id=njr.job_id,
        njr_snapshot={"normalized_job": njr.to_dict()},
        timestamp="2025-01-02T00:00:00Z",
        status="completed",
        history_schema=HISTORY_SCHEMA_VERSION,
        metadata={},
        runtime={},
        result=PipelineRunResult(
            run_id=njr.job_id,
            success=True,
            error=None,
            variants=[],
            learning_records=[],
            metadata={},
        ).to_dict(),
        ui_summary={},
    )
    view = service.summarize_history_record(record)
    assert isinstance(view, JobView)
    assert view.job_id == record.id
    assert view.result == record.result
