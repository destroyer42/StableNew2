"""Production pipeline runner integration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.api.client import SDWebUIClient
from src.gui.state import CancellationError
from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.learning.learning_record_builder import build_learning_record
from src.learning.run_metadata import write_run_metadata
from src.pipeline.artifact_contract import canonicalize_variant_entries
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
from src.state.output_routing import classify_njr_output_route, get_output_route_root
from src.utils import LogContext, StructuredLogger, get_logger, log_with_ctx
from src.utils.config import ConfigManager
from src.video.video_backend_registry import VideoBackendRegistry, build_default_video_backend_registry
from src.video.video_backend_types import VideoExecutionRequest, VideoExecutionResult

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from src.controller.app_controller import CancelToken


def _merge_output_dir_into_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    metadata = dict(data.get("metadata") or {})
    output_dir = data.get("output_dir")
    if output_dir and "output_dir" not in metadata:
        metadata["output_dir"] = output_dir
    return metadata


class PipelineRunner:
    """
    Adapter that drives the real multi-stage Pipeline executor.
    Consolidates output folders by prompt pack - all jobs from the same pack
    go into the same timestamped folder.
    """
    
    # Cache for active pack folders keyed by route + canonical folder key.
    _pack_folder_cache: dict[str, Path] = {}
    _folder_cache_timeout_minutes = 30  # Reuse folder if same pack within 30 minutes

    @staticmethod
    def _pin_stage_model_to_njr_base(
        config_dict: dict[str, Any],
        *,
        njr: NormalizedJobRecord,
        stage_name: str,
    ) -> None:
        """Default downstream image stages to the NJR base model unless overridden."""
        if stage_name not in {"img2img", "adetailer", "upscale"}:
            return
        if config_dict.get("model") or config_dict.get("sd_model_checkpoint"):
            return
        base_model = str(getattr(njr, "base_model", "") or "").strip()
        if not base_model:
            return
        config_dict["model"] = base_model
        logger.info(
            "[MODEL_PIN] Pinned %s stage to NJR base model: %s",
            stage_name,
            base_model,
        )

    @staticmethod
    def _sanitize_output_component(name: str) -> str:
        return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(name))

    @staticmethod
    def _shorten_model_name(name: str) -> str:
        value = str(name or "")
        for ext in [".safetensors", ".ckpt", ".pt"]:
            if value.lower().endswith(ext):
                value = value[:-len(ext)]
                break
        if len(value) <= 15:
            return value
        return value[:10] + value[-5:]

    @staticmethod
    def _extract_folder_timestamp(run_dir: Path) -> datetime | None:
        try:
            return datetime.strptime(run_dir.name[:15], "%Y%m%d_%H%M%S")
        except ValueError:
            return None

    @classmethod
    def _folder_is_reusable(cls, run_dir: Path, now: datetime) -> bool:
        folder_time = cls._extract_folder_timestamp(run_dir)
        if folder_time is None:
            try:
                folder_time = datetime.fromtimestamp(run_dir.stat().st_mtime)
            except Exception:
                return False
        timeout_seconds = cls._folder_cache_timeout_minutes * 60
        return (now - folder_time).total_seconds() < timeout_seconds

    @classmethod
    def _find_recent_matching_run_dir(
        cls,
        *,
        route_root: Path,
        folder_name: str,
        now: datetime,
    ) -> Path | None:
        suffix = f"_{folder_name}"
        if not route_root.exists():
            return None
        candidates = [
            child
            for child in route_root.iterdir()
            if child.is_dir() and (child.name == folder_name or child.name.endswith(suffix))
        ]
        candidates.sort(key=lambda path: path.name, reverse=True)
        for candidate in candidates:
            if cls._folder_is_reusable(candidate, now):
                return candidate
        return None

    @classmethod
    def _resolve_run_dir(
        cls,
        *,
        route_root: Path,
        route_cache_key: str,
        folder_name: str,
        now: datetime,
    ) -> Path:
        cached_dir = cls._pack_folder_cache.get(route_cache_key)
        if cached_dir and cached_dir.exists() and cls._folder_is_reusable(cached_dir, now):
            return cached_dir

        existing_dir = cls._find_recent_matching_run_dir(
            route_root=route_root,
            folder_name=folder_name,
            now=now,
        )
        if existing_dir is not None:
            cls._pack_folder_cache[route_cache_key] = existing_dir
            return existing_dir

        run_dir = route_root / f"{now.strftime('%Y%m%d_%H%M%S')}_{folder_name}"
        run_dir.mkdir(parents=True, exist_ok=True)
        cls._pack_folder_cache[route_cache_key] = run_dir
        return run_dir

    @staticmethod
    def _stage_config_dict_for_video(njr: NormalizedJobRecord, stage_name: str) -> dict[str, Any]:
        stage_config = next((s for s in njr.stage_chain if s.stage_type == stage_name), None)
        if stage_config is None:
            return {}
        config_dict = asdict(stage_config)
        if "extra" in config_dict:
            config_dict.update(config_dict.pop("extra"))
        return config_dict

    def _execute_video_stage(
        self,
        *,
        stage_name: str,
        njr: NormalizedJobRecord,
        current_stage_paths: list[str],
        prompt: str,
        negative_prompt: str,
        run_dir: Path,
        cancel_token: CancelToken | None,
        variants: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> list[str]:
        backend = self._video_backends.get_for_stage(stage_name)
        config_dict = self._stage_config_dict_for_video(njr, stage_name)
        if stage_name == "animatediff":
            config_dict["enabled"] = True
            if njr.scheduler:
                config_dict["scheduler"] = njr.scheduler

        next_stage_paths: list[str] = []
        manifest_paths: list[str] = []
        artifact_records: list[dict[str, Any]] = []
        backend_results: list[VideoExecutionResult] = []
        prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0

        from pathlib import Path as PathLib
        from src.utils.file_io import build_safe_image_name

        base_prefix = f"{stage_name}_p{prompt_row+1:02d}_v{njr.variant_index+1:02d}"
        matrix_values = getattr(njr, "matrix_slot_values", None) if hasattr(njr, "matrix_slot_values") else None
        pack_name = getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)
        original_inputs = getattr(njr, "input_image_paths", None)
        use_original_name = original_inputs and getattr(njr, "start_stage", None)

        video_paths: list[str] = []
        gif_paths: list[str] = []
        thumbnail_path: str | None = None
        frame_path_count = 0

        for img_idx, input_path in enumerate(current_stage_paths):
            image_name = None
            if stage_name == "animatediff":
                if use_original_name and img_idx < len(original_inputs):
                    input_stem = PathLib(original_inputs[img_idx]).stem[:30]
                    unique_prefix = f"{base_prefix}_{input_stem}"
                else:
                    unique_prefix = base_prefix
                image_name = build_safe_image_name(
                    base_prefix=unique_prefix,
                    matrix_values=matrix_values,
                    seed=None,
                    batch_index=img_idx,
                    pack_name=pack_name,
                    max_length=100,
                )
            request = VideoExecutionRequest(
                backend_id=backend.backend_id,
                stage_name=stage_name,
                stage_config=dict(config_dict),
                output_dir=run_dir,
                input_image_path=Path(input_path) if input_path else None,
                image_name=image_name,
                prompt=prompt,
                negative_prompt=negative_prompt,
                job_id=njr.job_id,
                cancel_token=cancel_token,
                context_metadata={
                    "prompt_pack_id": getattr(njr, "prompt_pack_id", ""),
                    "prompt_pack_name": getattr(njr, "prompt_pack_name", ""),
                    "variant_index": getattr(njr, "variant_index", 0),
                    "batch_index": img_idx,
                },
            )
            execution_result = backend.execute(self._pipeline, request)
            if execution_result is None:
                continue

            backend_results.append(execution_result)
            variant_payload = execution_result.to_variant_payload()
            variants.append(variant_payload)
            if execution_result.artifact:
                artifact_records.append(dict(execution_result.artifact))
            if execution_result.manifest_path:
                manifest_paths.append(str(execution_result.manifest_path))
            if execution_result.thumbnail_path:
                thumbnail_path = thumbnail_path or str(execution_result.thumbnail_path)
            if execution_result.output_paths:
                next_stage_paths.extend(str(item) for item in execution_result.output_paths if item)
            elif execution_result.primary_path:
                next_stage_paths.append(str(execution_result.primary_path))

            video_path = variant_payload.get("video_path")
            gif_path = variant_payload.get("gif_path")
            frame_paths = [str(item) for item in variant_payload.get("frame_paths") or [] if item]
            if video_path:
                video_paths.append(str(video_path))
            if gif_path:
                gif_paths.append(str(gif_path))
            if frame_paths and not video_path and not gif_path:
                frame_path_count += len(frame_paths)

        if stage_name == "animatediff" and next_stage_paths:
            metadata["animatediff_artifact"] = {
                "video_paths": list(next_stage_paths),
                "output_paths": list(next_stage_paths),
                "manifest_paths": manifest_paths,
                "primary_path": next_stage_paths[0],
                "count": len(next_stage_paths),
                "artifacts": artifact_records,
            }
        elif stage_name == "svd_native" and (next_stage_paths or manifest_paths):
            metadata["svd_native_artifact"] = {
                "output_paths": list(next_stage_paths),
                "video_paths": video_paths,
                "gif_paths": gif_paths,
                "frame_path_count": frame_path_count,
                "manifest_paths": manifest_paths,
                "thumbnail_path": thumbnail_path,
                "primary_path": next_stage_paths[0] if next_stage_paths else None,
                "count": len(next_stage_paths),
                "artifacts": artifact_records,
            }

        if backend_results:
            video_backend_results = metadata.setdefault("video_backend_results", {})
            video_backend_results[stage_name] = {
                "backend_id": backend.backend_id,
                "count": len(backend_results),
                "output_paths": list(next_stage_paths),
                "manifest_paths": manifest_paths,
                "primary_path": next_stage_paths[0] if next_stage_paths else None,
                "artifacts": artifact_records,
            }

        return next_stage_paths

    def run_njr(
        self,
        njr: NormalizedJobRecord,
        cancel_token: CancelToken | None = None,
        log_fn: Callable[[str], None] | None = None,
        run_plan: Any | None = None,
        checkpoint_callback: Callable[[str, list[str], dict[str, Any] | None], None] | None = None,
    ) -> PipelineRunResult:
        """
        Execute the pipeline using a NormalizedJobRecord (NJR-only, v2.6+ contract).
        This is the ONLY supported production entrypoint.
        """
        if hasattr(self._pipeline, "_begin_run_metrics"):
            self._pipeline._begin_run_metrics()
        # Best-effort local cleanup before every job. Do not block queued work on
        # refresh-checkpoints; that endpoint is reserved for explicit aggressive cleanup.
        try:
            client = getattr(self._pipeline, "client", None)
            if client and hasattr(client, "free_vram"):
                logger.info("Running best-effort pre-job memory cleanup.")
                client.free_vram(unload_model=False, refresh_checkpoints=False)
        except Exception:
            pass
        # Build run plan directly from NJR
        from src.pipeline.run_plan import build_run_plan_from_njr

        plan = build_run_plan_from_njr(njr)
        
        # Prepare output dir with pack-model-vae naming structure
        # Format: output/{pack_12chars}-{model_10+5chars}-{vae_12chars}/
        # Jobs from the same pack+model+vae share folder within cache timeout
        # Learning experiments always share folder (by experiment_id)
        pack_name = getattr(njr, "prompt_pack_name", "") or getattr(njr, "job_id", "unknown")
        
        # Extract model and VAE from config
        config = njr.config or {}
        model_name = config.get("txt2img", {}).get("model") or config.get("txt2img", {}).get("sd_model_checkpoint") or njr.base_model or "unknown"
        vae_name = config.get("txt2img", {}).get("vae") or njr.vae or "none"
        
        # Build folder name components
        pack_part = self._sanitize_output_component(pack_name[:12])
        model_part = self._sanitize_output_component(self._shorten_model_name(model_name))
        vae_part = (
            self._sanitize_output_component(vae_name[:12])
            if vae_name.lower() not in ["none", "", "automatic"]
            else "none"
        )
        
        # Determine cache key based on learning context or pack+model+vae
        learning_context = getattr(njr, "learning_context", None)
        
        if learning_context:
            # Learning experiments: use experiment_id so all variants share same folder
            cache_key = f"learning_{learning_context.experiment_id}"
            folder_name = f"learning_{self._sanitize_output_component(learning_context.experiment_id)}"
            logger.debug(f"Using learning experiment folder: {cache_key}")
        else:
            # Regular jobs: folder name includes pack+model+vae for clarity
            folder_name = f"{pack_part}-{model_part}-{vae_part}"
            cache_key = folder_name
            logger.debug(f"Using pack-model-vae folder: {folder_name}")

        output_route = classify_njr_output_route(njr)
        base_output_dir = getattr(njr, "path_output_dir", None) or self._runs_base_dir
        route_root = get_output_route_root(base_output_dir, output_route, create=True)
        route_cache_key = f"{output_route}:{cache_key}"
        
        now = datetime.now()
        run_dir = self._resolve_run_dir(
            route_root=route_root,
            route_cache_key=route_cache_key,
            folder_name=folder_name,
            now=now,
        )
        run_id = run_dir.name
        # Legacy post-resolver cache branch removed; _resolve_run_dir() is canonical.
        
        # Create manifests subfolder for JSON metadata
        manifests_dir = run_dir / "manifests"
        manifests_dir.mkdir(exist_ok=True)
        
        logger.info(f"ðŸŽ¯ [OUTPUT_PATH] Images will be saved to: {run_dir.absolute()}")
        logger.info(f"ðŸŽ¯ [OUTPUT_PATH] Manifests will be saved to: {manifests_dir.absolute()}")
        
        # PR-PIPE-001: Set current job ID on executor for manifest tracking
        self._pipeline._current_job_id = njr.job_id
        try:
            from src.utils.image_metadata import canonical_json_bytes, sha256_hex

            snapshot = njr.to_queue_snapshot()
            self._pipeline._current_njr_sha256 = sha256_hex(canonical_json_bytes(snapshot))
        except Exception:
            self._pipeline._current_njr_sha256 = None
        
        # Initialize stage tracking for runtime status
        stage_chain = [stage.stage_name for stage in plan.jobs]
        self._pipeline._current_stage_chain = stage_chain
        self._pipeline._current_stage_index = 0
        
        stage_events: list[dict[str, Any]] = []
        success = False
        error = None
        variants = []
        learning_records = []
        metadata = dict(njr.config or {})
        metadata["output_dir"] = str(run_dir)
        metadata["output_route"] = output_route

        def _should_reraise_for_queue_retry(exc: Exception) -> bool:
            diagnostics = getattr(exc, "diagnostics_context", None)
            if not isinstance(diagnostics, dict):
                return False
            request_summary = diagnostics.get("request_summary") or {}
            method = str(request_summary.get("method") or "").upper()
            try:
                status = int(request_summary.get("status"))
            except (TypeError, ValueError):
                status = None
            if diagnostics.get("crash_suspected") or diagnostics.get("webui_unavailable"):
                return True
            return bool(status == 500 and method == "POST")

        def _emit_stage_checkpoint(
            stage_name: str,
            output_paths: list[str],
            *,
            stage_metadata: dict[str, Any] | None = None,
        ) -> None:
            if checkpoint_callback is None:
                return
            try:
                checkpoint_callback(stage_name, list(output_paths or []), dict(stage_metadata or {}))
            except Exception:
                logger.warning("Failed to emit stage checkpoint for %s", stage_name, exc_info=True)

        try:
            # Execute stages sequentially, passing outputs forward
            # Track all image paths through the pipeline (supports batch processing)
            current_stage_paths: list[str] = []
            last_result = None
            prompt = getattr(njr, "positive_prompt", "") or ""
            negative_prompt = getattr(njr, "negative_prompt", "") or ""
            
            # REPROCESSING SUPPORT: Check if this is a reprocessing job
            # If input_image_paths are provided, use them as starting images
            input_images = getattr(njr, "input_image_paths", None) or []
            start_stage = getattr(njr, "start_stage", None)
            if input_images:
                current_stage_paths = list(input_images)
                logger.info(f"ðŸ”„ [REPROCESS] Starting with {len(current_stage_paths)} input images: {[str(p) for p in input_images[:3]]}")
                # Verify input files exist
                for img_path in input_images:
                    if not Path(img_path).exists():
                        logger.error(f"ðŸ”„ [REPROCESS] ERROR: Input image not found: {img_path}")
                        raise FileNotFoundError(f"Reprocess input image not found: {img_path}")
                if start_stage:
                    logger.info(f"ðŸ”„ [REPROCESS] Will start from stage: {start_stage}")
            else:
                logger.info("ðŸ”µ [PIPELINE] Normal job (not reprocessing)")
            
            # Track whether we've reached the start_stage (for reprocessing mode)
            reached_start_stage = (start_stage is None)  # If no start_stage, begin immediately
            
            for stage in plan.jobs:
                # REPROCESSING: Skip stages before start_stage
                if not reached_start_stage:
                    if stage.stage_name == start_stage:
                        # We've reached the start stage, process this and all subsequent stages
                        reached_start_stage = True
                    else:
                        # Skip this stage - we haven't reached start_stage yet
                        logger.info(f"â­ï¸  [REPROCESS] Skipping stage '{stage.stage_name}' (before start_stage '{start_stage}')")
                        # Don't increment stage_index when skipping
                        continue
                
                # Increment stage index for runtime status tracking
                # (Will be reset to 0 at the start of next NJR execution)
                
                # Dispatch to the appropriate stage executor based on stage_name
                if stage.stage_name == "txt2img":
                    # Build payload for txt2img
                    image_count = max(1, int(njr.images_per_prompt or 1))
                    # Serialize txt2img API batches to reduce WebUI post-sampling finalize pressure.
                    batch_size_value = 1
                    n_iter_value = image_count
                    logger.info(
                        "ðŸ”µ [BATCH_SIZE_DEBUG] pipeline_runner: njr.images_per_prompt=%s, using batch_size=%s, n_iter=%s",
                        njr.images_per_prompt,
                        batch_size_value,
                        n_iter_value,
                    )
                    
                    # Get config from NJR - it's a flat dict, not nested under 'txt2img'
                    njr_config = njr.config or {}
                    if not isinstance(njr_config, dict):
                        njr_config = {}
                    
                    # Build payload starting with base config
                    payload = {}
                    
                    # Add core txt2img parameters
                    payload["prompt"] = stage.prompt_text
                    payload["negative_prompt"] = negative_prompt
                    payload["model"] = stage.model
                    payload["sampler_name"] = stage.sampler
                    payload["steps"] = njr.steps or 20
                    payload["cfg_scale"] = stage.cfg_scale or njr.cfg_scale or 7.5
                    payload["width"] = njr.width or 1024
                    payload["height"] = njr.height or 1024
                    payload["batch_size"] = batch_size_value
                    payload["n_iter"] = n_iter_value
                    
                    # Add scheduler if present
                    if njr.scheduler:
                        payload["scheduler"] = njr.scheduler
                    
                    # Add hires fix settings from NJR config if present
                    if njr_config.get("enable_hr"):
                        payload["enable_hr"] = njr_config["enable_hr"]
                        payload["hr_scale"] = njr_config.get("hr_scale", 2.0)
                        payload["hr_upscaler"] = njr_config.get("hr_upscaler", "Latent")
                        payload["hr_second_pass_steps"] = njr_config.get("hr_second_pass_steps", 0)
                        payload["denoising_strength"] = njr_config.get("denoising_strength", 0.7)
                        if njr_config.get("hr_resize_x"):
                            payload["hr_resize_x"] = njr_config["hr_resize_x"]
                        if njr_config.get("hr_resize_y"):
                            payload["hr_resize_y"] = njr_config["hr_resize_y"]
                        if njr_config.get("hires_use_base_model") is not None:
                            payload["hires_use_base_model"] = njr_config["hires_use_base_model"]
                        if njr_config.get("hr_checkpoint_name"):
                            payload["hr_checkpoint_name"] = njr_config["hr_checkpoint_name"]
                    
                    # Add refiner settings only if use_refiner is explicitly True
                    if njr_config.get("use_refiner") and njr_config.get("refiner_checkpoint"):
                        payload["use_refiner"] = True  # Propagate flag so executor can see it
                        payload["refiner_checkpoint"] = njr_config["refiner_checkpoint"]
                        payload["refiner_switch_at"] = njr_config.get("refiner_switch_at", 0.8)
                    
                    # Add other settings that might be in config
                    # PR-LEARN-012: Check NJR attributes if not in config (learning jobs have seed at NJR level)
                    for key in ["clip_skip", "seed", "subseed", "subseed_strength",
                                "seed_resize_from_h", "seed_resize_from_w",
                                "restore_faces", "tiling", "do_not_save_samples", "do_not_save_grid",
                                "vae"]:
                        if key in njr_config:
                            payload[key] = njr_config[key]
                        elif hasattr(njr, key) and getattr(njr, key) is not None:
                            # Fallback to NJR attribute if not in config dict
                            payload[key] = getattr(njr, key)
                        elif hasattr(njr, 'extra_metadata') and isinstance(njr.extra_metadata, dict) and key in njr.extra_metadata:
                            # Fallback to extra_metadata for learning jobs
                            payload[key] = njr.extra_metadata[key]
                    
                    # Debug logging for hires fix
                    logger.info("ðŸ”µ [HIRES_DEBUG] payload: enable_hr=%s, hr_scale=%s, hr_upscaler=%s, hr_second_pass_steps=%s, denoise=%s",
                               payload.get("enable_hr"), payload.get("hr_scale"), payload.get("hr_upscaler"),
                               payload.get("hr_second_pass_steps"), payload.get("denoising_strength"))
                    # Add pipeline section for global negative settings
                    if isinstance(njr_config, dict) and "pipeline" in njr_config:
                        payload["pipeline"] = njr_config["pipeline"]
                    
                    logger.info(
                        "ðŸ”µ [BATCH_SIZE_DEBUG] pipeline_runner: payload['batch_size']=%s, payload['n_iter']=%s",
                        payload.get('batch_size'),
                        payload.get('n_iter'),
                    )
                    # Include prompt pack row index in naming to prevent overwrites
                    prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0
                    
                    # Build safe filename with human-readable identifiers (PR-FILENAME-001)
                    from src.utils.file_io import build_safe_image_name
                    # Use 1-based indexing to match GUI display (p01 = "Prompt 1", v01 = "Variant 1")
                    base_prefix = f"{stage.stage_name}_p{prompt_row+1:02d}_v{njr.variant_index+1:02d}"
                    matrix_values = getattr(njr, 'matrix_slot_values', None) if hasattr(njr, 'matrix_slot_values') else None
                    pack_name = getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)
                    seed = payload.get("seed")
                    image_name = build_safe_image_name(
                        base_prefix=base_prefix,
                        matrix_values=matrix_values,
                        seed=seed,
                        pack_name=pack_name,
                        max_length=100  # Conservative limit for Windows paths
                    )
                    
                    result = self._pipeline.run_txt2img_stage(
                        payload["prompt"],
                        payload["negative_prompt"],
                        payload,
                        run_dir,
                        image_name=image_name,
                        cancel_token=cancel_token,
                    )
                    # Extract ALL image paths from metadata for batch processing
                    if result and "all_paths" in result:
                        current_stage_paths = result["all_paths"]
                        logger.info(f"ðŸ”µ [BATCH_PIPELINE] txt2img produced {len(current_stage_paths)} images")
                    elif result and "path" in result:
                        # Fallback for single image (backward compatibility)
                        current_stage_paths = [result["path"]]
                    else:
                        current_stage_paths = []
                    
                    # Only append non-None results to variants
                    if result is not None:
                        variants.append(result)
                    last_result = result
                    
                elif stage.stage_name == "img2img":
                    if not current_stage_paths:
                        logger.warning("img2img stage skipped: no input images from previous stage")
                        continue
                    
                    # Get stage config from njr.stage_chain
                    stage_config = next((s for s in njr.stage_chain if s.stage_type == "img2img"), None)
                    if stage_config:
                        config_dict = asdict(stage_config)
                        # Flatten 'extra' dict to top level for executor
                        if "extra" in config_dict:
                            config_dict.update(config_dict.pop("extra"))
                    else:
                        config_dict = {}

                    self._pin_stage_model_to_njr_base(
                        config_dict,
                        njr=njr,
                        stage_name="img2img",
                    )
                    
                    # Add scheduler from NJR if present
                    if njr.scheduler:
                        config_dict["scheduler"] = njr.scheduler
                    
                    # Process ALL images from previous stage through img2img
                    next_stage_paths = []
                    prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0
                    
                    # Build safe base name with human-readable identifiers (PR-FILENAME-001)
                    from src.utils.file_io import build_safe_image_name
                    from pathlib import Path as PathLib
                    # Use 1-based indexing to match GUI display
                    base_prefix = f"{stage.stage_name}_p{prompt_row+1:02d}_v{njr.variant_index+1:02d}"
                    matrix_values = getattr(njr, 'matrix_slot_values', None) if hasattr(njr, 'matrix_slot_values') else None
                    pack_name = getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)
                    
                    # For reprocess jobs, get original input filename for uniqueness
                    original_inputs = getattr(njr, 'input_image_paths', None)
                    use_original_name = original_inputs and getattr(njr, 'start_stage', None)
                    
                    for img_idx, input_path in enumerate(current_stage_paths):
                        logger.info(f"ðŸ”µ [BATCH_PIPELINE] Processing img2img for image {img_idx + 1}/{len(current_stage_paths)}")
                        # For reprocess jobs, include original filename to prevent collisions
                        if use_original_name and img_idx < len(original_inputs):
                            input_stem = PathLib(original_inputs[img_idx]).stem[:30]  # First 30 chars of original filename
                            unique_prefix = f"{base_prefix}_{input_stem}"
                        else:
                            unique_prefix = base_prefix
                        image_name = build_safe_image_name(
                            base_prefix=unique_prefix,
                            matrix_values=matrix_values,
                            seed=None,
                            batch_index=img_idx,
                            pack_name=pack_name,
                            max_length=100
                        )
                        result = self._pipeline.run_img2img_stage(
                            input_image_path=Path(input_path),
                            prompt=prompt,
                            config=config_dict,
                            output_dir=run_dir,
                            image_name=image_name,
                            cancel_token=cancel_token,
                        )
                        # Collect output path from this image
                        if result and "path" in result:
                            next_stage_paths.append(result["path"])
                        variants.append(result)
                    
                    # Update current_stage_paths for next stage
                    current_stage_paths = next_stage_paths
                    logger.info(f"ðŸ”µ [BATCH_PIPELINE] img2img completed {len(current_stage_paths)} images")
                    
                elif stage.stage_name == "adetailer":
                    if not current_stage_paths:
                        logger.warning("adetailer stage skipped: no input images from previous stage")
                        continue
                    
                    # Get stage config from njr.stage_chain
                    stage_config = next((s for s in njr.stage_chain if s.stage_type == "adetailer"), None)
                    if stage_config:
                        config_dict = asdict(stage_config)
                        # Flatten 'extra' dict to top level for executor
                        if "extra" in config_dict:
                            extra = config_dict.pop("extra")
                            # Map generic 'prompt'/'negative_prompt' to adetailer-specific keys
                            if "prompt" in extra:
                                extra["adetailer_prompt"] = extra.pop("prompt")
                            if "negative_prompt" in extra:
                                extra["adetailer_negative_prompt"] = extra.pop("negative_prompt")
                            config_dict.update(extra)
                    else:
                        config_dict = {}
                    self._pin_stage_model_to_njr_base(
                        config_dict,
                        njr=njr,
                        stage_name="adetailer",
                    )
                    # CRITICAL: Add adetailer_enabled flag that run_adetailer() expects
                    config_dict["adetailer_enabled"] = True
                    # Add scheduler from NJR if present
                    if njr.scheduler:
                        config_dict["scheduler"] = njr.scheduler
                    
                    # Debug logging
                    logger.info("ðŸ”µ [ADETAILER_CONFIG_DEBUG] config_dict keys: %s", list(config_dict.keys()))
                    logger.info("ðŸ”µ [ADETAILER_CONFIG_DEBUG] adetailer_steps=%s, adetailer_denoise=%s, adetailer_cfg=%s",
                               config_dict.get("adetailer_steps", "NOT SET"),
                               config_dict.get("adetailer_denoise", "NOT SET"),
                               config_dict.get("adetailer_cfg", "NOT SET"))
                    logger.info("ðŸ”µ [ADETAILER_PROMPT_DEBUG] adetailer_prompt='%s', adetailer_negative='%s'",
                               config_dict.get("adetailer_prompt", "(not set)")[:60],
                               config_dict.get("adetailer_negative_prompt", "(not set)")[:60])
                    
                    # Process ALL images from previous stage through adetailer
                    next_stage_paths = []
                    prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0
                    
                    # Build safe base name with human-readable identifiers (PR-FILENAME-001)
                    from src.utils.file_io import build_safe_image_name
                    from pathlib import Path as PathLib
                    # Use 1-based indexing to match GUI display
                    base_prefix = f"{stage.stage_name}_p{prompt_row+1:02d}_v{njr.variant_index+1:02d}"
                    matrix_values = getattr(njr, 'matrix_slot_values', None) if hasattr(njr, 'matrix_slot_values') else None
                    pack_name = getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)
                    
                    # For reprocess jobs, get original input filename for uniqueness
                    original_inputs = getattr(njr, 'input_image_paths', None)
                    use_original_name = original_inputs and getattr(njr, 'start_stage', None)
                    
                    for img_idx, input_path in enumerate(current_stage_paths):
                        logger.info(f"ðŸ”µ [BATCH_PIPELINE] Processing adetailer for image {img_idx + 1}/{len(current_stage_paths)}")
                        
                        # For reprocess jobs, aggressively free VRAM BEFORE each image to prevent timeout
                        if use_original_name and img_idx > 0:  # Not first image (first one is fresh)
                            try:
                                if client and hasattr(client, "free_vram"):
                                    logger.info("ðŸ§¹ Freeing VRAM BEFORE adetailer image...")
                                    client.free_vram(unload_model=True)
                                    import time
                                    time.sleep(1.0)  # Give WebUI time to stabilize
                            except Exception:
                                pass  # Non-fatal
                        
                        # For reprocess jobs, include original filename to prevent collisions
                        if use_original_name and img_idx < len(original_inputs):
                            input_stem = PathLib(original_inputs[img_idx]).stem[:30]  # First 30 chars of original filename
                            unique_prefix = f"{base_prefix}_{input_stem}"
                        else:
                            unique_prefix = base_prefix
                        image_name = build_safe_image_name(
                            base_prefix=unique_prefix,
                            matrix_values=matrix_values,
                            seed=None,
                            batch_index=img_idx,
                            pack_name=pack_name,
                            max_length=100
                        )
                        result = self._pipeline.run_adetailer_stage(
                            input_image_path=Path(input_path),
                            config=config_dict,
                            output_dir=run_dir,
                            image_name=image_name,
                            prompt=prompt,
                            negative_prompt=negative_prompt,
                            cancel_token=cancel_token,
                        )
                        # Collect output path from this image
                        if result and "path" in result:
                            logger.info(f"âœ… [ADETAILER_OUTPUT] Saved: {result['path']}")
                            next_stage_paths.append(result["path"])
                        else:
                            logger.warning(f"âŒ [ADETAILER_OUTPUT] No output from image {img_idx}")
                        variants.append(result)
                        

                        # For reprocess jobs, aggressively free VRAM after each image to prevent timeout
                        if use_original_name and img_idx < len(current_stage_paths) - 1:  # Not last image
                            try:
                                if client and hasattr(client, "free_vram"):
                                    logger.info("ðŸ§¹ Freeing VRAM between adetailer images...")
                                    client.free_vram(unload_model=True)
                            except Exception:
                                pass  # Non-fatal
                    
                    # Update current_stage_paths for next stage
                    current_stage_paths = next_stage_paths
                    logger.info(f"ðŸ”µ [BATCH_PIPELINE] adetailer completed {len(current_stage_paths)} images")
                    
                elif stage.stage_name == "upscale":
                    if not current_stage_paths:
                        logger.warning("upscale stage skipped: no input images from previous stage")
                        continue
                    
                    # Get stage config from njr.stage_chain
                    stage_config = next((s for s in njr.stage_chain if s.stage_type == "upscale"), None)
                    if stage_config:
                        config_dict = asdict(stage_config)
                        # Flatten 'extra' dict to top level for executor
                        if "extra" in config_dict:
                            logger.info(f"ðŸ”µ [UPSCALE_CONFIG_DEBUG] extra dict before flatten: {config_dict['extra']}")
                            config_dict.update(config_dict.pop("extra"))
                            logger.info(f"ðŸ”µ [UPSCALE_CONFIG_DEBUG] config_dict after flatten - upscaler={config_dict.get('upscaler')}")
                    else:
                        config_dict = {}
                        logger.warning("[UPSCALE_CONFIG_DEBUG] No upscale stage config found in stage_chain")

                    self._pin_stage_model_to_njr_base(
                        config_dict,
                        njr=njr,
                        stage_name="upscale",
                    )
                    
                    # Process ALL images from previous stage through upscaler
                    next_stage_paths = []
                    prompt_row = getattr(njr, "prompt_pack_row_index", 0) or 0
                    
                    # Build safe base name with human-readable identifiers (PR-FILENAME-001)
                    from src.utils.file_io import build_safe_image_name
                    from pathlib import Path as PathLib
                    # Use 1-based indexing to match GUI display
                    base_prefix = f"{stage.stage_name}_p{prompt_row+1:02d}_v{njr.variant_index+1:02d}"
                    matrix_values = getattr(njr, 'matrix_slot_values', None) if hasattr(njr, 'matrix_slot_values') else None
                    pack_name = getattr(njr, "prompt_pack_name", None) or getattr(njr, "pack_name", None)
                    
                    # For reprocess jobs, get original input filename for uniqueness
                    original_inputs = getattr(njr, 'input_image_paths', None)
                    use_original_name = original_inputs and getattr(njr, 'start_stage', None)
                    
                    for img_idx, input_path in enumerate(current_stage_paths):
                        logger.info(f"ðŸ”µ [BATCH_PIPELINE] Processing upscale for image {img_idx + 1}/{len(current_stage_paths)}")
                        
                        # For reprocess jobs, aggressively free VRAM BEFORE each image to prevent timeout
                        if use_original_name and img_idx > 0:  # Not first image
                            try:
                                if client and hasattr(client, "free_vram"):
                                    logger.info("ðŸ§¹ Freeing VRAM BEFORE upscale image...")
                                    client.free_vram(unload_model=True)
                                    import time
                                    time.sleep(1.0)  # Give WebUI time to stabilize
                            except Exception:
                                pass  # Non-fatal
                        
                        # For reprocess jobs, include original filename to prevent collisions
                        if use_original_name and img_idx < len(original_inputs):
                            input_stem = PathLib(original_inputs[img_idx]).stem[:30]  # First 30 chars of original filename
                            unique_prefix = f"{base_prefix}_{input_stem}"
                        else:
                            unique_prefix = base_prefix
                        image_name = build_safe_image_name(
                            base_prefix=unique_prefix,
                            matrix_values=matrix_values,
                            seed=None,
                            batch_index=img_idx,
                            pack_name=pack_name,
                            max_length=100
                        )
                        result = self._pipeline.run_upscale_stage(
                            input_image_path=Path(input_path),
                            config=config_dict,
                            output_dir=run_dir,
                            image_name=image_name,
                            cancel_token=cancel_token,
                        )
                        # Collect output path from this image
                        if result and "path" in result:
                            logger.info(f"âœ… [UPSCALE_OUTPUT] Saved: {result['path']}")
                            next_stage_paths.append(result["path"])
                        else:
                            logger.warning(f"âŒ [UPSCALE_OUTPUT] No output from image {img_idx}")
                        variants.append(result)
                        
                    # Update current_stage_paths for next stage
                    current_stage_paths = next_stage_paths
                    logger.info(f"ðŸ”µ [BATCH_PIPELINE] upscale completed {len(current_stage_paths)} images")
                    
                elif self._video_backends.is_registered_stage(stage.stage_name):
                    if not current_stage_paths:
                        logger.warning("%s stage skipped: no input images from previous stage", stage.stage_name)
                        continue

                    current_stage_paths = self._execute_video_stage(
                        stage_name=stage.stage_name,
                        njr=njr,
                        current_stage_paths=current_stage_paths,
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        run_dir=run_dir,
                        cancel_token=cancel_token,
                        variants=variants,
                        metadata=metadata,
                    )
                    logger.info(
                        "[BATCH_PIPELINE] %s completed %d output artifact(s)",
                        stage.stage_name,
                        len(current_stage_paths),
                    )

                else:
                    logger.warning(f"Unknown stage type: {stage.stage_name}, skipping")
                    continue

                _emit_stage_checkpoint(
                    stage.stage_name,
                    current_stage_paths,
                    stage_metadata={"image_count": len(current_stage_paths)},
                )
                
                # Record stage event with actual image count
                stage_events.append(
                    {
                        "stage": stage.stage_name,
                        "phase": "exit",
                        "image_index": len(current_stage_paths),
                        "total_images": len(current_stage_paths),
                        "cancelled": False,
                    }
                )
                
                # Increment stage index for next iteration
                self._pipeline._current_stage_index += 1
                
            # A pipeline only succeeds if the final enabled stage produced durable outputs.
            success = bool(current_stage_paths)
            if not success and error is None:
                error = "No images were generated successfully"
        except Exception as exc:
            error = str(exc)
            logger.error(f"âŒ Pipeline execution failed: {exc}", exc_info=True)
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
            if checkpoint_callback is not None and _should_reraise_for_queue_retry(exc):
                raise
        finally:
            # PR-PIPE-001: Clear job ID from executor after execution
            self._pipeline._current_job_id = None
            self._pipeline._current_njr_sha256 = None
            
        efficiency_metrics: dict[str, Any] = {}
        if hasattr(self._pipeline, "get_run_efficiency_metrics"):
            try:
                efficiency_metrics = self._pipeline.get_run_efficiency_metrics(len(variants))
            except Exception:
                efficiency_metrics = {}
        if efficiency_metrics:
            metadata["efficiency_metrics"] = efficiency_metrics

        variants = canonicalize_variant_entries(variants)

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
        logger.info(f"ðŸ” DEBUG: PipelineRunResult created with success={success}, error={error}, variants={len(variants)}")
        result_dict = result.to_dict()
        logger.info(f"ðŸ” DEBUG: to_dict() success={result_dict.get('success')}, error={result_dict.get('error')}")
        try:
            njr.output_paths = list(current_stage_paths or [])
            artifact_thumbnail = (
                (metadata.get("svd_native_artifact") or {}).get("thumbnail_path")
                or (metadata.get("animatediff_artifact") or {}).get("thumbnail_path")
            )
            njr.thumbnail_path = artifact_thumbnail or (njr.output_paths[-1] if njr.output_paths else None)
        except Exception:
            pass
        try:
            # Build stage_outputs from variants (each variant is a dict with path, config, etc.)
            stage_outputs = []
            for variant in variants:
                if variant and isinstance(variant, dict):
                    stage_outputs.append(dict(variant))
            
            # For learning jobs, include experiment metadata and base config
            learning_context = getattr(njr, "learning_context", None)
            packs_list = []
            enhanced_metadata = dict(metadata)  # Copy base metadata
            
            if learning_context:
                packs_list = [{
                    "type": "learning_experiment",
                    "experiment_name": learning_context.experiment_name,
                    "variable": learning_context.variable_under_test,
                    "variant_count": len(stage_outputs),
                }]
                # Add base configuration to metadata
                enhanced_metadata.update({
                    "prompt": getattr(njr, "positive_prompt", ""),
                    "negative_prompt": getattr(njr, "negative_prompt", ""),
                    "model": getattr(njr, "base_model", ""),
                    "sampler": getattr(njr, "sampler_name", ""),
                    "scheduler": getattr(njr, "scheduler", ""),
                    "steps": getattr(njr, "steps", 0),
                    "width": getattr(njr, "width", 0),
                    "height": getattr(njr, "height", 0),
                    "learning_experiment": learning_context.experiment_name,
                    "learning_variable": learning_context.variable_under_test,
                })
            
            write_run_metadata(
                run_id,
                enhanced_metadata,
                packs=packs_list,
                stage_outputs=stage_outputs,
                base_dir=route_root
            )
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
        status_callback: Callable[[dict[str, Any]], None] | None = None,
        video_backend_registry: VideoBackendRegistry | None = None,
    ) -> None:
        self._api_client = api_client
        self._structured_logger = structured_logger
        self._config_manager = config_manager or ConfigManager()
        self._pipeline = Pipeline(api_client, structured_logger, status_callback=status_callback)
        self._learning_record_writer = learning_record_writer
        self._learning_record_callback = on_learning_record
        self._last_run_result: PipelineRunResult | None = None
        self._runs_base_dir = runs_base_dir or "output"
        self._learning_enabled = bool(learning_enabled)
        self._sequencer = sequencer or StageSequencer()
        self._video_backends = video_backend_registry or build_default_video_backend_registry()

    def _ensure_not_cancelled(self, cancel_token: CancelToken | None, context: str) -> None:
        if (
            cancel_token
            and getattr(cancel_token, "is_cancelled", None)
            and cancel_token.is_cancelled()
        ):
            raise CancellationError(f"Cancelled during {context}")

    def _is_image_producing_stage_type(self, stage_type: str) -> bool:
        return stage_type in {
            StageTypeEnum.TXT2IMG.value,
            StageTypeEnum.IMG2IMG.value,
            StageTypeEnum.UPSCALE.value,
            StageTypeEnum.ADETAILER.value,
        }

    def _validate_stage_plan(self, plan: StageExecutionPlan) -> None:
        stages = plan.stages or []
        if not stages:
            raise ValueError("Pipeline plan contains no enabled stages.")
        adetailers = [
            stage for stage in stages if stage.stage_type == StageTypeEnum.ADETAILER.value
        ]
        animatediffs = [
            stage for stage in stages if stage.stage_type == StageTypeEnum.ANIMATEDIFF.value
        ]
        svd_native = [
            stage for stage in stages if stage.stage_type == StageTypeEnum.SVD_NATIVE.value
        ]
        if len(adetailers) > 1:
            raise ValueError("Multiple ADetailer stages are not supported.")
        if len(animatediffs) > 1:
            raise ValueError("Multiple AnimateDiff stages are not supported.")
        if len(svd_native) > 1:
            raise ValueError("Multiple SVD Native stages are not supported.")
        if animatediffs and stages[-1].stage_type != StageTypeEnum.ANIMATEDIFF.value:
            raise ValueError("AnimateDiff stage must be the final stage.")
        if svd_native and stages[-1].stage_type != StageTypeEnum.SVD_NATIVE.value:
            raise ValueError("SVD Native stage must be the final stage.")
        if adetailers and not any(
            self._is_image_producing_stage_type(stage.stage_type)
            for stage in stages
            if stage.stage_type != StageTypeEnum.ADETAILER.value
        ):
            raise ValueError("ADetailer stage requires a preceding generation stage.")
        if adetailers:
            first_adetailer_index = next(
                i for i, stage in enumerate(stages) if stage.stage_type == StageTypeEnum.ADETAILER.value
            )
            trailing_img2img = any(
                stage.stage_type == StageTypeEnum.IMG2IMG.value for stage in stages[first_adetailer_index + 1 :]
            )
            if trailing_img2img:
                raise ValueError("ADetailer stage must not run before img2img.")
            trailing_non_animatediff = [
                stage.stage_type
                for stage in stages[first_adetailer_index + 1 :]
                if stage.stage_type != StageTypeEnum.ANIMATEDIFF.value
            ]
            if any(stage_type != StageTypeEnum.UPSCALE.value for stage_type in trailing_non_animatediff):
                raise ValueError(
                    "Only upscale and animatediff stages may follow ADetailer."
                )
        if animatediffs and not any(
            self._is_image_producing_stage_type(stage.stage_type)
            for stage in stages
            if stage.stage_type != StageTypeEnum.ANIMATEDIFF.value
        ):
            raise ValueError("AnimateDiff stage requires a preceding image-producing stage.")
        if svd_native and not any(
            self._is_image_producing_stage_type(stage.stage_type)
            for stage in stages
            if stage.stage_type != StageTypeEnum.SVD_NATIVE.value
        ):
            raise ValueError("SVD Native stage requires a preceding image-producing stage.")

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
                negative_prompt=payload.get("negative_prompt"),
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
        img2img_val = base.get("pipeline", {}).get("img2img_enabled")
        img2img.setdefault("enabled", bool(img2img_val) if img2img_val is not None else False)

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
        
        # PR-LEARN-012: Override seed parameters from config
        payload["seed"] = config.seed
        payload["subseed"] = getattr(config, "subseed", -1)
        payload["subseed_strength"] = getattr(config, "subseed_strength", 0.0)
        payload["clip_skip"] = getattr(config, "clip_skip", 2)

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
        variants = canonicalize_variant_entries(self.variants)
        return {
            "run_id": self.run_id,
            "success": self.success,
            "error": self.error,
            "output_dir": self.metadata.get("output_dir"),
            "variants": [dict(variant) for variant in variants if variant is not None],
            "learning_records": [asdict(record) for record in (self.learning_records or []) if record is not None],
            "randomizer_mode": self.randomizer_mode,
            "randomizer_plan_size": self.randomizer_plan_size,
            "metadata": dict(self.metadata or {}),
            "stage_plan": self._serialize_stage_plan(),
            "stage_events": [dict(event) for event in (self.stage_events or []) if event is not None],
        }

    def _serialize_stage_plan(self) -> dict[str, Any] | None:
        if not self.stage_plan:
            return None
        # Handle both StageExecutionPlan and RunPlan
        if hasattr(self.stage_plan, 'run_id'):
            # StageExecutionPlan
            return {
                "run_id": self.stage_plan.run_id,
                "stage_types": self.stage_plan.get_stage_types(),
                "one_click_action": self.stage_plan.one_click_action,
            }
        else:
            # RunPlan
            return {
                "total_jobs": getattr(self.stage_plan, "total_jobs", 0),
                "total_images": getattr(self.stage_plan, "total_images", 0),
                "enabled_stages": getattr(self.stage_plan, "enabled_stages", []),
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
            variants=canonicalize_variant_entries(data.get("variants") or []),
            learning_records=learning_records,
            randomizer_mode=str(data.get("randomizer_mode") or ""),
            randomizer_plan_size=int(data.get("randomizer_plan_size") or 0),
            metadata=_merge_output_dir_into_metadata(data),
            stage_plan=None,
            stage_events=stage_events,
        )


def normalize_run_result(value: Any, default_run_id: str | None = None) -> dict[str, Any]:
    """
    Return a canonical PipelineRunResult dict for any run output.
    Ensures all execution metadata (including run_mode, source) is present in the metadata dict.
    """
    if isinstance(value, PipelineRunResult):
        try:
            return value.to_dict()
        except Exception as e:
            logger.error(f"Failed to convert PipelineRunResult to dict: {e}")
            
    if isinstance(value, Mapping):
        try:
            mapping = dict(value)
            if "success" not in mapping:
                return {
                    "run_id": str(mapping.get("run_id") or default_run_id or ""),
                    "success": None,
                    "error": mapping.get("error"),
                    "output_dir": mapping.get("output_dir"),
                    "variants": canonicalize_variant_entries(mapping.get("variants") or []),
                    "learning_records": [dict(record) for record in mapping.get("learning_records") or []],
                    "randomizer_mode": str(mapping.get("randomizer_mode") or ""),
                    "randomizer_plan_size": int(mapping.get("randomizer_plan_size") or 0),
                    "metadata": _merge_output_dir_into_metadata(mapping),
                    "stage_plan": mapping.get("stage_plan"),
                    "stage_events": [dict(event) for event in mapping.get("stage_events") or []],
                }
            return PipelineRunResult.from_dict(mapping, default_run_id=default_run_id).to_dict()
        except Exception as e:
            logger.error(f"Failed to normalize Mapping to PipelineRunResult: {e}")
            
    # Fallback for any case that fails
    fallback = PipelineRunResult(
        run_id=default_run_id or "",
        success=False,
        error=str(value) if value is not None else "Unknown error in normalize_run_result",
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
