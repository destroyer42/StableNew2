# Subsystem: Learning
# Role: Defines learning plans and run steps used by learning execution.

"""Learning-mode plan data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class LearningMode(str, Enum):
    """Supported learning modes."""

    SINGLE_VARIABLE_SWEEP = "single_variable_sweep"
    MULTI_VARIABLE_EXPERIMENT = "multi_variable_experiment"


@dataclass
class LearningPlan:
    """Describes a learning run configuration."""

    mode: str
    stage: str
    target_variable: str
    sweep_values: List[Any]
    images_per_step: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningRunStep:
    """Single learning batch request."""

    index: int
    stage: str
    variable: str
    value: Any
    images_requested: int
    config_snapshot: Dict[str, Any]


@dataclass
class LearningRunResult:
    """Placeholder result for learning batches."""

    plan: LearningPlan
    steps: List[LearningRunStep]
    artifacts: List[Dict[str, Any]]
    summary: Dict[str, Any]


def _normalize_sweep_values(raw_values: Any) -> List[Any]:
    if raw_values is None:
        return []
    if isinstance(raw_values, (list, tuple, set)):
        return list(raw_values)
    return [raw_values]


def build_learning_plan_from_dict(payload: Dict[str, Any]) -> LearningPlan:
    """Construct a LearningPlan from a dict payload."""

    if payload is None:
        raise ValueError("payload must be provided")

    mode = payload.get("mode")
    stage = payload.get("stage")
    target_variable = payload.get("target_variable")

    if not mode or not stage or not target_variable:
        raise ValueError("mode, stage, and target_variable are required")

    sweep_values = _normalize_sweep_values(payload.get("sweep_values"))
    images_per_step = int(payload.get("images_per_step") or 1)
    metadata = payload.get("metadata") or {}

    return LearningPlan(
        mode=str(mode),
        stage=str(stage),
        target_variable=str(target_variable),
        sweep_values=sweep_values,
        images_per_step=images_per_step,
        metadata=dict(metadata),
    )
