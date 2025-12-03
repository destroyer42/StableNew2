"""PipelineRunner learning hook tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner
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
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", FakePipeline)


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


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

    config = PipelineConfig(
        prompt="Test prompt",
        model="Model-X",
        sampler="Euler",
        width=512,
        height=512,
        steps=30,
        cfg_scale=7.0,
        pack_name="packA",
        preset_name="presetA",
        randomizer_mode="fanout",
        randomizer_plan_size=2,
        variant_configs=[{"txt2img": {"model": "Model-X", "sampler_name": "Euler", "steps": 30}}],
    )

    result = runner.run(config, cancel_token=_cancel_token())

    assert len(writer.records) == 1
    record = writer.records[0]
    assert record.randomizer_mode == "fanout"
    assert record.primary_model == "Model-X"
    assert callback_records[0] == record
    assert result.learning_records[0] == record
    assert (tmp_path / "runs" / record.run_id / "run_metadata.json").exists()


def test_pipeline_runner_handles_missing_writer():
    runner = PipelineRunner(DummyClient(), DummyLogger())
    config = PipelineConfig(
        prompt="Prompt",
        model="Base",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
    )
    runner.run(config, cancel_token=_cancel_token())
    # No exceptions should occur without a writer/callback.
