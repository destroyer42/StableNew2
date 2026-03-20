"""Unit tests for src/video/sequence_planner.py — PR-VIDEO-216."""

from __future__ import annotations

import pytest
from src.video.sequence_models import VideoSequenceJob
from src.video.sequence_planner import VideoSequencePlanner, _segment_id


# ---------------------------------------------------------------------------
# _segment_id determinism
# ---------------------------------------------------------------------------


class TestSegmentId:
    def test_same_inputs_same_output(self):
        assert _segment_id("seq-001", 0) == _segment_id("seq-001", 0)

    def test_different_index_different_output(self):
        assert _segment_id("seq-001", 0) != _segment_id("seq-001", 1)

    def test_different_sequence_different_output(self):
        assert _segment_id("seq-001", 0) != _segment_id("seq-002", 0)

    def test_fixed_length_12(self):
        sid = _segment_id("anysequence", 42)
        assert len(sid) == 12

    def test_known_value(self):
        # Regression guard: changing the hash format must fail this test.
        import hashlib
        raw = "seq-001:seg:0000"
        expected = hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:12]
        assert _segment_id("seq-001", 0) == expected


# ---------------------------------------------------------------------------
# VideoSequencePlanner.plan()
# ---------------------------------------------------------------------------


def _make_job(**kwargs) -> VideoSequenceJob:
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


class TestVideoSequencePlannerPlan:
    def setup_method(self):
        self.planner = VideoSequencePlanner()

    def test_correct_segment_count(self):
        plans = self.planner.plan(_make_job(total_segments=4))
        assert len(plans) == 4

    def test_segment_indices(self):
        plans = self.planner.plan(_make_job(total_segments=3))
        assert [p.segment_index for p in plans] == [0, 1, 2]

    def test_deterministic_ids(self):
        job = _make_job(total_segments=2)
        plans_a = self.planner.plan(job)
        plans_b = self.planner.plan(job)
        assert [p.segment_id for p in plans_a] == [p.segment_id for p in plans_b]

    def test_total_segments_zero_raises(self):
        with pytest.raises(ValueError):
            self.planner.plan(_make_job(total_segments=0))

    # ------- last_frame policy -------

    def test_last_frame_seg0_gets_base_source(self):
        plans = self.planner.plan(_make_job(carry_forward_policy="last_frame"))
        assert plans[0].source_image_path == "/img/base.png"

    def test_last_frame_later_segs_have_no_source(self):
        plans = self.planner.plan(_make_job(carry_forward_policy="last_frame"))
        for plan in plans[1:]:
            assert plan.source_image_path is None

    # ------- first_frame policy -------

    def test_first_frame_all_segs_get_base_source(self):
        plans = self.planner.plan(_make_job(carry_forward_policy="first_frame"))
        assert all(p.source_image_path == "/img/base.png" for p in plans)

    # ------- none policy -------

    def test_none_policy_no_source_any_seg(self):
        plans = self.planner.plan(_make_job(carry_forward_policy="none"))
        assert all(p.source_image_path is None for p in plans)

    # ------- provided policy -------

    def test_provided_uses_override(self):
        job = _make_job(
            carry_forward_policy="provided",
            total_segments=2,
            per_segment_overrides=[
                {"source_image_path": "/img/override0.png"},
                {"source_image_path": "/img/override1.png"},
            ],
        )
        plans = self.planner.plan(job)
        assert plans[0].source_image_path == "/img/override0.png"
        assert plans[1].source_image_path == "/img/override1.png"

    def test_provided_falls_back_to_base_for_seg0_when_no_override(self):
        job = _make_job(
            carry_forward_policy="provided",
            total_segments=2,
            per_segment_overrides=[],
        )
        plans = self.planner.plan(job)
        assert plans[0].source_image_path == "/img/base.png"
        assert plans[1].source_image_path is None

    # ------- prompts and overrides -------

    def test_base_prompt_used_when_no_overrides(self):
        plans = self.planner.plan(_make_job())
        assert all(p.prompt == "a mountain" for p in plans)

    def test_per_segment_prompt_override(self):
        job = _make_job(
            total_segments=2,
            per_segment_overrides=[{"prompt": "custom prompt"}, {}],
        )
        plans = self.planner.plan(job)
        assert plans[0].prompt == "custom prompt"
        assert plans[1].prompt == "a mountain"

    def test_per_segment_workflow_id_override(self):
        job = _make_job(
            total_segments=2,
            per_segment_overrides=[{"workflow_id": "alt_workflow"}, {}],
        )
        plans = self.planner.plan(job)
        assert plans[0].workflow_id == "alt_workflow"
        assert plans[1].workflow_id == "ltx_multiframe_anchor_v1"

    def test_extra_fields_passed_through(self):
        job = _make_job(
            total_segments=1,
            per_segment_overrides=[{"custom_key": "custom_val"}],
        )
        plans = self.planner.plan(job)
        assert plans[0].extra.get("custom_key") == "custom_val"

    def test_reserved_fields_not_in_extra(self):
        job = _make_job(
            total_segments=1,
            per_segment_overrides=[{"prompt": "x", "workflow_id": "y", "custom_key": "z"}],
        )
        plans = self.planner.plan(job)
        assert "prompt" not in plans[0].extra
        assert "workflow_id" not in plans[0].extra
        assert plans[0].extra.get("custom_key") == "z"

    def test_overlap_frames_per_segment_override(self):
        job = _make_job(
            total_segments=2,
            overlap_frames=2,
            per_segment_overrides=[{"overlap_frames": 5}, {}],
        )
        plans = self.planner.plan(job)
        assert plans[0].overlap_frames == 5
        assert plans[1].overlap_frames == 2

    def test_carry_forward_policy_stamped_on_each_plan(self):
        plans = self.planner.plan(_make_job(carry_forward_policy="first_frame"))
        assert all(p.carry_forward_policy == "first_frame" for p in plans)


