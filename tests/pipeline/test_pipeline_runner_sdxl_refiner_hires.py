from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.stage_sequencer import StageConfig, StageExecution, StageExecutionPlan, StageMetadata, StageTypeEnum


class DummyClient:
    """Minimal fake API client for pipeline runner tests."""


class DummyLogger:
    """Lightweight stub matching the limited needs of PipelineRunner."""


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


class RecordingPipeline:
    """Pipeline stub that records stage payloads for inspection."""

    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, dict[str, dict[str, object]]]] = []
        self.stage_events: list[dict[str, object]] = []

    def run_txt2img_stage(self, prompt, negative_prompt, config, output_dir, image_name, cancel_token=None):
        # config is the stage payload, not a nested config dict
        self.calls.append(("txt2img", dict(config)))
        return {"path": str(Path(output_dir) / f"{image_name}.png")}

    def run_img2img_stage(self, input_image_path, prompt, config, output_dir, cancel_token=None):
        self.calls.append(("img2img", {"input": str(input_image_path)}))
        return {"path": str(Path(output_dir) / "img2img.png")}

    def run_upscale_stage(self, input_image_path, config, run_dir, image_name, cancel_token=None):
        self.calls.append(("upscale", {"input": str(input_image_path)}))
        return {"path": str(Path(run_dir) / "upscaled.png")}

    def run_adetailer_stage(self, input_image_path, config, run_dir, image_name, prompt=None, cancel_token=None):
        self.calls.append(("adetailer", {"input": str(input_image_path)}))
        return {"path": str(Path(run_dir) / "adetailer.png")}

    def reset_stage_events(self):
        self.stage_events = []

    def get_stage_events(self):
        return list(self.stage_events)


def _build_stage(stage_type: str, order_index: int) -> StageExecution:
    return StageExecution(
        stage_type=stage_type,
        config=StageConfig(enabled=True, payload={}, metadata={}),
        order_index=order_index,
        requires_input_image=False,
        produces_output_image=True,
    )


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", RecordingPipeline)


def _prime_runner_for_txt_only(runner: PipelineRunner):
    base_default = runner._config_manager.get_default_config()  # type: ignore[attr-defined]
    base_default["pipeline"]["img2img_enabled"] = False
    base_default["pipeline"]["upscale_enabled"] = False
    base_default["upscale"]["enabled"] = False
    runner._config_manager.get_default_config = lambda: base_default  # type: ignore[assignment]


def test_pipeline_runner_applies_hires_metadata_to_txt2img(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    _prime_runner_for_txt_only(runner)

    record = NormalizedJobRecord(
        job_id="hires-job",
        config={"model": "m", "sampler": "Euler a"},
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        randomizer_summary=None,
        stage_chain=[
            StageConfig(
                enabled=True,
                payload={
                    "model": "m",
                    "sampler_name": "Euler a",
                    "steps": 20,
                    "cfg_scale": 7.0,
                },
                metadata=StageMetadata(
                    hires_enabled=True,
                    hires_upscale_factor=1.5,
                    hires_upscaler_name="Latent",
                    hires_steps=8,
                    hires_denoise=0.42,
                ),
            )
        ],
        steps=20,
        cfg_scale=7.0,
        width=512,
        height=512,
        sampler_name="Euler a",
        base_model="m",
        positive_prompt="a scenic vista",
    )

    runner.run_njr(record, cancel_token=_cancel_token())

    recorded = runner._pipeline.calls  # type: ignore[attr-defined]
    assert recorded
    payload = recorded[0][1]
    assert payload["cfg_scale"] == pytest.approx(7.0)
    assert any(call[0] == "txt2img" for call in recorded)


def test_validate_stage_plan_requires_adetailer_last():
    runner = PipelineRunner(DummyClient(), DummyLogger())
    plan = StageExecutionPlan(
        stages=[
            _build_stage(StageTypeEnum.ADETAILER.value, 0),
            _build_stage(StageTypeEnum.TXT2IMG.value, 1),
        ]
    )
    with pytest.raises(ValueError):
        runner._validate_stage_plan(plan)
