from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.stage_sequencer import StageConfig, StageMetadata
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


def _make_record(tmp_path, *, prompt: str = "p") -> NormalizedJobRecord:
    stage = StageConfig(
        enabled=True,
        payload={
            "model": "m",
            "sampler_name": "Euler",
            "steps": 20,
            "cfg_scale": 7.0,
        },
        metadata=StageMetadata(),
    )
    return NormalizedJobRecord(
        job_id="learning-job",
        config={"prompt": prompt, "model": "m"},
        path_output_dir=str(tmp_path / "runs"),
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        randomizer_summary=None,
        stage_chain=[stage],
        steps=20,
        cfg_scale=7.0,
        width=512,
        height=512,
        sampler_name="Euler",
        base_model="m",
        positive_prompt=prompt,
    )


@dataclass
class DummyLearningConfig:
    prompt: str = "p"
    model: str = "m"
    sampler: str = "Euler"
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    pack_name: str = "packA"
    preset_name: str = "presetA"
    randomizer_mode: str = "fanout"
    randomizer_plan_size: int = 1
    variant_configs: list[dict[str, Any]] = field(
        default_factory=lambda: [{"txt2img": {"model": "m", "sampler_name": "Euler", "steps": 20}}]
    )
    metadata: dict[str, Any] = field(default_factory=lambda: {"run_label": "test"})


def _learning_config() -> DummyLearningConfig:
    return DummyLearningConfig(
        pack_name="packA",
        preset_name="presetA",
        metadata={"run_label": "test"},
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
    record = _make_record(tmp_path)
    result = runner.run_njr(record, cancel_token=_cancel_token())
    learning_record = runner._emit_learning_record(_learning_config(), result)
    assert learning_record is not None
    assert len(writer.records) == 1
    assert learning_record is writer.records[0]
    result.learning_records.append(learning_record)
    assert result.learning_records
    assert result.learning_records[0] == learning_record


def test_pipeline_runner_skips_learning_record_when_disabled(tmp_path):
    writer = MemoryWriter()
    runner = _runner_with_defaults(tmp_path, learning_enabled=False, writer=writer)
    record = _make_record(tmp_path)
    result = runner.run_njr(record, cancel_token=_cancel_token())
    learning_record = runner._emit_learning_record(_learning_config(), result)
    assert learning_record is None
    assert not writer.records
    assert not result.learning_records
