# Subsystem: Pipeline
# Role: Stage sequencer for building canonical execution plans.

"""Stage sequencer for v2 pipeline.

This module provides the canonical StageSequencer class for building
stage execution plans. All pipeline runs should go through StageSequencer.build_plan().

The canonical stage ordering is:
    txt2img -> img2img -> adetailer -> upscale -> animatediff -> video_workflow

The preferred still-image flow is:
    txt2img -> optional img2img -> optional adetailer -> optional final upscale

Refiner and Hires are advanced txt2img metadata, not separate stage types and
not part of the preferred still-image stage chain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

from src.pipeline.config_normalizer import normalize_pipeline_config
from src.pipeline.stage_models import (
    InvalidStagePlanError,
    StageType,
    StageTypeEnum,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageMetadata:
    """Metadata attached to a stage.

    Refiner and hires fields are canonical txt2img metadata. Later stages in the
    preferred still-image flow should not inherit them implicitly.
    """

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

    stage_type: str
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

    config = normalize_pipeline_config(config)
    stages: list[StageExecution] = []
    pipeline_meta = config.get("metadata", {}) or {}
    run_id = pipeline_meta.get("run_id") or config.get("run_id")
    one_click_action = pipeline_meta.get("one_click_action")

    pipeline_flags = config.get("pipeline", {}) or {}

    txt_enabled = pipeline_flags.get("txt2img_enabled", True) and _extract_enabled(
        config, "txt2img", True
    )
    img2img_val = pipeline_flags.get("img2img_enabled")
    img_enabled = (bool(img2img_val) if img2img_val is not None else False) or _extract_enabled(
        config, "img2img", False
    )
    ad_enabled = pipeline_flags.get("adetailer_enabled", False) or _extract_enabled(
        config, "adetailer", False
    )
    up_enabled = pipeline_flags.get("upscale_enabled", False) or _extract_enabled(
        config, "upscale", False
    )
    animatediff_enabled = pipeline_flags.get("animatediff_enabled", False) or _extract_enabled(
        config, "animatediff", False
    )
    video_workflow_enabled = pipeline_flags.get("video_workflow_enabled", False) or _extract_enabled(
        config, "video_workflow", False
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

    if up_enabled:
        payload = _stage_payload(config, "upscale")
        _require_fields(payload, ["upscaler"], "upscale")
        metadata = _build_stage_metadata(config, payload, stage="upscale")
        stage = StageExecution(
            stage_type="upscale",
            config=StageConfig(enabled=up_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=generative_enabled or ad_enabled,
            produces_output_image=True,
        )
        stages.append(stage)
        order += 1

    if animatediff_enabled:
        if not any(_is_image_producing_stage(stage) for stage in stages):
            raise InvalidStagePlanError(
                "AnimateDiff requires a preceding image-producing stage."
            )
        payload = _stage_payload(config, "animatediff")
        metadata = _build_stage_metadata(config, payload, stage="animatediff")
        stage = StageExecution(
            stage_type="animatediff",
            config=StageConfig(enabled=animatediff_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=True,
            produces_output_image=False,
        )
        stages.append(stage)
        order += 1

    if video_workflow_enabled:
        if not any(_is_image_producing_stage(stage) for stage in stages):
            raise InvalidStagePlanError(
                "Video workflow requires a preceding image-producing stage."
            )
        payload = _stage_payload(config, "video_workflow")
        # workflow_id may live at top level or inside sequence_metadata (sequence jobs).
        if not payload.get("workflow_id"):
            seq_meta = payload.get("sequence_metadata") or {}
            if isinstance(seq_meta, dict) and seq_meta.get("workflow_id"):
                payload["workflow_id"] = seq_meta["workflow_id"]
        _require_fields(payload, ["workflow_id"], "video_workflow")
        metadata = _build_stage_metadata(config, payload, stage="video_workflow")
        stage = StageExecution(
            stage_type="video_workflow",
            config=StageConfig(enabled=video_workflow_enabled, payload=payload, metadata=metadata),
            order_index=order,
            requires_input_image=True,
            produces_output_image=False,
        )
        stages.append(stage)
        order += 1

    if not stages:
        raise ValueError("Pipeline has no enabled stages.")

    ordered = _normalize_stage_order(stages)
    return StageExecutionPlan(stages=ordered, run_id=run_id, one_click_action=one_click_action)


def _is_image_producing_stage(stage: StageExecution) -> bool:
    """Return True if stage produces still images that later stages can consume."""

    return stage.stage_type in {"txt2img", "img2img", "upscale", "adetailer"}


def _normalize_stage_order(stages: list[StageExecution]) -> list[StageExecution]:
    """Ensure post stages are ordered canonically, with AnimateDiff last."""

    adetailers = [stage for stage in stages if stage.stage_type == "adetailer"]
    animatediffs = [stage for stage in stages if stage.stage_type == "animatediff"]
    video_workflows = [stage for stage in stages if stage.stage_type == "video_workflow"]

    if len(animatediffs) > 1:
        raise InvalidStagePlanError("Multiple AnimateDiff stages are not supported.")
    if len(video_workflows) > 1:
        raise InvalidStagePlanError("Multiple video workflow stages are not supported.")
    if animatediffs and video_workflows:
        raise InvalidStagePlanError("Only one terminal video stage may be enabled at a time.")
    if adetailers and not any(
        _is_image_producing_stage(stage) for stage in stages if stage.stage_type != "adetailer"
    ):
        raise InvalidStagePlanError("ADetailer stage requires a preceding generation stage.")
    if animatediffs and not any(
        _is_image_producing_stage(stage) for stage in stages if stage.stage_type != "animatediff"
    ):
        raise InvalidStagePlanError("AnimateDiff stage requires a preceding image-producing stage.")
    if video_workflows and not any(
        _is_image_producing_stage(stage) for stage in stages if stage.stage_type != "video_workflow"
    ):
        raise InvalidStagePlanError("Video workflow stage requires a preceding image-producing stage.")

    order_map = {
        "txt2img": 0,
        "img2img": 1,
        "adetailer": 2,
        "upscale": 3,
        "animatediff": 4,
        "video_workflow": 5,
    }
    ordered = sorted(stages, key=lambda stage: (order_map.get(stage.stage_type, 99), stage.order_index))
    if ordered != stages:
        logger.warning("Stage plan order normalized to canonical runtime order.")
    return [replace(stage, order_index=index) for index, stage in enumerate(ordered)]


def _build_stage_metadata(
    config: dict[str, Any], payload: dict[str, Any], *, stage: str
) -> StageMetadata:
    """Build StageMetadata from config and payload."""

    pipeline_flags = config.get("pipeline", {}) or {}
    hires_fix = config.get("hires_fix", {}) or {}
    is_txt2img_stage = stage == "txt2img"

    img2img_val = pipeline_flags.get("img2img_enabled")
    img2img_enabled = bool(img2img_val) if img2img_val is not None else False

    return StageMetadata(
        refiner_enabled=bool(payload.get("refiner_enabled", False)) if is_txt2img_stage else False,
        refiner_model_name=payload.get("refiner_model_name") if is_txt2img_stage else None,
        refiner_switch_at=payload.get("refiner_switch_at") if is_txt2img_stage else None,
        hires_enabled=(
            bool(hires_fix.get("enabled", False) or payload.get("hires_enabled", False))
            if is_txt2img_stage
            else False
        ),
        hires_upscale_factor=(
            hires_fix.get("upscale_factor") or payload.get("upscale_factor")
            if is_txt2img_stage
            else None
        ),
        hires_upscaler_name=(
            hires_fix.get("upscaler_name") or payload.get("hires_upscaler_name")
            if is_txt2img_stage
            else None
        ),
        hires_denoise=(
            hires_fix.get("denoise")
            or hires_fix.get("denoise_strength")
            or payload.get("hires_denoise")
            if is_txt2img_stage
            else None
        ),
        hires_steps=hires_fix.get("steps") if is_txt2img_stage else None,
        stage_flags={
            "txt2img_enabled": pipeline_flags.get("txt2img_enabled", False),
            "img2img_enabled": img2img_enabled,
            "upscale_enabled": pipeline_flags.get("upscale_enabled", False),
            "adetailer_enabled": pipeline_flags.get("adetailer_enabled", False),
            "animatediff_enabled": pipeline_flags.get("animatediff_enabled", False),
            "video_workflow_enabled": pipeline_flags.get("video_workflow_enabled", False),
        },
    )


class StageSequencer:
    """Build canonical stage execution plans from pipeline configuration.

    Preferred still-image flow:
        txt2img -> optional img2img -> optional adetailer -> optional final upscale
    """

    def build_plan(self, pipeline_config: dict[str, Any]) -> StageExecutionPlan:
        """Build an ordered stage execution plan from a pipeline config dict."""

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
