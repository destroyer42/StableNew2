# Subsystem: Pipeline
# Role: Stage sequencer for building canonical execution plans.

"""Stage sequencer for v2 pipeline.

This module provides the canonical StageSequencer class for building
stage execution plans. All pipeline runs should go through StageSequencer.build_plan().

The canonical stage ordering is:
    txt2img → img2img → upscale → adetailer

Refiner and Hires are metadata on generation stages, not separate stage types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.pipeline.stage_models import (
    InvalidStagePlanError,
    StageType,
    StageTypeEnum,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageMetadata:
    """Metadata attached to a stage (refiner, hires, flags)."""

    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float | None = None
    hires_enabled: bool = False
    hires_upscale_factor: float | None = None
    hires_upscaler_name: str | None = None
    hires_denoise: float | None = None
    hires_steps: int | None = None
    stage_flags: dict[str, bool] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like access for backward compatibility."""
        return getattr(self, key, default)


@dataclass(frozen=True)
class StageConfig:
    """Configuration for a single stage."""

    enabled: bool
    payload: dict[str, Any]
    metadata: StageMetadata


@dataclass(frozen=True)
class StageExecution:
    """A single stage in the execution plan."""

    stage_type: str  # Keep as str for backward compatibility
    config: StageConfig
    order_index: int
    requires_input_image: bool
    produces_output_image: bool
    learning_mode: str | None = None
    variant_index: int | None = None
    farm_hint: str | None = None


@dataclass(frozen=True)
class StageExecutionPlan:
    """Ordered list of stages to execute."""

    stages: list[StageExecution]
    run_id: str | None = None
    one_click_action: str | None = None

    def is_empty(self) -> bool:
        """Return True if the plan has no stages."""
        return not self.stages

    def has_generation_stage(self) -> bool:
        """Return True if the plan contains at least one generation stage."""
        return any(s.stage_type in ("txt2img", "img2img") for s in self.stages)

    def get_stage_types(self) -> list[str]:
        """Return the ordered list of stage types in this plan."""
        return [s.stage_type for s in self.stages]


def _extract_enabled(config: dict[str, Any], section: str, default: bool) -> bool:
    section_cfg = config.get(section, {}) or {}
    return bool(section_cfg.get("enabled", default))


