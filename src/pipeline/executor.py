"""Pipeline execution module"""

from __future__ import annotations

import base64
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image

from src.api.client import WebUIPayloadValidationError, PROGRESS_STALL_THRESHOLD_SEC
from src.api.types import GenerateError, GenerateErrorCode
from src.api.webui_process_manager import get_global_webui_process_manager
from src.prompting.prompt_optimizer_config import PromptOptimizerConfig
from src.prompting.prompt_optimizer_registry import (
    build_prompt_optimization_record,
    write_prompt_optimization_record,
)
from src.prompting.prompt_optimizer_service import PromptOptimizerService
from src.prompting.prompt_splitter import split_prompt_chunks
from src.prompting.prompt_types import PromptOptimizationPairResult
from src.pipeline.artifact_contract import artifact_manifest_payload
from src.pipeline.animatediff_models import (
    AnimateDiffConfig,
    attach_animatediff_to_payload,
    normalize_animatediff_response,
    resolve_animatediff_motion_module,
)
from src.pipeline.video import VideoCreator, write_video_frames
from src.utils.error_envelope_v2 import serialize_envelope, wrap_exception

from ..api import SDWebUIClient
from ..gui.state import CancellationError, CancelToken
from ..utils import (
    ConfigManager,
    LogContext,
    StructuredLogger,
    build_safe_image_stem,
    load_image_to_base64,
    log_with_ctx,
    merge_global_negative,
    save_image_from_base64,
)
from ..utils.negative_helpers_v2 import merge_global_positive

if TYPE_CHECKING:
    from src.services.diagnostics_service_v2 import DiagnosticsServiceV2


@lru_cache(maxsize=128)
def _cached_image_base64(path_str: str) -> str | None:
    """LRU cache for recently loaded images to cut down disk reads."""
    return load_image_to_base64(Path(path_str))


logger = logging.getLogger(__name__)

_RECOVERY_TIMEOUT_KEYWORDS = ("read timed out", "readtimeout", "timeout", "timed out")


def _capture_webui_tail() -> dict[str, Any] | None:
    manager = get_global_webui_process_manager()
    if manager is None:
        return None
    return manager.get_recent_output_tail()


_MAX_IMAGE_DIMENSION = 4096
_MAX_STAGE_STEPS = 150
_ALLOWED_TEXT_CONTROL_CODES = {9, 10}


def _strip_control_chars(value: str) -> str:
    return "".join(ch for ch in value if ord(ch) >= 32 or ord(ch) in _ALLOWED_TEXT_CONTROL_CODES)


def _raise_payload_error(stage: str, message: str) -> None:
    raise WebUIPayloadValidationError(f"Stage {stage} payload invalid: {message}")


def _sanitize_text_field(payload: dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, str):
        return
    sanitized = _strip_control_chars(value)
    if sanitized != value:
        payload[field] = sanitized


