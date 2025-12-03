"""Stage sequencer for v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Literal, List, Optional

import logging


StageType = Literal["txt2img", "img2img", "upscale", "adetailer"]

logger = logging.getLogger(__name__)


class StageTypeEnum(str, Enum):
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    UPSCALE = "upscale"
    ADETAILER = "adetailer"


@dataclass(frozen=True)
class StageMetadata:
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float | None = None
    hires_enabled: bool = False
    hires_upscale_factor: float | None = None
    hires_denoise: float | None = None
    hires_steps: int | None = None
    stage_flags: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class StageConfig:
    enabled: bool
    payload: dict[str, Any]
    metadata: StageMetadata


@dataclass(frozen=True)
class StageMetadata:
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float | None = None
    hires_enabled: bool = False
    hires_upscale_factor: float | None = None
    hires_denoise: float | None = None
    hires_steps: int | None = None
    stage_flags: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class StageExecution:
    stage_type: StageType
    config: StageConfig
    order_index: int
    requires_input_image: bool
    produces_output_image: bool
    learning_mode: str | None = None
    variant_index: int | None = None
    farm_hint: str | None = None


@dataclass(frozen=True)
class StageExecutionPlan:
    stages: List[StageExecution]
    run_id: str | None = None
    one_click_action: str | None = None


def _extract_enabled(config: dict[str, Any], section: str, default: bool) -> bool:
    section_cfg = config.get(section, {}) or {}
    return bool(section_cfg.get("enabled", default))


def _require_fields(payload: dict[str, Any], fields: list[str], stage_name: str) -> None:
    missing = [f for f in fields if payload.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{stage_name} missing required fields: {', '.join(missing)}")


def _stage_payload(config: dict[str, Any], section: str) -> dict[str, Any]:
    return dict((config.get(section, {}) or {}))


def build_stage_execution_plan(config: dict[str, Any]) -> StageExecutionPlan:
    """Build an ordered stage execution plan from a pipeline config dict."""

    stages: list[StageExecution] = []
    pipeline_meta = config.get("metadata", {}) or {}
    run_id = pipeline_meta.get("run_id") or config.get("run_id")
    one_click_action = pipeline_meta.get("one_click_action")

    pipeline_flags = config.get("pipeline", {}) or {}
    txt_enabled = _extract_enabled(config, "txt2img", True) and pipeline_flags.get(
        "txt2img_enabled", True
    )
    img_enabled = _extract_enabled(config, "img2img", False) and pipeline_flags.get(
        "img2img_enabled", True
    )
    ad_enabled = _extract_enabled(config, "adetailer", False) and pipeline_flags.get(
        "adetailer_enabled", False
    )
    up_enabled = _extract_enabled(config, "upscale", False) and pipeline_flags.get(
        "upscale_enabled", False
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
            requires_input_image=not generative_enabled,
            produces_output_image=True,
        )
        stages.append(stage)
        order += 1

    if ad_enabled:
        if not generative_enabled and not up_enabled:
            raise ValueError("ADetailer stage requires a preceding generation or upscale stage.")
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
    return stage.stage_type in {"txt2img", "img2img", "upscale"}


def _normalize_stage_order(stages: List[StageExecution]) -> List[StageExecution]:
    generation = [stage for stage in stages if _is_generative_stage(stage)]
    adetailers = [stage for stage in stages if stage.stage_type == "adetailer"]
    if adetailers and not generation:
        raise ValueError("ADetailer stage requires a preceding generation stage.")
    if adetailers and stages and stages[-1].stage_type != "adetailer":
        logger.warning(
            "ADetailer stage detected before generation/hires stages; auto-moving ADetailer to final position."
        )
    if not adetailers:
        return stages
    ordered = generation + adetailers
    if ordered == stages:
        return stages
    return ordered


def _build_stage_metadata(config: dict[str, Any], payload: dict[str, Any], *, stage: str) -> StageMetadata:
    pipeline_flags = config.get("pipeline", {}) or {}
    metadata = StageMetadata(
        refiner_enabled=payload.get("refiner_enabled", False),
        refiner_model_name=payload.get("refiner_model_name"),
        refiner_switch_at=payload.get("refiner_switch_at"),
        hires_enabled=config.get("hires_fix", {}).get("enabled", False)
        or payload.get("hires_enabled", False),
        hires_upscale_factor=config.get("hires_fix", {}).get("upscale_factor")
        or payload.get("upscale_factor"),
        hires_denoise=config.get("hires_fix", {}).get("denoise_strength")
        or payload.get("hires_denoise"),
        hires_steps=config.get("hires_fix", {}).get("steps"),
        stage_flags={
            "txt2img_enabled": pipeline_flags.get("txt2img_enabled", False),
            "img2img_enabled": pipeline_flags.get("img2img_enabled", False),
            "upscale_enabled": pipeline_flags.get("upscale_enabled", False),
            "adetailer_enabled": pipeline_flags.get("adetailer_enabled", False),
        },
    )
    return metadata
