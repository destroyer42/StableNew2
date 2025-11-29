"""LearningRecord serialization and writer tests."""

from __future__ import annotations

from pathlib import Path

from src.learning.learning_record import LearningRecord, LearningRecordWriter


def _sample_record() -> LearningRecord:
    return LearningRecord(
        run_id="abc123",
        timestamp="2025-01-01T00:00:00",
        base_config={"txt2img": {"model": "base", "steps": 20}},
        variant_configs=[{"txt2img": {"model": "variant", "steps": 30}}],
        randomizer_mode="fanout",
        randomizer_plan_size=2,
        primary_model="variant",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=30,
        primary_cfg_scale=7.5,
        metadata={"pack_name": "demo"},
    )


def test_learning_record_roundtrip_json():
    record = _sample_record()
    json_blob = record.to_json()
    restored = LearningRecord.from_json(json_blob)
    assert restored == record


def test_learning_record_writer(tmp_path: Path):
    record = _sample_record()
    writer = LearningRecordWriter(tmp_path)
    writer.write(record)
    records_file = writer.records_path
    assert records_file.exists()
    lines = records_file.read_text().splitlines()
    assert len(lines) == 1
    loaded = LearningRecord.from_json(lines[0])
    assert loaded.primary_model == record.primary_model
    assert loaded.randomizer_mode == record.randomizer_mode
