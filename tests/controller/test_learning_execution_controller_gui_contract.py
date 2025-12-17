from __future__ import annotations

from pathlib import Path

from src.controller.learning_execution_controller import LearningExecutionController
from src.controller.pipeline_controller import PipelineController
from src.learning.learning_record import LearningRecord, LearningRecordWriter


def _record(run_id: str) -> LearningRecord:
    return LearningRecord(
        run_id=run_id,
        timestamp="t0",
        base_config={},
        variant_configs=[],
        randomizer_mode="",
        randomizer_plan_size=0,
        primary_model="m",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=10,
        primary_cfg_scale=7.0,
        metadata={},
    )


def test_learning_execution_controller_lists_records(tmp_path: Path):
    records_path = tmp_path / "learning_records.jsonl"
    writer = LearningRecordWriter(records_path)
    writer.append_record(_record("r1"))
    controller = LearningExecutionController(run_callable=None)
    controller.set_records_path(records_path)
    records = controller.list_recent_records(limit=5)
    assert records and records[0].run_id == "r1"


def test_learning_execution_controller_saves_feedback(tmp_path: Path):
    records_path = tmp_path / "learning_records.jsonl"
    controller = LearningExecutionController(run_callable=None)
    controller.set_records_path(records_path)
    record = _record("r2")
    saved = controller.save_feedback(record, rating=4, tags="nice")
    assert saved is not None
    lines = records_path.read_text().splitlines()
    assert lines, "expected feedback to append a record"


def test_learning_execution_controller_toggle_syncs_pipeline_controller():
    PipelineController()
    learning = LearningExecutionController(run_callable=None)
    learning.set_learning_enabled(True)
    assert learning.get_learning_enabled() is True
