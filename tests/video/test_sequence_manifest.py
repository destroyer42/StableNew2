"""Unit tests for src/video/sequence_manifest.py — PR-VIDEO-216."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.video.sequence_manifest import (
    SEQUENCE_MANIFEST_SCHEMA,
    build_sequence_manifest,
    write_sequence_manifest,
)
from src.video.sequence_models import SegmentProvenanceRecord, VideoSequenceResult


def _make_result(
    completed: int = 2,
    total: int = 2,
    sequence_id: str = "seq-test-001",
) -> VideoSequenceResult:
    records = [
        SegmentProvenanceRecord(
            sequence_id=sequence_id,
            job_id="job-abc",
            segment_index=i,
            segment_id=f"seg{i:04d}",
            source_image_path=f"/img/frame{i}.png" if i == 0 else None,
            primary_output_path=f"/out/seg{i}.mp4",
            manifest_path=None,
        )
        for i in range(completed)
    ]
    return VideoSequenceResult(
        sequence_id=sequence_id,
        job_id="job-abc",
        total_segments=total,
        completed_segments=completed,
        segment_provenance=records,
        all_output_paths=[f"/out/seg{i}.mp4" for i in range(completed)],
    )


class TestBuildSequenceManifest:
    def test_schema_key(self):
        result = _make_result()
        m = build_sequence_manifest(result, sequence_job_dict={})
        assert m["schema"] == SEQUENCE_MANIFEST_SCHEMA

    def test_custom_schema(self):
        result = _make_result()
        m = build_sequence_manifest(result, sequence_job_dict={}, schema="custom_v2")
        assert m["schema"] == "custom_v2"

    def test_sequence_id(self):
        result = _make_result(sequence_id="my-seq")
        m = build_sequence_manifest(result, sequence_job_dict={})
        assert m["sequence_id"] == "my-seq"

    def test_is_complete_true(self):
        result = _make_result(completed=2, total=2)
        m = build_sequence_manifest(result, sequence_job_dict={})
        assert m["is_complete"] is True

    def test_is_complete_false(self):
        result = _make_result(completed=1, total=3)
        m = build_sequence_manifest(result, sequence_job_dict={})
        assert m["is_complete"] is False

    def test_segment_provenance_count(self):
        result = _make_result(completed=2, total=2)
        m = build_sequence_manifest(result, sequence_job_dict={})
        assert len(m["segment_provenance"]) == 2

    def test_all_output_paths(self):
        result = _make_result(completed=2)
        m = build_sequence_manifest(result, sequence_job_dict={})
        assert len(m["all_output_paths"]) == 2

    def test_sequence_job_embedded(self):
        result = _make_result()
        seq_job_dict = {"sequence_id": "seq-test-001", "total_segments": 2}
        m = build_sequence_manifest(result, sequence_job_dict=seq_job_dict)
        assert m["sequence_job"]["total_segments"] == 2

    def test_required_keys_present(self):
        result = _make_result()
        m = build_sequence_manifest(result, sequence_job_dict={})
        for key in (
            "schema",
            "sequence_id",
            "job_id",
            "total_segments",
            "completed_segments",
            "is_complete",
            "sequence_job",
            "segment_provenance",
            "all_output_paths",
            "all_frame_paths",
        ):
            assert key in m, f"missing key: {key}"


class TestWriteSequenceManifest:
    def test_creates_file(self, tmp_path: Path):
        result = _make_result()
        out = write_sequence_manifest(result, tmp_path, sequence_job_dict={})
        assert out.exists()

    def test_returns_path_object(self, tmp_path: Path):
        result = _make_result()
        out = write_sequence_manifest(result, tmp_path, sequence_job_dict={})
        assert isinstance(out, Path)

    def test_filename_contains_sequence_id(self, tmp_path: Path):
        result = _make_result(sequence_id="seq-test-001")
        out = write_sequence_manifest(result, tmp_path, sequence_job_dict={})
        assert "seq-test-001" in out.name

    def test_valid_json(self, tmp_path: Path):
        result = _make_result()
        out = write_sequence_manifest(result, tmp_path, sequence_job_dict={})
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_schema_in_written_file(self, tmp_path: Path):
        result = _make_result()
        out = write_sequence_manifest(result, tmp_path, sequence_job_dict={})
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == SEQUENCE_MANIFEST_SCHEMA

    def test_creates_directory_if_missing(self, tmp_path: Path):
        nested = tmp_path / "deep" / "subdir"
        result = _make_result()
        out = write_sequence_manifest(result, nested, sequence_job_dict={})
        assert out.exists()

    def test_special_chars_in_sequence_id_are_sanitized(self, tmp_path: Path):
        result = _make_result(sequence_id="seq/with:special")
        out = write_sequence_manifest(result, tmp_path, sequence_job_dict={})
        # The file must be created without path separators in the name.
        assert out.exists()
        assert "/" not in out.name
        assert ":" not in out.name
