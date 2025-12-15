from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config
from tests.helpers.pipeline_fakes import FakePipeline


class DummyClient:
    pass


class DummyLogger:
    pass


class MemoryWriter:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", FakePipeline)


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


def test_pipeline_runner_returns_result_and_learning_record(tmp_path):
    writer = MemoryWriter()
    callback_records = []
    runner = PipelineRunner(
        DummyClient(),
        DummyLogger(),
        learning_record_writer=writer,
        on_learning_record=callback_records.append,
        learning_enabled=True,
    )

    variant_cfgs = [
        {"txt2img": {"model": "A", "sampler_name": "Euler", "steps": 10}},
        {"txt2img": {"model": "B", "sampler_name": "Euler a", "steps": 20}},
    ]
    njr = make_pipeline_njr(
        config={
            "prompt": "prompt",
            "model": "Base",
            "variant_configs": variant_cfgs,
            "pack_name": "pack-one",
            "preset_name": "preset-one",
            "metadata": {"run_label": "test"},
        },
        randomizer_mode="fanout",
        variant_total=len(variant_cfgs),
        stage_chain=[make_stage_config()],
        base_model="Base",
        sampler_name="Euler",
        steps=20,
        cfg_scale=7.5,
    )

    result = runner.run_njr(njr, cancel_token=_cancel_token())
    learning_record = runner._emit_learning_record(njr, result)
    assert learning_record is not None
    result.learning_records.append(learning_record)

    assert isinstance(result, PipelineRunResult)
    assert result.success is True
    assert result.error is None
    assert result.run_id
    assert result.randomizer_plan_size == len(variant_cfgs)
    assert result.metadata.get("variant_configs") == variant_cfgs
    assert result.randomizer_mode == "fanout"
    assert len(result.learning_records) == 1
    assert result.learning_records[0] in writer.records
    assert callback_records[0] == result.learning_records[0]
