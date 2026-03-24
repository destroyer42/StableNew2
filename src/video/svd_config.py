"""Typed configuration models for native SVD image-to-video."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.video.svd_errors import SVDConfigError

SVDResizeMode = Literal["letterbox", "center_crop", "contain_then_crop"]
SVDOutputFormat = Literal["mp4", "gif", "frames"]
SVDDType = Literal["float16", "bfloat16", "float32"]
SVDInterpolationMethod = Literal["rife"]
SVDFaceRestoreMethod = Literal["CodeFormer", "GFPGAN"]
SVDUpscaleMethod = Literal["RealESRGAN"]

_VALID_RESIZE_MODES = {"letterbox", "center_crop", "contain_then_crop"}
_VALID_OUTPUT_FORMATS = {"mp4", "gif", "frames"}
_VALID_DTYPES = {"float16", "bfloat16", "float32"}
_VALID_FACE_RESTORE_METHODS = {"CodeFormer", "GFPGAN"}
_VALID_UPSCALE_METHODS = {"RealESRGAN"}


def _default_codeformer_weight_path() -> str | None:
    candidate = Path.home() / "stable-diffusion-webui" / "models" / "Codeformer" / "codeformer-v0.1.0.pth"
    return str(candidate) if candidate.exists() else None


def _default_gfpgan_weight_path() -> str | None:
    candidate = Path.home() / "stable-diffusion-webui" / "models" / "GFPGAN" / "GFPGANv1.4.pth"
    return str(candidate) if candidate.exists() else None


def _default_realesrgan_weight_path() -> str | None:
    candidate = Path.home() / "stable-diffusion-webui" / "models" / "RealESRGAN" / "RealESRGAN_x4plus.pth"
    return str(candidate) if candidate.exists() else None


def _default_facelib_model_root() -> str | None:
    candidate = Path.home() / "stable-diffusion-webui" / "models" / "GFPGAN"
    return str(candidate) if candidate.exists() else None


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
class SVDInterpolationConfig:
    enabled: bool = False
    method: SVDInterpolationMethod = "rife"
    multiplier: int = 2
    executable_path: str | None = None
    model_dir: str | None = None

    def __post_init__(self) -> None:
        _require(self.multiplier >= 2, "interpolation multiplier must be >= 2")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDInterpolationConfig:
        payload = dict(data or {})
        return cls(
            enabled=bool(payload.get("enabled", False)),
            method="rife",
            multiplier=int(payload.get("multiplier", 2)),
            executable_path=(str(payload.get("executable_path")).strip() or None)
            if payload.get("executable_path") not in (None, "")
            else None,
            model_dir=(str(payload.get("model_dir")).strip() or None)
            if payload.get("model_dir") not in (None, "")
            else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SVDFaceRestoreConfig:
    enabled: bool = False
    method: SVDFaceRestoreMethod = "CodeFormer"
    fidelity_weight: float = 0.7
    codeformer_weight_path: str | None = field(default_factory=_default_codeformer_weight_path)
    gfpgan_weight_path: str | None = field(default_factory=_default_gfpgan_weight_path)
    facelib_model_root: str | None = field(default_factory=_default_facelib_model_root)

    def __post_init__(self) -> None:
        _require(self.method in _VALID_FACE_RESTORE_METHODS, f"Invalid face restore method: {self.method}")
        _require(0.0 <= self.fidelity_weight <= 1.0, "fidelity_weight must be in 0.0..1.0")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDFaceRestoreConfig:
        payload = dict(data or {})
        return cls(
            enabled=bool(payload.get("enabled", False)),
            method=str(payload.get("method", "CodeFormer")),
            fidelity_weight=float(payload.get("fidelity_weight", 0.7)),
            codeformer_weight_path=(str(payload.get("codeformer_weight_path")).strip() or None)
            if payload.get("codeformer_weight_path") not in (None, "")
            else _default_codeformer_weight_path(),
            gfpgan_weight_path=(str(payload.get("gfpgan_weight_path")).strip() or None)
            if payload.get("gfpgan_weight_path") not in (None, "")
            else _default_gfpgan_weight_path(),
            facelib_model_root=(str(payload.get("facelib_model_root")).strip() or None)
            if payload.get("facelib_model_root") not in (None, "")
            else _default_facelib_model_root(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SVDUpscaleConfig:
    enabled: bool = False
    method: SVDUpscaleMethod = "RealESRGAN"
    scale: float = 2.0
    tile: int = 0
    model_path: str | None = field(default_factory=_default_realesrgan_weight_path)

    def __post_init__(self) -> None:
        _require(self.method in _VALID_UPSCALE_METHODS, f"Invalid upscale method: {self.method}")
        _require(self.scale >= 1.0, "upscale scale must be >= 1.0")
        _require(self.tile >= 0, "upscale tile must be >= 0")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDUpscaleConfig:
        payload = dict(data or {})
        return cls(
            enabled=bool(payload.get("enabled", False)),
            method=str(payload.get("method", "RealESRGAN")),
            scale=float(payload.get("scale", 2.0)),
            tile=int(payload.get("tile", 0)),
            model_path=(str(payload.get("model_path")).strip() or None)
            if payload.get("model_path") not in (None, "")
            else _default_realesrgan_weight_path(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SVDSecondaryMotionConfig:
    enabled: bool = False
    policy_id: str = ""
    intent: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    backend_mode: str = ""
    intensity: float = 0.0
    damping: float = 1.0
    frequency_hz: float = 0.0
    cap_pixels: int = 0
    regions: tuple[str, ...] = ()
    skip_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDSecondaryMotionConfig:
        payload = dict(data or {})
        raw_seed = payload.get("seed")
        seed = None if raw_seed in (None, "") else int(raw_seed)
        intent = dict(payload.get("intent") or {}) if isinstance(payload.get("intent"), dict) else {}
        policy = dict(payload.get("policy") or {}) if isinstance(payload.get("policy"), dict) else {}
        regions_raw = payload.get("regions", intent.get("regions"))
        if isinstance(regions_raw, str):
            regions = (regions_raw.strip(),) if regions_raw.strip() else ()
        elif isinstance(regions_raw, (list, tuple)):
            regions = tuple(str(item).strip() for item in regions_raw if str(item or "").strip())
        else:
            regions = ()
        backend_mode = str(payload.get("backend_mode") or policy.get("backend_mode") or "")
        enabled = bool(payload.get("enabled", policy.get("enabled", intent.get("enabled", False))))
        return cls(
            enabled=enabled,
            policy_id=str(payload.get("policy_id") or policy.get("policy_id") or ""),
            intent=intent,
            policy=policy,
            seed=seed,
            backend_mode=backend_mode,
            intensity=float(payload.get("intensity", policy.get("intensity", 0.0)) or 0.0),
            damping=float(payload.get("damping", policy.get("damping", 1.0)) or 1.0),
            frequency_hz=float(payload.get("frequency_hz", policy.get("frequency_hz", 0.0)) or 0.0),
            cap_pixels=int(payload.get("cap_pixels", policy.get("cap_pixels", 0)) or 0),
            regions=regions,
            skip_reason=str(payload.get("skip_reason") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "policy_id": self.policy_id,
            "intent": dict(self.intent),
            "policy": dict(self.policy),
            "seed": self.seed,
            "backend_mode": self.backend_mode,
            "intensity": self.intensity,
            "damping": self.damping,
            "frequency_hz": self.frequency_hz,
            "cap_pixels": self.cap_pixels,
            "regions": list(self.regions),
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True)
class SVDPostprocessConfig:
    secondary_motion: SVDSecondaryMotionConfig = field(default_factory=SVDSecondaryMotionConfig)
    interpolation: SVDInterpolationConfig = field(default_factory=SVDInterpolationConfig)
    face_restore: SVDFaceRestoreConfig = field(default_factory=SVDFaceRestoreConfig)
    upscale: SVDUpscaleConfig = field(default_factory=SVDUpscaleConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDPostprocessConfig:
        payload = dict(data or {})
        return cls(
            secondary_motion=SVDSecondaryMotionConfig.from_dict(payload.get("secondary_motion")),
            interpolation=SVDInterpolationConfig.from_dict(payload.get("interpolation")),
            face_restore=SVDFaceRestoreConfig.from_dict(payload.get("face_restore")),
            upscale=SVDUpscaleConfig.from_dict(payload.get("upscale")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "secondary_motion": self.secondary_motion.to_dict(),
            "interpolation": self.interpolation.to_dict(),
            "face_restore": self.face_restore.to_dict(),
            "upscale": self.upscale.to_dict(),
        }


@dataclass(frozen=True)
class SVDConfig:
    preprocess: SVDPreprocessConfig = field(default_factory=SVDPreprocessConfig)
    inference: SVDInferenceConfig = field(default_factory=SVDInferenceConfig)
    output: SVDOutputConfig = field(default_factory=SVDOutputConfig)
    postprocess: SVDPostprocessConfig = field(default_factory=SVDPostprocessConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SVDConfig:
        payload = dict(data or {})
        if "svd" in payload and isinstance(payload["svd"], dict):
            payload = dict(payload["svd"])
        return cls(
            preprocess=SVDPreprocessConfig.from_dict(payload.get("preprocess")),
            inference=SVDInferenceConfig.from_dict(payload.get("inference")),
            output=SVDOutputConfig.from_dict(payload.get("output")),
            postprocess=SVDPostprocessConfig.from_dict(payload.get("postprocess")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preprocess": self.preprocess.to_dict(),
            "inference": self.inference.to_dict(),
            "output": self.output.to_dict(),
            "postprocess": self.postprocess.to_dict(),
        }
