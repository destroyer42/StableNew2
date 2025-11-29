# Subsystem: Learning
# Role: Drives end-to-end learning plan execution.

"""Learning runner stub implementation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from .learning_plan import LearningPlan, LearningRunResult, LearningRunStep


class LearningRunner:
    """Stub runner that prepares deterministic learning batches."""

    def __init__(self, base_config: dict | None = None) -> None:
        self._base_config = deepcopy(base_config) if base_config else {}
        self._last_plan: LearningPlan | None = None

    def prepare_learning_batches(self, plan: LearningPlan) -> List[LearningRunStep]:
        """Return placeholder LearningRunStep entries for sweep values."""

        self._last_plan = plan
        steps: List[LearningRunStep] = []
        for idx, value in enumerate(plan.sweep_values):
            config_snapshot: Dict[str, Any] = deepcopy(self._base_config)
            stage_cfg = config_snapshot.setdefault(plan.stage, {})
            if isinstance(stage_cfg, dict):
                stage_cfg[plan.target_variable] = value
            else:
                config_snapshot[plan.stage] = {plan.target_variable: value}
            steps.append(
                LearningRunStep(
                    index=idx,
                    stage=plan.stage,
                    variable=plan.target_variable,
                    value=value,
                    images_requested=plan.images_per_step,
                    config_snapshot=config_snapshot,
                )
            )
        return steps

    def run_learning_batches(self, steps: List[LearningRunStep]) -> LearningRunResult:
        """Return deterministic placeholder artifacts for provided steps."""

        plan = self._last_plan or LearningPlan(
            mode="single_variable_sweep",
            stage=steps[0].stage if steps else "txt2img",
            target_variable=steps[0].variable if steps else "steps",
            sweep_values=[step.value for step in steps] or [],
            images_per_step=steps[0].images_requested if steps else 1,
        )

        artifacts = [
            {
                "step_index": step.index,
                "status": "pending",
                "value": step.value,
            }
            for step in steps
        ]

        summary = {
            "status": "learning_stub",
            "steps": len(steps),
            "mode": plan.mode,
        }

        return LearningRunResult(
            plan=plan,
            steps=steps,
            artifacts=artifacts,
            summary=summary,
        )

    def summarize_results(self, result: LearningRunResult) -> Dict[str, Any]:
        """Produce a deterministic summary dict."""

        values = [step.value for step in result.steps]
        return {
            "mode": result.plan.mode,
            "total_steps": len(result.steps),
            "unique_values": sorted(set(values)),
            "artifacts": len(result.artifacts),
        }
