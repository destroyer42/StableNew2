from __future__ import annotations

from src.controller.job_history_service import JobHistoryService
from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION
from src.pipeline.job_models_v2 import JobView
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.helpers.njr_factory import make_pipeline_njr


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
