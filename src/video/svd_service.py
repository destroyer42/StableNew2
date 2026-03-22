"""Native Diffusers-backed Stable Video Diffusion service."""

from __future__ import annotations

import gc
import importlib
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from src.video.svd_config import SVDInferenceConfig
from src.video.svd_errors import SVDInferenceError, SVDInputError, SVDModelLoadError
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
    ) -> list[Image.Image]:
        path = Path(prepared_image_path)
        if not path.exists():
            raise SVDInputError(f"Prepared SVD image does not exist: {path}")

        available, reason = self.is_available()
        if not available:
            raise SVDModelLoadError(reason or "Diffusers SVD runtime is unavailable")

        pipeline = self._get_pipeline(config)

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
        try:
            result = pipeline(
                image,
                decode_chunk_size=config.decode_chunk_size,
                motion_bucket_id=config.motion_bucket_id,
                noise_aug_strength=config.noise_aug_strength,
                num_frames=config.num_frames,
                num_inference_steps=config.num_inference_steps,
                min_guidance_scale=config.min_guidance_scale,
                max_guidance_scale=config.max_guidance_scale,
                generator=generator,
            )
            frames = getattr(result, "frames", result)
            if isinstance(frames, list) and frames and isinstance(frames[0], list):
                frames = frames[0]
            if isinstance(frames, tuple):
                frames = list(frames)
            if not isinstance(frames, list) or not frames:
                raise SVDInferenceError("SVD returned no frames")
            raw_frames = frames
            return [frame.convert("RGB") for frame in raw_frames]
        except Exception as exc:
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
                logger.warning(
                    "[SVD] Failed to load %s from local cache %s; retrying remote refresh: %s",
                    config.model_id,
                    cache_dir,
                    exc,
                )
            else:
                return self._initialize_pipeline_device(pipeline, torch=torch, config=config)

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