def _ensure_int_range(
    stage: str,
    payload: dict[str, Any],
    field: str,
    *,
    max_value: int,
) -> None:
    value = payload.get(field)
    if value is None:
        return
    if isinstance(value, bool):
        _raise_payload_error(stage, f"{field} must be a positive integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        _raise_payload_error(stage, f"{field} must be numeric")
    if not numeric.is_integer():
        _raise_payload_error(stage, f"{field} must be an integer")
    integer = int(numeric)
    if integer <= 0 or integer > max_value:
        _raise_payload_error(stage, f"{field} must be between 1 and {max_value}")
    payload[field] = integer


def _ensure_cfg_scale(stage: str, payload: dict[str, Any]) -> None:
    value = payload.get("cfg_scale")
    if value is None:
        return
    try:
        cfg_value = float(value)
    except (TypeError, ValueError):
        _raise_payload_error(stage, "cfg_scale must be numeric")
    if not math.isfinite(cfg_value):
        _raise_payload_error(stage, "cfg_scale must be finite")
    payload["cfg_scale"] = cfg_value


def _validate_webui_payload(stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        _raise_payload_error(stage, "payload must be a dictionary")
    sanitized = dict(payload)
    _sanitize_text_field(sanitized, "prompt")
    _sanitize_text_field(sanitized, "negative_prompt")
    _ensure_int_range(stage, sanitized, "width", max_value=_MAX_IMAGE_DIMENSION)
    _ensure_int_range(stage, sanitized, "height", max_value=_MAX_IMAGE_DIMENSION)
    _ensure_int_range(stage, sanitized, "steps", max_value=_MAX_STAGE_STEPS)
    _ensure_cfg_scale(stage, sanitized)
    try:
        json.dumps(sanitized, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise WebUIPayloadValidationError(
            f"Stage {stage} payload contains non-serializable values: {exc}"
        ) from exc
    return sanitized


_DIAGNOSTICS_SERVICE_INSTANCE: DiagnosticsServiceV2 | None = None


def _get_diagnostics_service() -> DiagnosticsServiceV2:
    global _DIAGNOSTICS_SERVICE_INSTANCE
    if _DIAGNOSTICS_SERVICE_INSTANCE is None:
        from src.services.diagnostics_service_v2 import DiagnosticsServiceV2

        _DIAGNOSTICS_SERVICE_INSTANCE = DiagnosticsServiceV2(Path("reports") / "diagnostics")
    return _DIAGNOSTICS_SERVICE_INSTANCE


class PipelineStageError(Exception):
    def __init__(self, error: GenerateError):
        stage = error.stage or "pipeline"
        super().__init__(f"{stage} error: {error.message}")
        self.error = error


class Pipeline:
    """Main pipeline orchestrator for txt2img → img2img → upscale → video"""

    def __init__(self, client: SDWebUIClient, structured_logger: StructuredLogger, status_callback: Callable[[dict[str, Any]], None] | None = None):
        """
        Initialize pipeline.

        Args:
            client: SD WebUI API client
            structured_logger: Structured logger instance
            status_callback: Optional callback for runtime status updates during execution
        """
        self.client = client
        self.logger = structured_logger
        self.config_manager = ConfigManager()  # For global negative prompt handling
        self.progress_controller = None
        self._status_callback = status_callback
        self._current_model: str | None = None
        self._current_vae: str | None = None
        self._current_hypernetwork: str | None = None
        self._current_hn_strength: float | None = None
        self._model_discovery_attempted = False
        self._webui_defaults_applied = False
        self._true_ready_gated = False  # Track if we've already waited for true-readiness
        self._last_img2img_result: dict[str, Any] | None = None
        self._last_upscale_result: dict[str, Any] | None = None
        self._last_adetailer_result: dict[str, Any] | None = None
        self._stage_events: list[dict[str, Any]] = []
        # PR-PIPE-001: Track current job ID for manifest linkage
        self._current_job_id: str | None = None
        self._current_njr_sha256: str | None = None
        # Stage tracking for runtime status
        self._current_stage_chain: list[str] = []
        self._current_stage_index: int = 0
        self._current_stage_start_time: datetime | None = None
        self._current_actual_seed: int | None = None
        # PR-PIPE-004: Progress polling infrastructure
        self._progress_poll_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="progress_poll")
        self._current_generation_progress: float = 0.0
        self._progress_lock = threading.Lock()
        self._run_started_at_monotonic: float | None = None
        self._run_model_switch_count: int = 0
        self._run_vae_switch_count: int = 0

    def _begin_run_metrics(self) -> None:
        """Reset per-run efficiency counters."""
        self._run_started_at_monotonic = time.monotonic()
        self._run_model_switch_count = 0
        self._run_vae_switch_count = 0

    def _record_model_switch(self) -> None:
        self._run_model_switch_count += 1

    def _record_vae_switch(self) -> None:
        self._run_vae_switch_count += 1

    def get_run_efficiency_metrics(self, images_processed: int) -> dict[str, Any]:
        """Return a structured run-efficiency snapshot for logs/UI/history."""
        if self._run_started_at_monotonic is None:
            elapsed_seconds = 0.0
        else:
            elapsed_seconds = max(0.0, time.monotonic() - self._run_started_at_monotonic)
        images_per_minute = 0.0
        if elapsed_seconds > 0 and images_processed > 0:
            images_per_minute = (images_processed / elapsed_seconds) * 60.0
        return {
            "elapsed_seconds": round(elapsed_seconds, 3),
            "images_processed": int(images_processed),
            "images_per_minute": round(images_per_minute, 3),
            "model_switches": int(self._run_model_switch_count),
            "vae_switches": int(self._run_vae_switch_count),
        }

    def _log_run_efficiency_metrics(
        self,
        *,
        run_type: str,
        images_processed: int,
    ) -> None:
        """Log per-run timing and switch counts for throughput diagnostics."""
        metrics = self.get_run_efficiency_metrics(images_processed)
        logger.info(
            "Run efficiency (%s): elapsed=%.2fs, images=%d, img_per_min=%.2f, model_switches=%d, vae_switches=%d",
            run_type,
            metrics["elapsed_seconds"],
            metrics["images_processed"],
            metrics["images_per_minute"],
            metrics["model_switches"],
            metrics["vae_switches"],
        )

    def _run_prompt_optimizer(
        self,
        *,
        positive_prompt: str,
        negative_prompt: str,
        config: dict[str, Any] | None,
        stage_name: str,
    ) -> tuple[PromptOptimizationPairResult, PromptOptimizerConfig]:
        config_payload = dict((config or {}).get("prompt_optimizer") or {})
        try:
            optimizer_config = PromptOptimizerConfig.from_dict(config_payload)
        except Exception as exc:
            logger.warning("Prompt optimizer disabled due to invalid config for %s: %s", stage_name, exc)
            optimizer_config = PromptOptimizerConfig(enabled=False)
        service = PromptOptimizerService(optimizer_config)
        enabled = service.should_optimize_for_pipeline(stage_name)
        positive_prompt = str(positive_prompt or "")
        negative_prompt = str(negative_prompt or "")
        positive_chunks = len(split_prompt_chunks(positive_prompt))
        negative_chunks = len(split_prompt_chunks(negative_prompt))
        if enabled:
            logger.info(
                "PROMPT OPTIMIZER ENABLED | pipeline=%s | positive_chunks=%d | negative_chunks=%d",
                stage_name,
                positive_chunks,
                negative_chunks,
            )
        else:
            logger.info(
                "PROMPT OPTIMIZER DISABLED | pipeline=%s | positive_chunks=%d | negative_chunks=%d",
                stage_name,
                positive_chunks,
                negative_chunks,
            )
        result = service.optimize_prompts(positive_prompt, negative_prompt, pipeline_name=stage_name)
        logger.info(
            "PROMPT OPTIMIZER RESULT | pipeline=%s | positive_changed=%s | negative_changed=%s | positive_len=%d->%d | negative_len=%d->%d",
            stage_name,
            result.positive.changed,
            result.negative.changed,
            len(result.positive.original_prompt),
            len(result.positive.optimized_prompt),
            len(result.negative.original_prompt),
            len(result.negative.optimized_prompt),
        )
        if optimizer_config.warn_on_large_chunk_count and (
            positive_chunks >= optimizer_config.large_chunk_warning_threshold
            or negative_chunks >= optimizer_config.large_chunk_warning_threshold
        ):
            logger.warning(
                "PROMPT OPTIMIZER CHUNK WARNING | pipeline=%s | positive_chunks=%d | negative_chunks=%d | threshold=%d",
                stage_name,
                positive_chunks,
                negative_chunks,
                optimizer_config.large_chunk_warning_threshold,
            )
        if optimizer_config.log_before_after:
            logger.info("ORIGINAL POSITIVE: %s", result.positive.original_prompt)
            logger.info("OPTIMIZED POSITIVE: %s", result.positive.optimized_prompt)
            logger.info("ORIGINAL NEGATIVE: %s", result.negative.original_prompt)
            logger.info("OPTIMIZED NEGATIVE: %s", result.negative.optimized_prompt)
        if optimizer_config.log_bucket_assignments:
            logger.debug("PROMPT OPTIMIZER BUCKETS | pipeline=%s | positive=%s", stage_name, result.positive.buckets)
            logger.debug("PROMPT OPTIMIZER BUCKETS | pipeline=%s | negative=%s", stage_name, result.negative.buckets)
            if result.positive.dropped_duplicates or result.negative.dropped_duplicates:
                logger.debug(
                    "PROMPT OPTIMIZER DROPPED | pipeline=%s | positive=%s | negative=%s",
                    stage_name,
                    result.positive.dropped_duplicates,
                    result.negative.dropped_duplicates,
                )
        return result, optimizer_config

    def _maybe_write_prompt_optimization_sidecar(
        self,
        *,
        manifest_path: Path,
        result: PromptOptimizationPairResult,
        config: PromptOptimizerConfig,
    ) -> None:
        if not (config.log_before_after or config.log_bucket_assignments):
            return
        sidecar = manifest_path.with_name(f"{manifest_path.stem}.prompt_optimization.json")
        try:
            write_prompt_optimization_record(sidecar, result)
        except Exception as exc:
            logger.debug("Failed to write prompt optimization sidecar %s: %s", sidecar, exc)

    def _attach_manifest_artifact(
        self,
        *,
        metadata: dict[str, Any],
        stage: str,
        primary_path: Path | str,
        manifest_path: Path | str | None,
        output_paths: list[str] | None = None,
        thumbnail_path: Path | str | None = None,
        input_image_path: Path | str | None = None,
        artifact_type: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(metadata or {})
        payload["artifact"] = artifact_manifest_payload(
            stage=stage,
            image_or_output_path=primary_path,
            manifest_path=manifest_path,
            output_paths=output_paths,
            thumbnail_path=thumbnail_path,
            input_image_path=input_image_path,
            artifact_type=artifact_type,
        )
        return payload

    def _write_manifest_file(
        self,
        *,
        manifest_path: Path,
        metadata: dict[str, Any],
        prompt_optimizer_result: PromptOptimizationPairResult | None = None,
        prompt_optimizer_config: PromptOptimizerConfig | None = None,
    ) -> None:
        manifest_path.parent.mkdir(exist_ok=True, parents=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        if prompt_optimizer_result is not None and prompt_optimizer_config is not None:
            self._maybe_write_prompt_optimization_sidecar(
                manifest_path=manifest_path,
                result=prompt_optimizer_result,
                config=prompt_optimizer_config,
            )

    def _clean_metadata_payload(self, payload: Any) -> Any:
        """Remove large binary blobs (e.g., base64 images) from metadata payloads."""
        if not isinstance(payload, dict):
            return payload

        excluded_keys = {
            "image",
            "images",
            "init_images",
            "input_image",
            "input_images",
            "mask",
            "image_cfg_scale",
        }
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if key in excluded_keys:
                continue
            cleaned[key] = value
        return cleaned

    def _build_image_metadata_payload(
        self,
        *,
        image_path: Path,
        stage: str,
        run_dir: Path,
        manifest: dict[str, Any],
        image_size: tuple[int, int] | None,
    ) -> dict[str, Any]:
        from src.utils.image_metadata import build_payload_from_manifest

        payload = build_payload_from_manifest(
            image_path=image_path,
            run_dir=run_dir,
            stage=stage,
            manifest=manifest,
            image_size=image_size,
            njr_sha256=self._current_njr_sha256,
        )
        if not payload.get("job_id"):
            payload["job_id"] = getattr(self, "_current_job_id", "") or ""
        return payload

    def _resolve_run_dir(self, output_dir: Path) -> Path:
        stage_dirs = {"txt2img", "img2img", "adetailer", "upscaled", "upscale"}
        if output_dir.name in stage_dirs and output_dir.parent.exists():
            return output_dir.parent
        return output_dir

    def _extract_stage_history_from_input(self, input_image_path: Path) -> list[dict[str, Any]]:
        """Extract stage history from input image metadata.
        
        Reads embedded metadata from the input image and extracts the stage_history
        array plus the current stage's manifest, building a complete history chain.
        Each stage includes full config, model, VAE, seeds for complete reproducibility.
        
        Args:
            input_image_path: Path to input image
            
        Returns:
            List of stage manifests in chronological order
        """
        try:
            from src.utils.image_metadata import extract_embedded_metadata
            
            result = extract_embedded_metadata(input_image_path)
            if result.status == "ok" and result.payload:
                # Get existing stage history
                stage_history = result.payload.get("stage_history", [])
                
                # Build complete stage manifest with all reproducibility info
                stage_manifest = result.payload.get("stage_manifest", {})
                if stage_manifest:
                    current_manifest = {
                        "stage": stage_manifest.get("stage", "unknown"),
                        "timestamp": stage_manifest.get("timestamp", ""),
                        "name": stage_manifest.get("name", ""),
                        # Include full config for reproducibility
                        "config": stage_manifest.get("config", {}),
                        "model": stage_manifest.get("model", "Unknown"),
                        "vae": stage_manifest.get("vae", "Automatic"),
                        "seeds": stage_manifest.get("seeds", {}),
                        "prompt": stage_manifest.get("prompt", ""),
                        "negative_prompt": stage_manifest.get("negative_prompt", ""),
                    }
                    # Create new history with current manifest appended
                    return stage_history + [current_manifest]
                return stage_history
        except Exception as exc:
            logger.debug(f"Could not extract stage history from {input_image_path.name}: {exc}")
        return []

    def _build_image_metadata_builder(
        self,
        *,
        image_path: Path,
        stage: str,
        run_dir: Path,
        manifest: dict[str, Any],
    ):
        from datetime import timezone
        from src.utils.image_metadata import build_contract_kv

        def _builder(image: Image.Image) -> dict[str, str] | None:
            try:
                payload = self._build_image_metadata_payload(
                    image_path=image_path,
                    stage=stage,
                    run_dir=run_dir,
                    manifest=manifest,
                    image_size=image.size if image else None,
                )
                created_utc = datetime.now(timezone.utc).isoformat()
                return build_contract_kv(
                    payload,
                    job_id=str(manifest.get("job_id") or getattr(self, "_current_job_id", "") or ""),
                    run_id=run_dir.name,
                    stage=stage,
                    created_utc=created_utc,
                    njr_sha256=self._current_njr_sha256,
                )
            except Exception:
                return None

        return _builder

    def _ensure_stage_prefix(self, image_name: str, stage: str) -> str:
        prefix = f"{stage}_"
        if image_name.startswith(prefix):
            return image_name
        if stage == "upscale" and image_name.startswith("upscaled_"):
            return image_name
        return f"{prefix}{image_name}"

    def _default_stage_image_name(self, *, stage: str, input_image_path: Path | None = None) -> str:
        if input_image_path is not None:
            stem = re.sub(r"\s+", "_", Path(input_image_path).stem.strip()) or stage
            stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem)
            return self._ensure_stage_prefix(stem, stage)
        return stage

    def _coerce_saved_path(self, actual_path: Path | bool | None, *, fallback: Path) -> Path | None:
        if not actual_path:
            return None
        if isinstance(actual_path, Path):
            return actual_path
        return fallback

    def _merge_stage_negative(
        self, base_negative: str, apply_global: bool
    ) -> tuple[str, str, bool, str]:
        """Compute original/final negative prompts plus metadata."""
        global_terms = (
            self.config_manager.get_global_negative_prompt().strip() if apply_global else ""
        )
        return merge_global_negative(base_negative, global_terms)

    def _merge_stage_positive(
        self, base_positive: str, apply_global: bool
    ) -> tuple[str, str, bool, str]:
        """Compute original/final positive prompts plus metadata."""
        global_terms = (
            self.config_manager.get_global_positive_prompt().strip() if apply_global else ""
        )
        return merge_global_positive(base_positive, global_terms)

    def _resolve_negative_prompt(
        self,
        primary_meta: dict[str, Any] | None,
        fallback_meta: dict[str, Any] | None = None,
        default_negative: str | None = None,
    ) -> str:
        """
        Resolve the most relevant negative prompt from stage metadata or config.

        Prefers the most recent stage metadata, then falls back to a prior stage
        (typically txt2img) before finally using a provided default string.
        """
        for candidate in (primary_meta, fallback_meta):
            if not isinstance(candidate, dict):
                continue
            neg = candidate.get("final_negative_prompt") or candidate.get("negative_prompt")
            if neg:
                return str(neg)
            cfg = candidate.get("config")
            if isinstance(cfg, dict):
                neg = cfg.get("negative_prompt")
                if neg:
                    return str(neg)
        if default_negative:
            return str(default_negative)
        return ""

    def set_progress_controller(self, controller: Any | None) -> None:
        """Attach a progress reporting controller."""

        self.progress_controller = controller

    def _emit_status_update(self, status_data: dict[str, Any]) -> None:
        """Emit runtime status update if callback is configured.
        
        Args:
            status_data: Dictionary containing status fields like:
                - job_id: str
                - current_stage: str (e.g., "txt2img", "img2img")
                - stage_detail: str | None
                - stage_index: int (0-based current stage)
                - total_stages: int
                - progress: float (0.0 to 1.0)
                - actual_seed: int | None
                - current_step: int
                - total_steps: int
        """
        if self._status_callback:
            try:
                self._status_callback(status_data)
            except Exception as exc:
                logger.warning(f"Status callback error: {exc}")

    def _emit_stage_start(self, stage_name: str, total_steps: int = 0) -> None:
        """Emit status update at the start of a pipeline stage.
        
        Args:
            stage_name: Name of the stage starting (e.g., "txt2img", "img2img")
            total_steps: Total steps for this stage (if known)
        """
        if not self._status_callback or not self._current_job_id:
            return
        
        self._current_stage_start_time = datetime.utcnow()
        
        status_data = {
            "job_id": self._current_job_id,
            "current_stage": stage_name,
            "stage_detail": None,
            "stage_index": self._current_stage_index,
            "total_stages": len(self._current_stage_chain) if self._current_stage_chain else 1,
            "progress": 0.0,
            "eta_seconds": None,
            "started_at": self._current_stage_start_time,
            "actual_seed": self._current_actual_seed,
            "current_step": 0,
            "total_steps": total_steps,
        }
        
        self._emit_status_update(status_data)

    def _emit_stage_detail_update(
        self,
        *,
        progress: float,
        stage_detail: str | None = None,
        eta_seconds: float | None = None,
        current_step: int = 0,
        total_steps: int = 0,
        stage_name: str | None = None,
    ) -> None:
        """Emit a runtime update for a finer-grained phase within the current stage."""
        if not self._status_callback or not self._current_job_id:
            return

        resolved_stage = stage_name
        if not resolved_stage:
            if self._current_stage_chain and 0 <= self._current_stage_index < len(self._current_stage_chain):
                resolved_stage = self._current_stage_chain[self._current_stage_index]
            else:
                resolved_stage = "pipeline"

        status_data = {
            "job_id": self._current_job_id,
            "current_stage": resolved_stage,
            "stage_detail": stage_detail,
            "stage_index": self._current_stage_index,
            "total_stages": len(self._current_stage_chain) if self._current_stage_chain else 1,
            "progress": max(0.0, min(1.0, float(progress))),
            "eta_seconds": eta_seconds,
            "started_at": self._current_stage_start_time or datetime.utcnow(),
            "actual_seed": self._current_actual_seed,
            "current_step": int(current_step),
            "total_steps": int(total_steps),
        }
        self._emit_status_update(status_data)

    def _apply_webui_defaults_once(self) -> None:
        """
        Apply StableNew-required WebUI defaults (metadata, upscale safety) once per run.
        """

        if self._webui_defaults_applied:
            return

        try:
            if hasattr(self.client, "apply_metadata_defaults"):
                self.client.apply_metadata_defaults()

            if hasattr(self.client, "apply_upscale_performance_defaults"):
                self.client.apply_upscale_performance_defaults()

            self._webui_defaults_applied = True
        except Exception as exc:
            logger.warning("Could not apply WebUI defaults: %s", exc)

    def _normalize_model_name(self, raw: str | None) -> str | None:
        """Normalize model name for comparison by removing extensions and hashes."""
        if not raw:
            return None
        cleaned = str(raw).strip()
        if not cleaned:
            return None
        
        # Remove hash in brackets like [dd08fa32f9] first
        import re
        cleaned = re.sub(r'\s*\[[a-f0-9]+\]$', '', cleaned, flags=re.IGNORECASE)
        # Then remove file extension (.safetensors, .ckpt, .pt, etc.)
        cleaned = re.sub(r'\.(safetensors|ckpt|pt|pth)$', '', cleaned, flags=re.IGNORECASE)
        return cleaned.lower()

    def _normalize_vae_name(self, raw: str | None) -> str:
        if raw is None:
            return "automatic"
        cleaned = str(raw).strip().lower()
        if cleaned in {"", "automatic", "none"}:
            return "automatic"
        return cleaned

    def _discover_current_model_if_needed(self) -> None:
        if self._model_discovery_attempted or self._current_model is not None:
            return
        self._model_discovery_attempted = True
        try:
            model = self.client.get_current_model()
            if model:
                self._current_model = model
        except Exception:
            logger.debug("Failed to detect WebUI current model for no-op switching", exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers for throughput improvements
    # ------------------------------------------------------------------

    def _ensure_model_and_vae(self, model_name: str | None, vae_name: str | None) -> None:
        """Set model and/or VAE. Model and VAE switches are independent operations."""
        model_switched = False
        # Handle model switching (if requested)
        desired_normalized = self._normalize_model_name(model_name)
        if desired_normalized:
            self._discover_current_model_if_needed()
            current_normalized = self._normalize_model_name(self._current_model)
            if desired_normalized == current_normalized:
                # Model already loaded - no switch needed, but continue to VAE logic
                logger.debug(f"Model already loaded: {model_name}")
            elif not self.client.options_write_enabled:
                # Only warn if models are actually different (avoids false warnings when normalized names match)
                if current_normalized != desired_normalized:
                    logger.warning(
                        "Model switch to %s requested but options writes are disabled (SafeMode); keeping %s",
                        model_name,
                        self._current_model or "current WebUI model",
                    )
            else:
                # Model needs switching
                try:
                    logger.info(f"Switching to model: {model_name}")
                    self.client.set_model(model_name)
                    self._current_model = model_name
                    model_switched = True
                    self._record_model_switch()
                except Exception:
                    self._current_model = None
                    raise

        # Handle VAE switching (independent of model - always execute if vae_name provided)
        try:
            if vae_name:
                desired_vae = self._normalize_vae_name(vae_name)
                current_vae = self._normalize_vae_name(self._current_vae)
                if desired_vae != current_vae:
                    logger.info(f"Switching to VAE: {vae_name}")
                    self.client.set_vae(vae_name)
                    self._current_vae = vae_name
                    self._record_vae_switch()
            elif model_switched:
                # If a new model is loaded and no explicit VAE is requested, clear any
                # stale VAE override so WebUI can use the model's preferred default.
                logger.info("Model switched without explicit VAE; resetting VAE to Automatic")
                self.client.set_vae("Automatic")
                self._current_vae = "Automatic"
                self._record_vae_switch()
        except Exception:
            self._current_vae = None
            raise

    def _ensure_hypernetwork(self, name: str | None, strength: float | None) -> None:
        """
        Ensure the requested hypernetwork (and optional strength) is active.

        Args:
            name: Hypernetwork name or None/"None" to disable.
            strength: Optional strength override.
        """

        normalized = None
        if isinstance(name, str) and name.strip():
            candidate = name.strip()
            if candidate.lower() != "none":
                normalized = candidate

        target_strength = float(strength) if strength is not None else None

        if normalized == self._current_hypernetwork and (
            (target_strength is None and self._current_hn_strength is None)
            or (
                target_strength is not None
                and self._current_hn_strength is not None
                and abs(self._current_hn_strength - target_strength) < 1e-3
            )
        ):
            return

        try:
            self.client.set_hypernetwork(normalized, target_strength)
            self._current_hypernetwork = normalized
            self._current_hn_strength = target_strength
        except Exception:
            # Reset cached state so future attempts are not skipped
            self._current_hypernetwork = None
            self._current_hn_strength = None
            raise

    def _load_image_base64(self, path: Path) -> str | None:
        """Load images through the shared cache to avoid redundant disk IO."""
        return _cached_image_base64(str(path))

    def _ensure_not_cancelled(self, cancel_token, context: str) -> None:
        """Raise CancellationError if a cancel token has been triggered."""
        if (
            cancel_token
            and getattr(cancel_token, "is_cancelled", None)
            and cancel_token.is_cancelled()
        ):
            logger.info("Cancellation requested, aborting %s", context)
            raise CancellationError(f"Cancelled during {context}")

    def reset_stage_events(self) -> None:
        """Clear recorded stage events for a new run."""

        self._stage_events = []

    def get_stage_events(self) -> list[dict[str, Any]]:
        """Return recorded stage events."""

        return list(self._stage_events)

    def _record_stage_event(
        self,
        stage: str,
        phase: str,
        image_index: int,
        total_images: int,
        cancelled: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record a stage-level lifecycle event."""

        payload: dict[str, Any] = {
            "stage": stage,
            "phase": phase,
            "image_index": image_index,
            "total_images": total_images,
            "cancelled": bool(cancelled),
        }
        if extra:
            payload.update(extra)
        self._stage_events.append(payload)

    def _classify_recovery_failure(
        self,
        *,
        stage: str,
        error: GenerateError | None = None,
        diagnostics: dict[str, Any] | None = None,
        reason_hint: str | None = None,
    ) -> str | None:
        if reason_hint:
            return reason_hint
        if error and error.details and error.details.get("recovery_classification"):
            return str(error.details.get("recovery_classification"))
        details = diagnostics or {}
        summary = details.get("request_summary") or {}
        error_message = str(details.get("error_message") or (error.message if error else "")).lower()
        try:
            status_code = int(summary.get("status"))
        except (TypeError, ValueError):
            status_code = None
        if details.get("crash_suspected"):
            return "request_connection_failure"
        if details.get("webui_unavailable"):
            if any(keyword in error_message for keyword in _RECOVERY_TIMEOUT_KEYWORDS):
                return "request_timeout_escalated"
            return "request_connection_failure"
        if status_code == 500:
            return "request_http_500"
        if any(keyword in error_message for keyword in _RECOVERY_TIMEOUT_KEYWORDS):
            return "request_timeout_escalated"
        return None

    def _should_attempt_stage_recovery(
        self,
        *,
        stage: str,
        error: GenerateError | None = None,
        diagnostics: dict[str, Any] | None = None,
        reason_hint: str | None = None,
    ) -> tuple[bool, str | None]:
        classification = self._classify_recovery_failure(
            stage=stage,
            error=error,
            diagnostics=diagnostics,
            reason_hint=reason_hint,
        )
        return classification in {
            "true_ready_timeout",
            "pre_stage_health_failed",
            "request_connection_failure",
            "request_http_500",
            "request_timeout_escalated",
        }, classification

    def _attempt_webui_recovery(
        self,
        *,
        stage: str,
        reason: str,
        max_attempts: int = 2,
        base_delay: float = 1.0,
        max_delay: float = 4.0,
    ) -> bool:
        manager = get_global_webui_process_manager()
        if manager is None:
            logger.warning(
                "Executor recovery requested for %s but no WebUI process manager is available",
                reason,
            )
            return False
        logger.warning(
            "Executor attempting WebUI recovery for stage=%s reason=%s",
            stage,
            reason,
        )
        try:
            recovered = manager.restart_webui(
                wait_ready=True,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
            )
        except Exception as exc:
            logger.error(
                "Executor WebUI recovery failed for stage=%s reason=%s: %s",
                stage,
                reason,
                exc,
            )
            return False
        if recovered:
            self._true_ready_gated = False
        return bool(recovered)

    def _ensure_webui_true_ready(self) -> None:
        """
        Defensive gate: ensure WebUI is truly ready (API + boot marker) before any generation.

        Called once per pipeline run, before the first generation call.
        Raises PipelineStageError if WebUI doesn't become truly ready within timeout.
        """
        if self._true_ready_gated:
            # Already gated in this pipeline run
            return

        from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout

        attempted_recovery = False
        while True:
            try:
                # Fast-path for normal runtime operation: if the API is already live,
                # options are readable, and the backend is idle, generation can begin
                # without re-checking a historical stdout boot marker.
                if self._is_webui_generation_ready():
                    self._true_ready_gated = True
                    logger.info("Pipeline generation gate: WebUI live API readiness confirmed")
                    return

                manager = get_global_webui_process_manager()
                helper = WebUIAPI(client=self.client)

                get_stdout_tail = None
                if manager and hasattr(manager, "get_stdout_tail_text"):
                    get_stdout_tail = manager.get_stdout_tail_text

                helper.wait_until_true_ready(
                    timeout_s=120.0,
                    poll_interval_s=2.0,
                    get_stdout_tail=get_stdout_tail,
                )
                self._true_ready_gated = True
                logger.info("Pipeline generation gate: WebUI TRUE-READY confirmed")
                return
            except WebUIReadinessTimeout as exc:
                if not attempted_recovery and self._attempt_webui_recovery(
                    stage="pre-generation-gate",
                    reason="true_ready_timeout",
                ):
                    attempted_recovery = True
                    continue
                error = GenerateError(
                    code=GenerateErrorCode.PAYLOAD_VALIDATION,
                    message=f"WebUI not truly ready within timeout: {exc.checks_status}",
                    stage="pre-generation-gate",
                    details={
                        "total_waited_s": exc.total_waited,
                        "checks": exc.checks_status,
                        "stdout_tail": exc.stdout_tail[:1000],
                        "recovery_classification": "true_ready_timeout",
                        "recovery_attempted": attempted_recovery,
                        "recovery_succeeded": False,
                        "recovery_attempt_count": 1 if attempted_recovery else 0,
                    },
                )
                logger.error(
                    "Pipeline generation gate failed: WebUI not truly ready. Checks: %s",
                    exc.checks_status,
                )
                raise PipelineStageError(error) from exc
            except PipelineStageError:
                raise
            except Exception as exc:
                logger.error("Unexpected error in true-readiness gate: %s", exc)
                error = GenerateError(
                    code=GenerateErrorCode.UNKNOWN,
                    message=f"True-readiness gate check failed: {exc}",
                    stage="pre-generation-gate",
                    details={
                        "recovery_attempted": attempted_recovery,
                        "recovery_succeeded": False,
                        "recovery_attempt_count": 1 if attempted_recovery else 0,
                    },
                )
                raise PipelineStageError(error) from exc

    def _is_webui_generation_ready(self) -> bool:
        """Return True when the WebUI API is already live and idle for generation."""
        try:
            if not self.client.check_api_ready(max_retries=1, retry_delay=0.1):
                return False
        except Exception:
            return False

        session = getattr(self.client, "_session", None)
        base_url = getattr(self.client, "base_url", "").rstrip("/")
        if session is None or not base_url:
            return False

        try:
            options_response = session.get(f"{base_url}/sdapi/v1/options", timeout=5.0)
            if options_response.status_code != 200:
                return False
        except Exception:
            return False

        try:
            progress_response = session.get(f"{base_url}/sdapi/v1/progress", timeout=5.0)
            if progress_response.status_code != 200:
                return False
            payload = progress_response.json()
            state = payload.get("state") or {}
            progress = float(payload.get("progress", 0.0) or 0.0)
            current_job = str(state.get("job") or "").strip()
            return progress == 0.0 and not current_job
        except Exception:
            return False

    def _check_webui_health_before_stage(self, stage: str) -> None:
        """
        PR-HARDEN-003: Lightweight per-stage health check.

        Unlike _ensure_webui_true_ready() which runs once per pipeline,
        this runs before EACH stage to detect mid-pipeline WebUI failures
        (e.g., VRAM exhaustion, crash between stages) early rather than
        waiting for a full generation timeout.

        Args:
            stage: Current stage name for error reporting

        Raises:
            PipelineStageError: If WebUI is not responding
        """
        try:
            # Quick 5s check - just verify WebUI is responding
            if not self.client.check_connection(timeout=5.0):
                recovered = self._attempt_webui_recovery(
                    stage=stage,
                    reason="pre_stage_health_failed",
                )
                if recovered:
                    self._ensure_webui_true_ready()
                    if self.client.check_connection(timeout=5.0):
                        logger.info(
                            "Recovered WebUI health before %s stage; continuing execution",
                            stage,
                        )
                        return
                error = GenerateError(
                    code=GenerateErrorCode.CONNECTION,
                    message=f"WebUI health check failed before {stage} stage",
                    stage=stage,
                    details={
                        "check_type": "pre-stage-health",
                        "timeout": 5.0,
                        "recovery_classification": "pre_stage_health_failed",
                        "recovery_attempted": True,
                        "recovery_succeeded": False,
                        "recovery_attempt_count": 1,
                    },
                )
                logger.error(
                    "PR-HARDEN-003: Pre-stage health check failed for %s - WebUI not responding",
                    stage,
                )
                raise PipelineStageError(error)
            logger.debug("PR-HARDEN-003: Pre-stage health check passed for %s", stage)
        except PipelineStageError:
            raise
        except Exception as exc:
            # Don't fail the pipeline for unexpected check errors - log and continue
            logger.warning(
                "PR-HARDEN-003: Pre-stage health check error for %s (continuing): %s",
                stage,
                exc,
            )

    def _extract_generation_info(self, response: dict[str, Any]) -> dict[str, Any]:
        """
        Extract generation metadata from WebUI response.
        
        Args:
            response: Raw WebUI API response with 'info' field
            
        Returns:
            Dict with extracted seed, subseed, and other useful fields.
            Returns empty dict if extraction fails.
        """
        info = response.get("info")
        if info is None:
            return {}
        
        # WebUI returns info as JSON string
        if isinstance(info, str):
            try:
                info = json.loads(info)
            except json.JSONDecodeError:
                logger.warning("Failed to parse WebUI info as JSON")
                return {}
        
        if not isinstance(info, dict):
            return {}
        
        return {
            "seed": info.get("seed"),
            "subseed": info.get("subseed"),
            "all_seeds": info.get("all_seeds"),
            "all_subseeds": info.get("all_subseeds"),
        }

    def _build_seed_metadata(self, config: dict[str, Any], gen_info: dict[str, Any]) -> dict[str, Any]:
        """
        Build comprehensive seed tracking structure for manifests (D-MANIFEST-001).
        
        Creates nested seeds object with both user input (original) and final values used by WebUI.
        This enables full reproducibility by tracking what the user requested vs what was actually used.
        
        Args:
            config: Pipeline config with user's seed/subseed input
            gen_info: Extracted generation info from WebUI response
            
        Returns:
            Dict with nested seed structure containing original and final values
        """
        original_seed = config.get("seed", -1)
        original_subseed = config.get("subseed", -1)
        original_subseed_strength = config.get("subseed_strength", 0.0)
        
        final_seed = gen_info.get("seed", -1)
        final_subseed = gen_info.get("subseed", -1)
        
        return {
            "original_seed": original_seed,
            "final_seed": final_seed,
            "original_subseed": original_subseed,
            "final_subseed": final_subseed,
            "subseed_strength": original_subseed_strength,
        }

    def _generate_images(self, stage: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Call the shared generate_images API for the requested stage."""
        return self._generate_images_with_recovery(stage, payload, recovery_attempted=False)

    def _generate_images_with_recovery(
        self,
        stage: str,
        payload: dict[str, Any],
        *,
        recovery_attempted: bool,
    ) -> dict[str, Any] | None:
        """Call the shared generate_images API for the requested stage with bounded recovery."""

        # Defensive gate: ensure WebUI is truly ready before first generation call
        self._ensure_webui_true_ready()

        # PR-HARDEN-003: Lightweight per-stage health check
        self._check_webui_health_before_stage(stage)

        try:
            payload = _validate_webui_payload(stage, payload)
        except WebUIPayloadValidationError as exc:
            validation_error = GenerateError(
                code=GenerateErrorCode.PAYLOAD_VALIDATION,
                message=str(exc),
                stage=stage,
                details={"stage": stage, "error": str(exc)},
            )
            raise PipelineStageError(validation_error) from exc
        
        # Log sanitized payload for debugging HTTP 500 errors
        logger.info(
            "Sending %s request to WebUI | payload keys: %s | prompt length: %d | negative length: %d | size: %dx%d | steps: %d | cfg: %.1f",
            stage,
            list(payload.keys()),
            len(payload.get("prompt", "")),
            len(payload.get("negative_prompt", "")),
            payload.get("width", 0),
            payload.get("height", 0),
            payload.get("steps", 0),
            payload.get("cfg_scale", 0.0),
        )
        
        outcome = self.client.generate_images(stage=stage, payload=payload)
        if not outcome.ok or outcome.result is None:
            error = outcome.error or GenerateError(
                code=GenerateErrorCode.UNKNOWN,
                message="Generation failed without details",
                stage=stage,
            )
            diag_details = (error.details or {}).get("diagnostics")
            should_recover, recovery_reason = self._should_attempt_stage_recovery(
                stage=stage,
                error=error,
                diagnostics=diag_details if isinstance(diag_details, dict) else None,
            )
            if should_recover and not recovery_attempted:
                recovered = self._attempt_webui_recovery(
                    stage=stage,
                    reason=recovery_reason or "request_connection_failure",
                )
                if recovered:
                    logger.warning(
                        "Executor recovered WebUI for stage=%s reason=%s; retrying request once",
                        stage,
                        recovery_reason,
                    )
                    return self._generate_images_with_recovery(
                        stage,
                        payload,
                        recovery_attempted=True,
                    )
            logger.error(
                "generate_images failed for %s (%s): %s",
                stage,
                error.code,
                error.message,
            )
            exc = PipelineStageError(error)
            request_summary = diag_details.get("request_summary") if diag_details else None
            envelope_context: dict[str, Any] = {
                "error_code": error.code.value,
                "recovery_attempted": recovery_attempted or should_recover,
                "recovery_reason": recovery_reason,
                "recovery_succeeded": False,
                "recovery_attempt_count": 1 if (recovery_attempted or should_recover) else 0,
            }
            if diag_details:
                envelope_context["diagnostics"] = diag_details
                if request_summary:
                    envelope_context.update(
                        {
                            "webui_endpoint": request_summary.get("endpoint"),
                            "webui_stage": request_summary.get("stage"),
                            "webui_method": request_summary.get("method"),
                            "webui_status": request_summary.get("status"),
                            "webui_session_id": request_summary.get("session_id"),
                        }
                    )
                    response_snippet = request_summary.get("response_snippet")
                    if response_snippet:
                        envelope_context["webui_response_snippet"] = response_snippet
                envelope_context["webui_unavailable"] = diag_details.get("webui_unavailable")
            tail_data = _capture_webui_tail()
            if tail_data:
                envelope_context.update(
                    {
                        "webui_stdout_tail": tail_data.get("stdout_tail"),
                        "webui_stderr_tail": tail_data.get("stderr_tail"),
                        "webui_pid": tail_data.get("pid"),
                        "webui_running": tail_data.get("running"),
                    }
                )
            if diag_details and diag_details.get("crash_suspected"):
                extra_context: dict[str, Any] = {"diagnostics": diag_details}
                if request_summary:
                    extra_context["request_summary"] = request_summary
                try:
                    _get_diagnostics_service().build_async(
                        reason="webui_crash_suspected",
                        extra_context=extra_context,
                        webui_tail=tail_data,
                    )
                    logger.info("Triggered WebUI crash diagnostics bundle")
                except Exception:
                    logger.debug("Failed to schedule WebUI diagnostics bundle", exc_info=True)
            envelope = wrap_exception(
                exc,
                subsystem="executor",
                stage=stage,
                context=envelope_context,
            )
            log_with_ctx(
                logger,
                logging.ERROR,
                f"generate_images failed for {stage} ({error.code}): {error.message}",
                ctx=LogContext(subsystem="executor"),
                extra_fields={"error_envelope": serialize_envelope(envelope)},
            )
            raise exc
        # Convert GenerateResult to dict for compatibility with existing code
        result = outcome.result
        return {
            "images": result.images,
            "info": result.info,
            "stage": result.stage,
            "timings": result.timings,
        }

    def _poll_progress_loop(
        self,
        stop_event: threading.Event,
        poll_interval: float,
        progress_callback: Any | None,
        stage_label: str,
        stall_detected_event: threading.Event | None = None,
    ) -> None:
        """
        Background thread that polls WebUI for progress.
        
        PR-HARDEN-004: Enhanced with stall detection - if no progress update
        for PROGRESS_STALL_THRESHOLD_SEC, sets stall_detected_event.
        """
        highest_progress = 0.0
        last_progress_time = time.monotonic()
        
        while not stop_event.is_set():
            try:
                info = self.client.get_progress(skip_current_image=True)
                
                if info is not None:
                    if info.progress > highest_progress:
                        highest_progress = info.progress
                        last_progress_time = time.monotonic()
                        
                        with self._progress_lock:
                            self._current_generation_progress = highest_progress
                        
                        # Extract actual seed if available
                        if hasattr(info, 'seed') and info.seed is not None:
                            self._current_actual_seed = info.seed
                        
                        # Emit runtime status update
                        if self._status_callback and self._current_job_id:
                            elapsed = time.monotonic() - (self._current_stage_start_time.timestamp() if self._current_stage_start_time else time.monotonic())
                            eta_seconds = info.eta_relative if (hasattr(info, 'eta_relative') and info.eta_relative > 0) else None
                            
                            # If no ETA from WebUI, estimate from progress
                            if eta_seconds is None and highest_progress > 0.01:
                                total_estimated = elapsed / highest_progress
                                eta_seconds = max(total_estimated - elapsed, 0.0)
                            
                            status_data = {
                                "job_id": self._current_job_id,
                                "current_stage": stage_label,
                                "stage_detail": None,
                                "stage_index": self._current_stage_index,
                                "total_stages": len(self._current_stage_chain) if self._current_stage_chain else 1,
                                "progress": highest_progress,
                                "eta_seconds": eta_seconds,
                                "started_at": self._current_stage_start_time,
                                "actual_seed": self._current_actual_seed,
                                "current_step": getattr(info, 'current_step', 0),
                                "total_steps": getattr(info, 'total_steps', 0),
                            }
                            self._emit_status_update(status_data)
                        
                        if progress_callback:
                            # Convert 0-1 to percentage
                            percent = highest_progress * 100.0
                            eta = info.eta_relative if (hasattr(info, 'eta_relative') and info.eta_relative > 0) else None
                            # Pass step info if available
                            current_step = getattr(info, 'current_step', 0)
                            total_steps = getattr(info, 'total_steps', 0)
                            progress_callback(percent, eta, current_step, total_steps)
                    
                    # PR-HARDEN-004: Check for stall (no progress for too long)
                    elapsed_since_progress = time.monotonic() - last_progress_time
                    if (
                        elapsed_since_progress > PROGRESS_STALL_THRESHOLD_SEC
                        and highest_progress > 0
                        and highest_progress < 0.99
                    ):
                        logger.warning(
                            "PR-HARDEN-004: Generation stall detected for %s - no progress for %.1fs (stuck at %.1f%%)",
                            stage_label,
                            elapsed_since_progress,
                            highest_progress * 100,
                        )
                        if stall_detected_event:
                            stall_detected_event.set()
                        
            except Exception:
                pass  # Ignore polling errors
            
            # Wait for next poll or stop signal
            stop_event.wait(poll_interval)
    
    def _generate_images_with_progress(
        self,
        stage: str,
        payload: dict[str, Any],
        *,
        poll_interval: float = 0.5,
        progress_callback: Any | None = None,
        stage_label: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Call generation endpoint with concurrent progress polling.
        
        PR-HARDEN-004: Always starts progress polling for stall detection,
        even when no progress_callback is provided.
        """
        
        if stage_label is None:
            stage_label = stage
        
        stop_event = threading.Event()
        stall_detected_event = threading.Event()
        poll_future: Future | None = None
        
        try:
            # PR-HARDEN-004: ALWAYS start polling for stall detection
            poll_future = self._progress_poll_executor.submit(
                self._poll_progress_loop,
                stop_event,
                poll_interval,
                progress_callback,  # May be None - that's fine
                stage_label,
                stall_detected_event,
            )
            
            # Make the actual generation request (blocking)
            response = self._generate_images(stage, payload)
            
            # Check if stall was detected during generation
            if stall_detected_event.is_set():
                logger.warning(
                    "PR-HARDEN-004: Generation for %s completed but stall was detected during execution",
                    stage_label,
                )
            
            return response
            
        finally:
            # Stop polling
            stop_event.set()
            if poll_future:
                try:
                    poll_future.result(timeout=1.0)
                except Exception:
                    pass

    def _log_pipeline_cancellation(self, phase: str, exc: Exception) -> None:
        """Emit a consistent INFO-level log for pipeline cancellations."""

        logger.info("⚠️ Pipeline cancelled during %s; aborting remaining stages. (%s)", phase, exc)

    def run_upscale(
        self,
        input_image_path: Path,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Batch-friendly wrapper for upscaling with cancellation handling.
        """

        try:
            return self._run_upscale_impl(
                input_image_path, config, run_dir, cancel_token=cancel_token
            )
        except CancellationError as exc:
            if isinstance(cancel_token, CancelToken):
                self._log_pipeline_cancellation("upscale", exc)
                return getattr(self, "_last_upscale_result", None)
            raise

    def _run_upscale_impl(
        self,
        input_image_path: Path,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Batch-friendly wrapper for upscaling an image, used in pipeline orchestration.

        Args:
            input_image_path: Path to input image
            config: Upscale configuration
            run_dir: Run directory for this pipeline run
            cancel_token: Optional cancellation token

        Returns:
            Metadata for upscaled image or None if failed/cancelled
        """
        self._last_upscale_result: dict[str, Any] | None = None

        upscale_dir = run_dir / "upscaled"
        upscale_dir.mkdir(parents=True, exist_ok=True)
        image_name = Path(input_image_path).stem

        # Early cancel
        self._ensure_not_cancelled(cancel_token, "upscale start")

        # Emit status update for stage start
        self._emit_stage_start("upscale", total_steps=0)

        result = self.run_upscale_stage(
            input_image_path,
            config,
            upscale_dir,
            image_name,
        )

        # Post cancel
        self._ensure_not_cancelled(cancel_token, "post-upscale")

        if result:
            self._last_upscale_result = result
        return result

    def _normalize_config_for_pipeline(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize config for consistent WebUI behavior.

        - Optionally disable txt2img hires-fix when downstream stages (img2img/upscale) are enabled,
          unless explicitly allowed by config["pipeline"]["allow_hr_with_stages"].
        - Normalize scheduler casing to match WebUI expectations (e.g., "karras" -> "Karras").
        """
        cfg = deepcopy(config or {})

        def norm_sched(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            v = value.strip()
            mapping = {
                "normal": "Normal",
                "karras": "Karras",
                "exponential": "Exponential",
                "polyexponential": "Polyexponential",
                "sgm_uniform": "SGM Uniform",
                "simple": "Simple",
                "ddim_uniform": "DDIM Uniform",
                "beta": "Beta",
                "linear": "Linear",
                "cosine": "Cosine",
            }
            return mapping.get(v.lower(), v)

        # Normalize schedulers across sections
        for section in ("txt2img", "img2img", "upscale"):
            sec = cfg.get(section)
            if isinstance(sec, dict) and "scheduler" in sec:
                try:
                    sec["scheduler"] = norm_sched(sec.get("scheduler"))
                except Exception:
                    pass

        # Optionally disable hires fix when running downstream stages
        try:
            pipeline = cfg.get("pipeline", {})
            # Check if img2img or upscale are enabled (no defaults - None = False)
            img2img_val = pipeline.get("img2img_enabled")
            img2img_enabled = bool(img2img_val) if img2img_val is not None else False
            upscale_val = pipeline.get("upscale_enabled")
            upscale_enabled = bool(upscale_val) if upscale_val is not None else False
            
            disable_hr = (img2img_enabled or upscale_enabled) and not pipeline.get("allow_hr_with_stages", False)
            if disable_hr:
                txt = cfg.setdefault("txt2img", {})
                if txt.get("enable_hr"):
                    txt["enable_hr"] = False
                    # Ensure second-pass is disabled
                    txt["hr_second_pass_steps"] = 0
                    logger.info(
                        "Disabled txt2img hires-fix for downstream stages (override with pipeline.allow_hr_with_stages)"
                    )
        except Exception:
            pass

        return cfg

    def _apply_aesthetic_to_payload(
        self, payload: dict[str, Any], full_config: dict[str, Any]
    ) -> tuple[str, str]:
        """Attach aesthetic gradient script data or fallback prompts to the payload."""

        prompt = payload.get("prompt", "")
        negative = payload.get("negative_prompt", "")

        aesthetic_cfg = (full_config or {}).get("aesthetic", {})
        if not aesthetic_cfg.get("enabled"):
            return prompt, negative

        mode = aesthetic_cfg.get("mode", "script")
        if mode == "script":
            script_args = self._build_aesthetic_script_args(aesthetic_cfg)
            if script_args:
                scripts = payload.setdefault("alwayson_scripts", {})
                scripts["Aesthetic embeddings"] = {"args": script_args}
            else:
                mode = "prompt"

        def append_phrase(base: str, addition: str) -> str:
            addition = (addition or "").strip()
            if not addition:
                return base
            return f"{base}, {addition}" if base else addition

        if mode == "prompt":
            text = aesthetic_cfg.get("text", "").strip()
            if text:
                if aesthetic_cfg.get("text_is_negative"):
                    negative = append_phrase(negative, text)
                else:
                    prompt = append_phrase(prompt, text)

            fallback = aesthetic_cfg.get("fallback_prompt", "").strip()
            if fallback:
                prompt = append_phrase(prompt, fallback)

            embedding = aesthetic_cfg.get("embedding")
            if embedding and embedding != "None":
                prompt = append_phrase(prompt, f"<embedding:{embedding}>")

        return prompt, negative

    def _build_aesthetic_script_args(self, cfg: dict[str, Any]) -> list[Any] | None:
        """Construct Always-on script args for the Aesthetic Gradient extension."""

        try:
            weight = float(cfg.get("weight", 0.9))
        except (TypeError, ValueError):
            weight = 0.9
        try:
            steps = int(cfg.get("steps", 5))
        except (TypeError, ValueError):
            steps = 5
        try:
            learning_rate = float(cfg.get("learning_rate", 0.0001))
        except (TypeError, ValueError):
            learning_rate = 0.0001
        slerp = bool(cfg.get("slerp", False))
        embedding = cfg.get("embedding", "None") or "None"
        text = cfg.get("text", "")
        try:
            angle = float(cfg.get("slerp_angle", 0.1))
        except (TypeError, ValueError):
            angle = 0.1
        text_negative = bool(cfg.get("text_is_negative", False))

        return [weight, steps, f"{learning_rate}", slerp, embedding, text, angle, text_negative]

    def _annotate_active_variant(
        self,
        config: dict[str, Any],
        variant_index: int,
        variant_label: str | None,
    ) -> None:
        """Record the active variant inside the pipeline config for downstream consumers."""

        pipeline_cfg = config.setdefault("pipeline", {})
        if variant_label or variant_index:
            pipeline_cfg["active_variant"] = {
                "index": variant_index,
                "label": variant_label,
            }
        else:
            pipeline_cfg.pop("active_variant", None)

    @staticmethod
    def _tag_variant_metadata(
        metadata: dict[str, Any] | None,
        variant_index: int,
        variant_label: str | None,
    ) -> dict[str, Any] | None:
        """Attach variant context to stage metadata dictionaries."""

        if not isinstance(metadata, dict):
            return metadata
        metadata["variant"] = {
            "index": variant_index,
            "label": variant_label,
        }
        return metadata

    @staticmethod
    def _build_variant_suffix(variant_index: int, variant_label: str | None) -> str:
        """Return a filesystem-safe suffix for the active variant."""

        slug = ""
        if variant_label:
            slug = re.sub(r"[^A-Za-z0-9]+", "-", variant_label).strip("-").lower()
        if slug:
            return f"_{slug}"
        if variant_index:
            return f"_v{variant_index + 1:02d}"
        return ""

    def _parse_sampler_config(self, config: dict[str, Any]) -> dict[str, str]:
        """
        Parse sampler configuration and extract scheduler if present.

        Args:
            config: Configuration dict that may contain sampler_name and scheduler

        Returns:
            Dict with 'sampler_name' and optional 'scheduler'
        """
        raw_sampler = config.get("sampler_name", "Euler a")
        sampler_name = (raw_sampler or "Euler a").strip() or "Euler a"
        # Strip and check for actual value (not just empty string)
        scheduler_value = (config.get("scheduler") or "").strip()

        scheduler_mappings = {
            "Karras": "Karras",
            "Exponential": "Exponential",
            "Polyexponential": "Polyexponential",
            "SGM Uniform": "SGM Uniform",
        }

        # Only try to extract from sampler name if no explicit scheduler provided
        if not scheduler_value:
            for scheduler_keyword, mapped in scheduler_mappings.items():
                if scheduler_keyword in sampler_name:
                    sampler_name = sampler_name.replace(scheduler_keyword, "").strip()
                    scheduler_value = mapped
                    break

        payload: dict[str, str] = {"sampler_name": sampler_name}
        # Include scheduler in payload if provided (not empty)
        if scheduler_value:
            payload["scheduler"] = scheduler_value
            logger.debug("Including scheduler in payload: '%s'", scheduler_value)
        else:
            logger.debug("No scheduler specified, WebUI will use default")
        return payload

    @staticmethod
    def _format_eta(seconds: float) -> str:
        """Format remaining seconds into a human-friendly ETA string."""

        if seconds <= 0:
            return "ETA: 00:00"

        total_seconds = int(round(seconds))
        minutes, secs = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if hours:
            return f"ETA: {hours:d}h {minutes:02d}m {secs:02d}s"
        return f"ETA: {minutes:02d}:{secs:02d}"

    def _extract_name_prefix(self, prompt: str) -> str | None:
        """
        Extract name prefix from prompt if it contains 'name:' metadata.

        Args:
            prompt: Text prompt that may contain 'name:' on first line

        Returns:
            Name prefix if found, None otherwise
        """
        lines = prompt.strip().split("\n")
        if lines:
            first_line = lines[0].strip()
            if first_line.lower().startswith("name:"):
                # Extract and clean the name
                name = first_line.split(":", 1)[1].strip()
                # Clean for filesystem safety
                name = re.sub(r"[^\w_-]", "_", name)
                return name if name else None
        return None

    def run_img2img(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run img2img cleanup/refinement with cancellation handling.
        """

        try:
            return self._run_img2img_impl(input_image_path, prompt, config, run_dir, cancel_token)
        except CancellationError as exc:
            if isinstance(cancel_token, CancelToken):
                self._log_pipeline_cancellation("img2img", exc)
                return getattr(self, "_last_img2img_result", None)
            raise

    def _run_img2img_impl(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run img2img cleanup/refinement.

        Args:
            input_image_path: Path to input image
            prompt: Text prompt
            config: Configuration for img2img
            run_dir: Run directory
            cancel_token: Optional cancellation token

        Returns:
            Generated image metadata
        """
        self._last_img2img_result: dict[str, Any] | None = None

        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "img2img start")

        # Emit status update for stage start
        total_steps = config.get("steps", 20)
        self._emit_stage_start("img2img", total_steps=total_steps)

        logger.info(f"Starting img2img cleanup for: {input_image_path.name}")

        # Load input image
        input_base64 = load_image_to_base64(input_image_path)
        if not input_base64:
            logger.error("Failed to load input image for img2img")
            return None

        # Apply global NSFW prevention to negative prompt
        base_negative = config.get("negative_prompt", "")
        enhanced_negative = self.config_manager.add_global_negative(base_negative)
        logger.info(
            f"🛡️ Applied global NSFW prevention (img2img) - Enhanced: '{enhanced_negative[:100]}...'"
        )

        # Set model and VAE if specified
        requested_model = config.get("model")
        # Handle VAE: only set if non-empty
        requested_vae = config.get("vae") if "vae" in config else config.get("vae_name")
        self._ensure_model_and_vae(requested_model, requested_vae)

        # Apply optional prompt adjustments from config
        prompt_adjust = (config.get("prompt_adjust") or "").strip()
        combined_prompt = prompt if not prompt_adjust else f"{prompt} {prompt_adjust}".strip()

        sampler_config = self._parse_sampler_config(config)

        payload = {
            "init_images": [input_base64],
            "prompt": combined_prompt,
            "negative_prompt": enhanced_negative,
            "steps": config.get("steps", 15),
            "cfg_scale": config.get("cfg_scale", 7.0),
            "denoising_strength": config.get("denoising_strength", 0.3),
            "width": config.get("width", 512),
            "height": config.get("height", 512),
            "seed": config.get("seed", -1),
            "clip_skip": config.get("clip_skip", 2),
        }

        payload.update(sampler_config)

        # Create progress callback that reports to controller
        def on_img2img_progress(percent: float, eta: float | None, current_step: int | None = None, total_steps: int | None = None) -> None:
            if self.progress_controller:
                eta_text = f"ETA: {int(eta)}s" if eta else "ETA: --"
                if current_step is not None and total_steps is not None:
                    eta_text = f"Step {current_step}/{total_steps}, {eta_text}"
                self.progress_controller.report_progress("img2img", percent, eta_text)

        # Track timing for this stage
        stage_start = time.monotonic()
        response = self._generate_images_with_progress(
            "img2img",
            payload,
            poll_interval=0.5,
            progress_callback=on_img2img_progress,
            stage_label="img2img",
        )
        stage_duration_ms = int((time.monotonic() - stage_start) * 1000)
        
        # Extract actual seed from response
        gen_info = self._extract_generation_info(response) if response else {}

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "img2img post-call")

        if not response or "images" not in response:
            logger.error("img2img failed")
            return None

        # Save cleaned image
        image_name = self._default_stage_image_name(stage="img2img", input_image_path=input_image_path)
        image_path = run_dir / "img2img" / f"{image_name}.png"

        # Extract stage history from input image
        stage_history = self._extract_stage_history_from_input(input_image_path)

        # Query WebUI for ACTUAL current model and VAE (what's really being used)
        model_name = self.client.get_current_model() or config.get("model") or config.get("sd_model_checkpoint") or "Unknown"
        vae_name = self.client.get_current_vae() or config.get("vae") or "Automatic"
        logger.info(f"📝 img2img manifest - Model: {model_name}, VAE: {vae_name}")

        metadata = {
            "name": image_name,
            "stage": "img2img",
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "prompt": prompt,
            "input_image": str(input_image_path),
            "config": self._clean_metadata_payload(payload),
            "path": str(image_path),
            # PR-PIPE-001: Enhanced metadata fields
            "job_id": getattr(self, "_current_job_id", None),
            "run_id": run_dir.name,  # PR-METADATA-001: Cross-reference to run_metadata.json
            "model": model_name,
            "vae": vae_name,
            "requested_seed": config.get("seed", -1),
            "actual_seed": gen_info.get("seed"),
            "actual_subseed": gen_info.get("subseed"),
            "stage_duration_ms": stage_duration_ms,
            # Accumulated stage history from input image
            "stage_history": stage_history,
        }
        metadata_builder = self._build_image_metadata_builder(
            image_path=image_path,
            stage="img2img",
            run_dir=run_dir,
            manifest=metadata,
        )
        actual_path = save_image_from_base64(
            response["images"][0], image_path, metadata_builder=metadata_builder
        )
        actual_path = self._coerce_saved_path(actual_path, fallback=image_path)
        if actual_path:
            self.logger.save_manifest(run_dir, actual_path.stem, metadata)
            self._last_img2img_result = metadata
            logger.info(f"img2img completed: {actual_path.name}")
            return metadata
        return None

    def run_adetailer(
        self,
        input_image_path: Path,
        prompt: str,
        negative_prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        image_name: str | None = None,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run ADetailer for automatic face/detail enhancement.

        Args:
            input_image_path: Path to input image
            prompt: Text prompt
            negative_prompt: Negative prompt (fallback if no adetailer_negative_prompt)
            config: Configuration for ADetailer
            run_dir: Run directory
            cancel_token: Optional cancellation token

        Returns:
            Enhanced image metadata or None if cancelled/failed
        """
        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "adetailer start")

        # Check if ADetailer is enabled
        if not config.get("adetailer_enabled", False):
            logger.info("ADetailer is disabled, skipping")
            return None

        # Emit status update for stage start
        total_steps = config.get("steps", 20)
        self._emit_stage_start("adetailer", total_steps=total_steps)

        # Set model and VAE if specified (ensure consistency across pipeline stages)
        # BUGFIX: Don't treat ADetailer model names as SD model checkpoints
        requested_model = config.get("model") or config.get("sd_model_checkpoint")
        # Handle VAE: get from config but don't default to fallback if empty
        requested_vae = config.get("vae") if "vae" in config else (config.get("sd_vae") if "sd_vae" in config else config.get("vae_name"))
        
        # Filter out ADetailer model names (they end with .pt and start with face_/hand_/person_/mediapipe)
        if requested_model:
            model_lower = requested_model.lower()
            is_adetailer_model = (
                model_lower.endswith('.pt') and 
                any(model_lower.startswith(prefix) for prefix in ['face_', 'hand_', 'person_', 'mediapipe'])
            )
            if is_adetailer_model:
                logger.warning(
                    "ADetailer detected adetailer model name '%s' in model field; ignoring SD model switch",
                    requested_model
                )
                requested_model = None  # Don't try to set this as SD model
        
        if requested_model or requested_vae:
            self._ensure_model_and_vae(requested_model, requested_vae)

        logger.info(f"Starting ADetailer for: {input_image_path.name}")

        # Load input image
        init_image = self._load_image_base64(input_image_path)
        if not init_image:
            logger.error("Failed to load input image")
            return None

        # Determine the working resolution for this image
        actual_width: int | None = None
        actual_height: int | None = None
        try:
            with Image.open(input_image_path) as image:
                actual_width, actual_height = image.size
        except Exception:
            actual_width = None
            actual_height = None

        def _coerce_dimension(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        payload_width = actual_width or _coerce_dimension(config.get("width"), 512)
        payload_height = actual_height or _coerce_dimension(config.get("height"), 512)

        # Use adetailer-specific negative prompt if provided, otherwise use txt2img negative
        # NOTE: ADetailer has its own custom prompts and should NOT get global positive/negative applied
        base_ad_neg = config.get("adetailer_negative_prompt", "")
        if base_ad_neg:
            # Use the specific adetailer negative prompt as-is (no global merging)
            ad_neg_final = base_ad_neg
            logger.info("🎯 Using custom ADetailer negative prompt (no global terms applied)")
        else:
            # No specific adetailer negative, use txt2img negative (already has global + aesthetic + pack)
            ad_neg_final = negative_prompt
            logger.info("🎯 Using txt2img negative prompt for ADetailer (inherited from previous stage)")

        # ADetailer uses custom prompts - never apply global negative merging
        apply_global = False

        # Import fallback tracking helper
        from src.utils.config_helpers import get_with_fallback_warning

        # DEBUG: Log ADetailer config received
        logger.info(
            "ADETAILER CONFIG RECEIVED: model=%s, steps=%s, denoise=%s, cfg=%s, sampler=%s, confidence=%s, mask_feather=%s",
            config.get("adetailer_model", "NOT_SET"),
            config.get("adetailer_steps", "NOT_SET"),
            config.get("adetailer_denoise", "NOT_SET"),
            config.get("adetailer_cfg", "NOT_SET"),
            config.get("adetailer_sampler", "NOT_SET"),
            config.get("adetailer_confidence", "NOT_SET"),
            config.get("adetailer_mask_feather", "NOT_SET"),
        )
        logger.info(
            "ADETAILER PROMPTS RECEIVED: positive='%s', negative='%s'",
            (config.get("adetailer_prompt", "")[:60] + "...") if len(config.get("adetailer_prompt", "")) > 60 else (config.get("adetailer_prompt", "") or "(empty)"),
            (base_ad_neg[:60] + "...") if len(base_ad_neg) > 60 else base_ad_neg,
        )

        # Use adetailer-specific prompt if provided, otherwise use txt2img prompt
        adetailer_prompt = config.get("adetailer_prompt", "")
        final_prompt = adetailer_prompt if adetailer_prompt else prompt
        prompt_optimizer_result, prompt_optimizer_config = self._run_prompt_optimizer(
            positive_prompt=final_prompt,
            negative_prompt=ad_neg_final,
            config=config,
            stage_name="adetailer",
        )
        final_prompt = prompt_optimizer_result.positive.optimized_prompt
        ad_neg_final = prompt_optimizer_result.negative.optimized_prompt
        logger.info("🔵 [ADETAILER_DEBUG] adetailer_prompt='%s', txt2img_prompt='%s', final_prompt='%s'", 
                    adetailer_prompt[:60] if adetailer_prompt else "(empty)",
                    prompt[:60] if prompt else "(empty)",
                    final_prompt[:60] if final_prompt else "(empty)")
        
        # Build ADetailer payload using smart fallback tracking
        # Warns only when keys are actually missing (true fallback), not when user chose defaults
        face_args = {
            "ad_model": get_with_fallback_warning(config, "adetailer_model", "face_yolov8n.pt", source="run_adetailer"),
            "ad_tab_enable": True,
            "ad_confidence": get_with_fallback_warning(config, "adetailer_confidence", 0.35, source="run_adetailer"),
            "ad_mask_filter_method": get_with_fallback_warning(config, "ad_mask_filter_method", "Area", source="run_adetailer", warn=False),
            "ad_mask_k": get_with_fallback_warning(config, "ad_mask_k_largest", 3, source="run_adetailer", warn=False),
            "ad_mask_min_ratio": get_with_fallback_warning(config, "ad_mask_min_ratio", 0.01, source="run_adetailer", warn=False),
            "ad_mask_max_ratio": get_with_fallback_warning(config, "ad_mask_max_ratio", 1.0, source="run_adetailer", warn=False),
            "ad_dilate_erode": get_with_fallback_warning(config, "ad_dilate_erode", 4, source="run_adetailer", warn=False),
            "ad_mask_blur": get_with_fallback_warning(config, "ad_mask_blur", 6, source="run_adetailer", warn=False),
            "ad_mask_merge_invert": get_with_fallback_warning(config, "ad_mask_merge_invert", "None", source="run_adetailer", warn=False),
            "ad_inpaint_only_masked": True,
            "ad_inpaint_only_masked_padding": get_with_fallback_warning(config, "adetailer_padding", 32, source="run_adetailer", warn=False),
            "ad_use_inpaint_width_height": False,  # Disable dimension optimization to prevent crashes on large images
            "ad_inpaint_width": payload_width,  # Lock to source dimensions - prevent resizing
            "ad_inpaint_height": payload_height,  # Lock to source dimensions - prevent resizing
            "ad_x_offset": 0,  # Disable x tiling
            "ad_y_offset": 0,  # Disable y tiling
            "ad_mask_only_top_k_largest": True,  # Process only largest detection
            "ad_use_steps": True,
            "ad_steps": get_with_fallback_warning(config, "adetailer_steps", 14, source="run_adetailer"),
            "ad_use_cfg_scale": True,
            "ad_cfg_scale": get_with_fallback_warning(config, "adetailer_cfg", 5.5, source="run_adetailer"),
            "ad_denoising_strength": get_with_fallback_warning(config, "adetailer_denoise", 0.32, source="run_adetailer"),
            "ad_use_sampler": True,
            "ad_sampler": get_with_fallback_warning(config, "adetailer_sampler", "DPM++ 2M Karras", source="run_adetailer"),
            "ad_scheduler": get_with_fallback_warning(config, "adetailer_scheduler", "Use same scheduler", source="run_adetailer", warn=False),
            "ad_prompt": config.get("adetailer_prompt", final_prompt),
            "ad_negative_prompt": config.get("adetailer_negative_prompt", ad_neg_final),
        }

        hand_args = {
            "ad_model": config.get("adetailer_hands_model", "hand_yolov8n.pt"),
            "ad_tab_enable": config.get("ad_hands_enabled", True),
            "ad_confidence": config.get("adetailer_hands_confidence", 0.30),
            "ad_mask_filter_method": config.get("ad_hands_mask_filter_method", "Area"),
            "ad_mask_k": config.get("ad_hands_mask_k", 6),
            "ad_mask_min_ratio": config.get("ad_hands_mask_min_ratio", 0.003),
            "ad_mask_max_ratio": config.get("ad_hands_mask_max_ratio", 1.0),
            "ad_dilate_erode": config.get("ad_hands_dilate_erode", 6),
            "ad_mask_blur": config.get("ad_hands_mask_blur", 4),
            "ad_mask_merge_invert": config.get("ad_hands_mask_merge_invert", "None"),
            "ad_inpaint_only_masked": True,
            "ad_inpaint_only_masked_padding": config.get("ad_hands_padding", 16),
            "ad_use_inpaint_width_height": False,  # Disable dimension optimization to prevent crashes on large images
            "ad_inpaint_width": payload_width,  # Lock to source dimensions - prevent resizing
            "ad_inpaint_height": payload_height,  # Lock to source dimensions - prevent resizing
            "ad_x_offset": 0,  # Disable x tiling
            "ad_y_offset": 0,  # Disable y tiling
            "ad_mask_only_top_k_largest": True,  # Process only largest detection
            "ad_use_steps": True,
            "ad_steps": config.get("adetailer_hands_steps", 12),
            "ad_use_cfg_scale": True,
            "ad_cfg_scale": config.get("adetailer_hands_cfg", 5.0),
            "ad_denoising_strength": config.get("adetailer_hands_denoise", 0.25),
            "ad_use_sampler": True,
            "ad_sampler": config.get("adetailer_hands_sampler", "DPM++ 2M Karras"),
            "ad_scheduler": config.get("adetailer_hands_scheduler", "Use same scheduler"),
            "ad_prompt": config.get(
                "adetailer_hands_prompt",
                "well-formed fingers, natural knuckles, correct hand anatomy, sharp details",
            ),
            "ad_negative_prompt": config.get(
                "adetailer_hands_negative_prompt",
                "extra fingers, fused fingers, broken fingers, deformed hands, missing fingers",
            ),
        }

        payload = {
            "init_images": [init_image],
            "prompt": final_prompt,
            "negative_prompt": ad_neg_final,
            "sampler_name": config.get("adetailer_sampler", "DPM++ 2M Karras"),
            "steps": config.get("adetailer_steps", 28),
            "cfg_scale": config.get("adetailer_cfg", 7.0),
            "denoising_strength": config.get("adetailer_denoise", 0.4),
            "width": payload_width,
            "height": payload_height,
            "alwayson_scripts": {
                "ADetailer": {
                    "args": [
                        True,
                        False,
                        face_args,
                        hand_args,
                    ]
                }
            },
        }
        # Add scheduler if present in config
        if config.get("scheduler"):
            payload["scheduler"] = config.get("scheduler")

        # DEBUG: Log ADetailer payload dimensions to verify no resizing
        logger.warning(
            "🔍 ADETAILER PAYLOAD: width=%s, height=%s, face[ad_use_inpaint_width_height]=%s, face[ad_inpaint_width]=%s, face[ad_inpaint_height]=%s",
            payload_width,
            payload_height,
            face_args.get("ad_use_inpaint_width_height"),
            face_args.get("ad_inpaint_width"),
            face_args.get("ad_inpaint_height"),
        )

        # Create progress callback that reports to controller
        def on_adetailer_progress(percent: float, eta: float | None, current_step: int | None = None, total_steps: int | None = None) -> None:
            if self.progress_controller:
                eta_text = f"ETA: {int(eta)}s" if eta else "ETA: --"
                if current_step is not None and total_steps is not None:
                    eta_text = f"Step {current_step}/{total_steps}, {eta_text}"
                self.progress_controller.report_progress("adetailer", percent, eta_text)

        # Track timing for this stage
        stage_start = time.monotonic()
        # Call img2img endpoint with ADetailer extension
        response = self._generate_images_with_progress(
            "img2img",
            payload,
            poll_interval=0.5,
            progress_callback=on_adetailer_progress,
            stage_label="adetailer",
        )
        stage_duration_ms = int((time.monotonic() - stage_start) * 1000)
        
        # Extract actual seed from response
        gen_info = self._extract_generation_info(response) if response else {}

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "adetailer post-call")

        if not response or "images" not in response:
            logger.error("adetailer failed")
            return None

        # Save enhanced image
        # Use provided image_name or fallback to timestamp
        if image_name:
            final_image_name = image_name
        else:
            final_image_name = self._default_stage_image_name(
                stage="adetailer",
                input_image_path=input_image_path,
            )
        image_path = run_dir / f"{final_image_name}.png"
        # PR-FILENAME-001: Apply collision failsafe
        from src.utils.file_io import get_unique_output_path
        image_path = get_unique_output_path(image_path)

        # Extract stage history from input image
        stage_history = self._extract_stage_history_from_input(input_image_path)

        # Query WebUI for ACTUAL current model and VAE
        model_name = self.client.get_current_model() or config.get("model") or config.get("sd_model_checkpoint") or "Unknown"
        vae_name = self.client.get_current_vae() or config.get("vae") or "Automatic"
        logger.info(f"📝 ADetailer manifest - Model: {model_name}, VAE: {vae_name}")

        metadata = {
            "name": final_image_name,
            "stage": "adetailer",
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "original_prompt": prompt,
            "final_prompt": payload.get("prompt", prompt),
            "original_negative_prompt": base_ad_neg,
            "final_negative_prompt": ad_neg_final,
            "global_negative_applied": apply_global,
            "global_negative_terms": "",  # Always empty for ADetailer per design
            "input_image": str(input_image_path),
            "config": self._clean_metadata_payload(payload),
            "path": str(image_path),
            "prompt_optimization": build_prompt_optimization_record(prompt_optimizer_result),
            # PR-PIPE-001: Enhanced metadata fields
            "job_id": getattr(self, "_current_job_id", None),
            "run_id": run_dir.name,  # PR-METADATA-001: Cross-reference to run_metadata.json
            "model": model_name,
            "vae": vae_name,
            "seeds": self._build_seed_metadata(config, gen_info),  # D-MANIFEST-001
            "stage_duration_ms": stage_duration_ms,
            # Accumulated stage history from input image
            "stage_history": stage_history,
            # Legacy fields for backward compatibility
            "requested_seed": config.get("seed", -1),
            "actual_seed": gen_info.get("seed"),
            "actual_subseed": gen_info.get("subseed"),
        }
        metadata_builder = self._build_image_metadata_builder(
            image_path=image_path,
            stage="adetailer",
            run_dir=run_dir,
            manifest=metadata,
        )
        actual_path = save_image_from_base64(
            response["images"][0], image_path, metadata_builder=metadata_builder
        )
        actual_path = self._coerce_saved_path(actual_path, fallback=image_path)
        if actual_path:
            # Save manifest in manifests/ subfolder (datetime/pack_name structure)
            manifest_dir = Path(run_dir) / "manifests"
            # Use actual image stem (includes _copy suffix if collision occurred)
            manifest_path = manifest_dir / f"{actual_path.stem}.json"
            try:
                metadata = self._attach_manifest_artifact(
                    metadata=metadata,
                    stage="adetailer",
                    primary_path=actual_path,
                    manifest_path=manifest_path,
                    output_paths=[str(actual_path)],
                    input_image_path=input_image_path,
                )
                self._write_manifest_file(
                    manifest_path=manifest_path,
                    metadata=metadata,
                    prompt_optimizer_result=prompt_optimizer_result,
                    prompt_optimizer_config=prompt_optimizer_config,
                )
            except Exception as e:
                logger.error(f"Error writing manifest file {manifest_path}: {e}")
                # Continue anyway - manifest is not critical
            
            logger.info(f"adetailer completed: {final_image_name}")
            return metadata

        return None
        """
        Run upscaling.

        Args:
            input_image_path: Path to input image
            config: Configuration for upscaling
            run_dir: Run directory
            cancel_token: Optional cancellation token

        Returns:
            Upscaled image metadata
        """
        # Check for cancellation before starting
        self._ensure_not_cancelled(cancel_token, "upscale stage start")

        logger.info(f"Starting upscale for: {input_image_path.name}")

        init_image = load_image_to_base64(input_image_path)
        if not init_image:
            logger.error("Failed to load input image")
            return None

        if hasattr(self.client, "ensure_safe_upscale_defaults"):
            try:
                self.client.ensure_safe_upscale_defaults()
            except Exception as exc:  # noqa: BLE001 - best-effort clamp
                logger.debug("ensure_safe_upscale_defaults failed: %s", exc)

        payload = {
            "image_base64": init_image,
            "upscaler": config.get("upscaler", "R-ESRGAN 4x+"),
            "upscaling_resize": config.get("upscaling_resize", 2.0),
            "gfpgan_visibility": config.get("gfpgan_visibility", 0.0),
            "codeformer_visibility": config.get("codeformer_visibility", 0.0),
            "codeformer_weight": config.get("codeformer_weight", 0.5),
        }
        
        # Track timing for this stage
        stage_start = time.monotonic()
        response = self._generate_images("upscale", payload)
        stage_duration_ms = int((time.monotonic() - stage_start) * 1000)
        
        # Extract info from response (upscale may not return seed, but try anyway)
        gen_info = self._extract_generation_info(response) if response else {}

        # Check for cancellation after API call
        self._ensure_not_cancelled(cancel_token, "upscale stage post-call")

        if not response or "image" not in response:
            logger.error("Upscale failed")
            return None

        image_name = self._default_stage_image_name(stage="upscale", input_image_path=input_image_path)
        image_path = run_dir / "upscaled" / f"{image_name}.png"

        # Extract stage history from input image
        stage_history = self._extract_stage_history_from_input(input_image_path)

        # Query WebUI for ACTUAL current model and VAE
        model_name = self.client.get_current_model() or config.get("model") or "Unknown"
        vae_name = self.client.get_current_vae() or config.get("vae") or "Automatic"
        logger.info(f"📝 run_upscale manifest - Model: {model_name}, VAE: {vae_name}")

        metadata = {
            "name": image_name,
            "stage": "upscale",
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "input_image": str(input_image_path),
            "config": config,
            "path": str(image_path),
            # PR-PIPE-001: Enhanced metadata fields
            "job_id": getattr(self, "_current_job_id", None),
            "run_id": run_dir.name,  # PR-METADATA-001: Cross-reference to run_metadata.json
            "model": model_name,
            "vae": vae_name,
            "seeds": self._build_seed_metadata(config, gen_info),  # D-MANIFEST-001
            "stage_duration_ms": stage_duration_ms,
            # Accumulated stage history from input image
            "stage_history": stage_history,
            # Legacy fields for backward compatibility
            "requested_seed": config.get("seed"),  # May be None for upscale
            "actual_seed": gen_info.get("seed"),  # Likely None for upscale
            "actual_subseed": gen_info.get("subseed"),  # Likely None for upscale
        }
        metadata_builder = self._build_image_metadata_builder(
            image_path=image_path,
            stage="upscale",
            run_dir=run_dir,
            manifest=metadata,
        )
        actual_path = save_image_from_base64(
            response["image"], image_path, metadata_builder=metadata_builder
        )
        actual_path = self._coerce_saved_path(actual_path, fallback=image_path)
        if actual_path:
            self.logger.save_manifest(run_dir, actual_path.stem, metadata)
            logger.info("Upscale completed successfully")
            return metadata

        return None

    def run_pack_pipeline(
        self,
        pack_name: str,
        prompt: str,
        config: dict[str, Any],
        run_dir: Path,
        prompt_index: int = 0,
        batch_size: int = 1,
        variant_index: int = 0,
        variant_label: str | None = None,
        negative_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Run pipeline for a single prompt from a pack with new directory structure.

        Args:
            pack_name: Name of the prompt pack (without .txt)
            prompt: Text prompt to process
            config: Configuration dictionary
            run_dir: Main session run directory
            prompt_index: Index of prompt within pack
            batch_size: Number of images to generate
            variant_index: Index of the active model/hypernetwork variant (0-based)
            variant_label: Human readable label for the active variant

        Returns:
            Pipeline results for this prompt
        """
        logger.info(f"🎨 Processing prompt {prompt_index + 1} from pack '{pack_name}'")

        # Create pack-specific directory structure
        self._begin_run_metrics()
        pack_dir = self.logger.create_pack_directory(run_dir, pack_name)

        # Save config for this pack run
        config_path = pack_dir / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        self.reset_stage_events()

        results: dict[str, Any] = {
            "pack_name": pack_name,
            "pack_dir": str(pack_dir),
            "prompt": prompt,
            "txt2img": [],  # list[dict]
            "img2img": [],  # list[dict]
            "adetailer": [],  # list[dict]
            "upscaled": [],  # list[dict]
            "summary": [],  # list[dict]
        }

        # Normalize config for this run (disable conflicting hires, normalize scheduler casing)
        config = self._normalize_config_for_pipeline(config)
        self._annotate_active_variant(config, variant_index, variant_label)

        # Emit a concise summary of stage parameters for this pack
        try:
            i2i_steps = config.get("img2img", {}).get("steps")
            up_mode = config.get("upscale", {}).get("upscale_mode", "single")
            up_steps = config.get("upscale", {}).get("steps")
            enable_hr = config.get("txt2img", {}).get("enable_hr")
            logger.info(
                "Pack '%s' params => img2img.steps=%s, upscale.mode=%s, upscale.steps=%s, txt2img.enable_hr=%s",
                pack_name,
                i2i_steps,
                up_mode,
                up_steps,
                enable_hr,
            )
        except Exception:
            pass

        # If caller provided an explicit negative prompt override, apply it early so
        # both the stage call and the config snapshot reflect the value (tests rely on this).
        if negative_prompt is not None:
            # Ensure txt2img section exists
            config.setdefault("txt2img", {})["negative_prompt"] = negative_prompt

        # ------------------------------------------------------------------
        # Batching strategy: generate ALL base txt2img images first, then perform
        # refinement & upscale passes. This minimizes costly model checkpoint
        # swaps when refiner is enabled but compare_mode is False.
        # ------------------------------------------------------------------
        txt_cfg = config.get("txt2img", {})
        refiner_checkpoint = txt_cfg.get("refiner_checkpoint")
        # Defensive: ensure refiner_checkpoint is string or None
        if refiner_checkpoint is not None:
            refiner_checkpoint = str(refiner_checkpoint)
        refiner_switch_at = txt_cfg.get("refiner_switch_at", 0.8)
        compare_mode = bool(config.get("pipeline", {}).get("refiner_compare_mode", False))
        use_refiner = (
            refiner_checkpoint
            and refiner_checkpoint != "None"
            and str(refiner_checkpoint).strip() != ""
            and 0.0 < float(refiner_switch_at) < 1.0
        )
        img2img_enabled = config.get("pipeline", {}).get("img2img_enabled", False)
        adetailer_enabled = config.get("pipeline", {}).get("adetailer_enabled", False)
        upscale_enabled = config.get("pipeline", {}).get("upscale_enabled", False)

        # Phase 1: txt2img for all images
        for batch_idx in range(batch_size):
            image_number = (prompt_index * batch_size) + batch_idx + 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            variant_suffix = self._build_variant_suffix(variant_index, variant_label)
            image_name = f"{image_number:03d}_{timestamp}{variant_suffix}"
            txt2img_dir = pack_dir / "txt2img"
            effective_negative = config.get("txt2img", {}).get("negative_prompt", "")
            meta = self.run_txt2img_stage(
                prompt, effective_negative, config, txt2img_dir, image_name
            )
            if meta:
                # ensure name present for downstream base prefix extraction
                meta = self._tag_variant_metadata(meta, variant_index, variant_label)
                results["txt2img"].append(meta)

        # Early exit if no base images
        if not results["txt2img"]:
            logger.error("No txt2img outputs produced; aborting pack pipeline early")
            return results
        
        # Log phase completion at WARNING level for visibility
        logger.warning(f"✅ txt2img phase completed: {len(results['txt2img'])} image(s) generated")
        
        # CRITICAL: Free VRAM after txt2img phase completes
        # Prevents VRAM accumulation before refinement stages
        try:
            logger.warning("🧹 Clearing VRAM after txt2img phase...")
            if hasattr(self.client, 'free_vram'):
                if self.client.free_vram(unload_model=False):
                    logger.warning("✅ VRAM cleared successfully after txt2img phase")
                else:
                    logger.warning("⚠️  VRAM clear returned False after txt2img phase")
        except Exception as exc:
            logger.warning(f"❌ Failed to clear VRAM after txt2img phase: {exc}")

        # Phase 2: refinement (img2img/adetailer/upscale) per base image
        for batch_idx, txt2img_meta in enumerate(results["txt2img"]):
            image_number = (prompt_index * batch_size) + batch_idx + 1
            # txt2img_meta is a dict; name key guaranteed from stage
            base_image_name = Path(txt2img_meta.get("name", "base")).stem
            last_image_path = txt2img_meta.get("path", "")
            final_image_path = last_image_path
            last_stage_meta: dict[str, Any] | None = txt2img_meta

            # Compare mode keeps original + refined branch logic (unchanged broadly)
            if compare_mode and use_refiner:
                candidates: list[dict[str, Any]] = [
                    {"label": "base", "path": txt2img_meta["path"], "meta": txt2img_meta}
                ]
                try:
                    # Defensive: ensure refiner_checkpoint is string before split
                    ref_str = str(refiner_checkpoint) if refiner_checkpoint else ""
                    ref_clean = ref_str.split(" [")[0] if " [" in ref_str else ref_str
                except Exception:
                    ref_clean = str(refiner_checkpoint) if refiner_checkpoint else ""
                forced_i2i_cfg = dict(config.get("img2img", {}))
                forced_i2i_cfg["model"] = ref_clean or forced_i2i_cfg.get("model", "")
                forced_i2i_cfg.setdefault("denoising_strength", 0.25)
                forced_i2i_cfg.setdefault("steps", max(10, int(forced_i2i_cfg.get("steps", 15))))
                img2img_dir_cmp = pack_dir / "img2img"
                refined_name = f"{base_image_name}_refined"
                try:
                    cmp_meta = self.run_img2img_stage(
                        Path(txt2img_meta["path"]),
                        prompt,
                        forced_i2i_cfg,
                        img2img_dir_cmp,
                        refined_name,
                        config,
                    )
                except TypeError:
                    cmp_meta = self.run_img2img_stage(
                        Path(txt2img_meta["path"]),
                        prompt,
                        forced_i2i_cfg,
                        img2img_dir_cmp,
                        refined_name,
                    )
                if cmp_meta:
                    cmp_meta = self._tag_variant_metadata(cmp_meta, variant_index, variant_label)
                    results["img2img"].append(cmp_meta)
                    candidates.append({"label": "refined", "path": cmp_meta["path"], "meta": cmp_meta})

                processed_final_paths: list[str] = []
                for cand in candidates:
                    branch_last = cand["path"]
                    if adetailer_enabled:
                        adetailer_cfg = dict(config.get("adetailer", {}))
                        txt_settings = config.get("txt2img", {})
                        adetailer_cfg.setdefault("width", txt_settings.get("width", 512))
                        adetailer_cfg.setdefault("height", txt_settings.get("height", 512))
                        # ADetailer uses its own custom prompts, no global prompt application needed
                        cand_negative = self._resolve_negative_prompt(
                            cand.get("meta"),
                            txt2img_meta,
                            (config.get("txt2img", {}) or {}).get("negative_prompt", ""),
                        )
                        adetailer_meta = self.run_adetailer(
                            Path(branch_last), prompt, cand_negative, adetailer_cfg, pack_dir
                        )
                        if adetailer_meta:
                            adetailer_meta = self._tag_variant_metadata(
                                adetailer_meta, variant_index, variant_label
                            )
                            results["adetailer"].append(adetailer_meta)
                            branch_last = adetailer_meta["path"]
                    if upscale_enabled:
                        upscale_dir = pack_dir / "upscaled"
                        up_name = f"{base_image_name}_{cand['label']}"
                        up_meta = self.run_upscale_stage(
                            Path(branch_last), config.get("upscale", {}), upscale_dir, up_name
                        )
                        if up_meta:
                            up_meta = self._tag_variant_metadata(
                                up_meta, variant_index, variant_label
                            )
                            results["upscaled"].append(up_meta)
                            processed_final_paths.append(up_meta["path"])
                        else:
                            processed_final_paths.append(branch_last)
                    else:
                        processed_final_paths.append(branch_last)
                final_image_path = (
                    processed_final_paths[0]
                    if processed_final_paths
                    else txt2img_meta.get("path", "")
                )
                last_image_path = final_image_path
            else:
                # Non-compare mode refinement path (single branch)
                if img2img_enabled:
                    img2img_dir = pack_dir / "img2img"
                    try:
                        img2img_meta = self.run_img2img_stage(
                            Path(txt2img_meta["path"]),
                            prompt,
                            config.get("img2img", {}),
                            img2img_dir,
                            base_image_name,
                            config,
                        )
                    except TypeError:
                        img2img_meta = self.run_img2img_stage(
                            Path(txt2img_meta["path"]),
                            prompt,
                            config.get("img2img", {}),
                            img2img_dir,
                            base_image_name,
                        )
                    if img2img_meta:
                        img2img_meta = self._tag_variant_metadata(
                            img2img_meta, variant_index, variant_label
                        )
                        results["img2img"].append(img2img_meta)
                        last_image_path = img2img_meta["path"]
                        last_stage_meta = img2img_meta
                        final_image_path = last_image_path
                        
                        # CRITICAL: Free VRAM after img2img before next stage
                        logger.warning("✅ img2img stage completed")
                        try:
                            logger.warning("🧹 Clearing VRAM after img2img stage...")
                            if hasattr(self.client, 'free_vram'):
                                if self.client.free_vram(unload_model=False):
                                    logger.warning("✅ VRAM cleared successfully after img2img")
                                else:
                                    logger.warning("⚠️  VRAM clear returned False after img2img")
                        except Exception as exc:
                            logger.warning(f"❌ Failed to clear VRAM after img2img: {exc}")
                            
                if adetailer_enabled:
                    adetailer_cfg = dict(config.get("adetailer", {}))
                    txt_settings = config.get("txt2img", {})
                    adetailer_cfg.setdefault("width", txt_settings.get("width", 512))
                    adetailer_cfg.setdefault("height", txt_settings.get("height", 512))
                    # ADetailer uses its own custom prompts, no global prompt application needed
                    fallback_neg = self._resolve_negative_prompt(
                        last_stage_meta,
                        txt2img_meta,
                        (config.get("txt2img", {}) or {}).get("negative_prompt", ""),
                    )
                    adetailer_meta = self.run_adetailer(
                        Path(last_image_path), prompt, fallback_neg, adetailer_cfg, pack_dir
                    )
                    if adetailer_meta:
                        adetailer_meta = self._tag_variant_metadata(
                            adetailer_meta, variant_index, variant_label
                        )
                        results["adetailer"].append(adetailer_meta)
                        last_image_path = adetailer_meta["path"]
                        last_stage_meta = adetailer_meta
                        final_image_path = last_image_path
                        
                        # CRITICAL: Free VRAM before upscale to prevent OOM
                        # ADetailer can leave models loaded consuming 14+ GB
                        logger.warning("✅ adetailer stage completed")
                        try:
                            logger.warning("🧹 Clearing VRAM after ADetailer before upscale...")
                            if hasattr(self.client, 'free_vram'):
                                if self.client.free_vram(unload_model=False):
                                    logger.warning("✅ VRAM cleared successfully after ADetailer")
                                else:
                                    logger.warning("⚠️  VRAM clear returned False after ADetailer")
                        except Exception as exc:
                            logger.warning(f"❌ Failed to clear VRAM after ADetailer: {exc}")
                
                if upscale_enabled:
                    upscale_dir = pack_dir / "upscaled"
                    upscaled_meta = self.run_upscale_stage(
                        Path(last_image_path),
                        config.get("upscale", {}),
                        upscale_dir,
                        base_image_name,
                    )
                    if upscaled_meta:
                        upscaled_meta = self._tag_variant_metadata(
                            upscaled_meta, variant_index, variant_label
                        )
                        results["upscaled"].append(upscaled_meta)
                        final_image_path = upscaled_meta["path"]
                        
                        # CRITICAL: Free VRAM after upscale for cleanup
                        # Ensures next job starts with clean VRAM state
                        logger.warning("✅ upscale stage completed")
                        try:
                            logger.warning("🧹 Clearing VRAM after upscale for next job...")
                            if hasattr(self.client, 'free_vram'):
                                if self.client.free_vram(unload_model=False):
                                    logger.warning("✅ VRAM cleared successfully after upscale")
                                else:
                                    logger.warning("⚠️  VRAM clear returned False after upscale")
                        except Exception as exc:
                            logger.warning(f"❌ Failed to clear VRAM after upscale: {exc}")
                    else:
                        final_image_path = last_image_path
                else:
                    final_image_path = last_image_path

            # Build summary entry
            summary_entry = {
                "pack": pack_name,
                "prompt_index": prompt_index,
                "batch_index": batch_idx,
                "image_number": image_number,
                "prompt": prompt,
                "final_image": final_image_path,
                "steps_completed": [],
                "variant": {"index": variant_index, "label": variant_label},
                "txt2img_final_prompt": txt2img_meta.get("final_prompt", ""),
                "txt2img_final_negative": txt2img_meta.get("final_negative_prompt", ""),
            }
            summary_entry["steps_completed"].append("txt2img")
            if results["img2img"]:
                # Collect img2img prompts for this base name
                try:
                    base_prefix = Path(txt2img_meta.get("name", "base")).stem
                    img2img_prompts: list[str] = []
                    img2img_negatives: list[str] = []
                    for m in results["img2img"]:
                        if isinstance(m, dict) and m.get("name", "").startswith(base_prefix):
                            img2img_prompts.append(m.get("final_prompt") or m.get("prompt", ""))
                            img2img_negatives.append(
                                m.get("final_negative_prompt") or m.get("negative_prompt", "")
                            )
                    if img2img_prompts:
                        summary_entry["steps_completed"].append("img2img")
                        summary_entry["img2img_final_prompt"] = "; ".join(img2img_prompts)
                        summary_entry["img2img_final_negative"] = "; ".join(img2img_negatives)
                except Exception:
                    pass
            if results["adetailer"]:
                try:
                    adetailer_meta = next(
                        (
                            m
                            for m in results["adetailer"]
                            if isinstance(m, dict) and m.get("path") == last_image_path
                        ),
                        None,
                    )
                    if adetailer_meta:
                        summary_entry["steps_completed"].append("adetailer")
                        summary_entry["adetailer_final_prompt"] = adetailer_meta.get(
                            "final_prompt", ""
                        )
                        summary_entry["adetailer_final_negative"] = adetailer_meta.get(
                            "final_negative_prompt", ""
                        )
                except Exception:
                    pass
            if results["upscaled"]:
                try:
                    up_meta = next(
                        (
                            m
                            for m in results["upscaled"]
                            if isinstance(m, dict) and m.get("path") == final_image_path
                        ),
                        None,
                    )
                    if up_meta:
                        summary_entry["steps_completed"].append("upscaled")
                        summary_entry["upscale_final_negative"] = up_meta.get(
                            "final_negative_prompt", ""
                        )
                except Exception:
                    pass
            results["summary"].append(summary_entry)

        # Create CSV summary for this pack
        if results["summary"]:
            summary_path = pack_dir / "summary.csv"
            self.logger.create_pack_csv_summary(summary_path, results["summary"])

        results["efficiency_metrics"] = self.get_run_efficiency_metrics(
            len(results.get("summary", []))
        )
        self._log_run_efficiency_metrics(
            run_type="pack_pipeline",
            images_processed=len(results.get("summary", [])),
        )
        logger.info(
            f"✅ Completed pack '{pack_name}' prompt {prompt_index + 1}: {len(results['summary'])} images"
        )
        return results

    def run_txt2img_stage(
        self,
        prompt: str,
        negative_prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run single txt2img stage for individual prompt.

        Args:
            prompt: Text prompt
            negative_prompt: Negative prompt
            config: Configuration dictionary
            output_dir: Output directory
            image_index: Index for naming

        Returns:
            Generated image metadata or None if failed
        """
        self._record_stage_event("txt2img", "enter", 1, 1, False)
        try:
            self._ensure_not_cancelled(cancel_token, "txt2img stage start")
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Verify directory creation succeeded
            if not output_dir.exists():
                logger.error(f"Failed to create output directory: {output_dir}")
                return None
            
            logger.debug(f"Output directory confirmed: {output_dir}")

            # Build txt2img payload - config may have txt2img sub-dict OR be flat
            # Support both formats for compatibility
            txt2img_config = config.get("txt2img", None)
            if txt2img_config is None:
                # Flat payload format from PipelineRunner._build_stage_payload
                txt2img_config = config
            
            # Extract batch_size from config (images_per_prompt)
            stage_batch_size = config.get("batch_size", 1)
            logger.info("🔵 [BATCH_SIZE_DEBUG] executor.run_txt2img_stage: config['batch_size']=%s, stage_batch_size=%s", config.get('batch_size'), stage_batch_size)

            # Apply global positive and negative prompts to txt2img stage only
            pipeline_section = config.get("pipeline", {})
            apply_global_positive = pipeline_section.get("apply_global_positive_txt2img", True)
            apply_global_negative = pipeline_section.get("apply_global_negative_txt2img", True)
            
            # Apply global positive (prepends quality/style terms)
            original_positive_prompt = prompt
            _, enhanced_positive, positive_global_applied, positive_global_terms = self._merge_stage_positive(
                original_positive_prompt, apply_global_positive
            )
            if positive_global_applied:
                logger.info(
                    "✨ Applied global positive terms (txt2img stage) - Enhanced: '%s'",
                    (enhanced_positive[:100] + "...")
                    if len(enhanced_positive) > 100
                    else enhanced_positive,
                )
            
            # Apply global negative (appends NSFW prevention terms)
            original_negative_prompt = negative_prompt
            _, enhanced_negative, negative_global_applied, negative_global_terms = self._merge_stage_negative(
                original_negative_prompt, apply_global_negative
            )
            if negative_global_applied:
                logger.info(
                    "dY>нЛ,? Applied global negative terms (txt2img stage) - Enhanced: '%s'",
                    (enhanced_negative[:100] + "...")
                    if len(enhanced_negative) > 100
                    else enhanced_negative,
                )

            # Check if refiner is configured for SDXL (native API support via override_settings)
            refiner_checkpoint = txt2img_config.get("refiner_checkpoint")
            # Allow either ratio (0-1) or absolute step count via refiner_switch_steps
            refiner_switch_at = txt2img_config.get("refiner_switch_at", 0.8)
            try:
                base_steps_for_switch = int(txt2img_config.get("steps", 20))
            except Exception:
                base_steps_for_switch = 20
            try:
                switch_steps = int(txt2img_config.get("refiner_switch_steps", 0) or 0)
            except Exception:
                switch_steps = 0
            if switch_steps and base_steps_for_switch > 0:
                # Convert absolute step to ratio clamped to (0,1)
                computed_ratio = max(0.01, min(0.99, switch_steps / float(base_steps_for_switch)))
                logger.info(
                    "🔀 Converting refiner_switch_steps=%d of %d to ratio=%.3f",
                    switch_steps,
                    base_steps_for_switch,
                    computed_ratio,
                )
                refiner_switch_at = computed_ratio
            # use_refiner must be explicitly True in config AND valid checkpoint/ratio
            # Read from txt2img_config (nested) or fall back to top-level config (flat payload)
            use_refiner_flag = txt2img_config.get("use_refiner", config.get("use_refiner", False))
            use_refiner = (
                use_refiner_flag  # Must be explicitly True
                and refiner_checkpoint
                and refiner_checkpoint != "None"
                and refiner_checkpoint.strip() != ""
                and 0.0 < refiner_switch_at < 1.0
            )
            
            # Log refiner status for debugging
            if not use_refiner_flag and refiner_checkpoint:
                logger.info("🚫 Refiner disabled via use_refiner=False (checkpoint present but ignored)")
            elif use_refiner:
                logger.info("✅ Refiner enabled: checkpoint=%s, switch_at=%.3f", refiner_checkpoint, refiner_switch_at)

            if use_refiner:
                # Compute expected switch step number within the base pass and within combined progress
                try:
                    base_steps = int(txt2img_config.get("steps", 20))
                except Exception:
                    base_steps = 20
                enable_hr = bool(txt2img_config.get("enable_hr", False))
                hr_steps_cfg = int(txt2img_config.get("hr_second_pass_steps", 0) or 0)
                effective_hr_steps = (
                    (hr_steps_cfg if hr_steps_cfg > 0 else base_steps) if enable_hr else 0
                )
                expected_switch_step_base = max(1, int(round(refiner_switch_at * base_steps)))
                expected_switch_step_total = (
                    expected_switch_step_base  # progress bars often show total steps
                )
                total_steps_progress = base_steps + effective_hr_steps
                logger.info(
                    "🎨 SDXL Refiner enabled: %s | switch_at=%s (≈ step %d of base %d; ≈ %d/%d total)",
                    refiner_checkpoint,
                    refiner_switch_at,
                    expected_switch_step_base,
                    base_steps,
                    expected_switch_step_total,
                    total_steps_progress,
                )

            # Set model and VAE if specified
            requested_model = txt2img_config.get("model") or txt2img_config.get("sd_model_checkpoint")
            requested_vae = txt2img_config.get("vae")
            
            # Debug: log what config we received
            logger.info(f"🔍 [EXECUTOR] Config keys: {list(txt2img_config.keys())}")
            logger.info(f"🔍 [EXECUTOR] Received requested_model='{requested_model}', requested_vae='{requested_vae}'")
            
            if requested_model or requested_vae:
                self._ensure_model_and_vae(requested_model, requested_vae)
            
            # Use the requested model/VAE for manifest (what we asked for)
            # Query WebUI only as fallback if not specified in config
            if requested_model:
                model_name = requested_model
            else:
                logger.info(f"🔍 Querying WebUI for current model...")
                model_name = self.client.get_current_model() or "Unknown"
            
            # For VAE: check if key exists in config (even if empty string)
            if "vae" in txt2img_config:
                vae_name = requested_vae or ""  # Use empty string if explicitly set to empty
            else:
                logger.info(f"🔍 Querying WebUI for current VAE...")
                vae_name = self.client.get_current_vae() or "Automatic"
            
            logger.info(f"📝 Manifest will use - Model: {model_name}, VAE: {vae_name}")

            self._ensure_hypernetwork(
                txt2img_config.get("hypernetwork"),
                txt2img_config.get("hypernetwork_strength"),
            )

            # Parse sampler configuration for this stage
            sampler_config = self._parse_sampler_config(txt2img_config)

            # Log configuration validation
            logger.debug(f"📝 Input txt2img config: {json.dumps(txt2img_config, indent=2)}")

            logger.info("🔵 [BATCH_SIZE_DEBUG] executor: About to create WebUI payload with batch_size=%s", stage_batch_size)
            payload = {
                "prompt": enhanced_positive,  # Use enhanced positive with global terms
                "negative_prompt": enhanced_negative,
                "steps": txt2img_config.get("steps", 20),
                "cfg_scale": txt2img_config.get("cfg_scale", 7.0),
                "width": txt2img_config.get("width", 512),
                "height": txt2img_config.get("height", 512),
                "seed": txt2img_config.get("seed", -1),
                "subseed": txt2img_config.get("subseed", -1),
                "subseed_strength": txt2img_config.get("subseed_strength", 0.0),
                "seed_resize_from_h": txt2img_config.get("seed_resize_from_h", -1),
                "seed_resize_from_w": txt2img_config.get("seed_resize_from_w", -1),
                "clip_skip": txt2img_config.get("clip_skip", 2),
                "batch_size": stage_batch_size,
                "n_iter": txt2img_config.get("n_iter", 1),
                "restore_faces": txt2img_config.get("restore_faces", False),
                "tiling": txt2img_config.get("tiling", False),
                "do_not_save_samples": txt2img_config.get("do_not_save_samples", True),
                "do_not_save_grid": txt2img_config.get("do_not_save_grid", True),
                # Include model and VAE in payload so WebUI uses them for this specific generation
                "sd_model": requested_model,
                "sd_vae": requested_vae,
            }

            # Always include hires.fix parameters (will be ignored if enable_hr is False)
            payload.update(
                {
                    "enable_hr": txt2img_config.get("enable_hr", False),
                    "hr_scale": txt2img_config.get("hr_scale", 2.0),
                    "hr_upscaler": txt2img_config.get("hr_upscaler", "Latent"),
                    "hr_second_pass_steps": txt2img_config.get("hr_second_pass_steps", 0),
                    "hr_resize_x": txt2img_config.get("hr_resize_x", 0),
                    "hr_resize_y": txt2img_config.get("hr_resize_y", 0),
                    "denoising_strength": txt2img_config.get("denoising_strength", 0.7),
                }
            )
            # Optional separate sampler for hires second pass
            try:
                hr_sampler_name = txt2img_config.get("hr_sampler_name")
                if hr_sampler_name:
                    payload["hr_sampler_name"] = hr_sampler_name
            except Exception:
                pass

            payload.update(sampler_config)

            prompt_after, negative_after = self._apply_aesthetic_to_payload(payload, config)
            payload["prompt"] = prompt_after
            payload["negative_prompt"] = negative_after
            prompt_optimizer_result, prompt_optimizer_config = self._run_prompt_optimizer(
                positive_prompt=payload.get("prompt", ""),
                negative_prompt=payload.get("negative_prompt", ""),
                config=config,
                stage_name="txt2img",
            )
            payload["prompt"] = prompt_optimizer_result.positive.optimized_prompt
            payload["negative_prompt"] = prompt_optimizer_result.negative.optimized_prompt
            try:
                logger.info(
                    "🎨 Final txt2img negative prompt (with global + aesthetic): '%s'",
                    (payload["negative_prompt"][:160] + "...")
                    if len(payload["negative_prompt"]) > 160
                    else payload["negative_prompt"],
                )
            except Exception:
                pass

            # Add styles if specified
            if txt2img_config.get("styles"):
                payload["styles"] = txt2img_config["styles"]

            # Add refiner support (SDXL native API - top-level parameters)
            if use_refiner:
                # WebUI v1.10+ supports native refiner via API parameters
                # This doesn't require explicit model switching, so Safe Mode shouldn't block it
                # However, if the refiner checkpoint name doesn't exist in WebUI, it may fail silently
                
                # Strip hash from checkpoint name if present (e.g., "model.safetensors [abc123]" -> "model.safetensors")
                # Defensive: ensure refiner_checkpoint is string before split
                try:
                    ref_str = str(refiner_checkpoint) if refiner_checkpoint else ""
                    refiner_checkpoint_clean = (
                        ref_str.split(" [")[0] if " [" in ref_str else ref_str
                    )
                except Exception:
                    refiner_checkpoint_clean = str(refiner_checkpoint) if refiner_checkpoint else ""
                
                # Log Safe Mode status for transparency
                if not self.client.options_write_enabled:
                    logger.info(
                        "🎨 Refiner enabled with Safe Mode active. "
                        "Using WebUI's native refiner API (no explicit model switch needed). "
                        "Refiner checkpoint: %s",
                        refiner_checkpoint_clean
                    )
                
                # Refiner parameters go at the top level of the payload
                payload["refiner_checkpoint"] = refiner_checkpoint_clean
                payload["refiner_switch_at"] = refiner_switch_at
                logger.debug(
                    f"🎨 Refiner params: checkpoint={refiner_checkpoint_clean}, switch_at={refiner_switch_at}"
                )

            # Log final payload for validation
            logger.debug(f"🚀 Sending txt2img payload: {json.dumps(payload, indent=2)}")
            logger.info("🔵 [BATCH_SIZE_DEBUG] executor: Final payload batch_size=%s, n_iter=%s (should generate %s total images)", payload.get('batch_size'), payload.get('n_iter'), payload.get('batch_size', 1) * payload.get('n_iter', 1))

            # Generate image
            self._apply_webui_defaults_once()
            def on_txt2img_progress(percent: float, eta: float | None, current_step: int | None = None, total_steps: int | None = None) -> None:
                if self.progress_controller:
                    eta_text = f"ETA: {int(eta)}s" if eta else "ETA: --"
                    if current_step is not None and total_steps is not None:
                        eta_text = f"Step {current_step}/{total_steps}, {eta_text}"
                    self.progress_controller.report_progress("txt2img", percent, eta_text)

            response = self._generate_images_with_progress(
                "txt2img",
                payload,
                poll_interval=0.5,
                progress_callback=on_txt2img_progress,
                stage_label="txt2img",
            )
            if not response or "images" not in response or not response["images"]:
                logger.error("txt2img failed - no images returned")
                return None

            gen_info = self._extract_generation_info(response) if response else {}

            # Log how many images were actually generated
            num_images_received = len(response["images"])
            logger.info("🔵 [BATCH_SIZE_DEBUG] WebUI returned %s images (expected %s)", num_images_received, payload.get('batch_size', 1) * payload.get('n_iter', 1))
            
            # Save ALL images with unique filenames
            # When multiple images are returned (batch_size > 1 OR n_iter > 1), use _batch{idx} suffix
            saved_paths = []
            batch_size = payload.get('batch_size', 1)
            n_iter = payload.get('n_iter', 1)
            expected_image_count = max(1, int(batch_size) * int(n_iter))
            run_dir = self._resolve_run_dir(output_dir)
            base_metadata = {
                "stage": "txt2img",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "original_prompt": original_positive_prompt,
                "final_prompt": payload.get("prompt", enhanced_positive),
                "global_positive_applied": positive_global_applied,
                "global_positive_terms": positive_global_terms if positive_global_applied else "",
                "original_negative_prompt": original_negative_prompt,
                "final_negative_prompt": payload.get("negative_prompt", enhanced_negative),
                "global_negative_applied": negative_global_applied,
                "global_negative_terms": negative_global_terms if negative_global_applied else "",
                "seed": payload.get("seed", -1),
                "subseed": payload.get("subseed", -1),
                "subseed_strength": payload.get("subseed_strength", 0.0),
                "config": self._clean_metadata_payload(payload),
                "job_id": getattr(self, "_current_job_id", None),
                "requested_seed": payload.get("seed", -1),
                "actual_seed": gen_info.get("seed"),
                "actual_subseed": gen_info.get("subseed"),
                "model": model_name,
                "vae": vae_name,
                "prompt_optimization": build_prompt_optimization_record(prompt_optimizer_result),
            }
            saved_variants: list[tuple[Path, dict[str, Any]]] = []
            
            for batch_idx in range(num_images_received):
                # Multiple images: use suffix _batch0, _batch1, etc.
                # This applies when batch_size > 1 OR n_iter > 1
                if num_images_received > 1:
                    batch_image_name = f"{image_name}_batch{batch_idx}"
                    image_path = output_dir / f"{batch_image_name}.png"
                else:
                    # Single image: use original name
                    image_path = output_dir / f"{image_name}.png"
                    batch_image_name = image_name
                
                # PR-FILENAME-001: Apply collision failsafe
                from src.utils.file_io import get_unique_output_path
                image_path = get_unique_output_path(image_path)
                
                logger.info("🔵 [BATCH_SIZE_DEBUG] Saving image %s/%s: %s", batch_idx + 1, num_images_received, image_path.name)
                image_metadata = dict(base_metadata)
                image_metadata["name"] = batch_image_name
                image_metadata["path"] = str(image_path)
                image_metadata["output_path"] = str(image_path)
                metadata_builder = self._build_image_metadata_builder(
                    image_path=image_path,
                    stage="txt2img",
                    run_dir=run_dir,
                    manifest=image_metadata,
                )
                actual_path = save_image_from_base64(
                    response["images"][batch_idx],
                    image_path,
                    metadata_builder=metadata_builder,
                )
                if not actual_path:
                    logger.error("Failed to save image %s", image_path)
                    continue
                    
                saved_paths.append(actual_path)
                manifest_dir = output_dir / "manifests"
                manifest_dir.mkdir(exist_ok=True, parents=True)
                variant_manifest_path = manifest_dir / f"{actual_path.stem}.json"
                saved_variants.append((variant_manifest_path, image_metadata))
            
            # Use the first image for metadata and return value (backward compatibility)
            if saved_paths:
                image_path = saved_paths[0]
                # Always use original image_name for metadata (without _batch suffix)
                batch_image_name = image_name
            else:
                logger.error("No images were saved successfully")
                return None

            saved_image_count = len(saved_paths)
            partial_success = (
                0 < saved_image_count < expected_image_count
                or 0 < num_images_received < expected_image_count
                or saved_image_count < num_images_received
            )
            if partial_success:
                logger.warning(
                    "txt2img partial success: expected=%s returned=%s saved=%s",
                    expected_image_count,
                    num_images_received,
                    saved_image_count,
                )

            for variant_manifest_path, image_metadata in saved_variants:
                image_metadata["expected_images"] = expected_image_count
                image_metadata["returned_images"] = num_images_received
                image_metadata["saved_images"] = saved_image_count
                image_metadata["partial_success"] = partial_success
                image_metadata["recovery_classification"] = (
                    "partial_image_response" if partial_success else None
                )
                image_metadata = self._attach_manifest_artifact(
                    metadata=image_metadata,
                    stage="txt2img",
                    primary_path=image_metadata.get("path") or image_metadata.get("output_path") or "",
                    manifest_path=variant_manifest_path,
                    output_paths=[image_metadata.get("path") or image_metadata.get("output_path") or ""],
                )
                try:
                    self._write_manifest_file(
                        manifest_path=variant_manifest_path,
                        metadata=image_metadata,
                        prompt_optimizer_result=prompt_optimizer_result,
                        prompt_optimizer_config=prompt_optimizer_config,
                    )
                    logger.debug(f"Saved variant manifest: {variant_manifest_path.name}")
                except Exception as e:
                    logger.error(f"Failed to save variant manifest {variant_manifest_path}: {e}")
            
            if True:  # Keep original indentation for metadata block
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                metadata = {
                    "name": image_name,
                    "stage": "txt2img",
                    "timestamp": timestamp,
                    "original_prompt": original_positive_prompt,
                    "final_prompt": payload.get("prompt", enhanced_positive),
                    "global_positive_applied": positive_global_applied,
                    "global_positive_terms": positive_global_terms if positive_global_applied else "",
                    "original_negative_prompt": original_negative_prompt,
                    "final_negative_prompt": payload.get("negative_prompt", enhanced_negative),
                    "global_negative_applied": negative_global_applied,
                    "global_negative_terms": negative_global_terms if negative_global_applied else "",
                    "seed": payload.get("seed", -1),
                    "subseed": payload.get("subseed", -1),
                    "subseed_strength": payload.get("subseed_strength", 0.0),
                    "config": self._clean_metadata_payload(payload),
                    "output_path": str(image_path),
                    "path": str(image_path),
                    "all_paths": [str(p) for p in saved_paths],  # All generated images for batch processing
                    "expected_images": expected_image_count,
                    "returned_images": num_images_received,
                    "saved_images": saved_image_count,
                    "partial_success": partial_success,
                    "recovery_classification": "partial_image_response" if partial_success else None,
                    "prompt_optimization": build_prompt_optimization_record(prompt_optimizer_result),
                }

                # Manifests already saved per-variant in the loop above
                self._record_stage_event("txt2img", "exit", 1, 1, False)
                return metadata
            else:
                logger.error("Failed to save generated image")
                self._record_stage_event("txt2img", "exit", 1, 1, False)
                return None

        except CancellationError:
            self._record_stage_event("txt2img", "cancelled", 1, 1, True)
            raise
        except Exception as e:
            logger.error(f"txt2img stage failed: {str(e)}")
            return None

    def run_img2img_stage(
        self,
        input_image_path: Path,
        prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        full_config: dict[str, Any] | None = None,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run img2img stage for image cleanup/refinement.

        Args:
            input_image_path: Path to input image
            prompt: Text prompt
            config: img2img configuration
            output_dir: Output directory
            image_name: Base name for output image

        Returns:
            Generated image metadata or None if failed
        """
        self._record_stage_event("img2img", "enter", 1, 1, False)
        try:
            self._ensure_not_cancelled(cancel_token, "img2img stage start")
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Load input image as base64
            input_image_b64 = self._load_image_base64(input_image_path)
            if not input_image_b64:
                logger.error(f"Failed to load input image: {input_image_path}")
                return None

            # Set model and VAE if specified
            model_name = config.get("model")
            vae_name = config.get("vae")
            if model_name or vae_name:
                self._ensure_model_and_vae(model_name, vae_name)

            self._ensure_hypernetwork(
                config.get("hypernetwork"),
                config.get("hypernetwork_strength"),
            )

            # Build img2img payload
            # Combine negative prompt with optional adjustments
            base_negative = config.get("negative_prompt", "")
            neg_adjust = (config.get("negative_adjust") or "").strip()
            original_negative_prompt = (
                base_negative if not neg_adjust else f"{base_negative} {neg_adjust}".strip()
            )

            # Optionally apply global negative safety terms based on stage flag
            apply_global = (
                (full_config or {}).get("pipeline", {}).get("apply_global_negative_img2img", True)
            )
            _, enhanced_negative, global_applied, global_terms = self._merge_stage_negative(
                original_negative_prompt, apply_global
            )
            if global_applied:
                try:
                    logger.info(
                        "dY>нЛ,? Applied global NSFW prevention (img2img stage) - Enhanced: '%s'",
                        (enhanced_negative[:100] + "...")
                        if len(enhanced_negative) > 100
                        else enhanced_negative,
                    )
                except Exception:
                    pass

            sampler_config = self._parse_sampler_config(config)

            payload = {
                "init_images": [input_image_b64],
                "prompt": prompt,
                "negative_prompt": enhanced_negative,
                "steps": config.get("steps", 15),
                "cfg_scale": config.get("cfg_scale", 7.0),
                "denoising_strength": config.get("denoising_strength", 0.3),
                "width": config.get("width", 512),
                "height": config.get("height", 512),
                "seed": config.get("seed", -1),
                "clip_skip": config.get("clip_skip", 2),
                "batch_size": 1,
                "n_iter": 1,
            }

            mask_image_path = config.get("mask_image_path") or config.get("mask_path")
            if mask_image_path:
                mask_image_b64 = self._load_image_base64(Path(str(mask_image_path)))
                if not mask_image_b64:
                    logger.error(f"Failed to load mask image: {mask_image_path}")
                    return None
                payload["mask"] = mask_image_b64
                payload["mask_blur"] = int(config.get("mask_blur", 4))
                payload["inpaint_full_res"] = bool(config.get("inpaint_full_res", True))
                payload["inpaint_full_res_padding"] = int(config.get("inpaint_full_res_padding", 32))
                payload["inpainting_fill"] = int(config.get("inpainting_fill", 1))
                payload["inpainting_mask_invert"] = 1 if config.get("inpainting_mask_invert", False) else 0

            payload.update(sampler_config)

            # Apply aesthetic adjustments AFTER global negative safety terms so they layer on top
            prompt_after, negative_after = self._apply_aesthetic_to_payload(
                payload, full_config or {"aesthetic": {}}
            )
            payload["prompt"] = prompt_after
            payload["negative_prompt"] = negative_after
            prompt_optimizer_result, prompt_optimizer_config = self._run_prompt_optimizer(
                positive_prompt=payload.get("prompt", ""),
                negative_prompt=payload.get("negative_prompt", ""),
                config=full_config or config,
                stage_name="img2img",
            )
            payload["prompt"] = prompt_optimizer_result.positive.optimized_prompt
            payload["negative_prompt"] = prompt_optimizer_result.negative.optimized_prompt
            try:
                logger.info(
                    "🎨 Final img2img negative prompt (with%s global + aesthetic): '%s'",
                    "" if apply_global else "out",
                    (payload["negative_prompt"][:160] + "...")
                    if len(payload["negative_prompt"]) > 160
                    else payload["negative_prompt"],
                )
            except Exception:
                pass

            # Log key parameters at INFO to correlate with WebUI progress
            try:
                logger.info(
                    "img2img params => steps=%s, denoise=%s, sampler=%s, scheduler=%s",
                    payload.get("steps"),
                    payload.get("denoising_strength"),
                    payload.get("sampler_name"),
                    payload.get("scheduler"),
                )
            except Exception:
                pass

            # Execute img2img
            response = self._generate_images("img2img", payload)
            if not response or "images" not in response or not response["images"]:
                logger.error("img2img request failed or returned no images")
                return None

            # Save image
            image_path = output_dir / f"{image_name}.png"
            # PR-FILENAME-001: Apply collision failsafe
            from src.utils.file_io import get_unique_output_path
            image_path = get_unique_output_path(image_path)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            gen_info = self._extract_generation_info(response)
            metadata = {
                "name": image_name,
                "stage": "img2img",
                "timestamp": timestamp,
                "source_image_path": str(input_image_path),
                "mask_image_path": str(mask_image_path) if mask_image_path else None,
                "original_prompt": prompt,
                "final_prompt": payload.get("prompt", prompt),
                "original_negative_prompt": original_negative_prompt,
                "final_negative_prompt": payload.get("negative_prompt", ""),
                "global_negative_applied": global_applied,
                "global_negative_terms": global_terms if global_applied else "",
                "seed": payload.get("seed", -1),
                "subseed": payload.get("subseed", -1),
                "subseed_strength": payload.get("subseed_strength", 0.0),
                "input_image": str(input_image_path),
                "config": self._clean_metadata_payload(payload),
                "path": str(image_path),
                "seeds": self._build_seed_metadata(payload, gen_info),  # D-MANIFEST-001
                "prompt_optimization": build_prompt_optimization_record(prompt_optimizer_result),
                # Legacy fields for backward compatibility
                "requested_seed": payload.get("seed", -1),
                "actual_seed": gen_info.get("seed"),
                "actual_subseed": gen_info.get("subseed"),
            }
            run_dir = self._resolve_run_dir(output_dir)
            metadata_builder = self._build_image_metadata_builder(
                image_path=image_path,
                stage="img2img",
                run_dir=run_dir,
                manifest=metadata,
            )
            actual_path = save_image_from_base64(
                response["images"][0], image_path, metadata_builder=metadata_builder
            )
            actual_path = self._coerce_saved_path(actual_path, fallback=image_path)
            if actual_path:
                # Save manifest in manifests/ subfolder (datetime/pack_name structure)
                manifest_dir = Path(output_dir) / "manifests"
                # Use actual stem from saved path (includes _copy suffix if collision)
                manifest_path = manifest_dir / f"{actual_path.stem}.json"
                try:
                    metadata = self._attach_manifest_artifact(
                        metadata=metadata,
                        stage="img2img",
                        primary_path=actual_path,
                        manifest_path=manifest_path,
                        output_paths=[str(actual_path)],
                        input_image_path=input_image_path,
                    )
                    self._write_manifest_file(
                        manifest_path=manifest_path,
                        metadata=metadata,
                        prompt_optimizer_result=prompt_optimizer_result,
                        prompt_optimizer_config=prompt_optimizer_config,
                    )
                except Exception as e:
                    logger.error(f"Error writing manifest file {manifest_path}: {e}")

                logger.info(f"img2img completed: {image_path.name}")
                self._record_stage_event("img2img", "exit", 1, 1, False)
                return metadata
            else:
                logger.error(f"Failed to save img2img image: {image_path}")
                self._record_stage_event("img2img", "exit", 1, 1, False)
                return None

        except CancellationError:
            self._record_stage_event("img2img", "cancelled", 1, 1, True)
            raise
        except Exception as e:
            logger.error(f"img2img stage failed: {e}")
            return None

    def run_animatediff_stage(
        self,
        input_image_path: Path | None,
        prompt: str,
        negative_prompt: str,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """Run AnimateDiff through the standard WebUI txt2img/img2img endpoints."""

        self._record_stage_event("animatediff", "enter", 1, 1, False)
        try:
            self._ensure_not_cancelled(cancel_token, "animatediff stage start")
            output_dir.mkdir(parents=True, exist_ok=True)

            capability = self.client.get_animatediff_capability()
            if not capability.available:
                raise RuntimeError(
                    capability.reason or "AnimateDiff is not available from the WebUI scripts API"
                )

            animatediff_cfg = AnimateDiffConfig.from_dict(config)
            if not animatediff_cfg.enabled:
                raise RuntimeError("AnimateDiff stage is disabled in the runtime config")

            current_model = self.client.get_current_model()
            if not isinstance(current_model, str) or not current_model.strip():
                current_model = None
            requested_model = (
                config.get("model")
                or config.get("sd_model_checkpoint")
                or current_model
            )
            requested_vae = config.get("vae")
            if requested_model or requested_vae:
                self._ensure_model_and_vae(requested_model, requested_vae)

            self._ensure_hypernetwork(
                config.get("hypernetwork"),
                config.get("hypernetwork_strength"),
            )

            sampler_config = self._parse_sampler_config(config)
            self._ensure_webui_true_ready()
            self._check_webui_health_before_stage("animatediff")

            run_mode = "img2img" if input_image_path is not None else "txt2img"
            payload: dict[str, Any] = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "steps": config.get("steps", 16),
                "cfg_scale": config.get("cfg_scale", 7.0),
                "width": config.get("width", 512),
                "height": config.get("height", 512),
                "seed": config.get("seed", -1),
                "clip_skip": config.get("clip_skip", 2),
                "batch_size": 1,
                "n_iter": 1,
            }
            payload.update(sampler_config)
            if input_image_path is not None:
                input_image_b64 = self._load_image_base64(input_image_path)
                if not input_image_b64:
                    raise RuntimeError(f"Failed to load AnimateDiff input image: {input_image_path}")
                payload["init_images"] = [input_image_b64]
                denoising_strength = config.get("denoising_strength")
                if denoising_strength in (None, ""):
                    denoising_strength = 0.3
                payload["denoising_strength"] = denoising_strength

            resolved_motion_module = resolve_animatediff_motion_module(
                animatediff_cfg,
                capability,
                requested_model,
            )
            if resolved_motion_module and resolved_motion_module != animatediff_cfg.motion_module:
                animatediff_cfg = AnimateDiffConfig(
                    enabled=animatediff_cfg.enabled,
                    motion_module=resolved_motion_module,
                    fps=animatediff_cfg.fps,
                    video_length=animatediff_cfg.video_length,
                    loop_number=animatediff_cfg.loop_number,
                    closed_loop=animatediff_cfg.closed_loop,
                    batch_size=animatediff_cfg.batch_size,
                    stride=animatediff_cfg.stride,
                    overlap=animatediff_cfg.overlap,
                    format=list(animatediff_cfg.format),
                )
                logger.info(
                    "animatediff stage auto-selected motion module %s for model %s",
                    resolved_motion_module,
                    requested_model or "<unknown>",
                )

            payload = attach_animatediff_to_payload(payload, animatediff_cfg, capability)
            response = self.client.img2img(payload) if run_mode == "img2img" else self.client.txt2img(payload)
            normalized = normalize_animatediff_response(response)
            frame_images = normalized["frame_images"]
            expected_frame_count = max(2, animatediff_cfg.video_length)
            if not frame_images:
                raise RuntimeError("AnimateDiff returned no frame images")
            if not normalized.get("animate_detected") and len(frame_images) < expected_frame_count:
                raise RuntimeError(
                    "AnimateDiff payload was accepted by WebUI but did not produce an AnimateDiff response"
                )

            from src.utils.file_io import get_unique_output_path

            video_path = get_unique_output_path(output_dir / f"{image_name}.mp4")
            frames_dir = output_dir / f"{video_path.stem}_frames"
            frame_paths = write_video_frames(frame_images, frames_dir, frame_prefix="frame")
            if not frame_paths:
                raise RuntimeError("AnimateDiff frames could not be written to disk")

            video_creator = VideoCreator()
            if not video_creator.create_video_from_images(
                frame_paths,
                video_path,
                fps=animatediff_cfg.fps,
            ):
                raise RuntimeError("AnimateDiff video assembly failed")

            gen_info = self._extract_generation_info(response or {})
            metadata = {
                "name": image_name,
                "stage": "animatediff",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "input_image": str(input_image_path) if input_image_path else None,
                "source_image_path": str(input_image_path) if input_image_path else None,
                "config": self._clean_metadata_payload(payload),
                "path": str(video_path),
                "output_path": str(video_path),
                "video_path": str(video_path),
                "output_paths": [str(video_path)],
                "frame_paths": [str(path) for path in frame_paths],
                "frame_path_count": len(frame_paths),
                "frame_count": len(frame_paths),
                "fps": animatediff_cfg.fps,
                "motion_module": animatediff_cfg.motion_module,
                "extension_contract": normalized["extension_contract"],
                "requested_seed": payload.get("seed", -1),
                "actual_seed": gen_info.get("seed"),
                "actual_subseed": gen_info.get("subseed"),
            }

            manifest_dir = output_dir / "manifests"
            manifest_dir.mkdir(exist_ok=True, parents=True)
            manifest_path = manifest_dir / f"{video_path.stem}.json"
            metadata["manifest_path"] = str(manifest_path)
            metadata["manifest_paths"] = [str(manifest_path)]
            metadata["count"] = 1
            metadata["artifact"] = artifact_manifest_payload(
                stage="animatediff",
                image_or_output_path=video_path,
                manifest_path=manifest_path,
                output_paths=[str(video_path)],
                input_image_path=input_image_path,
                artifact_type="video",
            )
            self._write_manifest_file(
                manifest_path=manifest_path,
                metadata=metadata,
            )

            self._record_stage_event(
                "animatediff",
                "exit",
                len(frame_paths),
                len(frame_paths),
                False,
                extra={"video_path": str(video_path)},
            )
            return metadata
        except CancellationError:
            self._record_stage_event("animatediff", "cancelled", 1, 1, True)
            raise
        except Exception as exc:
            logger.error("animatediff stage failed: %s", exc)
            return None

    def run_svd_native_stage(
        self,
        *,
        input_image_path: Path | None,
        stage_config: dict[str, Any],
        output_dir: Path,
        job_id: str,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """Run the native Stable Video Diffusion stage against an existing image."""

        self._record_stage_event("svd_native", "enter", 1, 1, False)
        try:
            self._ensure_not_cancelled(cancel_token, "svd_native stage start")
            if input_image_path is None:
                raise RuntimeError("svd_native stage requires an input image")

            from src.video.svd_config import SVDConfig
            from src.video.svd_runner import SVDRunner

            config = SVDConfig.from_dict(stage_config)
            self._emit_stage_start("svd_native", total_steps=4)

            def _on_svd_status(status: dict[str, Any]) -> None:
                self._emit_stage_detail_update(
                    stage_name="svd_native",
                    stage_detail=str(status.get("stage_detail") or "").strip() or None,
                    progress=float(status.get("progress", 0.0) or 0.0),
                    eta_seconds=status.get("eta_seconds"),
                    current_step=int(status.get("current_step", 0) or 0),
                    total_steps=int(status.get("total_steps", 0) or 0),
                )

            runner = SVDRunner(output_root=output_dir, status_callback=_on_svd_status)
            result = runner.run(
                source_image_path=input_image_path,
                config=config,
                job_id=job_id,
            )
            self._emit_stage_detail_update(
                stage_name="svd_native",
                stage_detail="complete",
                progress=1.0,
                current_step=result.frame_count,
                total_steps=result.frame_count,
            )

            output_paths = [str(path) for path in result.frame_paths]
            primary_path = None
            if result.video_path is not None:
                primary_path = str(result.video_path)
                output_paths = [primary_path]
            elif result.gif_path is not None:
                primary_path = str(result.gif_path)
                output_paths = [primary_path]
            elif output_paths:
                primary_path = output_paths[0]

            metadata = {
                "stage": "svd_native",
                "path": primary_path,
                "output_paths": output_paths,
                "video_path": str(result.video_path) if result.video_path else None,
                "gif_path": str(result.gif_path) if result.gif_path else None,
                "frame_paths": [str(path) for path in result.frame_paths],
                "frame_count": result.frame_count,
                "fps": result.fps,
                "thumbnail_path": str(result.thumbnail_path) if result.thumbnail_path else None,
                "manifest_path": str(result.metadata_path) if result.metadata_path else None,
                "model_id": result.model_id,
                "seed": result.seed,
                "source_image_path": str(result.source_image_path),
                "postprocess": result.postprocess,
                "preprocess": {
                    "source_path": str(result.preprocess.source_path),
                    "prepared_path": str(result.preprocess.prepared_path),
                    "original_width": result.preprocess.original_width,
                    "original_height": result.preprocess.original_height,
                    "target_width": result.preprocess.target_width,
                    "target_height": result.preprocess.target_height,
                    "resize_mode": result.preprocess.resize_mode,
                    "was_resized": result.preprocess.was_resized,
                    "was_padded": result.preprocess.was_padded,
                    "was_cropped": result.preprocess.was_cropped,
                },
            }
            metadata["artifact"] = artifact_manifest_payload(
                stage="svd_native",
                image_or_output_path=primary_path or "",
                manifest_path=metadata["manifest_path"],
                output_paths=output_paths,
                thumbnail_path=metadata["thumbnail_path"],
                input_image_path=metadata["source_image_path"],
                artifact_type="video",
            )
            self._record_stage_event(
                "svd_native",
                "exit",
                result.frame_count,
                result.frame_count,
                False,
                extra={
                    "path": primary_path,
                    "video_path": metadata["video_path"],
                    "gif_path": metadata["gif_path"],
                },
            )
            return metadata
        except CancellationError:
            self._record_stage_event("svd_native", "cancelled", 1, 1, True)
            raise
        except Exception as exc:
            logger.error("svd_native stage failed: %s", exc)
            return None

    def run_upscale_stage(
        self,
        input_image_path: Path,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run upscale stage for image enhancement.

        Args:
            input_image_path: Path to input image
            config: Upscale configuration
            output_dir: Output directory
            image_name: Base name for output image

        Returns:
            Generated image metadata or None if failed
        """
        self._record_stage_event("upscale", "enter", 1, 1, False)
        try:
            self._ensure_not_cancelled(cancel_token, "upscale stage start")
            
            # Set model and VAE if specified (ensure consistency across pipeline stages)
            requested_model = config.get("model") or config.get("sd_model_checkpoint")
            # Handle VAE: get from config but don't default to fallback if empty
            requested_vae = config.get("vae") if "vae" in config else (config.get("sd_vae") if "sd_vae" in config else config.get("vae_name"))
            if requested_model or requested_vae:
                self._ensure_model_and_vae(requested_model, requested_vae)
            
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Load input image as base64
            input_image_b64 = self._load_image_base64(input_image_path)
            if not input_image_b64:
                logger.error(f"Failed to load input image: {input_image_path}")
                return None

            upscale_mode = config.get("upscale_mode", "single")

            # DEBUG: Log full upscale config
            logger.info(
                "UPSCALE CONFIG RECEIVED: mode=%s, upscaler=%s, resize=%s, steps=%s, sampler=%s, denoise=%s",
                upscale_mode,
                config.get("upscaler", "NOT_SET"),
                config.get("upscaling_resize", "NOT_SET"),
                config.get("steps", "NOT_SET"),
                config.get("sampler_name", "NOT_SET"),
                config.get("denoising_strength", "NOT_SET"),
            )

            # REMOVED: ensure_safe_upscale_defaults() was interfering with user's tile_size=0 config
            # Forcing ESRGAN_tile to 512 broke the upscaler's tiling logic
            # User has been running tile_size=0 successfully - don't override it
            
            # Pre-upscale memory management (upscale is memory-intensive)
            try:
                import gc
                import psutil
                
                mem = psutil.virtual_memory()
                mem_percent = mem.percent
                mem_available_gb = mem.available / (1024**3)
                
                # Upscale can use a lot of RAM - check memory pressure
                if mem_percent > 85.0 or mem_available_gb < 3.0:
                    logger.warning(
                        "⚠️ High memory pressure before upscale: %.1f%% used, %.1fGB available - freeing caches",
                        mem_percent, mem_available_gb
                    )
                    
                    # Force GC and VRAM clear to free memory
                    gc.collect()
                    if hasattr(self.client, 'free_vram'):
                        self.client.free_vram(unload_model=False, force_gc=True)
                        
            except Exception as exc:
                logger.debug("Pre-upscale memory check failed (non-fatal): %s", exc)

            if upscale_mode == "img2img":
                # Use img2img for upscaling with denoising
                # First get original image dimensions to calculate target size
                try:
                    image_bytes = base64.b64decode(input_image_b64)
                    with Image.open(BytesIO(image_bytes)) as pil_image:
                        orig_width, orig_height = pil_image.size
                except Exception as exc:
                    logger.error("Failed to inspect image dimensions for upscale: %s", exc)
                    return None

                upscale_factor = config.get("upscaling_resize", 2.0)
                target_width = int(orig_width * upscale_factor)
                target_height = int(orig_height * upscale_factor)

                logger.info(
                    "UPSCALE DIAG: mode=img2img, upscaler=%s, resize=%s, input=%sx%s, target=%sx%s",
                    config.get("upscaler", "R-ESRGAN 4x+"),
                    upscale_factor,
                    orig_width,
                    orig_height,
                    target_width,
                    target_height,
                )

                payload = {
                    "init_images": [input_image_b64],
                    "prompt": config.get("prompt", ""),
                    "negative_prompt": config.get("negative_prompt", ""),
                    "steps": config.get("steps", 20),
                    "cfg_scale": config.get("cfg_scale", 7.0),
                    "denoising_strength": config.get("denoising_strength", 0.35),
                    "width": target_width,
                    "height": target_height,
                    "sampler_name": config.get("sampler_name", "Euler a"),
                    "scheduler": config.get("scheduler", "normal"),
                    "seed": config.get("seed", -1),
                    "clip_skip": config.get("clip_skip", 2),
                    "batch_size": 1,
                    "n_iter": 1,
                }

                try:
                    logger.info(
                        "upscale(img2img) params => steps=%s, denoise=%s, sampler=%s, scheduler=%s, target=%sx%s",
                        payload.get("steps"),
                        payload.get("denoising_strength"),
                        payload.get("sampler_name"),
                        payload.get("scheduler"),
                        target_width,
                        target_height,
                    )
                except Exception:
                    pass

                # Apply global negative if any (upscale-as-img2img path may include a negative prompt)
                global_applied = False
                global_terms = ""
                try:
                    original_neg = payload.get("negative_prompt", "")
                    if original_neg:
                        apply_global = (
                            config.get("pipeline", {}) if isinstance(config, dict) else {}
                        ).get("apply_global_negative_upscale", True)
                        _, enhanced_neg, global_applied, global_terms = self._merge_stage_negative(
                            original_neg, apply_global
                        )
                        payload["negative_prompt"] = enhanced_neg
                        if global_applied:
                            logger.info(
                                "Applied global NSFW prevention (upscale img2img) - Enhanced: '%s'",
                                (enhanced_neg[:120] + "...")
                                if len(enhanced_neg) > 120
                                else enhanced_neg,
                            )
                        else:
                            logger.info("Global negative skipped for upscale(img2img) stage")
                except Exception:
                    pass

                # Track timing for this stage
                stage_start = time.monotonic()
                response = self._generate_images("img2img", payload)
                stage_duration_ms = int((time.monotonic() - stage_start) * 1000)
                response_key = "images"
                image_key = 0
            else:
                # Use extra-single-image upscaling via client API
                upscaler = config.get("upscaler", "R-ESRGAN 4x+")
                upscaling_resize = config.get("upscaling_resize", 2.0)
                gfpgan_vis = config.get("gfpgan_visibility", 0.0)
                codeformer_vis = config.get("codeformer_visibility", 0.0)
                codeformer_weight = config.get("codeformer_weight", 0.5)

                orig_width: int | None = None
                orig_height: int | None = None
                try:
                    image_bytes = base64.b64decode(input_image_b64)
                    with Image.open(BytesIO(image_bytes)) as pil_image:
                        orig_width, orig_height = pil_image.size
                except Exception as exc:
                    logger.warning(
                        "UPSCALE DIAG: failed to read input size for %s: %s",
                        input_image_path.name,
                        exc,
                    )

                logger.info(
                    "UPSCALE DIAG: mode=single, upscaler=%s, resize=%s, input=%sx%s, target=%sx%s",
                    upscaler,
                    upscaling_resize,
                    orig_width if orig_width is not None else "?",
                    orig_height if orig_height is not None else "?",
                    int(orig_width * upscaling_resize) if orig_width is not None else "?",
                    int(orig_height * upscaling_resize) if orig_height is not None else "?",
                )

                # Track timing for this stage
                stage_start = time.monotonic()
                # Call client.upscale_image() which properly formats the payload
                response = self.client.upscale_image(
                    image_base64=input_image_b64,
                    upscaler=upscaler,
                    upscaling_resize=upscaling_resize,
                    gfpgan_visibility=gfpgan_vis,
                    codeformer_visibility=codeformer_vis,
                    codeformer_weight=codeformer_weight,
                )
                stage_duration_ms = int((time.monotonic() - stage_start) * 1000)
                response_key = "image"
                image_key = None

            if not response or response_key not in response:
                logger.error("Upscale request failed or returned no image")
                return None

            # Save image
            image_path = output_dir / f"{image_name}.png"
            # PR-FILENAME-001: Apply collision failsafe
            from src.utils.file_io import get_unique_output_path
            image_path = get_unique_output_path(image_path)

            # Extract the correct image data based on upscale mode
            if image_key is None:
                image_data = response[response_key]
            else:
                if not response[response_key] or len(response[response_key]) <= image_key:
                    logger.error("No image data returned from upscale")
                    return None
                image_data = response[response_key][image_key]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Build metadata config based on upscale mode
            if upscale_mode == "img2img":
                config_dict = self._clean_metadata_payload(payload)
                neg_prompt = payload.get("negative_prompt")
            else:
                # Single-image mode doesn't have full payload - include all relevant params
                # BUGFIX: Include steps, sampler, scheduler, denoise in manifest for single mode
                config_dict = {
                    "upscaler": upscaler,
                    "upscaling_resize": upscaling_resize,
                    "gfpgan_visibility": gfpgan_vis,
                    "codeformer_visibility": codeformer_vis,
                    "codeformer_weight": codeformer_weight,
                    "steps": config.get("steps", 20),
                    "denoising_strength": config.get("denoising_strength", 0.35),
                    "sampler_name": config.get("sampler_name", "Euler a"),
                    "scheduler": config.get("scheduler", "normal"),
                }
                neg_prompt = None

            # Extract stage history from input image
            stage_history = self._extract_stage_history_from_input(input_image_path)

            # Query WebUI for ACTUAL current model and VAE
            model_name = self.client.get_current_model() or config.get("model") or "Unknown"
            vae_name = self.client.get_current_vae() or config.get("vae") or "Automatic"
            logger.info(f"📝 Upscale manifest - Model: {model_name}, VAE: {vae_name}")
            
            metadata = {
                "name": image_name,
                "stage": "upscale",
                "timestamp": timestamp,
                "input_image": str(input_image_path),
                "final_negative_prompt": neg_prompt,
                "global_negative_applied": global_applied
                if "global_applied" in locals()
                else False,
                "global_negative_terms": global_terms
                if "global_terms" in locals() and global_applied
                else "",
                "config": config_dict,
                "path": str(image_path),
                # PR-PIPE-001: Enhanced metadata fields
                "job_id": getattr(self, "_current_job_id", None),
                "model": model_name,
                "vae": vae_name,
                "requested_seed": config.get("seed") if upscale_mode == "img2img" else None,
                "actual_seed": None,  # Upscale doesn't return seed info
                "actual_subseed": None,  # Upscale doesn't return seed info
                "stage_duration_ms": stage_duration_ms,
                # Accumulated stage history from previous stages
                "stage_history": stage_history,
            }
            run_dir = self._resolve_run_dir(output_dir)
            metadata_builder = self._build_image_metadata_builder(
                image_path=image_path,
                stage="upscale",
                run_dir=run_dir,
                manifest=metadata,
            )
            actual_path = save_image_from_base64(
                image_data, image_path, metadata_builder=metadata_builder
            )
            actual_path = self._coerce_saved_path(actual_path, fallback=image_path)
            if actual_path:
                # Save manifest in manifests/ subfolder (datetime/pack_name structure)
                manifest_dir = Path(output_dir) / "manifests"
                # Use actual stem from saved path (includes _copy suffix if collision)
                manifest_path = manifest_dir / f"{actual_path.stem}.json"
                try:
                    metadata = self._attach_manifest_artifact(
                        metadata=metadata,
                        stage="upscale",
                        primary_path=actual_path,
                        manifest_path=manifest_path,
                        output_paths=[str(actual_path)],
                        input_image_path=input_image_path,
                    )
                    self._write_manifest_file(
                        manifest_path=manifest_path,
                        metadata=metadata,
                    )
                except Exception as e:
                    logger.error(f"Error writing manifest file {manifest_path}: {e}")

                logger.info(f"Upscale completed: {image_path.name}")
                
                # Post-upscale memory check (warn if still under pressure)
                try:
                    import psutil
                    mem = psutil.virtual_memory()
                    if mem.percent > 90.0:
                        logger.warning(
                            "⚠️ Memory still high after upscale: %.1f%% used - consider reducing upscale factor or batch size",
                            mem.percent
                        )
                except Exception:
                    pass
                
                self._record_stage_event("upscale", "exit", 1, 1, False)
                return metadata
            else:
                logger.error(f"Failed to save upscaled image: {image_path}")
                self._record_stage_event("upscale", "exit", 1, 1, False)
                return None

        except CancellationError:
            self._record_stage_event("upscale", "cancelled", 1, 1, True)
            raise
        except Exception as e:
            import traceback
            logger.error(f"Upscale stage failed: {e}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            self._record_stage_event("upscale", "exit", 1, 1, False)
            return None

    def run_adetailer_stage(
        self,
        input_image_path: Path,
        config: dict[str, Any],
        output_dir: Path,
        image_name: str,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        cancel_token=None,
    ) -> dict[str, Any] | None:
        """
        Run adetailer stage using the shared ADetailer helper.
        """
        self._record_stage_event("adetailer", "enter", 1, 1, False)
        try:
            self._ensure_not_cancelled(cancel_token, "adetailer stage start")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # DEBUG: Log what config was received
            logger.info(
                "ADETAILER_STAGE CONFIG KEYS: %s",
                list(config.keys()) if config else "EMPTY"
            )
            logger.info(
                "ADETAILER_STAGE VALUES: denoise=%s, steps=%s, model=%s, sampler=%s",
                config.get("adetailer_denoise") if config else "NO_CONFIG",
                config.get("adetailer_steps") if config else "NO_CONFIG",
                config.get("adetailer_model") if config else "NO_CONFIG",
                config.get("adetailer_sampler") if config else "NO_CONFIG",
            )
            
            adetailer_cfg = dict(config or {})
            adetailer_cfg.setdefault(
                "pipeline", config.get("pipeline", {}) if isinstance(config, dict) else {}
            )
            if isinstance(config, dict) and "prompt_optimizer" in config:
                adetailer_cfg.setdefault("prompt_optimizer", config.get("prompt_optimizer"))
            # Use adetailer-specific prompts if provided, otherwise fallback to txt2img prompts
            config_positive = adetailer_cfg.get("adetailer_prompt", "").strip()
            config_negative = adetailer_cfg.get("adetailer_negative_prompt", "").strip()
            prompt_text = config_positive if config_positive else (prompt or "")
            negative_text = config_negative if config_negative else (negative_prompt or "")
            logger.info("🔵 [ADETAILER_PROMPT_DEBUG] config_positive='%s', config_negative='%s', using prompt='%s', negative='%s'",
                       config_positive[:40] if config_positive else "(empty)",
                       config_negative[:40] if config_negative else "(empty)",
                       prompt_text[:40] if prompt_text else "(empty)",
                       negative_text[:40] if negative_text else "(empty)")
            result = self.run_adetailer(
                input_image_path, prompt_text, negative_text, adetailer_cfg, output_dir, 
                image_name=image_name, cancel_token=cancel_token
            )
            if result:
                self._last_adetailer_result = result
            return result
        except CancellationError:
            self._record_stage_event("adetailer", "cancelled", 1, 1, True)
            raise
        except Exception as e:
            logger.error(f"adetailer stage failed: {e}")
            return None
        finally:
            self._record_stage_event("adetailer", "exit", 1, 1, False)
