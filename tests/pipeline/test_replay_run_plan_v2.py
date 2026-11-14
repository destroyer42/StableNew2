from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    SourceDescriptor,
    SourceKind,
    StageConfig,
)
from src.pipeline.replay_engine import ReplayEngine
from src.pipeline.run_plan import build_run_plan_from_njr
from src.queue.job_model import Job, StageCheckpoint
from tests.helpers.njr_factory import make_pipeline_njr


class StubRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_njr(
        self,
        njr: NormalizedJobRecord,
        cancel_token=None,
        run_plan=None,
        log_fn=None,
        checkpoint_callback=None,
    ):
        if checkpoint_callback is not None:
            checkpoint_callback("txt2img", ["output/generated.png"], {"image_count": 1})
        self.calls.append(
            {
                "njr": njr,
                "cancel_token": cancel_token,
                "run_plan": run_plan,
                "checkpoint_callback": checkpoint_callback,
            }
        )
        return {"status": "ok", "run_plan": run_plan}


def _make_njr() -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id="replay-001",
        config={"prompt": "castle", "model": "v1-5"},
        seed=123,
        positive_prompt="castle",
        negative_prompt="fog",
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler"
            )
        ],
        base_model="v1-5",
        images_per_prompt=1,
        path_output_dir="out",
    )


def test_build_run_plan_from_njr_produces_expected_shape() -> None:
    njr = _make_njr()
    plan = build_run_plan_from_njr(njr)

    assert plan.total_jobs == 1
    assert plan.total_images == 1
    assert plan.enabled_stages == ["txt2img"]
    assert plan.jobs[0].stage_name == "txt2img"
    assert plan.jobs[0].prompt_text == "castle"
    assert plan.jobs[0].seed == 123
    assert plan.source_job_id == njr.job_id
    assert plan.replay_of == njr.job_id


def test_replay_engine_invokes_runner_with_built_plan() -> None:
    njr = _make_njr()
    runner = StubRunner()
    engine = ReplayEngine(runner, cancel_token=None)

    result = engine.replay_njr(njr)

    assert runner.calls, "Runner was not invoked"
    call = runner.calls[0]
    assert call["run_plan"] is not None
    assert call["run_plan"].jobs[0].prompt_text == "castle"
    assert result["status"] == "ok"


def test_replay_engine_resumes_from_last_valid_checkpoint(tmp_path: Path) -> None:
    checkpoint_file = tmp_path / "txt2img.png"
    checkpoint_file.write_bytes(b"png")
    njr = _make_njr()
    njr = replace(
        njr,
        stages=(
            StageConfig(stage_type="txt2img", enabled=True),
            StageConfig(stage_type="adetailer", enabled=True),
            StageConfig(stage_type="upscale", enabled=True),
        ),
    )
    job = Job(job_id=njr.job_id, prompt_pack_id="test-pack")
    job.execution_metadata.stage_checkpoints.append(
        StageCheckpoint(stage_name="adetailer", output_paths=[str(checkpoint_file)])
    )
    runner = StubRunner()
    engine = ReplayEngine(runner, cancel_token=None)

    engine.replay_njr(njr, job=job)

    resumed = runner.calls[0]["njr"]
    assert resumed.job_id != njr.job_id
    assert resumed.source.parent_job_id == njr.job_id
    assert resumed.start_stage == "upscale"
    assert resumed.input_image_paths == (str(checkpoint_file),)


def test_a_resumed_record_is_derived_with_the_exact_pre_core_lineage(tmp_path: Path) -> None:
    """P4-2F: the checkpoint resume (V3) derives through the core; its record keeps the lineage it always had.

    The lineage carries the parent id and ``original_source_kind`` only: the parent's display name and artifact id are
    not inherited, and the metadata gains the two resume keys on top of the parent's.
    """

    checkpoint_file = tmp_path / "adetailer.png"
    checkpoint_file.write_bytes(b"png")
    njr = _make_njr()
    njr = replace(
        njr,
        source=replace(njr.source, display_name="Parent label"),
        stages=(
            StageConfig(stage_type="txt2img", enabled=True),
            StageConfig(stage_type="adetailer", enabled=True),
            StageConfig(stage_type="upscale", enabled=True),
        ),
    )
    job = Job(job_id=njr.job_id, prompt_pack_id="test-pack")
    job.execution_metadata.stage_checkpoints.append(
        StageCheckpoint(stage_name="adetailer", output_paths=[str(checkpoint_file)])
    )
    runner = StubRunner()

    ReplayEngine(runner, cancel_token=None).replay_njr(njr, job=job)

    resumed = runner.calls[0]["njr"]
    assert resumed.source == SourceDescriptor(
        kind=SourceKind.HISTORY_REPLAY,
        parent_job_id=njr.job_id,
        metadata={"original_source_kind": njr.source.kind.value},
    )
    assert resumed.source.display_name is None
    assert len(resumed.job_id) == 32
    assert dict(resumed.provenance.metadata) == {
        **dict(njr.provenance.metadata),
        "resumed_from_stage": "adetailer",
        "resume_input_count": 1,
    }
    unchanged = replace(
        resumed,
        job_id=njr.job_id,
        source=njr.source,
        workload=njr.workload,
        provenance=njr.provenance,
    )
    assert unchanged.to_dict() == njr.to_dict()


def test_replay_engine_checkpoint_callback_updates_job_metadata() -> None:
    njr = _make_njr()
    job = Job(job_id=njr.job_id, prompt_pack_id="test-pack")
    runner = StubRunner()
    engine = ReplayEngine(runner, cancel_token=None)

    engine.replay_njr(njr, job=job)

    assert job.execution_metadata.stage_checkpoints
    assert job.execution_metadata.stage_checkpoints[0].stage_name == "txt2img"
    assert job.execution_metadata.stage_checkpoints[0].output_paths == ["output/generated.png"]


def test_replay_engine_rejects_malformed_plan_before_runner() -> None:
    runner = StubRunner()
    engine = ReplayEngine(runner, cancel_token=None)
    malformed = SimpleNamespace(
        job_id="replay-bad",
        positive_prompt="castle",
        stage_chain=(SimpleNamespace(stage_type="", enabled=True),),
    )

    with pytest.raises(ValueError, match="explicit stage_type"):
        engine.replay_njr(malformed)  # type: ignore[arg-type]

    assert runner.calls == []
