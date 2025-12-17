from __future__ import annotations

from src.learning.learning_execution import LearningExecutionContext, LearningExecutionRunner
from src.learning.learning_plan import LearningPlan
from src.pipeline.pipeline_runner import PipelineRunResult


def _fake_pipeline_run(config: dict, step) -> PipelineRunResult:
    run_id = f"run-{step.index}"
    return PipelineRunResult(
        run_id=run_id,
        success=True,
        error=None,
        variants=[config],
        learning_records=[],
        randomizer_mode="",
        randomizer_plan_size=1,
        metadata={"step_index": step.index, "variable": step.variable, "value": step.value},
        stage_plan=None,
    )


def test_learning_execution_runner_invokes_per_step():
    plan = LearningPlan(
        mode="single_variable_sweep",
        stage="txt2img",
        target_variable="cfg_scale",
        sweep_values=[5.0, 7.5],
        images_per_step=1,
    )
    base_cfg = {"txt2img": {"cfg_scale": 7.0}}
    context = LearningExecutionContext(
        plan=plan, base_config=base_cfg, metadata={"experiment": "test"}
    )
    runner = LearningExecutionRunner(run_callable=_fake_pipeline_run)
    result = runner.run(context)

    assert result.steps_executed == 2
    assert result.metadata["experiment"] == "test"
    assert result.step_results[0].pipeline_result.metadata["value"] == 5.0
    assert result.step_results[1].pipeline_result.metadata["value"] == 7.5
