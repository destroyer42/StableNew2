from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineRunner
from src.controller.archive.pipeline_config_types import PipelineConfig
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


def test_pipeline_runner_reports_variant_count_from_config():
    runner = PipelineRunner(DummyClient(), DummyLogger())
    variant_cfgs = [
        {"txt2img": {"model": "A"}},
        {"txt2img": {"model": "B"}},
        {"txt2img": {"model": "C"}},
    ]
    config = PipelineConfig(
        prompt="prompt",
        model="Base",
        sampler="Euler",
        width=512,
        height=512,
        steps=30,
        cfg_scale=7.0,
        variant_configs=variant_cfgs,
        randomizer_mode="rotate",
        randomizer_plan_size=3,
    )

    result = runner.run(config, cancel_token=_cancel_token())

    assert result.variant_count == len(variant_cfgs)
    assert result.variants == variant_cfgs
