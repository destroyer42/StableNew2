from __future__ import annotations

from src.learning.learning_record_builder import build_learning_record
from src.pipeline.pipeline_runner import PipelineRunResult
from src.controller.archive.pipeline_config_types import PipelineConfig
from src.pipeline.stage_sequencer import StageExecutionPlan, StageExecution, StageConfig
from src.learning.learning_record import LearningRecord


def _run_result_stub(run_id: str = "run-123") -> PipelineRunResult:
    stage_plan = StageExecutionPlan(
        stages=[
            StageExecution(
                stage_type="txt2img",
                config=StageConfig(enabled=True, payload={}, metadata={}),
                order_index=0,
                requires_input_image=False,
                produces_output_image=True,
            )
        ],
        run_id=run_id,
    )
    return PipelineRunResult(
        run_id=run_id,
        success=True,
        error=None,
        variants=[{"txt2img": {"model": "m", "sampler_name": "Euler", "steps": 10}}],
        learning_records=[],
        randomizer_mode="fanout",
        randomizer_plan_size=1,
        metadata={"timestamp": "t0"},
        stage_plan=stage_plan,
        stage_events=[{"stage": "txt2img", "phase": "exit", "image_index": 1, "total_images": 1, "cancelled": False}],
    )


def test_learning_record_builder_basic_roundtrip():
    cfg = PipelineConfig(
        prompt="p",
        model="m",
        sampler="Euler",
        width=512,
        height=512,
        steps=20,
        cfg_scale=7.5,
        metadata={"user": "tester"},
    )
    result = _run_result_stub()
    record = build_learning_record(cfg, result)
    assert isinstance(record, LearningRecord)
    assert record.run_id == result.run_id
    assert record.stage_plan == ["txt2img"]
    assert record.stage_events
    assert record.base_config["txt2img"]["model"] == "m"
    assert record.primary_model == "m"
