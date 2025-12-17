# Subsystem: Learning
# Role: Stores learning-mode UI state and user selections.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LearningExperiment:
    """Represents a learning experiment definition."""

    name: str = ""
    description: str = ""
    baseline_config: dict[str, Any] = field(default_factory=dict)
    prompt_text: str = ""
    stage: str = "txt2img"
    variable_under_test: str = ""
    values: list[Any] = field(default_factory=list)
    images_per_value: int = 1


@dataclass
class LearningVariant:
    """Represents a single variant in a learning plan."""

    experiment_id: str = ""
    param_value: Any = None
    status: str = "pending"  # pending, running, completed, failed
    planned_images: int = 0
    completed_images: int = 0
    image_refs: list[str] = field(default_factory=list)


@dataclass
class LearningImageRef:
    """Reference to a generated image in a learning context."""

    image_path: str = ""
    variant_id: str = ""
    learning_record_id: str = ""
    rating: int | None = None
    notes: str = ""


class LearningState:
    """State management for the Learning module."""

    def __init__(self) -> None:
        self.current_experiment: LearningExperiment | None = None
        self.plan: list[LearningVariant] = []
        self.selected_variant: LearningVariant | None = None
        self.selected_image_index: int = 0
