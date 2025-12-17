"""Production pipeline runner integration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.api.client import SDWebUIClient
from src.gui.state import CancellationError
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.learning_record_builder import build_learning_record
from src.learning.run_metadata import write_run_metadata
from src.pipeline.executor import Pipeline
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.payload_builder import build_sdxl_payload
from src.pipeline.stage_sequencer import (
    StageExecution,
    StageExecutionPlan,
    StageMetadata,
    StageSequencer,
    StageTypeEnum,
)
from src.utils import LogContext, StructuredLogger, get_logger, log_with_ctx
from src.utils.config import ConfigManager

if TYPE_CHECKING:  # pragma: no cover
    from src.controller.app_controller import CancelToken


class PipelineRunner:
    """
    Adapter that drives the real multi-stage Pipeline executor.
    """

    def run_njr(
        self,
        njr: NormalizedJobRecord,
        cancel_token: CancelToken | None = None,
        log_fn: Callable[[str], None] | None = None,
        run_plan: Any | None = None,
    ) -> PipelineRunResult:
        """
        Execute the pipeline using a NormalizedJobRecord (NJR-only, v2.6+ contract).
        This is the ONLY supported production entrypoint.
        """
        # Build run plan directly from NJR
        from src.pipeline.run_plan import build_run_plan_from_njr

        plan = build_run_plan_from_njr(njr)
        # Prepare output dir and metadata
        run_id = str(uuid4())
        run_dir = Path(self._runs_base_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stage_events: list[dict[str, Any]] = []
        success = False
        error = None
        variants = []
        learning_records = []
        metadata = dict(njr.config or {})
        try:
            # For each stage in the plan, execute and collect results
            last_image_meta = None
            prompt = getattr(njr, "positive_prompt", "") or ""
            negative_prompt = getattr(njr, "negative_prompt", "") or ""
            for stage in plan.jobs:
                # Build payload for this stage
                payload = {
                    "prompt": stage.prompt_text,
                    "negative_prompt": negative_prompt,
                    "model": stage.model,
                    "sampler_name": stage.sampler,
                    "steps": njr.steps or 20,
                    "cfg_scale": stage.cfg_scale or njr.cfg_scale or 7.5,
                    "width": njr.width or 1024,
                    "height": njr.height or 1024,
                }
                # Call the appropriate pipeline stage
                result = self._pipeline.run_txt2img_stage(
                    payload["prompt"],
                    payload["negative_prompt"],
                    payload,
                    run_dir,
                    image_name=f"{stage.stage_name}_{stage.variant_id:02d}",
                    cancel_token=cancel_token,
                )
                variants.append(result)
                stage_events.append(
                    {
                        "stage": stage.stage_name,
                        "phase": "exit",
                        "image_index": 1,
                        "total_images": 1,
                        "cancelled": False,
                    }
                )
            success = True
        except Exception as exc:
            error = str(exc)
            stage_events.append(
                {
                    "stage": stage.stage_name if "stage" in locals() else "pipeline",
                    "phase": "error",
                    "image_index": 1,
                    "total_images": 1,
                    "cancelled": True,
                    "error_message": str(exc),
                }
            )
        result = PipelineRunResult(
            run_id=run_id,
            success=success,
            error=error,
            variants=variants,
            learning_records=learning_records,
            randomizer_mode=getattr(njr, "randomizer_mode", ""),
            randomizer_plan_size=getattr(njr, "variant_total", 1),
            metadata=metadata,
            stage_plan=plan,
            stage_events=stage_events,
        )
        try:
            write_run_metadata(run_id, metadata, base_dir=self._runs_base_dir)
        except Exception:
            pass
        self._last_run_result = result
        return result

    # Remove legacy run() and _pipeline_config_from_njr from production path

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
        config_manager: ConfigManager | None = None,
        learning_record_writer: LearningRecordWriter | None = None,
        on_learning_record: Callable[[LearningRecord], None] | None = None,
        runs_base_dir: str | None = None,
        learning_enabled: bool = False,
        sequencer: StageSequencer | None = None,
    ) -> None:
        self._api_client = api_client
        self._structured_logger = structured_logger
        self._config_manager = config_manager or ConfigManager()
        self._pipeline = Pipeline(api_client, structured_logger)
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_run_result: PipelineRunResult | None = None
        self._runs_base_dir = runs_base_dir or "output"
        self._learning_enabled = bool(learning_enabled)
        self._sequencer = sequencer or StageSequencer()

    def _ensure_not_cancelled(self, cancel_token: CancelToken | None, context: str) -> None:
        if (
            cancel_token
            and getattr(cancel_token, "is_cancelled", None)
            and cancel_token.is_cancelled()
        ):
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
        adetailers = [
            stage for stage in stages if stage.stage_type == StageTypeEnum.ADETAILER.value
        ]
        if len(adetailers) > 1:
            raise ValueError("Multiple ADetailer stages are not supported.")
        if adetailers and stages[-1].stage_type != StageTypeEnum.ADETAILER.value:
            raise ValueError("ADetailer stage must be the final stage.")
        if adetailers and not any(
            self._is_generative_stage_type(stage.stage_type) for stage in stages
        ):
            raise ValueError("ADetailer stage requires a preceding generation stage.")

    def set_learning_enabled(self, enabled: bool) -> None:
        """Toggle passive learning record emission."""

        self._learning_enabled = bool(enabled)

    # Legacy controller config-based execution paths removed per v2.6 contract.
    # See build_run_plan_from_njr() + run_njr() for canonical NJR-only execution.

    # Note: canonical NJR entrypoint defined earlier in this module. Do not define
    # a secondary run_njr conversion path that converts NJR -> legacy config.

    pass

    def _call_stage(
        self,
        stage: StageExecution,
        payload: dict[str, Any],
        run_dir: Path,
        cancel_token: CancelToken | None,
        input_image_path: Path | None,
        prompt_index: int = 1,
        job_date: str = "",
        job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Execute a stage using the executor helpers and the built payload.

        Image naming convention: {stage_type}_{prompt_index:02d}_{date}.png
        Example: txt2img_01_2024-12-04.png
        """

        stage_type = StageTypeEnum(stage.stage_type)
        log_with_ctx(
            get_logger(__name__),
            logging.INFO,
            "PIPELINE_STAGE_API_CALL | Calling generate_images",
            ctx=LogContext(job_id=job_id or "unknown", subsystem="pipeline_runner"),
            extra_fields={
                "stage_type": stage_type.value,
                "sampler": payload.get("sampler_name"),
                "steps": payload.get("steps"),
                "job_id": job_id,
            },
        )

        if job_date:
            image_name = f"{stage_type.value}_{prompt_index:02d}_{job_date}"
        else:
            image_name = f"{stage_type.value}_{prompt_index:02d}"

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
                image_name,
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

    def _build_executor_config(self, config: Any) -> dict[str, Any]:
        """Prepare the executor configuration dict from a legacy controller config."""

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
        config: Any,
        executor_config: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        input_image_path: Path | None,
    ) -> dict[str, Any]:
        """Construct a per-stage payload from the plan metadata.

        Uses the canonical build_sdxl_payload() builder and then applies
        runner-specific augmentations (prompt, model, input images).
        """
        # Build last_image_meta for chaining if we have an input image
        last_image_meta: dict[str, Any] | None = None
        if input_image_path:
            encoded = self._pipeline._load_image_base64(input_image_path)
            if encoded:
                last_image_meta = {
                    "images": [encoded],
                    "path": str(input_image_path),
                }

        # Use canonical payload builder for refiner/hires/upscaler consistency
        payload = build_sdxl_payload(stage, last_image_meta)  # type: ignore[arg-type]

        # Apply runner-specific overrides
        payload["prompt"] = prompt
        payload["negative_prompt"] = negative_prompt
        payload["model"] = config.model
        payload["sd_model"] = config.model
        payload["sampler_name"] = config.sampler
        payload.setdefault("scheduler", executor_config.get("txt2img", {}).get("scheduler"))
        payload["steps"] = config.steps
        payload["cfg_scale"] = config.cfg_scale
        payload["width"] = config.width
        payload["height"] = config.height

        if config.pack_name:
            payload["pack_name"] = config.pack_name
        if config.preset_name:
            payload["preset_name"] = config.preset_name

        payload["stage_type"] = stage.stage_type

        # Preserve stage flags from metadata for backward compatibility
        metadata = stage.config.metadata
        if isinstance(metadata, dict):
            metadata = StageMetadata(
                refiner_enabled=bool(metadata.get("refiner_enabled", False)),
                refiner_model_name=metadata.get("refiner_model_name"),
                refiner_switch_at=metadata.get("refiner_switch_at"),
                hires_enabled=bool(metadata.get("hires_enabled", False)),
                hires_upscale_factor=metadata.get("hires_upscale_factor"),
                hires_upscaler_name=metadata.get("hires_upscaler_name"),
                hires_denoise=metadata.get("hires_denoise"),
                hires_steps=metadata.get("hires_steps"),
                stage_flags=metadata.get("stage_flags", {}),
            )
        if isinstance(metadata, StageMetadata):
            for flag, value in metadata.stage_flags.items():
                payload.setdefault(flag, value)

        # Set input image path for logging/tracking
        if input_image_path:
            payload["input_image_path"] = str(input_image_path)

        return payload

    def _emit_learning_record(
        self, config: Any, run_result: PipelineRunResult
    ) -> LearningRecord | None:
        if not self._learning_enabled:
            return None
        if not (self._learning_record_writer or self._learning_record_callback):
            return None
        try:
            metadata: dict[str, Any] = {}
            for candidate in (
                getattr(config, "metadata", None),
                getattr(config, "extra_metadata", None),
            ):
                if isinstance(candidate, dict):
                    metadata.update(candidate)
            pack_name = getattr(config, "pack_name", None) or getattr(
                config, "prompt_pack_name", None
            )
            if pack_name:
                metadata["pack_name"] = pack_name
            preset_name = getattr(config, "preset_name", None)
            if preset_name:
                metadata["preset_name"] = preset_name
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
    """Stable output contract for PipelineRunner.run_njr."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "success": self.success,
            "error": self.error,
            "variants": [dict(variant) for variant in self.variants],
            "learning_records": [asdict(record) for record in self.learning_records],
            "randomizer_mode": self.randomizer_mode,
            "randomizer_plan_size": self.randomizer_plan_size,
            "metadata": dict(self.metadata or {}),
            "stage_plan": self._serialize_stage_plan(),
            "stage_events": [dict(event) for event in self.stage_events],
        }

    def _serialize_stage_plan(self) -> dict[str, Any] | None:
        if not self.stage_plan:
            return None
        return {
            "run_id": self.stage_plan.run_id,
            "stage_types": self.stage_plan.get_stage_types(),
            "one_click_action": self.stage_plan.one_click_action,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], default_run_id: str | None = None
    ) -> PipelineRunResult:
        run_id = str(data.get("run_id") or default_run_id or "")
        learning_records: list[LearningRecord] = []
        for record in data.get("learning_records") or []:
            if isinstance(record, Mapping):
                learning_records.append(LearningRecord(**record))
        stage_events = [dict(event) for event in data.get("stage_events") or []]
        return cls(
            run_id=run_id,
            success=bool(data.get("success", False)),
            error=data.get("error"),
            variants=[dict(variant) for variant in data.get("variants") or []],
            learning_records=learning_records,
            randomizer_mode=str(data.get("randomizer_mode") or ""),
            randomizer_plan_size=int(data.get("randomizer_plan_size") or 0),
            metadata=dict(data.get("metadata") or {}),
            stage_plan=None,
            stage_events=stage_events,
        )


def normalize_run_result(value: Any, default_run_id: str | None = None) -> dict[str, Any]:
    """
    Return a canonical PipelineRunResult dict for any run output.
    Ensures all execution metadata (including run_mode, source) is present in the metadata dict.
    """
    if isinstance(value, PipelineRunResult):
        return value.to_dict()
    if isinstance(value, Mapping):
        try:
            return PipelineRunResult.from_dict(dict(value), default_run_id=default_run_id).to_dict()
        except Exception:
            pass
    fallback = PipelineRunResult(
        run_id=default_run_id or "",
        success=False,
        error=str(value) if value is not None else None,
        variants=[],
        learning_records=[],
    )
    return fallback.to_dict()


def _extract_primary_knobs(config: dict[str, Any]) -> dict[str, Any]:
    txt2img = (config or {}).get("txt2img", {}) or {}
    return {
        "model": txt2img.get("model", ""),
        "sampler": txt2img.get("sampler_name", ""),
        "scheduler": txt2img.get("scheduler", ""),
        "steps": txt2img.get("steps", 0),
        "cfg_scale": txt2img.get("cfg_scale", 0.0),
    }


__all__ = ["PipelineRunner", "PipelineRunResult", "normalize_run_result"]
