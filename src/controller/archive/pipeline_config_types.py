# VIEW-ONLY (v2.6)
"""Legacy PipelineConfig types (archived, view-only).

This module contains the historical PipelineConfig dataclass used by
legacy code paths. It is preserved only for reference and archive
usage; runtime execution must not depend on this module in v2.6.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PipelineConfig:
    """Controller-facing configuration passed into the pipeline runner (legacy)."""

    prompt: str
    model: str
    sampler: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    negative_prompt: str = ""
    pack_name: Optional[str] = None
    preset_name: Optional[str] = None
    variant_configs: Optional[List[Dict[str, Any]]] = None
    randomizer_mode: Optional[str] = None
    randomizer_plan_size: int = 0
    lora_settings: Optional[Dict[str, Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_at: float = 0.8
    hires_fix: Dict[str, Any] = field(default_factory=dict)
