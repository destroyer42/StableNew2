from __future__ import annotations

from pathlib import Path

from src.gui_v2.adapters.learning_adapter_v2 import (
    LearningRecordSummary,
    list_recent_learning_records,
    list_recent_summaries,
    update_record_feedback,
)
from src.learning.learning_record import LearningRecord, LearningRecordWriter


def _record(run_id: str, rating: int | None = None, tags: str | None = None) -> LearningRecord:
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
        metadata={"rating": rating, "tags": tags or ""},
    )


def test_list_recent_summaries(tmp_path: Path):
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1", rating=4, tags="good"))
    writer.append_record(_record("r2", rating=5, tags="great,sharp"))
    records = list_recent_learning_records(tmp_path)
    summaries = list_recent_summaries(tmp_path, limit=5)
    assert len(records) == 2
    assert isinstance(summaries[0], LearningRecordSummary)
    assert summaries[0].run_id in {"r1", "r2"}
    assert summaries[0].tags is not None


def test_update_record_feedback_appends(tmp_path: Path):
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record("r1", rating=3))
    updated = update_record_feedback(tmp_path, "r1", rating=5, tags=["nice"])
    assert updated is not None
    lines = (tmp_path / "learning_records.jsonl").read_text().splitlines()
    assert len(lines) == 2
    final = list_recent_learning_records(tmp_path)[0]
    assert final.metadata.get("rating") == 5
    assert "nice" in str(final.metadata.get("tags"))
