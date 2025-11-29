# Subsystem: Learning
# Role: Builds learning plans and sweeps from base configs and pipeline context.

"""Learning adapter helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple

from .learning_plan import LearningPlan, LearningRunStep
from .learning_runner import LearningRunner


def build_learning_plan_from_config(
    base_config: Dict[str, Any],
    *,
    stage: str,
    target_variable: str,
    sweep_values: List[Any],
    images_per_step: int = 1,
    metadata: Dict[str, Any] | None = None,
) -> LearningPlan:
    """Construct a plan from config + sweep parameters."""

    return LearningPlan(
        mode="single_variable_sweep",
        stage=stage,
        target_variable=target_variable,
        sweep_values=list(sweep_values),
        images_per_step=int(images_per_step or 1),
        metadata=dict(metadata or {}),
    )


def prepare_learning_run(
    base_config: Dict[str, Any],
    options: Dict[str, Any],
) -> Tuple[LearningPlan, List[LearningRunStep]]:
    """Return plan + steps based on base_config and options."""

    stage = options.get("stage", "txt2img")
    target_variable = options.get("target_variable", "steps")
    sweep_values = options.get("sweep_values") or []
    images_per_step = options.get("images_per_step", 1)
    metadata = options.get("metadata") or {}

    plan = build_learning_plan_from_config(
        base_config,
        stage=stage,
        target_variable=target_variable,
        sweep_values=list(sweep_values),
        images_per_step=images_per_step,
        metadata=metadata,
    )

    runner = LearningRunner(deepcopy(base_config))
    steps = runner.prepare_learning_batches(plan)
    return plan, steps
