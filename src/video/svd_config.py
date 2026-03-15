"""Typed configuration models for native SVD image-to-video."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from src.video.svd_errors import SVDConfigError

SVDResizeMode = Literal["letterbox", "center_crop", "contain_then_crop"]
SVDOutputFormat = Literal["mp4", "gif", "frames"]
SVDDType = Literal["float16", "bfloat16", "float32"]

_VALID_RESIZE_MODES = {"letterbox", "center_crop", "contain_then_crop"}
_VALID_OUTPUT_FORMATS = {"mp4", "gif", "frames"}
_VALID_DTYPES = {"float16", "bfloat16", "float32"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SVDConfigError(message)


@dataclass(frozen=True)
class SVDPreprocessConfig:
    target_width: int = 1024
    target_height: int = 576
    resize_mode: SVDResizeMode = "letterbox"
    preserve_aspect_ratio: bool = True
    center_crop: bool = True
    pad_color: tuple[int, int, int] = (0, 0, 0)

    def __post_init__(self) -> None:
        _require(self.target_width > 0, "target_width must be positive")
        _require(self.target_height > 0, "target_height must be positive")
        _require(self.resize_mode in _VALID_RESIZE_MODES, f"Invalid resize_mode: {self.resize_mode}")
        _require(len(self.pad_color) == 3, "pad_color must contain exactly 3 integers")
        _require(all(0 <= int(value) <= 255 for value in self.pad_color), "pad_color values must be in 0..255")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDPreprocessConfig:
        payload = dict(data or {})
        pad_color = payload.get("pad_color", (0, 0, 0))
        if isinstance(pad_color, list):
            pad_color = tuple(int(value) for value in pad_color)
        return cls(
            target_width=int(payload.get("target_width", 1024)),
            target_height=int(payload.get("target_height", 576)),
            resize_mode=str(payload.get("resize_mode", "letterbox")),
            preserve_aspect_ratio=bool(payload.get("preserve_aspect_ratio", True)),
            center_crop=bool(payload.get("center_crop", True)),
            pad_color=tuple(int(value) for value in pad_color),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SVDInferenceConfig:
    model_id: str = "stabilityai/stable-video-diffusion-img2vid-xt"
    variant: str | None = "fp16"
    torch_dtype: SVDDType = "float16"
    num_frames: int = 25
    fps: int = 7
    motion_bucket_id: int = 127
    noise_aug_strength: float = 0.05
    decode_chunk_size: int = 2
    num_inference_steps: int = 25
    min_guidance_scale: float = 1.0
    max_guidance_scale: float = 3.0
    seed: int | None = None
    cpu_offload: bool = True
    forward_chunking: bool = True
    local_files_only: bool = False
    cache_dir: str | None = None

    def __post_init__(self) -> None:
        _require(bool(self.model_id.strip()), "model_id must be non-empty")
        _require(self.torch_dtype in _VALID_DTYPES, f"Invalid torch_dtype: {self.torch_dtype}")
        _require(self.num_frames > 0, "num_frames must be positive")
        _require(self.fps > 0, "fps must be positive")
        _require(self.motion_bucket_id >= 0, "motion_bucket_id must be >= 0")
        _require(0.0 <= self.noise_aug_strength <= 1.0, "noise_aug_strength must be in 0.0..1.0")
        _require(self.decode_chunk_size > 0, "decode_chunk_size must be positive")
        _require(self.num_inference_steps > 0, "num_inference_steps must be positive")
        _require(self.min_guidance_scale > 0, "min_guidance_scale must be positive")
        _require(self.max_guidance_scale >= self.min_guidance_scale, "max_guidance_scale must be >= min_guidance_scale")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDInferenceConfig:
        payload = dict(data or {})
        seed = payload.get("seed")
        return cls(
            model_id=str(payload.get("model_id", "stabilityai/stable-video-diffusion-img2vid-xt")),
            variant=payload.get("variant", "fp16"),
            torch_dtype=str(payload.get("torch_dtype", "float16")),
            num_frames=int(payload.get("num_frames", 25)),
            fps=int(payload.get("fps", 7)),
            motion_bucket_id=int(payload.get("motion_bucket_id", 127)),
            noise_aug_strength=float(payload.get("noise_aug_strength", 0.05)),
            decode_chunk_size=int(payload.get("decode_chunk_size", 2)),
            num_inference_steps=int(payload.get("num_inference_steps", 25)),
            min_guidance_scale=float(payload.get("min_guidance_scale", 1.0)),
            max_guidance_scale=float(payload.get("max_guidance_scale", 3.0)),
            seed=None if seed in (None, "") else int(seed),
            cpu_offload=bool(payload.get("cpu_offload", True)),
            forward_chunking=bool(payload.get("forward_chunking", True)),
            local_files_only=bool(payload.get("local_files_only", False)),
            cache_dir=payload.get("cache_dir"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SVDOutputConfig:
    output_format: SVDOutputFormat = "mp4"
    save_frames: bool = False
    save_preview_image: bool = True

    def __post_init__(self) -> None:
        _require(self.output_format in _VALID_OUTPUT_FORMATS, f"Invalid output_format: {self.output_format}")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDOutputConfig:
        payload = dict(data or {})
        return cls(
            output_format=str(payload.get("output_format", "mp4")),
            save_frames=bool(payload.get("save_frames", False)),
            save_preview_image=bool(payload.get("save_preview_image", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SVDConfig:
    preprocess: SVDPreprocessConfig = field(default_factory=SVDPreprocessConfig)
    inference: SVDInferenceConfig = field(default_factory=SVDInferenceConfig)
    output: SVDOutputConfig = field(default_factory=SVDOutputConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDConfig:
        payload = dict(data or {})
        if "svd" in payload and isinstance(payload["svd"], dict):
            payload = dict(payload["svd"])
        return cls(
            preprocess=SVDPreprocessConfig.from_dict(payload.get("preprocess")),
            inference=SVDInferenceConfig.from_dict(payload.get("inference")),
            output=SVDOutputConfig.from_dict(payload.get("output")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preprocess": self.preprocess.to_dict(),
            "inference": self.inference.to_dict(),
            "output": self.output.to_dict(),
        }
