"""Capability discovery for native SVD postprocess helpers."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path

from src.video.restoration.runtime import POSTPROCESS_INSTALL_HINT
from src.video.restoration.upscale_models import SOURCE_MODEL_PATH, requests_two_times
from src.video.rife_runtime import default_rife_multiplier, find_rife_executable
from src.video.svd_config import SVDConfig
from src.video.svd_models import is_svd_model_cached, resolve_svd_cache_dir, resolve_svd_model_spec
from src.video.svd_postprocess import (
    get_codeformer_runtime_issues,
    get_gfpgan_runtime_issues,
    get_realesrgan_runtime_issues,
    resolve_svd_upscale_model,
)
from src.video.svd_preprocess import validate_svd_source_image


@dataclass(frozen=True)
class SVDCapability:
    name: str
    status: str
    available: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SVDPreflight:
    """Read-only admission facts for a native SVD request."""

    available: bool
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    model_id: str
    model_supported: bool
    model_cached: bool
    local_files_only: bool
    cache_dir: str
    torch_available: bool
    diffusers_available: bool
    pipeline_available: bool
    cuda_available: bool
    gpu_name: str | None
    gpu_memory_gb: float | None
    core_summary: str
    source_image_path: str | None
    source_image_valid: bool | None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "blocking_reasons": list(self.blocking_reasons),
            "warnings": list(self.warnings),
            "model": {
                "id": self.model_id,
                "supported": self.model_supported,
                "cached": self.model_cached,
                "local_files_only": self.local_files_only,
                "cache_dir": self.cache_dir,
            },
            "runtime": {
                "torch_available": self.torch_available,
                "diffusers_available": self.diffusers_available,
                "pipeline_available": self.pipeline_available,
                "cuda_available": self.cuda_available,
                "gpu_name": self.gpu_name,
                "gpu_memory_gb": self.gpu_memory_gb,
            },
            "core_summary": self.core_summary,
            "source_image": {
                "path": self.source_image_path,
                "valid": self.source_image_valid,
            },
        }


def get_svd_preflight(
    config: SVDConfig, *, source_image_path: str | Path | None = None
) -> SVDPreflight:
    """Inspect admission facts without loading a model, downloading, or writing files."""
    inference = config.inference
    blockers: list[str] = []
    warnings: list[str] = []
    source_path = str(source_image_path).strip() if source_image_path else None
    source_image_valid: bool | None = None
    if not source_path:
        blockers.append("Select a source image.")
    else:
        try:
            validate_svd_source_image(source_path)
            source_image_valid = True
        except Exception as exc:
            source_image_valid = False
            blockers.append(f"Invalid SVD source image: {exc}")
    try:
        resolve_svd_model_spec(inference.model_id)
        model_supported = True
    except Exception as exc:
        model_supported = False
        blockers.append(str(exc))

    cache_dir = resolve_svd_cache_dir(inference.cache_dir)
    model_cached = model_supported and is_svd_model_cached(inference.model_id, cache_dir=cache_dir)
    if inference.local_files_only and not model_cached:
        blockers.append(f"Local-only mode requires a complete cached SVD model at '{cache_dir}'.")
    elif not model_cached:
        warnings.append(
            "Model is not cached; online acquisition will be required when the job runs."
        )

    torch_available = importlib.util.find_spec("torch") is not None
    diffusers_available = importlib.util.find_spec("diffusers") is not None
    pipeline_available = False
    if not torch_available:
        blockers.append("PyTorch is unavailable; install the supported SVD runtime dependencies.")
    if not diffusers_available:
        blockers.append("Diffusers is unavailable; install the supported SVD runtime dependencies.")
    else:
        try:
            pipeline_available = hasattr(
                importlib.import_module("diffusers"),
                "StableVideoDiffusionPipeline",
            )
        except Exception as exc:
            warnings.append(f"Diffusers could not be inspected: {exc}")
        if not pipeline_available:
            blockers.append("Diffusers StableVideoDiffusionPipeline is unavailable.")

    cuda_available = False
    gpu_name: str | None = None
    gpu_memory_gb: float | None = None
    if torch_available:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                gpu_name = str(torch.cuda.get_device_name(0))
                gpu_memory_gb = round(
                    torch.cuda.get_device_properties(0).total_memory / (1024**3), 1
                )
            else:
                warnings.append(
                    "CUDA is unavailable; native SVD may be too slow or unsupported on this host."
                )
        except Exception:
            warnings.append("CUDA capability could not be inspected.")

    summary = (
        f"XT effective config: {inference.num_frames} frames at {inference.fps} fps, "
        f"{inference.torch_dtype}, motion bucket {inference.motion_bucket_id}, "
        f"noise {inference.noise_aug_strength}, decode chunk {inference.decode_chunk_size}, "
        f"{inference.num_inference_steps} steps, "
        f"CPU offload={'enabled' if inference.cpu_offload else 'disabled'}, "
        f"forward chunking={'enabled' if inference.forward_chunking else 'disabled'}."
    )
    return SVDPreflight(
        available=not blockers,
        blocking_reasons=tuple(blockers),
        warnings=tuple(warnings),
        model_id=inference.model_id,
        model_supported=model_supported,
        model_cached=bool(model_cached),
        local_files_only=inference.local_files_only,
        cache_dir=str(cache_dir),
        torch_available=torch_available,
        diffusers_available=diffusers_available,
        pipeline_available=pipeline_available,
        cuda_available=cuda_available,
        gpu_name=gpu_name,
        gpu_memory_gb=gpu_memory_gb,
        core_summary=summary,
        source_image_path=source_path,
        source_image_valid=source_image_valid,
    )


def get_svd_postprocess_capabilities(config: SVDConfig | None = None) -> dict[str, SVDCapability]:
    active_config = config or SVDConfig()
    return {
        "codeformer": _detect_codeformer(active_config),
        "realesrgan": _detect_realesrgan(active_config),
        "rife": _detect_rife(active_config),
        "gfpgan": _detect_gfpgan(active_config),
    }


def apply_recommended_svd_defaults(config: SVDConfig | None = None) -> SVDConfig:
    """Enable the strongest native postprocess defaults that are actually runnable."""
    active_config = config or SVDConfig()
    capabilities = get_svd_postprocess_capabilities(active_config)
    payload = active_config.to_dict()

    # CodeFormer is the only offered face method (GFPGAN is retired, decision D8).
    payload["postprocess"]["face_restore"]["method"] = "CodeFormer"
    payload["postprocess"]["face_restore"]["enabled"] = bool(capabilities["codeformer"].available)
    payload["postprocess"]["upscale"]["enabled"] = bool(capabilities["realesrgan"].available)
    payload["postprocess"]["interpolation"]["enabled"] = bool(capabilities["rife"].available)

    rife_candidate = _find_rife_candidate(active_config)
    if rife_candidate is not None and not payload["postprocess"]["interpolation"].get(
        "executable_path"
    ):
        payload["postprocess"]["interpolation"]["executable_path"] = str(rife_candidate)
    if capabilities["rife"].available:
        # Smooth to 24 fps or more: x2 for a fast source, x4 for a slow one (SVD generates at ~7 fps).
        payload["postprocess"]["interpolation"]["multiplier"] = default_rife_multiplier(
            active_config.inference.fps
        )

    return SVDConfig.from_dict(payload)


def _detect_codeformer(config: SVDConfig) -> SVDCapability:
    missing = get_codeformer_runtime_issues(config.postprocess)
    if missing:
        return SVDCapability(
            name="CodeFormer",
            status="missing",
            available=False,
            detail=_missing_detail(missing),
        )
    return SVDCapability(
        name="CodeFormer",
        status="ready",
        available=True,
        detail="Detected modern loader, face helper, weight, and required facelib assets.",
    )


def _detect_gfpgan(config: SVDConfig) -> SVDCapability:
    """GFPGAN is retired (D8): reported so a stored config naming it explains itself, never available."""

    missing = list(dict.fromkeys(get_gfpgan_runtime_issues(config.postprocess)))
    return SVDCapability(
        name="GFPGAN",
        status="missing",
        available=False,
        detail=_missing_detail(missing),
    )


def _detect_realesrgan(config: SVDConfig) -> SVDCapability:
    missing = get_realesrgan_runtime_issues(config.postprocess)
    if missing:
        return SVDCapability(
            name="RealESRGAN",
            status="missing",
            available=False,
            detail=_missing_detail(missing),
        )
    return SVDCapability(
        name="RealESRGAN",
        status="experimental",
        available=True,
        detail="Detected modern loader, local weight, and worker runtime."
        + _upscale_model_note(config),
    )


def _upscale_model_note(config: SVDConfig) -> str:
    """Which weights the configured scale would use, so a 2x resize through the 4x model is visible."""

    selection = resolve_svd_upscale_model(config.postprocess)
    if selection is None or not requests_two_times(config.postprocess.upscale.scale):
        return ""
    if selection.source == SOURCE_MODEL_PATH:
        return " 2x resizes the 4x model's output; add RealESRGAN_x2plus.pth beside the 4x weights for native 2x."
    return f" Native 2x model: {Path(selection.model_path).name}."


def _missing_detail(missing: list[str]) -> str:
    detail = "Missing: " + ", ".join(missing)
    if any(item.endswith(" package") for item in missing):
        detail += ". " + POSTPROCESS_INSTALL_HINT
    return detail


def _detect_rife(config: SVDConfig) -> SVDCapability:
    candidate = _find_rife_candidate(config)
    if candidate is None:
        return SVDCapability(
            name="RIFE",
            status="missing",
            available=False,
            detail=(
                "No rife-ncnn-vulkan executable detected. Use Locate RIFE, set "
                "STABLENEW_RIFE_EXE, or unpack a release into tools/rife."
            ),
        )
    return SVDCapability(
        name="RIFE",
        status="external",
        available=True,
        detail=f"Using external runtime at {candidate}",
    )


def _find_rife_candidate(config: SVDConfig) -> Path | None:
    return find_rife_executable(config.postprocess.interpolation.executable_path)
