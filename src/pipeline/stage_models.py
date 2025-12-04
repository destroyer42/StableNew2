# Subsystem: Pipeline
# Role: Canonical stage type definitions and execution plan data models.

"""Stage models for the StableNew pipeline execution system.

This module defines the canonical stage types and data structures used by
StageSequencer and PipelineRunner. All stage ordering and execution flows
must use these types.

Canonical ordering: txt2img → img2img → upscale → adetailer

Refiner and Hires are metadata on generation stages, not separate stage types.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StageType(str, Enum):
    """Canonical pipeline stage types.

    Ordering: TXT2IMG → IMG2IMG → UPSCALE → ADETAILER

    Note: Refiner and Hires are metadata on generation stages (TXT2IMG, IMG2IMG),
    not separate stage types.
    """

    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    UPSCALE = "upscale"
    ADETAILER = "adetailer"

    def is_generation_stage(self) -> bool:
        """Return True if this is a generation stage (txt2img or img2img)."""
        return self in (StageType.TXT2IMG, StageType.IMG2IMG)


class InvalidStagePlanError(ValueError):
    """Raised when a pipeline configuration produces an invalid stage plan.

    Examples:
    - ADetailer enabled without any generation stage
    - No stages enabled at all
    """

    pass


@dataclass
class StageExecution:
    """A single stage entry in a StageExecutionPlan.

    Attributes:
        stage_type: The type of stage (txt2img, img2img, upscale, adetailer)
        config_key: Pointer to the logical slot in pipeline config (e.g., "txt2img")
        config: Shallow snapshot of values needed to build the payload
        order_index: Position in the execution order (0-based)
        requires_input_image: Whether this stage needs input from a previous stage
        produces_output_image: Whether this stage produces an output image

        Refiner/Hires metadata (optional, only used on generation stages):
        refiner_enabled: Whether SDXL refiner is enabled
        refiner_model_name: Name of the refiner model
        refiner_switch_step: Step at which to switch to refiner

        hires_enabled: Whether hires fix is enabled
        hires_upscaler_name: Name of the hires upscaler
        hires_denoise_strength: Denoising strength for hires
        hires_scale_factor: Scale factor for hires

        adetailer_enabled: Whether ADetailer post-processing is enabled
    """

    stage_type: StageType
    config_key: str
    config: Mapping[str, Any] = field(default_factory=dict)
    order_index: int = 0
    requires_input_image: bool = False
    produces_output_image: bool = True

    # Refiner metadata (generation stages only)
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_step: int | None = None

    # Hires fix metadata (generation stages only)
    hires_enabled: bool = False
    hires_upscaler_name: str | None = None
    hires_denoise_strength: float | None = None
    hires_scale_factor: float | None = None

    # ADetailer toggle (may be linked as separate stage)
    adetailer_enabled: bool = False

    # Learning/variant metadata
    learning_mode: str | None = None
    variant_index: int | None = None
    farm_hint: str | None = None


@dataclass
class StageExecutionPlan:
    """Ordered list of stages to execute in a pipeline run.

    This is the canonical execution plan produced by StageSequencer.build_plan()
    and consumed by PipelineRunner.run().
    """

    stages: list[StageExecution] = field(default_factory=list)
    run_id: str | None = None
    one_click_action: str | None = None

    def is_empty(self) -> bool:
        """Return True if the plan has no stages."""
        return not self.stages

    def has_generation_stage(self) -> bool:
        """Return True if the plan contains at least one generation stage."""
        return any(
            s.stage_type in (StageType.TXT2IMG, StageType.IMG2IMG) for s in self.stages
        )

    def get_stage_types(self) -> list[StageType]:
        """Return the ordered list of stage types in this plan."""
        return [s.stage_type for s in self.stages]

    def __iter__(self) -> Iterator[StageExecution]:
        """Iterate over stages in execution order."""
        return iter(self.stages)

    def __len__(self) -> int:
        """Return the number of stages in the plan."""
        return len(self.stages)


# Backwards compatibility aliases
StageTypeEnum = StageType


__all__ = [
    "StageType",
    "StageTypeEnum",
    "StageExecution",
    "StageExecutionPlan",
    "InvalidStagePlanError",
]
