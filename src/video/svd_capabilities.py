"""Capability discovery for native SVD postprocess helpers."""

from __future__ import annotations

import os
import shutil
import site
from dataclasses import asdict, dataclass
from pathlib import Path

from src.video.svd_config import SVDConfig
from src.video.svd_postprocess import (
    get_codeformer_runtime_issues,
    get_gfpgan_runtime_issues,
    get_realesrgan_runtime_issues,
)


@dataclass(frozen=True)
class SVDCapability:
    name: str
    status: str
    available: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
