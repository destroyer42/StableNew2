"""Tests for learning analytics engine.

PR-LEARN-010: Analytics Dashboard
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.learning.learning_analytics import LearningAnalytics
from src.learning.learning_record import LearningRecord, LearningRecordWriter


def test_get_overall_summary_empty():
    """Verify summary with no records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(str(records_path))

        analytics = LearningAnalytics(writer)
        summary = analytics.get_overall_summary()

        assert summary.total_experiments == 0
        assert summary.total_ratings == 0
        assert summary.avg_rating == 0


def test_get_overall_summary_with_ratings():
    """Verify summary calculation with ratings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(str(records_path))

        # Create test records
        for rating in [3, 4, 5]:
            record = LearningRecord.from_pipeline_context(
                base_config={"prompt": "test"},
                variant_configs=[{"cfg": 7.0}],
                randomizer_mode="learning_experiment",
                randomizer_plan_size=1,
                metadata={
                    "experiment_name": "test_exp",
                    "user_rating": rating,
                },
            )
            writer.append_record(record)

        analytics = LearningAnalytics(writer)
        summary = analytics.get_overall_summary()

        assert summary.total_experiments == 1
        assert summary.total_ratings == 3
        assert summary.avg_rating == 4.0


def test_get_overall_summary_tracks_curation_evidence_and_reason_tags():
    """Verify staged-curation evidence is summarized separately."""
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        writer = LearningRecordWriter(str(records_path))

        record = LearningRecord.from_pipeline_context(
            base_config={"prompt": "portrait", "stage": "txt2img"},
            variant_configs=[{"sampler": "DPM++ 2M", "steps": 28, "cfg_scale": 6.5}],
            randomizer_mode="staged_curation",
            randomizer_plan_size=1,
            metadata={
                "record_kind": "staged_curation_event",
                "experiment_name": "curation:disc-1",
                "user_rating": 4.3,
                "evidence_class": "observational",
                "advancement_decision": "advanced_to_upscale",
                "reason_tags": ["good_composition", "keeper"],
            },
        )
        writer.append_record(record)

        analytics = LearningAnalytics(writer)
        summary = analytics.get_overall_summary()

        assert summary.total_experiments == 1
        assert summary.total_ratings == 1
        assert summary.evidence_class_counts == {"observational": 1}
        assert summary.decision_counts == {"advanced_to_upscale": 1}
        assert summary.reason_tag_counts == {"good_composition": 1, "keeper": 1}


def test_export_to_json():
    """Verify JSON export."""
    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        output_path = Path(tmpdir) / "analytics.json"

        writer = LearningRecordWriter(str(records_path))
        analytics = LearningAnalytics(writer)

        analytics.export_to_json(output_path)

        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)
            assert "total_experiments" in data


def test_export_to_csv():
    """Verify CSV export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        records_path = Path(tmpdir) / "records.jsonl"
        output_path = Path(tmpdir) / "analytics.csv"

        writer = LearningRecordWriter(str(records_path))
        analytics = LearningAnalytics(writer)

        analytics.export_to_csv(output_path)

        assert output_path.exists()

        with open(output_path) as f:
            content = f.read()
            assert "Experiment ID" in content
