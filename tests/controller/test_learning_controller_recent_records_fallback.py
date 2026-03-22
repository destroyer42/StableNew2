from __future__ import annotations

from pathlib import Path

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningState
from src.learning.learning_record import LearningRecord, LearningRecordWriter


class _NoReviewExecutionController:
    """Execution-controller shape used by the runtime learning tab."""

    def set_completion_callback(self, _callback) -> None:
        return

    def set_failure_callback(self, _callback) -> None:
        return

    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def _write_record(path: Path, run_id: str = "run-1") -> LearningRecord:
    writer = LearningRecordWriter(path)
    record = LearningRecord(
        run_id=run_id,
        timestamp="2026-03-21T20:00:00",
        base_config={"stage": "txt2img"},
        variant_configs=[],
        randomizer_mode="",
        randomizer_plan_size=0,
        primary_model="juggernautXL",
        primary_sampler="DPM++ 2M",
        primary_scheduler="Karras",
        primary_steps=30,
        primary_cfg_scale=6.5,
        metadata={"prompt": "portrait"},
        stage_plan=[],
        stage_events=[],
        outputs=[],
        sidecar_priors={},
    )
    writer.append_record(record)
    return record


def test_list_recent_records_falls_back_to_canonical_records(tmp_path: Path) -> None:
    records_path = tmp_path / "data" / "learning" / "learning_records.jsonl"
    _write_record(records_path)
    controller = LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
        learning_record_writer=LearningRecordWriter(records_path),
        execution_controller=_NoReviewExecutionController(),
    )

    records = controller.list_recent_records(limit=5)

    assert len(records) == 1
    assert records[0].run_id == "run-1"


def test_save_feedback_falls_back_to_canonical_records(tmp_path: Path) -> None:
    records_path = tmp_path / "data" / "learning" / "learning_records.jsonl"
    original = _write_record(records_path, run_id="run-feedback")
    controller = LearningController(
        learning_state=LearningState(),
        pipeline_controller=object(),
        learning_record_writer=LearningRecordWriter(records_path),
        execution_controller=_NoReviewExecutionController(),
    )

    updated = controller.save_feedback(original, rating=4, tags="good_face")

    assert updated is not None
    assert updated.metadata.get("rating") == 4
    assert updated.metadata.get("tags") == "good_face"
