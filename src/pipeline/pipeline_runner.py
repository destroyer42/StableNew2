"""Production pipeline runner integration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4
import logging

from src.api.client import SDWebUIClient
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.learning_record_builder import build_learning_record
from src.learning.run_metadata import write_run_metadata
from src.gui.state import CancellationError
from src.pipeline.executor import Pipeline
from src.pipeline.stage_sequencer import (
    StageExecutionPlan,
    StageTypeEnum,
    build_stage_execution_plan,
)
from src.utils import StructuredLogger, get_logger, LogContext, log_with_ctx
from src.utils.config import ConfigManager

if TYPE_CHECKING:  # pragma: no cover
    from src.controller.app_controller import CancelToken


@dataclass
class PipelineConfig:
    """Controller-facing configuration passed into the pipeline runner."""

    prompt: str
    model: str
    sampler: str
    width: int
    height: int
    steps: int
    cfg_scale: float
    pack_name: Optional[str] = None
    preset_name: Optional[str] = None
    variant_configs: Optional[List[dict[str, Any]]] = None
    randomizer_mode: Optional[str] = None
    randomizer_plan_size: int = 0
    lora_settings: Optional[Dict[str, dict[str, Any]]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class PipelineRunner:
    """
    Adapter that drives the real multi-stage Pipeline executor.
    """

    def run_txt2img_once(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Minimal V2.5 happy path: run txt2img once and return result dict.
        """
        ctx = LogContext(subsystem="pipeline")
        log_with_ctx(get_logger(__name__), logging.INFO, "Starting txt2img once", ctx=ctx)
        # Build minimal payload for txt2img
        payload = {
            "prompt": config.get("prompt", "A beautiful landscape, trending on artstation"),
            "negative_prompt": config.get("negative_prompt", ""),
            "steps": config.get("steps", 20),
            "cfg_scale": config.get("cfg_scale", 7.0),
            "width": config.get("width", 512),
            "height": config.get("height", 512),
            "sampler_name": config.get("sampler", "Euler a"),
            "batch_size": 1,
            "n_iter": 1,
        }
        result = self._api_client.txt2img(payload)
        # Return a minimal result dict for GUI feedback
        if result and "images" in result:
            # Simulate output path for feedback
            return {"output_path": "(image generated)", **result}
        return {"output_path": "(no image generated)", **(result or {})}

    def __init__(
        self,
        api_client: SDWebUIClient,
        structured_logger: StructuredLogger,
        *,
        config_manager: Optional[ConfigManager] = None,
        learning_record_writer: Optional[LearningRecordWriter] = None,
        on_learning_record: Optional[Callable[[LearningRecord], None]] = None,
        runs_base_dir: str | None = None,
        learning_enabled: bool = False,
    ) -> None:
        self._api_client = api_client
        self._structured_logger = structured_logger
        self._config_manager = config_manager or ConfigManager()
        self._pipeline = Pipeline(api_client, structured_logger)
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_run_result: PipelineRunResult | None = None
        self._runs_base_dir = runs_base_dir or "runs"
        self._learning_enabled = bool(learning_enabled)

    def _ensure_not_cancelled(self, cancel_token: "CancelToken" | None, context: str) -> None:
        if cancel_token and getattr(cancel_token, "is_cancelled", None) and cancel_token.is_cancelled():
            raise CancellationError(f"Cancelled during {context}")

    def set_learning_enabled(self, enabled: bool) -> None:
        """Toggle passive learning record emission."""

        self._learning_enabled = bool(enabled)

    def run(
        self,
        config: PipelineConfig,
        cancel_token: "CancelToken",
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> "PipelineRunResult":
        """Execute the full pipeline using the provided configuration."""

        if log_fn:
            log_fn("[pipeline] PipelineRunner starting execution.")

        executor_config = self._build_executor_config(config)
        prompt = config.prompt.strip() or config.pack_name or config.preset_name or "StableNew GUI Run"
        run_name = config.pack_name or config.preset_name or "stable_new_session"
        success = False
        last_image_meta: dict[str, Any] | None = None
        stage_plan: StageExecutionPlan | None = None
        run_id = str(uuid4())
        stage_events: list[dict[str, Any]] = []
        current_stage: StageTypeEnum | None = None

        try:
            reset_events = getattr(self._pipeline, "reset_stage_events", None)
            if callable(reset_events):
                reset_events()
            stage_plan = build_stage_execution_plan(executor_config)
            if not stage_plan.stages:
                raise ValueError("No pipeline stages enabled")
            self._ensure_not_cancelled(cancel_token, "pipeline start")
            run_dir = Path(self._runs_base_dir) / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            for stage in stage_plan.stages:
                current_stage = StageTypeEnum(stage.stage_type)
                self._ensure_not_cancelled(cancel_token, f"{current_stage.value} start")
                stage_events.append(
                    {
                        "stage": current_stage.value,
                        "phase": "enter",
                        "image_index": 1,
                        "total_images": 1,
                        "cancelled": False,
                    }
                )
                if current_stage == StageTypeEnum.TXT2IMG:
                    negative = executor_config.get("txt2img", {}).get("negative_prompt", "")
                    global_neg = getattr(config, "global_negative", None)
                    if global_neg and global_neg.get("enabled") and global_neg.get("text"):
                        if negative:
                            negative = f"{negative}, {global_neg['text']}"
                        else:
                            negative = global_neg["text"]
                    last_image_meta = self._call_stage(
                        self._pipeline.run_txt2img_stage,
                        prompt,
                        negative,
                        executor_config,
                        run_dir,
                        image_name=f"txt2img_{stage.order_index}",
                        cancel_token=cancel_token,
                    )
                elif current_stage == StageTypeEnum.IMG2IMG:
                    if not last_image_meta or not last_image_meta.get("path"):
                        raise ValueError("img2img requires input image from previous stage")
                    negative = executor_config.get("img2img", {}).get("negative_prompt", "")
                    global_neg = getattr(config, "global_negative", None)
                    if global_neg and global_neg.get("enabled") and global_neg.get("text"):
                        if negative:
                            negative = f"{negative}, {global_neg['text']}"
                        else:
                            negative = global_neg["text"]
                    last_image_meta = self._call_stage(
                        self._pipeline.run_img2img_stage,
                        Path(last_image_meta["path"]),
                        prompt,
                        negative,
                        executor_config.get("img2img", {}),
                        run_dir,
                        image_name=f"img2img_{stage.order_index}",
                        cancel_token=cancel_token,
                    )
                elif current_stage == StageTypeEnum.UPSCALE:
                    if not last_image_meta or not last_image_meta.get("path"):
                        raise ValueError("upscale requires input image from previous stage")
                    negative = executor_config.get("upscale", {}).get("negative_prompt", "")
                    global_neg = getattr(config, "global_negative", None)
                    if global_neg and global_neg.get("enabled") and global_neg.get("text"):
                        if negative:
                            negative = f"{negative}, {global_neg['text']}"
                        else:
                            negative = global_neg["text"]
                    last_image_meta = self._call_stage(
                        self._pipeline.run_upscale_stage,
                        Path(last_image_meta["path"]),
                        negative,
                        executor_config.get("upscale", {}),
                        run_dir,
                        image_name=Path(last_image_meta["path"]).stem,
                        cancel_token=cancel_token,
                    )
                elif current_stage == StageTypeEnum.ADETAILER:
                    if not last_image_meta or not last_image_meta.get("path"):
                        raise ValueError("adetailer requires input image from previous stage")
                    adetailer_cfg = dict(executor_config.get("adetailer", {}))
                    adetailer_cfg.setdefault("pipeline", executor_config.get("pipeline", {}))
                    last_image_meta = self._call_stage(
                        self._pipeline.run_adetailer_stage,
                        Path(last_image_meta["path"]),
                        adetailer_cfg,
                        run_dir,
                        image_name=Path(last_image_meta["path"]).stem,
                        prompt=prompt,
                        cancel_token=cancel_token,
                    )
                self._ensure_not_cancelled(cancel_token, f"{current_stage.value} post")
                stage_events.append(
                    {
                        "stage": current_stage.value,
                        "phase": "exit",
                        "image_index": 1,
                        "total_images": 1,
                        "cancelled": False,
                    }
                )
            success = True
        except CancellationError:
            stage_events.append(
                {
                    "stage": current_stage.value if current_stage else "pipeline",
                    "phase": "cancelled",
                    "image_index": 1,
                    "total_images": 1,
                    "cancelled": True,
                }
            )
        finally:
            record = None

        if log_fn:
            log_fn("[pipeline] PipelineRunner completed execution.")

        variants = config.variant_configs or [executor_config]
        if record:
            run_id = record.run_id
        metadata_payload = dict(config.metadata or {})
        metadata_payload.setdefault("stage_outputs", [])
        write_run_metadata(
            run_id,
            executor_config,
            packs=[config.pack_name] if config.pack_name else [],
            one_click_action=(config.metadata or {}).get("one_click_action"),
            stage_outputs=[],
            base_dir=self._runs_base_dir,
        )
        get_events = getattr(self._pipeline, "get_stage_events", None)
        if callable(get_events):
            stage_events = get_events() or stage_events
        result = PipelineRunResult(
            run_id=run_id,
            success=success,
            error=None,
            variants=deepcopy(variants),
            learning_records=[record] if record else [],
            randomizer_mode=config.randomizer_mode or "",
            randomizer_plan_size=config.randomizer_plan_size or len(variants),
            metadata=metadata_payload,
            stage_plan=stage_plan,
            stage_events=stage_events,
        )
        if success and self._learning_enabled:
            record = self._emit_learning_record(config, result)
            if record:
                result.learning_records = [record]
        self._last_run_result = result
        return result

    def _call_stage(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke a stage function, tolerating implementations without cancel_token."""
        try:
            return fn(*args, **kwargs)
        except TypeError:
            kwargs.pop("cancel_token", None)
            return fn(*args, **kwargs)

    def _build_executor_config(self, config: PipelineConfig) -> dict[str, Any]:
        """Prepare the executor configuration dict from PipelineConfig."""

        base = deepcopy(self._config_manager.get_default_config())

        txt2img = base.setdefault("txt2img", {})
        txt2img["model"] = config.model
        txt2img["sampler_name"] = config.sampler
        txt2img["width"] = config.width
        txt2img["height"] = config.height
        txt2img["steps"] = config.steps
        txt2img["cfg_scale"] = config.cfg_scale
        txt2img.setdefault("enabled", True)

        img2img = base.setdefault("img2img", {})
        img2img["model"] = config.model
        img2img["sampler_name"] = config.sampler
        img2img["steps"] = max(img2img.get("steps", 15), 1)
        img2img.setdefault("enabled", base.get("pipeline", {}).get("img2img_enabled", False))

        metadata = base.setdefault("metadata", {})
        if config.pack_name:
            metadata["pack_name"] = config.pack_name
        if config.preset_name:
            metadata["preset_name"] = config.preset_name
        pipeline_flags = base.setdefault("pipeline", {})
        upscale = base.setdefault("upscale", {})
        upscale.setdefault("enabled", pipeline_flags.get("upscale_enabled", False))

        return base

    def _emit_learning_record(
        self, config: PipelineConfig, run_result: PipelineRunResult
    ) -> LearningRecord | None:
        if not (self._learning_record_writer or self._learning_record_callback):
            return None
        try:
            metadata = dict(config.metadata or {})
            if config.pack_name:
                metadata["pack_name"] = config.pack_name
            if config.preset_name:
                metadata["preset_name"] = config.preset_name
            record = build_learning_record(config, run_result, learning_context=metadata)
        except Exception:
            return None

        if self._learning_record_writer:
            try:
                append = getattr(self._learning_record_writer, "append_record", None)
                if callable(append):
                    append(record)
                else:
                    self._learning_record_writer.write(record)
            except Exception:
                pass
        if self._learning_record_callback:
            try:
                self._learning_record_callback(record)
            except Exception:
                pass
        return record


@dataclass
class PipelineRunResult:
    """Stable output contract for PipelineRunner.run."""

    run_id: str
    success: bool
    error: str | None
    variants: list[dict[str, Any]]
    learning_records: list[LearningRecord]
    randomizer_mode: str = ""
    randomizer_plan_size: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    stage_plan: StageExecutionPlan | None = None
    stage_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def variant_count(self) -> int:
        return len(self.variants)


def _extract_primary_knobs(config: dict[str, Any]) -> dict[str, Any]:
    txt2img = (config or {}).get("txt2img", {}) or {}
    return {
        "model": txt2img.get("model", ""),
        "sampler": txt2img.get("sampler_name", ""),
        "scheduler": txt2img.get("scheduler", ""),
        "steps": txt2img.get("steps", 0),
        "cfg_scale": txt2img.get("cfg_scale", 0.0),
    }


__all__ = ["PipelineConfig", "PipelineRunner", "PipelineRunResult"]
