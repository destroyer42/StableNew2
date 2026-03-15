"""Typed models and registry for native SVD."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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


def get_default_svd_model_id() -> str:
    for model_id, spec in _SUPPORTED_SVD_MODELS.items():
        if spec.recommended:
            return model_id
    return next(iter(_SUPPORTED_SVD_MODELS))


def resolve_svd_model_spec(model_id: str) -> SVDModelSpec:
    try:
        return _SUPPORTED_SVD_MODELS[model_id]
    except KeyError as exc:
        raise SVDConfigError(f"Unsupported SVD model_id: {model_id}") from exc


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
