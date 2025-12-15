from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
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


def _make_variant_record(variant_cfgs: list[dict[str, object]]) -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id="variant-job",
        config={"model": "Base", "variant_configs": variant_cfgs},
        stage_chain=[make_stage_config()],
        steps=30,
        cfg_scale=7.0,
        sampler_name="Euler",
        base_model="Base",
        positive_prompt="prompt",
        variant_total=len(variant_cfgs),
        variant_index=0,
    )


def test_pipeline_runner_reports_variant_count_from_config():
    runner = PipelineRunner(DummyClient(), DummyLogger())
    variant_cfgs = [
        {"txt2img": {"model": "A"}},
        {"txt2img": {"model": "B"}},
        {"txt2img": {"model": "C"}},
    ]
    record = _make_variant_record(variant_cfgs)

    result = runner.run_njr(record, cancel_token=_cancel_token())

    assert result.metadata.get("variant_configs") == variant_cfgs
    assert result.variant_count == len(result.variants)
    assert result.stage_events
    assert result.stage_events[0]["stage"] == "txt2img"
    assert result.variants[0]["path"].endswith(".png")