def _require_fields(payload: dict[str, Any], fields: list[str], stage_name: str) -> None:
    missing = [f for f in fields if payload.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{stage_name} missing required fields: {', '.join(missing)}")


def _stage_payload(config: dict[str, Any], section: str) -> dict[str, Any]:
    return dict(config.get(section, {}) or {})


def build_stage_execution_plan(config: dict[str, Any]) -> StageExecutionPlan:
    """Build an ordered stage execution plan from a pipeline config dict."""

    stages: list[StageExecution] = []
    pipeline_meta = config.get("metadata", {}) or {}
    run_id = pipeline_meta.get("run_id") or config.get("run_id")
    one_click_action = pipeline_meta.get("one_click_action")

    pipeline_flags = config.get("pipeline", {}) or {}

    # Determine which stages are enabled using pipeline flags as primary source
    # Fall back to section-level enabled flags for backward compatibility
    txt_enabled = pipeline_flags.get("txt2img_enabled", True) and _extract_enabled(
        config, "txt2img", True
    )
    img_enabled = pipeline_flags.get("img2img_enabled", False) or _extract_enabled(
        config, "img2img", False
    )
    ad_enabled = pipeline_flags.get("adetailer_enabled", False) or _extract_enabled(
        config, "adetailer", False
    )
    up_enabled = pipeline_flags.get("upscale_enabled", False) or _extract_enabled(
        config, "upscale", False
    )

    order = 0
    generation_stages = []
    if txt_enabled:
        payload = _stage_payload(config, "txt2img")
        _require_fields(payload, ["model", "sampler_name", "steps", "cfg_scale"], "txt2img")
        metadata = _build_stage_metadata(config, payload, stage="txt2img")
        stage = StageExecution(
            stage_type="txt2img",
            config=StageConfig(enabled=txt_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=False,
            produces_output_image=True,
        )
        stages.append(stage)
        generation_stages.append(stage)
        order += 1

    if img_enabled:
        payload = _stage_payload(config, "img2img")
        _require_fields(payload, ["model", "sampler_name", "steps"], "img2img")
        metadata = _build_stage_metadata(config, payload, stage="img2img")
        stage = StageExecution(
            stage_type="img2img",
            config=StageConfig(enabled=img_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=True,
            produces_output_image=True,
        )
        stages.append(stage)
        generation_stages.append(stage)
        order += 1

    generative_enabled = bool(generation_stages)

    if up_enabled:
        payload = _stage_payload(config, "upscale")
        _require_fields(payload, ["upscaler"], "upscale")
        metadata = _build_stage_metadata(config, payload, stage="upscale")
        stage = StageExecution(
            stage_type="upscale",
            config=StageConfig(enabled=up_enabled, payload=payload, metadata=metadata),
            order_index=order,
            # Upscale requires input if there's a preceding generation stage
            requires_input_image=generative_enabled,
            produces_output_image=True,
        )
        stages.append(stage)
        order += 1

    if ad_enabled:
        if not generative_enabled and not up_enabled:
            raise InvalidStagePlanError(
                "ADetailer requires at least one generation stage (txt2img or img2img)."
            )
        payload = _stage_payload(config, "adetailer")
        metadata = _build_stage_metadata(config, payload, stage="adetailer")
        stage = StageExecution(
            stage_type="adetailer",
            config=StageConfig(enabled=ad_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=True,
            produces_output_image=True,
        )
        stages.append(stage)
        order += 1

    if not stages:
        raise ValueError("Pipeline has no enabled stages.")

    ordered = _normalize_stage_order(stages)
    return StageExecutionPlan(stages=ordered, run_id=run_id, one_click_action=one_click_action)


def _is_generative_stage(stage: StageExecution) -> bool:
    """Return True if stage is a generative stage (txt2img, img2img, upscale)."""
    return stage.stage_type in {"txt2img", "img2img", "upscale"}


def _normalize_stage_order(stages: list[StageExecution]) -> list[StageExecution]:
    """Ensure ADetailer is always the final stage."""
    generation = [stage for stage in stages if _is_generative_stage(stage)]
    adetailers = [stage for stage in stages if stage.stage_type == "adetailer"]

    if adetailers and not generation:
        raise InvalidStagePlanError("ADetailer stage requires a preceding generation stage.")

    if adetailers and stages and stages[-1].stage_type != "adetailer":
        logger.warning(
            "ADetailer stage detected before generation/hires stages; "
            "auto-moving ADetailer to final position."
        )

    if not adetailers:
        return stages

    ordered = generation + adetailers
    if ordered == stages:
        return stages
    return ordered


def _build_stage_metadata(
    config: dict[str, Any], payload: dict[str, Any], *, stage: str
) -> StageMetadata:
    """Build StageMetadata from config and payload."""
    pipeline_flags = config.get("pipeline", {}) or {}
    hires_fix = config.get("hires_fix", {}) or {}

    metadata = StageMetadata(
        refiner_enabled=payload.get("refiner_enabled", False),
        refiner_model_name=payload.get("refiner_model_name"),
        refiner_switch_at=payload.get("refiner_switch_at"),
        hires_enabled=hires_fix.get("enabled", False) or payload.get("hires_enabled", False),
        hires_upscale_factor=hires_fix.get("upscale_factor") or payload.get("upscale_factor"),
        hires_upscaler_name=hires_fix.get("upscaler_name") or payload.get("hires_upscaler_name"),
        hires_denoise=hires_fix.get("denoise")
        or hires_fix.get("denoise_strength")
        or payload.get("hires_denoise"),
        hires_steps=hires_fix.get("steps"),
        stage_flags={
            "txt2img_enabled": pipeline_flags.get("txt2img_enabled", False),
            "img2img_enabled": pipeline_flags.get("img2img_enabled", False),
            "upscale_enabled": pipeline_flags.get("upscale_enabled", False),
            "adetailer_enabled": pipeline_flags.get("adetailer_enabled", False),
        },
    )
    return metadata


class StageSequencer:
    """Builds canonical stage execution plans from pipeline configuration.

    This is the single source of truth for stage ordering. All pipeline runs
    should go through StageSequencer.build_plan().

    Usage:
        sequencer = StageSequencer()
        plan = sequencer.build_plan(pipeline_config)
    """

    def build_plan(self, pipeline_config: dict[str, Any]) -> StageExecutionPlan:
        """Build an ordered stage execution plan from a pipeline config dict.

        Args:
            pipeline_config: Dictionary containing stage configurations and flags.

        Returns:
            StageExecutionPlan with ordered stages.

        Raises:
            InvalidStagePlanError: If ADetailer is enabled without any generation stage.
            ValueError: If required fields are missing or no stages are enabled.
        """
        return build_stage_execution_plan(pipeline_config)


__all__ = [
    "StageSequencer",
    "StageExecution",
    "StageExecutionPlan",
    "StageMetadata",
    "StageConfig",
    "StageType",
    "StageTypeEnum",
    "InvalidStagePlanError",
    "build_stage_execution_plan",
]
