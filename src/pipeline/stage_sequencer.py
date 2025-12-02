"""Stage sequencer for v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

import logging


StageType = Literal["txt2img", "img2img", "upscale", "adetailer"]

logger = logging.getLogger(__name__)


class StageTypeEnum(str, Enum):
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    UPSCALE = "upscale"
    ADETAILER = "adetailer"


@dataclass(frozen=True)
class StageConfig:
    enabled: bool
    payload: dict[str, Any]


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
    stages: list[StageExecution]
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
    if txt_enabled:
        payload = _stage_payload(config, "txt2img")
        _require_fields(payload, ["model", "sampler_name", "steps", "cfg_scale"], "txt2img")
        stages.append(
            StageExecution(
                stage_type="txt2img",
                config=StageConfig(enabled=txt_enabled, payload=payload),
                order_index=order,
                requires_input_image=False,
                produces_output_image=True,
            )
        )
        order += 1

    if img_enabled:
        payload = _stage_payload(config, "img2img")
        _require_fields(payload, ["model", "sampler_name", "steps"], "img2img")
        stages.append(
            StageExecution(
                stage_type="img2img",
                config=StageConfig(enabled=img_enabled, payload=payload),
                order_index=order,
                requires_input_image=True,
                produces_output_image=True,
            )
        )
        order += 1

    generative_enabled = txt_enabled or img_enabled
    if ad_enabled:
        payload = _stage_payload(config, "adetailer")
        if not generative_enabled:
            logger.warning("ADetailer enabled but no generative stage active; skipping adetailer.")
        else:
            stages.append(
                StageExecution(
                    stage_type="adetailer",
                    config=StageConfig(enabled=ad_enabled, payload=payload),
                    order_index=order,
                    requires_input_image=True,
                    produces_output_image=True,
                )
            )
        order += 1

    if up_enabled:
        payload = _stage_payload(config, "upscale")
        _require_fields(payload, ["upscaler"], "upscale")
        stages.append(
            StageExecution(
                stage_type="upscale",
                config=StageConfig(enabled=up_enabled, payload=payload),
                order_index=order,
                requires_input_image=True,
                produces_output_image=True,
            )
        )

    return StageExecutionPlan(stages=stages, run_id=run_id, one_click_action=one_click_action)
