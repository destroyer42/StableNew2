from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineConfig, PipelineRunner, PipelineRunResult


class FakePipeline:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def run_txt2img_stage(self, prompt, negative_prompt, config, output_dir, image_name):
        self.calls.append(("txt2img", prompt, output_dir, image_name))
        return {"path": str(Path(output_dir) / f"{image_name}.png")}

    def run_img2img_stage(self, input_image_path, prompt, config, output_dir):
        self.calls.append(("img2img", prompt, str(input_image_path)))
        return {"path": str(Path(output_dir) / "img2img.png")}

    def run_upscale_stage(self, input_image_path, config, output_dir, image_name):
        self.calls.append(("upscale", str(input_image_path), image_name))
        return {"path": str(Path(output_dir) / "upscaled.png")}


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
    config = PipelineConfig(
        prompt="prompt",
        model="Base",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
        pack_name="pack-one",
        preset_name="preset-one",
        randomizer_mode="fanout",
        randomizer_plan_size=len(variant_cfgs),
        variant_configs=variant_cfgs,
        metadata={"run_label": "test"},
    )

    result = runner.run(config, cancel_token=_cancel_token())

    assert isinstance(result, PipelineRunResult)
    assert result.success is True
    assert result.error is None
    assert result.run_id
    assert result.variant_count == len(variant_cfgs)
    assert result.variants == variant_cfgs
    assert len(result.learning_records) == 1
    assert result.learning_records[0] in writer.records
    assert callback_records[0] == result.learning_records[0]
