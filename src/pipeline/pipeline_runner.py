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
from src.pipeline.executor import Pipeline, PipelineStageError
from src.pipeline.stage_sequencer import (
    StageExecution,
    StageExecutionPlan,
    StageMetadata,
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
    negative_prompt: str = ""
    pack_name: Optional[str] = None
    preset_name: Optional[str] = None
    variant_configs: Optional[List[dict[str, Any]]] = None
    randomizer_mode: Optional[str] = None
    randomizer_plan_size: int = 0
    lora_settings: Optional[Dict[str, dict[str, Any]]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    refiner_enabled: bool = False
    refiner_model_name: str | None = None
    refiner_switch_at: float = 0.8
    hires_fix: dict[str, Any] = field(default_factory=dict)


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

    def _is_generative_stage_type(self, stage_type: str) -> bool:
        return stage_type in {
            StageTypeEnum.TXT2IMG.value,
            StageTypeEnum.IMG2IMG.value,
            StageTypeEnum.UPSCALE.value,
        }

    def _validate_stage_plan(self, plan: StageExecutionPlan) -> None:
        stages = plan.stages or []
        if not stages:
            raise ValueError("Pipeline plan contains no enabled stages.")
        adetailers = [stage for stage in stages if stage.stage_type == StageTypeEnum.ADETAILER.value]
        if len(adetailers) > 1:
            raise ValueError("Multiple ADetailer stages are not supported.")
        if adetailers and stages[-1].stage_type != StageTypeEnum.ADETAILER.value:
            raise ValueError("ADetailer stage must be the final stage.")
        if adetailers and not any(self._is_generative_stage_type(stage.stage_type) for stage in stages):
            raise ValueError("ADetailer stage requires a preceding generation stage.")

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
            self._validate_stage_plan(stage_plan)
            if not stage_plan.stages:
                raise ValueError("No pipeline stages enabled")
            self._ensure_not_cancelled(cancel_token, "pipeline start")
            run_dir = Path(self._runs_base_dir) / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            prev_image_path: Path | None = None
            prompt = config.prompt
            negative_prompt = getattr(config, "negative_prompt", "") or ""
            for stage in stage_plan.stages:
                current_stage = StageTypeEnum(stage.stage_type)
                self._apply_stage_metadata(executor_config, stage)
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
                input_image_path = None
                if last_image_meta and last_image_meta.get("path"):
                    input_image_path = Path(last_image_meta["path"])
                payload = self._build_stage_payload(
                    stage,
                    config,
                    executor_config,
                    prompt,
                    negative_prompt,
                    input_image_path,
                )
                last_image_meta = self._call_stage(
                    stage,
                    payload,
                    run_dir,
                    cancel_token,
                    input_image_path,
                )
                if last_image_meta and last_image_meta.get("path"):
                    prev_image_path = Path(last_image_meta["path"])
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
        except PipelineStageError as exc:
            stage_events.append(
                {
                    "stage": exc.error.stage or "pipeline",
                    "phase": "error",
                    "image_index": 1,
                    "total_images": 1,
                    "cancelled": True,
                    "error_code": exc.error.code.value,
                    "error_message": exc.error.message,
                }
            )
            log_with_ctx(
                get_logger(__name__),
                logging.ERROR,
                f"Pipeline stage failed: {exc.error.stage} ({exc.error.code}) {exc.error.message}",
                ctx=LogContext(subsystem="pipeline"),
            )
            raise
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

    def _call_stage(
        self,
        stage: StageExecution,
        payload: dict[str, Any],
        run_dir: Path,
        cancel_token: "CancelToken" | None,
        input_image_path: Path | None,
    ) -> dict[str, Any] | None:
        """Execute a stage using the executor helpers and the built payload."""

        stage_type = StageTypeEnum(stage.stage_type)
        image_name = f"{stage_type.value}_{stage.order_index}"
        if stage_type == StageTypeEnum.TXT2IMG:
            return self._pipeline.run_txt2img_stage(
                payload.get("prompt", ""),
                payload.get("negative_prompt", ""),
                payload,
                run_dir,
                image_name=image_name,
                cancel_token=cancel_token,
            )
        if stage_type == StageTypeEnum.IMG2IMG:
            if not input_image_path:
                raise ValueError("img2img requires input image from previous stage")
            return self._pipeline.run_img2img_stage(
                input_image_path,
                payload.get("prompt", ""),
                payload,
                run_dir,
                image_name=image_name,
                cancel_token=cancel_token,
            )
        if stage_type == StageTypeEnum.UPSCALE:
            if not input_image_path:
                raise ValueError("upscale requires input image from previous stage")
            return self._pipeline.run_upscale_stage(
                input_image_path,
                payload,
                run_dir,
                image_name=image_name,
                cancel_token=cancel_token,
            )
        if stage_type == StageTypeEnum.ADETAILER:
            if not input_image_path:
                raise ValueError("adetailer requires input image from previous stage")
            return self._pipeline.run_adetailer_stage(
                input_image_path,
                payload,
                run_dir,
                image_name=image_name,
                prompt=payload.get("prompt"),
                cancel_token=cancel_token,
            )
        raise ValueError(f"Unsupported stage {stage_type.value}")

    def _apply_stage_metadata(self, executor_config: dict[str, Any], stage: StageExecution) -> None:
        """Merge stage metadata into the executor config before execution."""
        if stage.stage_type != StageTypeEnum.TXT2IMG.value:
            return
        metadata = stage.config.metadata
        if not isinstance(metadata, StageMetadata):
            return
        txt_cfg = executor_config.setdefault("txt2img", {})
        txt_cfg["refiner_enabled"] = metadata.refiner_enabled
        if metadata.refiner_enabled:
            if metadata.refiner_model_name:
                txt_cfg["refiner_model_name"] = metadata.refiner_model_name
            if metadata.refiner_switch_at is not None:
                try:
                    txt_cfg["refiner_switch_at"] = float(metadata.refiner_switch_at)
                except Exception:
                    pass
        txt_cfg["enable_hr"] = metadata.hires_enabled
        if metadata.hires_enabled:
            if metadata.hires_upscale_factor is not None:
                try:
                    txt_cfg["hr_scale"] = float(metadata.hires_upscale_factor)
                except Exception:
                    pass
            if metadata.hires_denoise is not None:
                try:
                    txt_cfg["denoising_strength"] = float(metadata.hires_denoise)
                except Exception:
                    pass
            if metadata.hires_steps is not None:
                try:
                    txt_cfg["hr_second_pass_steps"] = max(0, int(metadata.hires_steps))
                except Exception:
                    pass

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
        txt2img["refiner_enabled"] = config.refiner_enabled
        txt2img["refiner_model_name"] = config.refiner_model_name or ""
        txt2img["refiner_switch_at"] = config.refiner_switch_at

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
        metadata_flag = (config.metadata or {}).get("adetailer_enabled")
        if isinstance(metadata_flag, bool):
            pipeline_flags["adetailer_enabled"] = metadata_flag
        pipeline_flags.setdefault("adetailer_enabled", False)
        up_enabled = pipeline_flags.get("upscale_enabled", False)
        upscale = base.setdefault("upscale", {})
        upscale.setdefault("enabled", up_enabled)

        ad_cfg = base.setdefault("adetailer", {})
        metadata_adetailer = (config.metadata or {}).get("adetailer")
        if isinstance(metadata_adetailer, dict):
            ad_cfg.update(metadata_adetailer)
        ad_cfg["enabled"] = pipeline_flags["adetailer_enabled"]
        ad_cfg["adetailer_enabled"] = pipeline_flags["adetailer_enabled"]
        base["hires_fix"] = dict(config.hires_fix or {})

        return base

    def _build_stage_payload(
        self,
        stage: StageExecution,
        config: PipelineConfig,
        executor_config: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        input_image_path: Path | None,
    ) -> dict[str, Any]:
        """Construct a per-stage payload from the plan metadata."""

        payload = dict(stage.config.payload or {})
        payload.setdefault("prompt", prompt)
        payload.setdefault("negative_prompt", negative_prompt)

        payload.setdefault("model", config.model)
        payload.setdefault("sampler_name", config.sampler)
        payload.setdefault("scheduler", executor_config.get("txt2img", {}).get("scheduler"))
        payload.setdefault("steps", config.steps)
        payload.setdefault("cfg_scale", config.cfg_scale)
        if config.pack_name:
            payload.setdefault("pack_name", config.pack_name)
        if config.preset_name:
            payload.setdefault("preset_name", config.preset_name)

        payload["stage_type"] = stage.stage_type
        metadata = stage.config.metadata
        if isinstance(metadata, dict):
            metadata = StageMetadata(
                refiner_enabled=bool(metadata.get("refiner_enabled", False)),
                refiner_model_name=metadata.get("refiner_model_name"),
                refiner_switch_at=metadata.get("refiner_switch_at"),
                hires_enabled=bool(metadata.get("hires_enabled", False)),
                hires_upscale_factor=metadata.get("hires_upscale_factor"),
                hires_denoise=metadata.get("hires_denoise"),
                hires_steps=metadata.get("hires_steps"),
                stage_flags=metadata.get("stage_flags", {}),
            )
        if not isinstance(metadata, StageMetadata):
            metadata = StageMetadata()
            payload["refiner_enabled"] = metadata.refiner_enabled
            payload["refiner_model_name"] = metadata.refiner_model_name
            if metadata.refiner_switch_at is not None:
                payload["refiner_switch_at"] = metadata.refiner_switch_at
            payload["hires_enabled"] = metadata.hires_enabled
            if metadata.hires_upscale_factor is not None:
                payload["hires_upscale_factor"] = metadata.hires_upscale_factor
            if metadata.hires_denoise is not None:
                payload["hires_denoise"] = metadata.hires_denoise
            if metadata.hires_steps is not None:
                payload["hires_steps"] = metadata.hires_steps
            for flag, value in metadata.stage_flags.items():
                payload.setdefault(flag, value)

        if input_image_path:
            encoded = self._pipeline._load_image_base64(input_image_path)
            if encoded:
                payload["init_images"] = [encoded]
                payload["input_image_path"] = str(input_image_path)
        return payload

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
