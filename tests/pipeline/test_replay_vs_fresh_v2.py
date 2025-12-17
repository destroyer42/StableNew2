from __future__ import annotations

from dataclasses import asdict

from src.history.history_record import HistoryRecord
from src.history.history_schema_v26 import HISTORY_SCHEMA_VERSION
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.replay_engine import ReplayEngine
from src.pipeline.run_plan import build_run_plan_from_njr


class RecordingRunner:
    def __init__(self) -> None:
        self.run_plans = []

    def run_njr(self, njr: NormalizedJobRecord, cancel_token=None, run_plan=None, log_fn=None):
        self.run_plans.append(run_plan)
        return {"status": "ok"}


def _njr() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="fresh-001",
        config={"prompt": "mountain", "model": "sdxl"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=77,
        positive_prompt="mountain",
        negative_prompt="lowres",
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=30, cfg_scale=7.0, sampler_name="Euler a"
            )
        ],
        steps=30,
        cfg_scale=7.0,
        width=640,
        height=640,
        sampler_name="Euler a",
        scheduler="ddim",
        base_model="sdxl",
        images_per_prompt=1,
    )


def test_replay_run_plan_matches_fresh_plan() -> None:
    njr = _njr()
    fresh_plan = build_run_plan_from_njr(njr)

    runner = RecordingRunner()
    engine = ReplayEngine(runner, cancel_token=None)
    record = HistoryRecord(
        id=njr.job_id,
        timestamp="2025-01-01T00:00:00Z",
        status="completed",
        history_schema=HISTORY_SCHEMA_VERSION,
        njr_snapshot={
            "normalized_job": asdict(njr),
            "schema_version": HISTORY_SCHEMA_VERSION,
        },
        metadata={},
        runtime={},
        ui_summary={},
    )

    engine.replay_history_record(record)

    assert runner.run_plans, "Replay did not produce a run plan"
    replay_plan = runner.run_plans[0]
    assert replay_plan.jobs[0].prompt_text == fresh_plan.jobs[0].prompt_text
    assert replay_plan.jobs[0].stage_name == fresh_plan.jobs[0].stage_name
    assert replay_plan.total_images == fresh_plan.total_images
    assert replay_plan.enabled_stages == fresh_plan.enabled_stages
