from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.stage_models import StageType
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.pipeline_fakes import FakePipeline


class DummyClient:
    pass


class DummyLogger:
    pass


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", FakePipeline)


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


def _make_njr_for_stages(stage_types: list[StageType | str]) -> NormalizedJobRecord:
    return make_pipeline_njr(
        stage_chain=[make_stage_config(stage_type=stage) for stage in stage_types],
        positive_prompt="p",
        base_model="m",
        config={"prompt": "p", "model": "m"},
    )


def test_stage_runner_executes_in_order_txt2img_only(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    njr = _make_njr_for_stages([StageType.TXT2IMG])
    result = runner.run_njr(njr, cancel_token=_cancel_token())
    pipeline = runner._pipeline  # type: ignore[attr-defined]
    assert [c[0] for c in pipeline.calls] == ["txt2img"]
    assert result.success is True
    assert result.stage_plan is not None
    assert result.stage_plan.enabled_stages == ["txt2img"]


def test_stage_runner_executes_txt2img_then_upscale(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    njr = _make_njr_for_stages([StageType.TXT2IMG, StageType.UPSCALE])
    result = runner.run_njr(njr, cancel_token=_cancel_token())
    pipeline = runner._pipeline  # type: ignore[attr-defined]
    assert result.success is True
    assert result.stage_plan is not None
    assert result.stage_plan.enabled_stages == ["txt2img", "upscale"]


def test_stage_runner_executes_adetailer_stage(tmp_path):
    runner = PipelineRunner(DummyClient(), DummyLogger(), runs_base_dir=tmp_path / "runs")
    njr = _make_njr_for_stages([StageType.TXT2IMG, StageType.ADETAILER])
    result = runner.run_njr(njr, cancel_token=_cancel_token())
    pipeline = runner._pipeline  # type: ignore[attr-defined]
    assert result.success is True
    assert result.stage_plan is not None
    assert result.stage_plan.enabled_stages == ["txt2img", "adetailer"]
