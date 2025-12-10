from __future__ import annotations

from dataclasses import asdict

from src.controller.job_execution_controller import JobExecutionController
from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION, validate_entry
from src.pipeline.job_models_v2 import NormalizedJobRecord


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
        ui_summary={},
    )

    ok, errors = validate_entry(record.to_dict())
    assert ok, errors

    controller.replay(record)

    assert "record" in captured
    assert captured["record"].job_id == njr.job_id
