from __future__ import annotations

from src.controller.learning_execution_controller import LearningExecutionController
from src.learning.learning_plan import LearningPlan
from src.pipeline.pipeline_runner import PipelineRunResult


def _fake_run_callable(cfg: dict, step) -> PipelineRunResult:
    return PipelineRunResult(
        run_id=f"r{step.index}",
        success=True,
        error=None,
        variants=[cfg],
        learning_records=[],
        randomizer_mode="",
        randomizer_plan_size=1,
        metadata={"step": step.index, "variable": step.variable, "value": step.value},
        stage_plan=None,
    )


def test_learning_execution_controller_runs_plan():
    controller = LearningExecutionController(run_callable=_fake_run_callable)
    plan = LearningPlan(
        mode="single_variable_sweep",
        stage="txt2img",
        target_variable="steps",
        sweep_values=[10, 20],
        images_per_step=1,
    )
    base_cfg = {"txt2img": {"steps": 5}}
    result = controller.run_learning_plan(plan, base_cfg, metadata={"run_type": "learning"})

    assert result.steps_executed == 2
    assert result.metadata["run_type"] == "learning"
    assert controller.get_last_learning_execution_result_for_tests() is result