# ---------------------------------------------------------------------------
# VideoSequencePlanner.apply_carry_forward()
# ---------------------------------------------------------------------------


class TestApplyCarryForward:
    def setup_method(self):
        self.planner = VideoSequencePlanner()

    def _make_plan(self, idx: int, source: str | None, policy: str = "last_frame"):
        from src.video.sequence_models import VideoSegmentPlan

        return VideoSegmentPlan(
            segment_index=idx,
            segment_id=_segment_id("seq-001", idx),
            source_image_path=source,
            carry_forward_policy=policy,  # type: ignore[arg-type]
            overlap_frames=0,
            segment_length_frames=25,
            prompt="p",
            negative_prompt="np",
            workflow_id="wf",
        )

    def test_updates_none_source_for_last_frame_non_zero_seg(self):
        plan = self._make_plan(idx=1, source=None, policy="last_frame")
        updated = self.planner.apply_carry_forward(plan, prior_output_path="/out/seg0.mp4")
        assert updated.source_image_path == "/out/seg0.mp4"

    def test_does_not_update_seg0_last_frame(self):
        plan = self._make_plan(idx=0, source="/base.png", policy="last_frame")
        updated = self.planner.apply_carry_forward(plan, prior_output_path="/out/seg0.mp4")
        # Seg 0 already has a source; apply_carry_forward only triggers when source is None
        assert updated.source_image_path == "/base.png"

    def test_passthrough_for_first_frame_policy(self):
        plan = self._make_plan(idx=2, source="/base.png", policy="first_frame")
        updated = self.planner.apply_carry_forward(plan, prior_output_path="/out/seg1.mp4")
        assert updated is plan  # unchanged, same object

    def test_passthrough_for_none_policy(self):
        plan = self._make_plan(idx=1, source=None, policy="none")
        updated = self.planner.apply_carry_forward(plan, prior_output_path="/out/seg0.mp4")
        assert updated is plan  # unchanged

    def test_returns_new_frozen_instance(self):
        plan = self._make_plan(idx=1, source=None, policy="last_frame")
        updated = self.planner.apply_carry_forward(plan, prior_output_path="/out/seg0.mp4")
        assert updated is not plan
        assert updated.segment_id == plan.segment_id
        assert updated.segment_index == plan.segment_index
