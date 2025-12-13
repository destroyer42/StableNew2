from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from src.pipeline.pipeline_runner import PipelineRunner
from src.controller.archive.pipeline_config_types import PipelineConfig
from src.pipeline.stage_models import StageExecution, StageExecutionPlan, StageTypeEnum
from src.utils.logger import StructuredLogger


def test_pipeline_runner_logs_stage_events(monkeypatch, tmp_path, caplog) -> None:
    class DummyPipeline:
        def __init__(self, api_client, structured_logger):
            self.api_client = api_client
            self.logger = structured_logger

    monkeypatch.setattr("src.pipeline.pipeline_runner.Pipeline", DummyPipeline)
    runner = PipelineRunner(
        api_client=SimpleNamespace(),
        structured_logger=StructuredLogger(output_dir=str(tmp_path)),
    )

    stage = StageExecution(stage_type=StageTypeEnum.TXT2IMG, config_key="txt2img")
    stage.config = SimpleNamespace(metadata={})
    plan = StageExecutionPlan(stages=[stage])

    monkeypatch.setattr(
        "src.pipeline.pipeline_runner.build_stage_execution_plan",
        lambda config: plan,
    )
    monkeypatch.setattr(
        PipelineRunner,
        "_call_stage",
        lambda self, stage, payload, run_dir, cancel_token, input_image_path, **kwargs: {"path": str(run_dir / "stage.png")},
    )
    monkeypatch.setattr(PipelineRunner, "_apply_stage_metadata", lambda self, executor_config, stage: None)

    config = PipelineConfig(
        prompt="test prompt",
        model="model",
        sampler="sampler",
        width=64,
        height=64,
        steps=1,
        cfg_scale=1.0,
        metadata={"_job_id": "job123", "_prompt_pack_id": "pack123"},
    )

    caplog.set_level(logging.INFO)
    runner._execute_with_config(config, cancel_token=SimpleNamespace(is_cancelled=lambda: False))

    messages = [record.getMessage() for record in caplog.records]
    assert any("NJR_EXEC_START" in message for message in messages)
    assert any("NJR_STAGE_START" in message for message in messages)
    assert any("NJR_STAGE_DONE" in message for message in messages)
