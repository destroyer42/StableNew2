from __future__ import annotations

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.replay_engine import ReplayEngine
from src.pipeline.run_plan import build_run_plan_from_njr


class StubRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_njr(self, njr: NormalizedJobRecord, cancel_token=None, run_plan=None, log_fn=None):
        self.calls.append({"njr": njr, "cancel_token": cancel_token, "run_plan": run_plan})
        return {"status": "ok", "run_plan": run_plan}


def _make_njr() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="replay-001",
        config={"prompt": "castle", "model": "v1-5"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=123,
        positive_prompt="castle",
        negative_prompt="fog",
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler"
            )
        ],
        steps=20,
        cfg_scale=7.5,
        width=512,
        height=512,
        sampler_name="Euler",
        scheduler="ddim",
        base_model="v1-5",
        images_per_prompt=1,
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
