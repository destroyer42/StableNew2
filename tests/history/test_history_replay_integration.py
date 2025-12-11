from __future__ import annotations

from dataclasses import asdict

from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_history_service import JobHistoryService
from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION, validate_entry
from src.pipeline.job_models_v2 import JobView, NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_queue import JobQueue


def test_replay_invokes_njr_path() -> None:
    captured: dict[str, NormalizedJobRecord] = {}

    def execute_njr(record: NormalizedJobRecord) -> dict:
        captured["record"] = record
        return {"status": "ok"}

    controller = JobExecutionController(execute_job=execute_njr)
    njr = NormalizedJobRecord(
        job_id="replay-001",
        config={"prompt": "castle", "model": "v1-5"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=123,
    )
    record = HistoryRecord(
        id=njr.job_id,
        njr_snapshot=asdict(njr),
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

    controller.replay(record)

    assert "record" in captured
    assert captured["record"].job_id == njr.job_id


def test_history_record_summary_returns_job_view(tmp_path) -> None:
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    njr = NormalizedJobRecord(
        job_id="replay-002",
        config={"prompt": "forest", "model": "v1-5"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=456,
    )
    record = HistoryRecord(
        id=njr.job_id,
        njr_snapshot={"normalized_job": asdict(njr)},
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
