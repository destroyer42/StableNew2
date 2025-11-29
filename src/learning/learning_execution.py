# Subsystem: Learning
# Role: Coordinates execution of learning-mode runs without GUI dependencies.

"""Learning execution orchestrator (GUI/Tk free)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.learning.learning_plan import LearningPlan, LearningRunStep
from src.learning.learning_runner import LearningRunner
from src.pipeline.pipeline_runner import PipelineRunResult


PipelineRunCallable = Callable[[dict[str, Any], LearningRunStep], PipelineRunResult]


@dataclass
class LearningExecutionContext:
    """Bundled inputs for a learning execution."""

    plan: LearningPlan
    base_config: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningStepExecutionResult:
    """Result of a single learning step execution."""

    step: LearningRunStep
    pipeline_result: PipelineRunResult


@dataclass
class LearningExecutionResult:
    """Aggregate learning execution result."""

    plan: LearningPlan
    step_results: List[LearningStepExecutionResult]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def steps_executed(self) -> int:
        return len(self.step_results)


class LearningExecutionRunner:
    """Runs a LearningPlan by invoking a pipeline run per step."""

    def __init__(self, run_callable: PipelineRunCallable) -> None:
        self._run_callable = run_callable

    def run(
        self,
        context: LearningExecutionContext,
    ) -> LearningExecutionResult:
        runner = LearningRunner(context.base_config)
        steps = runner.prepare_learning_batches(context.plan)
        step_results: List[LearningStepExecutionResult] = []
        for step in steps:
            pipeline_result = self._run_callable(step.config_snapshot, step)
            step_results.append(LearningStepExecutionResult(step=step, pipeline_result=pipeline_result))
        return LearningExecutionResult(
            plan=context.plan,
            step_results=step_results,
            metadata=dict(context.metadata or {}),
        )
