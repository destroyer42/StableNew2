from __future__ import annotations

from pathlib import Path

from src.learning.learning_record import LearningRecord, LearningRecordWriter


def _record(idx: int) -> LearningRecord:
    return LearningRecord(
        run_id=f"run-{idx}",
        timestamp=f"2025-01-01T00:00:0{idx}",
        base_config={"txt2img": {"model": f"m{idx}", "steps": 20}},
        variant_configs=[],
        randomizer_mode="",
        randomizer_plan_size=0,
        primary_model=f"m{idx}",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=20,
        primary_cfg_scale=7.5,
        metadata={},
    )


def test_learning_record_writer_appends_jsonl_lines(tmp_path: Path):
    writer = LearningRecordWriter(tmp_path)
    writer.append_record(_record(1))
    writer.append_record(_record(2))
    contents = writer.records_path.read_text().splitlines()
    assert len(contents) == 2
    assert all(line.strip().startswith("{") for line in contents)
