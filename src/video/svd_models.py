"""Typed models and registry for native SVD."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.video.svd_config import SVDResizeMode
from src.video.svd_errors import SVDConfigError


@dataclass(frozen=True)
class SVDModelSpec:
    model_id: str
    display_name: str
    default_num_frames: int
    recommended: bool
    notes: str


_SUPPORTED_SVD_MODELS: dict[str, SVDModelSpec] = {
    "stabilityai/stable-video-diffusion-img2vid": SVDModelSpec(
        model_id="stabilityai/stable-video-diffusion-img2vid",
        display_name="Stable Video Diffusion Img2Vid",
        default_num_frames=14,
        recommended=False,
        notes="Shorter clip model with lower default frame count.",
    ),
    "stabilityai/stable-video-diffusion-img2vid-xt": SVDModelSpec(
        model_id="stabilityai/stable-video-diffusion-img2vid-xt",
        display_name="Stable Video Diffusion Img2Vid XT",
        default_num_frames=25,
        recommended=True,
        notes="Recommended Phase 1 default for short hero-frame animation.",
    ),
    "stabilityai/stable-video-diffusion-img2vid-xt-1-1": SVDModelSpec(
        model_id="stabilityai/stable-video-diffusion-img2vid-xt-1-1",
        display_name="Stable Video Diffusion Img2Vid XT 1.1",
        default_num_frames=25,
        recommended=False,
        notes="Newer consistency-focused checkpoint; download once before using local-only mode.",
    ),
}


def get_supported_svd_models() -> Mapping[str, SVDModelSpec]:
    return dict(_SUPPORTED_SVD_MODELS)


def discover_cached_svd_models(*, cache_dir: str | Path | None = None) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for root in _iter_svd_cache_roots(cache_dir=cache_dir):
        if not root.exists():
            continue
        for candidate in root.iterdir():
            if not candidate.is_dir():
                continue
            if not candidate.name.startswith("models--stabilityai--stable-video-diffusion"):
                continue
            model_id = _model_id_from_cache_dir(candidate.name)
            if not model_id or model_id in seen:
                continue
            if _has_complete_snapshot(candidate):
                seen.add(model_id)
                discovered.append(model_id)
    return discovered


def is_svd_model_cached(model_id: str, *, cache_dir: str | Path | None = None) -> bool:
    target_name = _cache_dir_name_for_model(model_id)
    for root in _iter_svd_cache_roots(cache_dir=cache_dir):
        candidate = root / target_name
        if candidate.exists() and _has_complete_snapshot(candidate):
            return True
    return False


def get_svd_model_options(
    *,
    cache_dir: str | Path | None = None,
    local_files_only: bool = False,
) -> list[str]:
    cached = discover_cached_svd_models(cache_dir=cache_dir)
    if local_files_only:
        return cached

    values: list[str] = []
    seen: set[str] = set()
    for model_id in cached:
        if model_id not in seen:
            seen.add(model_id)
            values.append(model_id)
    for model_id in _SUPPORTED_SVD_MODELS:
        if model_id not in seen:
            seen.add(model_id)
            values.append(model_id)
    return values


def get_default_svd_model_id() -> str:
    for model_id, spec in _SUPPORTED_SVD_MODELS.items():
        if spec.recommended:
            return model_id
    return next(iter(_SUPPORTED_SVD_MODELS))


def resolve_svd_model_spec(model_id: str) -> SVDModelSpec:
    spec = _SUPPORTED_SVD_MODELS.get(model_id)
    if spec is not None:
        return spec
    if model_id.startswith("stabilityai/stable-video-diffusion"):
        return SVDModelSpec(
            model_id=model_id,
            display_name=model_id.split("/")[-1],
            default_num_frames=25,
            recommended=False,
            notes="Locally discovered SVD model.",
        )
    raise SVDConfigError(f"Unsupported SVD model_id: {model_id}")


def _iter_svd_cache_roots(*, cache_dir: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if cache_dir:
        root = Path(cache_dir).expanduser()
        candidates.extend((root, root / "hub", root / "huggingface" / "hub"))
    else:
        repo_root = Path(__file__).resolve().parents[2]
        candidates.extend(
            (
                repo_root / "cache",
                repo_root / "cache" / "hub",
                repo_root / "cache" / "huggingface" / "hub",
            )
        )
        env_hub = os.getenv("HUGGINGFACE_HUB_CACHE")
        if env_hub:
            candidates.append(Path(env_hub).expanduser())
        env_home = os.getenv("HF_HOME")
        if env_home:
            candidates.append(Path(env_home).expanduser() / "hub")
        candidates.append(Path.home() / ".cache" / "huggingface" / "hub")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _cache_dir_name_for_model(model_id: str) -> str:
    return "models--" + model_id.replace("/", "--")


def _model_id_from_cache_dir(name: str) -> str | None:
    if not name.startswith("models--"):
        return None
    return name[len("models--") :].replace("--", "/")


def _has_complete_snapshot(cache_dir: Path) -> bool:
    snapshot_root = cache_dir / "snapshots"
    if not snapshot_root.exists():
        return False
    for candidate in snapshot_root.iterdir():
        if candidate.is_dir() and (candidate / "model_index.json").exists():
            return True
    return False


@dataclass(frozen=True)
class SVDPreprocessResult:
    source_path: Path
    prepared_path: Path
    original_width: int
    original_height: int
    target_width: int
    target_height: int
    resize_mode: SVDResizeMode
    was_resized: bool
    was_padded: bool
    was_cropped: bool


@dataclass(frozen=True)
class SVDResult:
    source_image_path: Path
    video_path: Path | None
    gif_path: Path | None
    frame_paths: list[Path]
    thumbnail_path: Path | None
    metadata_path: Path | None
    frame_count: int
    fps: int
    seed: int | None
    model_id: str
    preprocess: SVDPreprocessResult
    postprocess: dict[str, Any] | None = None
