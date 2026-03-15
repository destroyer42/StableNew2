"""Native Diffusers-backed Stable Video Diffusion service."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from PIL import Image

from src.video.svd_config import SVDInferenceConfig
from src.video.svd_errors import SVDInferenceError, SVDInputError, SVDModelLoadError


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
        if model_id is None:
            self._pipeline_cache.clear()
            return
        for key in list(self._pipeline_cache.keys()):
            if key[0] == model_id:
                self._pipeline_cache.pop(key, None)

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
        try:
            image = Image.open(path).convert("RGB")
        except Exception as exc:
            raise SVDInputError(f"Failed to open prepared SVD image: {exc}") from exc

        torch = importlib.import_module("torch")
        generator = None
        if config.seed is not None:
            generator = torch.Generator(device="cpu").manual_seed(int(config.seed))

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
        except Exception as exc:
            raise SVDInferenceError(f"SVD inference failed: {exc}") from exc

        frames = getattr(result, "frames", result)
        if isinstance(frames, list) and frames and isinstance(frames[0], list):
            frames = frames[0]
        if not isinstance(frames, list) or not frames:
            raise SVDInferenceError("SVD returned no frames")
        return [frame.convert("RGB") for frame in frames]

    def _get_pipeline(self, config: SVDInferenceConfig) -> Any:
        cache_key = (
            config.model_id,
            config.torch_dtype,
            config.variant,
            config.cache_dir or self._cache_dir,
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
        kwargs: dict[str, Any] = {
            "torch_dtype": dtype,
            "local_files_only": config.local_files_only,
        }
        cache_dir = config.cache_dir or self._cache_dir
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        if config.variant:
            kwargs["variant"] = config.variant
        try:
            pipeline = pipeline_cls.from_pretrained(config.model_id, **kwargs)
        except Exception as exc:
            raise SVDModelLoadError(f"Failed to load SVD model '{config.model_id}': {exc}") from exc

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
