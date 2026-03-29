"""Legacy PipelineConfig types preserved only for compat/reference tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineConfig:
    """Historical controller-facing configuration used by legacy tests."""

    prompt: str
    model: str
    sampler: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    negative_prompt: str = ""
    pack_name: str | None = None
    preset_name: str | None = None
    variant_configs: list[dict[str, Any]] | None = None
    randomizer_mode: str | None = None
    randomizer_plan_size: int = 0
    lora_settings: dict[str, dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float = 0.8
    hires_fix: dict[str, Any] = field(default_factory=dict)
