"""Unit tests for src/video/sequence_models.py — PR-VIDEO-216."""

from __future__ import annotations

import pytest
from src.video.sequence_models import (
    CarryForwardPolicy,
    SegmentProvenanceRecord,
    VideoSegmentPlan,
    VideoSequenceJob,
    VideoSequenceResult,
)


# ---------------------------------------------------------------------------
# VideoSegmentPlan
# ---------------------------------------------------------------------------


class TestVideoSegmentPlan:
    def _make(self, **kwargs) -> VideoSegmentPlan:
        defaults = dict(
            segment_index=0,
            segment_id="abc123def456",
            source_image_path="/img/frame0.png",
            carry_forward_policy="last_frame",
            overlap_frames=2,
            segment_length_frames=25,
            prompt="a sunset",
            negative_prompt="blurry",
            workflow_id="ltx_multiframe_anchor_v1",
        )
        defaults.update(kwargs)
        return VideoSegmentPlan(**defaults)

    def test_frozen(self):
        plan = self._make()
        with pytest.raises((AttributeError, TypeError)):
            plan.segment_index = 99  # type: ignore[misc]

    def test_to_dict_round_trip(self):
        plan = self._make(extra={"custom_key": "value"})
        d = plan.to_dict()
        restored = VideoSegmentPlan.from_dict(d)
        assert restored.segment_index == 0
        assert restored.segment_id == "abc123def456"
        assert restored.source_image_path == "/img/frame0.png"
        assert restored.carry_forward_policy == "last_frame"
        assert restored.overlap_frames == 2
        assert restored.segment_length_frames == 25
        assert restored.prompt == "a sunset"
        assert restored.negative_prompt == "blurry"
        assert restored.workflow_id == "ltx_multiframe_anchor_v1"
        assert restored.extra == {"custom_key": "value"}

    def test_from_dict_defaults(self):
        plan = VideoSegmentPlan.from_dict({})
        assert plan.segment_index == 0
        assert plan.segment_id == ""
        assert plan.source_image_path is None
        assert plan.carry_forward_policy == "none"
        assert plan.workflow_id is None

    def test_none_source_path(self):
        plan = self._make(source_image_path=None)
        assert plan.source_image_path is None
        d = plan.to_dict()
        assert d["source_image_path"] is None


# ---------------------------------------------------------------------------
# VideoSequenceJob
# ---------------------------------------------------------------------------


class TestVideoSequenceJob:
    def _make(self, **kwargs) -> VideoSequenceJob:
        defaults = dict(
            sequence_id="seq-001",
            job_id="job-abc",
            workflow_id="ltx_multiframe_anchor_v1",
            total_segments=3,
            segment_length_frames=25,
            overlap_frames=2,
            carry_forward_policy="last_frame",
            base_source_image_path="/img/base.png",
            base_prompt="a mountain",
            base_negative_prompt="blurry",
        )
        defaults.update(kwargs)
        return VideoSequenceJob(**defaults)

    def test_to_dict_round_trip(self):
        job = self._make(per_segment_overrides=[{"prompt": "override"}])
        d = job.to_dict()
        restored = VideoSequenceJob.from_dict(d)
        assert restored.sequence_id == "seq-001"
        assert restored.total_segments == 3
        assert restored.per_segment_overrides == [{"prompt": "override"}]

    def test_from_dict_defaults(self):
        job = VideoSequenceJob.from_dict({})
        assert job.total_segments == 1
        assert job.carry_forward_policy == "none"
        assert job.per_segment_overrides == []

    def test_mutable(self):
        job = self._make()
        job.total_segments = 5
        assert job.total_segments == 5


# ---------------------------------------------------------------------------
# SegmentProvenanceRecord
# ---------------------------------------------------------------------------


class TestSegmentProvenanceRecord:
    def _make(self, **kwargs) -> SegmentProvenanceRecord:
        defaults = dict(
            sequence_id="seq-001",
            job_id="job-abc",
            segment_index=1,
            segment_id="seg0001id123",
            source_image_path="/img/base.png",
            primary_output_path="/out/seg1.mp4",
            manifest_path="/out/manifest1.json",
        )
        defaults.update(kwargs)
        return SegmentProvenanceRecord(**defaults)

    def test_frozen(self):
        record = self._make()
        with pytest.raises((AttributeError, TypeError)):
            record.segment_index = 99  # type: ignore[misc]

    def test_to_dict_keys(self):
        record = self._make()
        d = record.to_dict()
        assert d["segment_index"] == 1
        assert d["primary_output_path"] == "/out/seg1.mp4"
        assert d["carry_forward_policy"] == "none"

    def test_default_policy(self):
        record = self._make()
        assert record.carry_forward_policy == "none"


# ---------------------------------------------------------------------------
# VideoSequenceResult
# ---------------------------------------------------------------------------


class TestVideoSequenceResult:
    def test_is_complete_false_initially(self):
        result = VideoSequenceResult(
            sequence_id="seq-001",
            job_id="job-abc",
            total_segments=3,
        )
        assert not result.is_complete

    def test_is_complete_true_when_all_done(self):
        result = VideoSequenceResult(
            sequence_id="seq-001",
            job_id="job-abc",
            total_segments=2,
            completed_segments=2,
        )
        assert result.is_complete

    def test_to_dict_includes_is_complete(self):
        result = VideoSequenceResult(
            sequence_id="seq-001",
            job_id="job-abc",
            total_segments=1,
            completed_segments=1,
        )
        d = result.to_dict()
        assert d["is_complete"] is True
        assert d["total_segments"] == 1
        assert d["sequence_id"] == "seq-001"

    def test_to_dict_segment_provenance(self):
        record = SegmentProvenanceRecord(
            sequence_id="seq-001",
            job_id="job-abc",
            segment_index=0,
            segment_id="id000",
            source_image_path=None,
            primary_output_path="/out/seg0.mp4",
            manifest_path=None,
        )
        result = VideoSequenceResult(
            sequence_id="seq-001",
            job_id="job-abc",
            total_segments=1,
            completed_segments=1,
            segment_provenance=[record],
        )
        d = result.to_dict()
        assert len(d["segment_provenance"]) == 1
        assert d["segment_provenance"][0]["segment_index"] == 0

    def test_mutable_fields(self):
        result = VideoSequenceResult(
            sequence_id="seq-001",
            job_id="job-abc",
            total_segments=2,
        )
        result.completed_segments += 1
        result.all_output_paths.append("/out/seg0.mp4")
        assert result.completed_segments == 1
        assert len(result.all_output_paths) == 1
