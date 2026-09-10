"""Capability discovery for native SVD postprocess helpers."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import site
from dataclasses import asdict, dataclass
from pathlib import Path

from src.video.svd_config import SVDConfig
from src.video.svd_models import is_svd_model_cached, resolve_svd_cache_dir, resolve_svd_model_spec
from src.video.svd_postprocess import (
    get_codeformer_runtime_issues,
    get_gfpgan_runtime_issues,
    get_realesrgan_runtime_issues,
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


def get_svd_preflight(config: SVDConfig, *, source_image_path: str | Path | None = None) -> SVDPreflight:
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
        blockers.append(
            f"Local-only mode requires a complete cached SVD model at '{cache_dir}'."
        )
    elif not model_cached:
        warnings.append("Model is not cached; online acquisition will be required when the job runs.")

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
                gpu_memory_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
            else:
                warnings.append("CUDA is unavailable; native SVD may be too slow or unsupported on this host.")
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

    if capabilities["codeformer"].available:
        payload["postprocess"]["face_restore"]["method"] = "CodeFormer"
        payload["postprocess"]["face_restore"]["enabled"] = True
    elif capabilities["gfpgan"].available:
        payload["postprocess"]["face_restore"]["method"] = "GFPGAN"
        payload["postprocess"]["face_restore"]["enabled"] = True
    else:
        payload["postprocess"]["face_restore"]["method"] = "CodeFormer"
        payload["postprocess"]["face_restore"]["enabled"] = False
    payload["postprocess"]["upscale"]["enabled"] = bool(capabilities["realesrgan"].available)
    payload["postprocess"]["interpolation"]["enabled"] = bool(capabilities["rife"].available)

    rife_candidate = _find_rife_candidate(active_config)
    if rife_candidate is not None and not payload["postprocess"]["interpolation"].get("executable_path"):
        payload["postprocess"]["interpolation"]["executable_path"] = str(rife_candidate)

    return SVDConfig.from_dict(payload)


def _detect_codeformer(config: SVDConfig) -> SVDCapability:
    package_root = _find_site_package_dir("codeformer")
    missing: list[str] = []
    if package_root is None:
        missing.append("codeformer package")
    missing.extend(get_codeformer_runtime_issues(config.postprocess))
    if missing:
        return SVDCapability(
            name="CodeFormer",
            status="missing",
            available=False,
            detail="Missing: " + ", ".join(missing),
        )
    return SVDCapability(
        name="CodeFormer",
        status="ready",
        available=True,
        detail="Detected package, weight, and required facelib assets.",
    )


def _detect_gfpgan(config: SVDConfig) -> SVDCapability:
    package_root = _find_site_package_dir("gfpgan")
    missing: list[str] = []
    if package_root is None:
        missing.append("gfpgan package")
    missing.extend(get_gfpgan_runtime_issues(config.postprocess))
    missing = list(dict.fromkeys(missing))
    if missing:
        return SVDCapability(
            name="GFPGAN",
            status="missing",
            available=False,
            detail="Missing: " + ", ".join(missing),
        )
    return SVDCapability(
        name="GFPGAN",
        status="ready",
        available=True,
        detail="Detected package, weight, and required facelib assets.",
    )


def _detect_realesrgan(config: SVDConfig) -> SVDCapability:
    package_root = _find_site_package_dir("codeformer")
    missing: list[str] = []
    if package_root is None:
        missing.append("codeformer package")
    missing.extend(get_realesrgan_runtime_issues(config.postprocess))
    if missing:
        return SVDCapability(
            name="RealESRGAN",
            status="missing",
            available=False,
            detail="Missing: " + ", ".join(missing),
        )
    return SVDCapability(
        name="RealESRGAN",
        status="experimental",
        available=True,
        detail="Detected local weight and worker runtime.",
    )


def _detect_rife(config: SVDConfig) -> SVDCapability:
    candidate = _find_rife_candidate(config)
    if candidate is None:
        return SVDCapability(
            name="RIFE",
            status="missing",
            available=False,
            detail="No rife-ncnn-vulkan executable detected.",
        )
    return SVDCapability(
        name="RIFE",
        status="external",
        available=True,
        detail=f"Using external runtime at {candidate}",
    )


def _find_rife_candidate(config: SVDConfig) -> Path | None:
    explicit = config.postprocess.interpolation.executable_path
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
    env_path = os.getenv("STABLENEW_RIFE_EXE")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    which_path = shutil.which("rife-ncnn-vulkan")
    if which_path:
        return Path(which_path)
    repo_candidate = Path(__file__).resolve().parents[2] / "tools" / "rife" / "rife-ncnn-vulkan.exe"
    if repo_candidate.exists():
        return repo_candidate
    return None


def _find_site_package_dir(name: str) -> Path | None:
    roots: list[Path] = []
    for root in site.getsitepackages():
        roots.append(Path(root))
    try:
        user_site = site.getusersitepackages()
        if user_site:
            roots.append(Path(user_site))
    except Exception:
        pass
    for root in roots:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None
