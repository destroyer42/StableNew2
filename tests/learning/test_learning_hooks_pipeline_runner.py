"""PipelineRunner learning hook tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.stage_sequencer import StageConfig, StageMetadata
from tests.helpers.pipeline_fakes import FakePipeline


class MemoryWriter:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


class DummyClient:
    pass


class DummyLogger:
    pass


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", FakePipeline, raising=False)


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


def _make_learning_record(tmp_path):
    stage = StageConfig(
        enabled=True,
        payload={
            "model": "Model-X",
            "sampler_name": "Euler",
            "steps": 30,
            "cfg_scale": 7.0,
        },
        metadata=StageMetadata(),
    )
    return NormalizedJobRecord(
        job_id="learning-job",
        config={
            "prompt": "Test prompt",
            "model": "Model-X",
            "variant_configs": [
                {"txt2img": {"model": "Model-X", "sampler_name": "Euler", "steps": 30}}
            ],
        },
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        seed=101,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        randomizer_summary=None,
        stage_chain=[stage],
        steps=30,
        cfg_scale=7.0,
        width=512,
        height=512,
        sampler_name="Euler",
        variant_mode="fanout",
        base_model="Model-X",
        positive_prompt="Test prompt",
    )


def test_pipeline_runner_emits_learning_record(tmp_path):
    writer = MemoryWriter()
    callback_records = []

    runner = PipelineRunner(
        DummyClient(),
        DummyLogger(),
        learning_record_writer=writer,
        on_learning_record=callback_records.append,
        runs_base_dir=tmp_path / "runs",
        learning_enabled=True,
    )

    record = _make_learning_record(tmp_path)
    result = runner.run_njr(record, cancel_token=_cancel_token())
    learning_record = runner._emit_learning_record(record, result)
    assert learning_record is not None
    result.learning_records.append(learning_record)

    assert len(writer.records) == 1
    record = writer.records[0]
    assert record.randomizer_mode == "fanout"
    assert record.primary_model == "Model-X"
    assert callback_records[0] == record
    learning_records = result.learning_records
    assert learning_records, "learning_records should contain at least one entry"
    first = learning_records[0]
    if isinstance(first, dict):
        assert first.get("base_config") == record.base_config
    else:
        assert first == record
    assert result.metadata.get("output_dir")


def test_pipeline_runner_handles_missing_writer(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger())
    record = _make_learning_record(tmp_path)
    result = runner.run_njr(record, cancel_token=_cancel_token())
    learning_record = runner._emit_learning_record(record, result)
    assert learning_record is None
    # No exceptions should occur without a writer/callback.


def test_pipeline_runner_emits_compact_refinement_learning_context(tmp_path):
    writer = MemoryWriter()
    runner = PipelineRunner(
        DummyClient(),
        DummyLogger(),
        learning_record_writer=writer,
        runs_base_dir=tmp_path / "runs",
        learning_enabled=True,
    )

    record = _make_learning_record(tmp_path)
    result = runner.run_njr(record, cancel_token=_cancel_token())
    result.metadata["adaptive_refinement"] = {
        "intent": {
            "mode": "full",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "algorithm_version": "v1",
        },
        "prompt_intent": {"intent_band": "portrait", "requested_pose": "profile"},
        "decision_bundle": {
            "algorithm_version": "v1",
            "policy_id": "full_upscale_detail_v1",
            "detector_id": "null",
            "observation": {
                "subject_assessment": {
                    "scale_band": "small",
                    "pose_band": "profile",
                    "detection_count": 1,
                    "face_area_ratio": 0.2,
                }
            },
            "applied_overrides": {"upscale_steps": 18},
            "prompt_patch": {"add_positive": ["clear irises"]},
        },
        "image_decisions": [{"decision_bundle": {"policy_id": "full_upscale_detail_v1"}}],
    }

    learning_record = runner._emit_learning_record(record, result)

    assert learning_record is not None
    refinement = learning_record.metadata["adaptive_refinement"]
    assert refinement["mode"] == "full"
    assert refinement["policy_id"] == "full_upscale_detail_v1"
    assert refinement["scale_band"] == "small"
    assert refinement["face_detected"] is True
    assert refinement["has_prompt_patch"] is True


def test_pipeline_runner_emits_compact_secondary_motion_learning_context(tmp_path):
    writer = MemoryWriter()
    runner = PipelineRunner(
        DummyClient(),
        DummyLogger(),
        learning_record_writer=writer,
        runs_base_dir=tmp_path / "runs",
        learning_enabled=True,
    )

    record = _make_learning_record(tmp_path)
    result = runner.run_njr(record, cancel_token=_cancel_token())
    result.metadata["video_primary_backend_id"] = "comfy"
    result.metadata["secondary_motion"] = {
        "summary": {
            "enabled": True,
            "status": "applied",
            "policy_id": "workflow_motion_v1",
            "application_path": "video_reencode_worker",
            "backend_mode": "apply_shared_postprocess_candidate",
            "intent": {"mode": "apply", "intent": "micro_sway"},
            "metrics": {
                "frames_in": 16,
                "frames_out": 16,
                "applied_frame_count": 10,
                "intensity": 0.25,
                "avg_abs_dx": 1.0,
                "avg_abs_dy": 0.25,
                "max_abs_dx": 2,
                "max_abs_dy": 1,
                "cap_pixels": 12,
            },
        }
    }

    learning_record = runner._emit_learning_record(record, result)

    assert learning_record is not None
    secondary_motion = learning_record.metadata["secondary_motion"]
    assert secondary_motion["backend_id"] == "comfy"
    assert secondary_motion["policy_id"] == "workflow_motion_v1"
    assert secondary_motion["application_path"] == "video_reencode_worker"
    assert secondary_motion["applied_motion_strength"] == 0.25
    assert secondary_motion["quality_risk_score"] > 0.0
