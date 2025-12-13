from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineRunner
from src.controller.archive.pipeline_config_types import PipelineConfig
from tests.helpers.pipeline_fakes import FakePipeline


class DummyClient:
    pass


class DummyLogger:
    pass


class MemoryWriter:
    def __init__(self):
        self.records = []

    def append_record(self, record):
        self.records.append(record)


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", FakePipeline)


def _cancel_token():
    return SimpleNamespace(is_cancelled=lambda: False)


def _runner_with_defaults(tmp_path, learning_enabled: bool, writer: MemoryWriter | None = None):
    runner = PipelineRunner(
        DummyClient(),
        DummyLogger(),
        learning_record_writer=writer,
        runs_base_dir=tmp_path / "runs",
        learning_enabled=learning_enabled,
    )
    base_default = runner._config_manager.get_default_config()  # type: ignore[attr-defined]
    base_default["pipeline"]["img2img_enabled"] = False
    base_default["pipeline"]["upscale_enabled"] = False
    base_default["pipeline"]["adetailer_enabled"] = False
    runner._config_manager.get_default_config = lambda: base_default  # type: ignore[assignment]
    return runner


def _pipeline_config():
    return PipelineConfig(
        prompt="p",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.0,
    )


def test_pipeline_runner_emits_learning_record_when_enabled(tmp_path):
    writer = MemoryWriter()
    runner = _runner_with_defaults(tmp_path, learning_enabled=True, writer=writer)
    runner.run(_pipeline_config(), cancel_token=_cancel_token())
    assert len(writer.records) == 1


def test_pipeline_runner_skips_learning_record_when_disabled(tmp_path):
    writer = MemoryWriter()
    runner = _runner_with_defaults(tmp_path, learning_enabled=False, writer=writer)
    runner.run(_pipeline_config(), cancel_token=_cancel_token())
    assert not writer.records
