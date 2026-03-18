# Subsystem: Learning
# Role: Stores learning-mode UI state and user selections.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LearningExperiment:
    """Represents a learning experiment definition.
    
    PR-LEARN-020: Added metadata field for variable specifications.
    """

    name: str = ""
    description: str = ""
    baseline_config: dict[str, Any] = field(default_factory=dict)
    prompt_text: str = ""
    stage: str = "txt2img"
    input_image_path: str = ""
    variable_under_test: str = ""
    values: list[Any] = field(default_factory=list)
    images_per_value: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)  # PR-LEARN-020: Value spec storage

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "baseline_config": dict(self.baseline_config or {}),
            "prompt_text": self.prompt_text,
            "stage": self.stage,
            "input_image_path": self.input_image_path,
            "variable_under_test": self.variable_under_test,
            "values": list(self.values or []),
            "images_per_value": int(self.images_per_value or 0),
            "metadata": dict(self.metadata or {}),
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "LearningExperiment":
        return LearningExperiment(
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            baseline_config=dict(payload.get("baseline_config") or {}),
            prompt_text=str(payload.get("prompt_text", "")),
            stage=str(payload.get("stage", "txt2img")),
            input_image_path=str(payload.get("input_image_path", "")),
            variable_under_test=str(payload.get("variable_under_test", "")),
            values=list(payload.get("values") or []),
            images_per_value=int(payload.get("images_per_value", 1) or 1),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class LearningVariant:
    """Represents a single variant in a learning plan."""

    experiment_id: str = ""
    param_value: Any = None
    status: str = "pending"  # pending, running, completed, failed
    planned_images: int = 0
    completed_images: int = 0
    image_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "param_value": self.param_value,
            "status": self.status,
            "planned_images": int(self.planned_images or 0),
            "completed_images": int(self.completed_images or 0),
            "image_refs": [str(ref) for ref in (self.image_refs or [])],
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "LearningVariant":
        return LearningVariant(
            experiment_id=str(payload.get("experiment_id", "")),
            param_value=payload.get("param_value"),
            status=str(payload.get("status", "pending")),
            planned_images=int(payload.get("planned_images", 0) or 0),
            completed_images=int(payload.get("completed_images", 0) or 0),
            image_refs=[str(ref) for ref in (payload.get("image_refs") or [])],
        )


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
        # PR-GUI-LEARN-041: Discovered-review inbox state
        self.selected_discovered_group_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        selected_variant_index = -1
        if self.selected_variant is not None:
            try:
                selected_variant_index = self.plan.index(self.selected_variant)
            except ValueError:
                selected_variant_index = -1
        return {
            "current_experiment": self.current_experiment.to_dict()
            if self.current_experiment
            else None,
            "plan": [variant.to_dict() for variant in self.plan],
            "selected_variant_index": selected_variant_index,
            "selected_image_index": int(self.selected_image_index or 0),
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "LearningState":
        state = LearningState()
        experiment_payload = payload.get("current_experiment")
        if isinstance(experiment_payload, dict):
            state.current_experiment = LearningExperiment.from_dict(experiment_payload)
        state.plan = [
            LearningVariant.from_dict(item)
            for item in (payload.get("plan") or [])
            if isinstance(item, dict)
        ]
        selected_variant_index = int(payload.get("selected_variant_index", -1) or -1)
        if 0 <= selected_variant_index < len(state.plan):
            state.selected_variant = state.plan[selected_variant_index]
        state.selected_image_index = int(payload.get("selected_image_index", 0) or 0)
        return state
