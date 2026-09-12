"""Native Diffusers-backed Stable Video Diffusion service."""

from __future__ import annotations

import gc
import importlib
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from src.controller.runtime_state import CancellationError, CancelToken
from src.video.svd_config import SVDInferenceConfig
from src.video.svd_errors import (
    SVDInferenceError,
    SVDInputError,
    SVDModelLoadError,
    SVDOutOfMemoryError,
)
from src.video.svd_models import is_svd_model_cached, resolve_svd_cache_dir

logger = logging.getLogger(__name__)


class SVDService:
    """Loads and caches native SVD pipelines and generates frames."""

    _pipeline_cache: dict[tuple[str, str, str | None, str | None], Any] = {}

    def __init__(self, *, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir

    def is_available(self) -> tuple[bool, str | None]:
        try:
            importlib.import_module("torch")
            diffusers = importlib.import_module("diffusers")
            getattr(diffusers, "StableVideoDiffusionPipeline")
        except Exception as exc:
            return False, self._format_dependency_error(exc)
        return True, None

    def clear_model_cache(self, model_id: str | None = None) -> None:
        pipelines: list[Any] = []
        if model_id is None:
            pipelines = list(self._pipeline_cache.values())
            self._pipeline_cache.clear()
        else:
            for key in list(self._pipeline_cache.keys()):
                if key[0] == model_id:
                    pipeline = self._pipeline_cache.pop(key, None)
                    if pipeline is not None:
                        pipelines.append(pipeline)
        self._release_pipelines(pipelines)

    def generate_frames(
        self,
        *,
        prepared_image_path: str | Path,
        config: SVDInferenceConfig,
        cancel_token: CancelToken | None = None,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[Image.Image]:
        self._ensure_not_cancelled(cancel_token, "native SVD inference setup")
        path = Path(prepared_image_path)
        if not path.exists():
            raise SVDInputError(f"Prepared SVD image does not exist: {path}")

        available, reason = self.is_available()
        if not available:
            raise SVDModelLoadError(reason or "Diffusers SVD runtime is unavailable")

        pipeline = self.prepare_runtime(
            config=config,
            cancel_token=cancel_token,
            status_callback=status_callback,
        )

        torch = importlib.import_module("torch")
        generator = None
        if config.seed is not None:
            generator = torch.Generator(device="cpu").manual_seed(int(config.seed))

        image: Image.Image | None = None
        try:
            with Image.open(path) as loaded_image:
                image = loaded_image.convert("RGB")
        except Exception as exc:
            raise SVDInputError(f"Failed to open prepared SVD image: {exc}") from exc

        result: Any | None = None
        raw_frames: list[Image.Image] = []
        converted_frames: list[Image.Image] = []
        try:
            self._ensure_not_cancelled(cancel_token, "native SVD preprocessing")
            prepared_width, prepared_height = image.size
            call_kwargs: dict[str, Any] = {
                "decode_chunk_size": config.decode_chunk_size,
                "height": prepared_height,
                "motion_bucket_id": config.motion_bucket_id,
                "noise_aug_strength": config.noise_aug_strength,
                "num_frames": config.num_frames,
                "num_inference_steps": config.num_inference_steps,
                "min_guidance_scale": config.min_guidance_scale,
                "max_guidance_scale": config.max_guidance_scale,
                "width": prepared_width,
                "generator": generator,
            }
            if self._supports_step_callback(pipeline):
                call_kwargs["callback_on_step_end"] = self._build_step_callback(
                    cancel_token=cancel_token,
                    status_callback=status_callback,
                    total_steps=config.num_inference_steps,
                )
            result = pipeline(
                image,
                **call_kwargs,
            )
            self._ensure_not_cancelled(cancel_token, "native SVD inference")
            frames = getattr(result, "frames", result)
            if isinstance(frames, list) and frames and isinstance(frames[0], list):
                frames = frames[0]
            if isinstance(frames, tuple):
                frames = list(frames)
            if not isinstance(frames, list) or not frames:
                raise SVDInferenceError("SVD returned no frames")
            raw_frames = frames
            converted_frames = [frame.convert("RGB") for frame in raw_frames]
            self._validate_frame_geometry(
                converted_frames,
                expected_width=prepared_width,
                expected_height=prepared_height,
                model_id=config.model_id,
            )
            return converted_frames
        except CancellationError:
            raise
        except SVDInferenceError:
            self._close_images(converted_frames)
            raise
        except Exception as exc:
            self._close_images(converted_frames)
            if self._is_cuda_out_of_memory(exc):
                raise SVDOutOfMemoryError(self._format_oom_error(config, exc)) from exc
            raise SVDInferenceError(f"SVD inference failed: {exc}") from exc
        finally:
            if image is not None:
                try:
                    image.close()
                except Exception:
                    pass
            self._close_images(raw_frames)
            result = None
            generator = None
            self._release_runtime_memory()

    @staticmethod
    def _validate_frame_geometry(
        frames: list[Image.Image],
        *,
        expected_width: int,
        expected_height: int,
        model_id: str,
    ) -> None:
        actual_sizes = [tuple(int(value) for value in frame.size) for frame in frames]
        expected = (int(expected_width), int(expected_height))
        if not actual_sizes or any(size != expected for size in actual_sizes):
            actual = ", ".join(f"{width}x{height}" for width, height in actual_sizes) or "none"
            raise SVDInferenceError(
                "SVD inference geometry mismatch: "
                f"expected {expected[0]}x{expected[1]}, actual {actual}, model {model_id}."
            )

    def prepare_runtime(
        self,
        *,
        config: SVDInferenceConfig,
        cancel_token: CancelToken | None = None,
        status_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        """Load or reuse the model at a cancellable boundary before preprocessing."""
        self._ensure_not_cancelled(cancel_token, "native SVD model loading")
        self._emit_status(status_callback, stage_detail="loading_model")
        pipeline = self._get_pipeline(config)
        self._ensure_not_cancelled(cancel_token, "native SVD model loading")
        return pipeline

    @staticmethod
    def _ensure_not_cancelled(cancel_token: CancelToken | None, context: str) -> None:
        if cancel_token is not None:
            cancel_token.check_cancelled()

    @staticmethod
    def _emit_status(
        callback: Callable[[dict[str, Any]], None] | None,
        **status: Any,
    ) -> None:
        if callback is None:
            return
        callback(status)

    @staticmethod
    def _supports_step_callback(pipeline: Any) -> bool:
        """Use only Diffusers' documented callback_on_step_end parameter when present."""
        try:
            target = pipeline.__call__ if callable(pipeline) else pipeline
            signature = inspect.signature(target)
        except (TypeError, ValueError):
            return False
        return "callback_on_step_end" in signature.parameters

    def _build_step_callback(
        self,
        *,
        cancel_token: CancelToken | None,
        status_callback: Callable[[dict[str, Any]], None] | None,
        total_steps: int,
    ) -> Callable[[Any, int, Any, dict[str, Any]], dict[str, Any]]:
        def _on_step_end(
            _pipeline: Any,
            step_index: int,
            _timestep: Any,
            callback_kwargs: dict[str, Any],
        ) -> dict[str, Any]:
            self._ensure_not_cancelled(cancel_token, "native SVD denoising")
            completed_step = min(max(0, int(step_index) + 1), total_steps)
            self._emit_status(
                status_callback,
                stage_detail="inference",
                progress=(completed_step / total_steps) if total_steps else 0.0,
                current_step=completed_step,
                total_steps=total_steps,
            )
            return callback_kwargs

        return _on_step_end

    @staticmethod
    def _is_cuda_out_of_memory(exc: Exception) -> bool:
        try:
            torch = importlib.import_module("torch")
        except Exception:
            torch = None
        oom_types: list[type[BaseException]] = []
        for owner in (torch, getattr(torch, "cuda", None) if torch is not None else None):
            candidate = getattr(owner, "OutOfMemoryError", None)
            if isinstance(candidate, type) and issubclass(candidate, BaseException):
                oom_types.append(candidate)
        if oom_types and isinstance(exc, tuple(oom_types)):
            return True
        message = str(exc).lower()
        return "cuda out of memory" in message or "cuda error: out of memory" in message

    @staticmethod
    def _format_oom_error(config: SVDInferenceConfig, exc: Exception) -> str:
        return (
            "Native SVD exhausted GPU memory. Effective config: "
            f"model={config.model_id}, num_frames={config.num_frames}, "
            f"num_inference_steps={config.num_inference_steps}, "
            f"decode_chunk_size={config.decode_chunk_size}, dtype={config.torch_dtype}, "
            f"cpu_offload={config.cpu_offload}, forward_chunking={config.forward_chunking}. "
            "StableNew did not automatically rerun or downgrade this job. "
            "Use the 12 GB conservative baseline when retrying explicitly. "
            f"Original error: {exc}"
        )

    def _get_pipeline(self, config: SVDInferenceConfig) -> Any:
        resolved_cache_dir = str(self._resolve_cache_dir(config))
        cache_key = (
            config.model_id,
            config.torch_dtype,
            config.variant,
            resolved_cache_dir,
        )
        cached = self._pipeline_cache.get(cache_key)
        if cached is not None:
            return cached
        pipeline = self._load_pipeline(config)
        self._pipeline_cache[cache_key] = pipeline
        return pipeline

    def _load_pipeline(self, config: SVDInferenceConfig) -> Any:
        try:
            torch = importlib.import_module("torch")
            diffusers = importlib.import_module("diffusers")
            pipeline_cls = getattr(diffusers, "StableVideoDiffusionPipeline")
        except Exception as exc:
            raise SVDModelLoadError(self._format_dependency_error(exc)) from exc

        dtype = self._resolve_torch_dtype(torch, config.torch_dtype)
        cache_dir = self._resolve_cache_dir(config)
        kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "cache_dir": str(cache_dir),
        }
        if config.variant:
            kwargs["variant"] = config.variant

        cached_snapshot = is_svd_model_cached(config.model_id, cache_dir=cache_dir)
        if config.local_files_only and not cached_snapshot:
            raise SVDModelLoadError(
                f"SVD local-only mode requires a complete cached model '{config.model_id}' "
                f"at '{cache_dir}'. Download the model into this cache first, or deliberately "
                "disable local-only mode to permit online acquisition."
            )

        local_error: Exception | None = None
        if cached_snapshot:
            try:
                pipeline = pipeline_cls.from_pretrained(
                    config.model_id,
                    local_files_only=True,
                    **kwargs,
                )
            except Exception as exc:
                local_error = exc
                if config.local_files_only:
                    raise SVDModelLoadError(
                        f"Failed to load SVD model '{config.model_id}' from the local-only cache "
                        f"at '{cache_dir}': {exc}. Repair or replace the local cache, or deliberately "
                        "disable local-only mode to permit online acquisition."
                    ) from exc
                logger.warning(
                    "[SVD] Failed to load %s from local cache %s; retrying remote refresh: %s",
                    config.model_id,
                    cache_dir,
                    exc,
                )
            else:
                return self._initialize_pipeline_device(pipeline, torch=torch, config=config)

        # Reaching the remote load is an explicit opt-in through local_files_only=False.
        try:
            pipeline = pipeline_cls.from_pretrained(
                config.model_id,
                local_files_only=False,
                **kwargs,
            )
        except Exception as exc:
            if local_error is not None:
                raise SVDModelLoadError(
                    f"Failed to load SVD model '{config.model_id}' from cache at '{cache_dir}' "
                    f"and remote refresh also failed. Cache error: {local_error}. Remote error: {exc}"
                ) from exc
            raise SVDModelLoadError(f"Failed to load SVD model '{config.model_id}': {exc}") from exc

        return self._initialize_pipeline_device(pipeline, torch=torch, config=config)

    def _initialize_pipeline_device(self, pipeline: Any, *, torch: Any, config: SVDInferenceConfig) -> Any:
        try:
            if config.cpu_offload and hasattr(pipeline, "enable_model_cpu_offload"):
                pipeline.enable_model_cpu_offload()
            elif hasattr(torch, "cuda") and torch.cuda.is_available():
                pipeline.to("cuda")
            else:
                pipeline.to("cpu")
        except Exception as exc:
            raise SVDModelLoadError(f"Failed to initialize SVD device placement: {exc}") from exc

        if config.forward_chunking:
            unet = getattr(pipeline, "unet", None)
            if unet is not None and hasattr(unet, "enable_forward_chunking"):
                try:
                    unet.enable_forward_chunking()
                except Exception:
                    pass

        return pipeline

    def _resolve_cache_dir(self, config: SVDInferenceConfig) -> Path:
        cache_dir = resolve_svd_cache_dir(config.cache_dir or self._cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @classmethod
    def _release_pipelines(cls, pipelines: list[Any]) -> None:
        for pipeline in pipelines:
            cls._release_pipeline(pipeline)
        cls._release_runtime_memory()

    @staticmethod
    def _release_pipeline(pipeline: Any) -> None:
        if pipeline is None:
            return
        maybe_free_hooks = getattr(pipeline, "maybe_free_model_hooks", None)
        if callable(maybe_free_hooks):
            try:
                maybe_free_hooks()
            except Exception:
                pass
        remove_all_hooks = getattr(pipeline, "remove_all_hooks", None)
        if callable(remove_all_hooks):
            try:
                remove_all_hooks()
            except Exception:
                pass
        move_to = getattr(pipeline, "to", None)
        if callable(move_to):
            try:
                move_to("cpu")
            except Exception:
                pass

    @staticmethod
    def _close_images(images: list[Image.Image]) -> None:
        for image in images:
            close = getattr(image, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    @staticmethod
    def _release_runtime_memory() -> None:
        gc.collect()
        try:
            torch = importlib.import_module("torch")
        except Exception:
            return
        cuda = getattr(torch, "cuda", None)
        if cuda is None:
            return
        try:
            if not cuda.is_available():
                return
        except Exception:
            return
        empty_cache = getattr(cuda, "empty_cache", None)
        if callable(empty_cache):
            try:
                empty_cache()
            except Exception:
                pass
        ipc_collect = getattr(cuda, "ipc_collect", None)
        if callable(ipc_collect):
            try:
                ipc_collect()
            except Exception:
                pass

    @staticmethod
    def _resolve_torch_dtype(torch_module: Any, torch_dtype: str) -> Any:
        mapping = {
            "float16": getattr(torch_module, "float16"),
            "bfloat16": getattr(torch_module, "bfloat16"),
            "float32": getattr(torch_module, "float32"),
        }
        try:
            return mapping[torch_dtype]
        except KeyError as exc:
            raise SVDModelLoadError(f"Unsupported torch dtype: {torch_dtype}") from exc

    @staticmethod
    def _format_dependency_error(exc: Exception) -> str:
        if isinstance(exc, ModuleNotFoundError):
            missing = getattr(exc, "name", None) or str(exc)
            return (
                "Native SVD dependencies are not installed in the active Python environment "
                f"(missing module: {missing}). Install them with "
                "`python -m pip install -r requirements-svd.txt` "
                "or `pip install .[svd]`."
            )
        return (
            "Native SVD dependencies are unavailable. Install them with "
            "`python -m pip install -r requirements-svd.txt` "
            f"and retry. Original error: {exc}"
        )
