"""Typed AnimateDiff runtime helpers for NJR pipeline execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


_ANIMATEDIFF_SCRIPT_KEY = "AnimateDiff"
_SDXL_MOTION_MODULE_CANDIDATES = (
    "mm_sdxl_hs.safetensors",
    "mm_sdxl_v10_beta.safetensors",
    "mm_sdxl_hs.ckpt",
    "mm_sdxl_v10_beta.ckpt",
)
_SD15_MOTION_MODULE_CANDIDATES = (
    "mm_sd15_v3.safetensors",
    "mm_sd15_v2.safetensors",
    "mm_sd15_v1.safetensors",
    "mm_sd15_AnimateLCM.safetensors",
    "mm_sd_v15_v3.ckpt",
    "mm_sd_v15_v2.ckpt",
)


@dataclass(frozen=True)
class AnimateDiffConfig:
    """Normalized AnimateDiff stage config used by the executor."""

    enabled: bool = False
    motion_module: str | None = None
    fps: int = 8
    video_length: int = 16
    loop_number: int = 0
    closed_loop: str = "N"
    batch_size: int = 16
    stride: int | None = None
    overlap: int | None = None
    format: list[str] = field(default_factory=lambda: ["PNG", "Frame"])

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> AnimateDiffConfig:
        data = dict(payload or {})

        def _as_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        format_value = data.get("format", ["PNG", "Frame"])
        if isinstance(format_value, str):
            format_list = [format_value]
        elif isinstance(format_value, list):
            format_list = [str(item) for item in format_value if item not in (None, "")]
        else:
            format_list = ["PNG", "Frame"]

        stride_value = data.get("stride")
        overlap_value = data.get("overlap")
        try:
            stride = int(stride_value) if stride_value is not None else None
        except (TypeError, ValueError):
            stride = None
        try:
            overlap = int(overlap_value) if overlap_value is not None else None
        except (TypeError, ValueError):
            overlap = None

        return cls(
            enabled=bool(data.get("enabled", False)),
            motion_module=(str(data.get("motion_module")).strip() or None)
            if data.get("motion_module") not in (None, "")
            else None,
            fps=max(1, _as_int(data.get("fps"), 8)),
            video_length=max(1, _as_int(data.get("video_length"), 16)),
            loop_number=max(0, _as_int(data.get("loop_number"), 0)),
            closed_loop=str(data.get("closed_loop") or "N"),
            batch_size=max(1, _as_int(data.get("batch_size"), 16)),
            stride=stride,
            overlap=overlap,
            format=format_list or ["PNG", "Frame"],
        )


@dataclass(frozen=True)
class AnimateDiffCapability:
    """Best-effort script capability snapshot from the WebUI scripts API."""

    available: bool
    script_name: str | None = None
    motion_modules: list[str] = field(default_factory=list)
    extension_contract: str = "alwayson_scripts"
    reason: str | None = None


def _iter_script_entries(
    scripts_payload: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    data = scripts_payload or {}
    entries: list[dict[str, Any]] = []
    names: list[str] = []
    for section in ("txt2img", "img2img"):
        section_entries = data.get(section, [])
        if isinstance(section_entries, list):
            entries.extend(item for item in section_entries if isinstance(item, dict))
            names.extend(str(item).strip() for item in section_entries if isinstance(item, str))
    return entries, names


def _looks_like_motion_module_field(arg: dict[str, Any]) -> bool:
    label = str(arg.get("label") or arg.get("name") or "").strip().lower()
    return "motion" in label or ("module" in label and "model" in label) or label == "model"


def _extract_choices(arg: dict[str, Any]) -> list[str]:
    choices = arg.get("choices", [])
    if not isinstance(choices, list):
        return []
    return [str(choice) for choice in choices if choice not in (None, "")]


def parse_animatediff_capability(scripts_payload: dict[str, Any] | None) -> AnimateDiffCapability:
    """Parse WebUI scripts payload into a typed AnimateDiff capability snapshot."""

    entries, names = _iter_script_entries(scripts_payload)
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if name.lower() != _ANIMATEDIFF_SCRIPT_KEY.lower():
            continue
        motion_modules: list[str] = []
        for arg in entry.get("args", []) or []:
            if isinstance(arg, dict) and _looks_like_motion_module_field(arg):
                motion_modules.extend(_extract_choices(arg))
        deduped = list(dict.fromkeys(motion_modules))
        return AnimateDiffCapability(
            available=True,
            script_name=name or _ANIMATEDIFF_SCRIPT_KEY,
            motion_modules=deduped,
            extension_contract="alwayson_scripts",
        )
    if any(name.lower() == _ANIMATEDIFF_SCRIPT_KEY.lower() for name in names):
        return AnimateDiffCapability(
            available=True,
            script_name=_ANIMATEDIFF_SCRIPT_KEY,
            motion_modules=[],
            extension_contract="alwayson_scripts",
            reason="AnimateDiff reported by /sdapi/v1/scripts without argument metadata",
        )
    return AnimateDiffCapability(
        available=False,
        script_name=None,
        motion_modules=[],
        extension_contract="alwayson_scripts",
        reason="AnimateDiff script not reported by /sdapi/v1/scripts",
    )


def infer_animatediff_model_family(model_name: str | None) -> str | None:
    """Infer the target checkpoint family from a model or motion-module name."""

    name = str(model_name or "").strip().lower()
    if not name:
        return None
    if any(token in name for token in ("sdxl", "_xl", "-xl", "pony", "xl_")):
        return "sdxl"
    if any(token in name for token in ("sd15", "sd 1.5", "sd1.5", "v15", "1.5")):
        return "sd15"
    return None


def resolve_animatediff_motion_module(
    config: AnimateDiffConfig,
    capability: AnimateDiffCapability,
    model_name: str | None,
) -> str | None:
    """Choose a motion module without relying on the extension's checkpoint-agnostic default."""

    if config.motion_module:
        return config.motion_module

    family = infer_animatediff_model_family(model_name)
    available = [str(item) for item in capability.motion_modules if item]
    available_by_lower = {item.lower(): item for item in available}

    candidate_groups: list[tuple[str, ...]] = []
    if family == "sdxl":
        candidate_groups.append(_SDXL_MOTION_MODULE_CANDIDATES)
        candidate_groups.append(_SD15_MOTION_MODULE_CANDIDATES)
    elif family == "sd15":
        candidate_groups.append(_SD15_MOTION_MODULE_CANDIDATES)
        candidate_groups.append(_SDXL_MOTION_MODULE_CANDIDATES)
    else:
        candidate_groups.append(_SD15_MOTION_MODULE_CANDIDATES)
        candidate_groups.append(_SDXL_MOTION_MODULE_CANDIDATES)

    if available:
        for group in candidate_groups:
            for candidate in group:
                resolved = available_by_lower.get(candidate.lower())
                if resolved:
                    return resolved
        if family:
            for item in available:
                if infer_animatediff_model_family(item) == family:
                    return item
        return available[0]

    for group in candidate_groups:
        if group:
            return group[0]
    return None


def build_animatediff_script_payload(
    config: AnimateDiffConfig,
    capability: AnimateDiffCapability,
) -> dict[str, Any]:
    """Build the `alwayson_scripts` payload for AnimateDiff."""

    output_formats = [item for item in config.format if item]
    if "Frame" not in output_formats:
        output_formats.append("Frame")
    if not any(item in {"GIF", "MP4", "WEBP", "WEBM", "PNG"} for item in output_formats):
        output_formats.insert(0, "PNG")

    script_args: dict[str, Any] = {
        "enable": True,
        "video_length": config.video_length,
        "fps": config.fps,
        "loop_number": config.loop_number,
        "closed_loop": config.closed_loop,
        "batch_size": config.batch_size,
        "format": output_formats,
    }
    if config.motion_module:
        script_args["model"] = config.motion_module
    if config.stride is not None:
        script_args["stride"] = config.stride
    if config.overlap is not None:
        script_args["overlap"] = config.overlap

    script_name = capability.script_name or _ANIMATEDIFF_SCRIPT_KEY
    return {script_name: {"args": [script_args]}}


def attach_animatediff_to_payload(
    base_payload: dict[str, Any],
    config: AnimateDiffConfig,
    capability: AnimateDiffCapability,
) -> dict[str, Any]:
    """Return a generation payload with AnimateDiff attached."""

    payload = dict(base_payload)
    alwayson_scripts = dict(payload.get("alwayson_scripts", {}) or {})
    alwayson_scripts.update(build_animatediff_script_payload(config, capability))
    payload["alwayson_scripts"] = alwayson_scripts
    return payload


def _normalize_info_payload(info: Any) -> dict[str, Any]:
    if isinstance(info, dict):
        return dict(info)
    if isinstance(info, str) and info:
        try:
            parsed = json.loads(info)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _info_mentions_animatediff(info: dict[str, Any]) -> bool:
    if not info:
        return False
    extra_params = info.get("extra_generation_params")
    if isinstance(extra_params, dict):
        if any("animatediff" in str(key).lower() for key in extra_params.keys()):
            return True
        if any("animatediff" in str(value).lower() for value in extra_params.values()):
            return True
    for key, value in info.items():
        if "animatediff" in str(key).lower():
            return True
        if isinstance(value, str) and "animatediff" in value.lower():
            return True
        if isinstance(value, list):
            if any(isinstance(item, str) and "animatediff" in item.lower() for item in value):
                return True
    return False


def normalize_animatediff_response(response: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize AnimateDiff generation output into frame-oriented metadata."""

    data = dict(response or {})
    info = _normalize_info_payload(data.get("info"))
    frame_images = data.get("images", [])
    if not isinstance(frame_images, list):
        frame_images = []
    return {
        "frame_images": [str(image) for image in frame_images if image],
        "frame_count": len(frame_images),
        "info": info,
        "animate_detected": _info_mentions_animatediff(info),
        "extension_contract": "alwayson_scripts",
    }


__all__ = [
    "AnimateDiffCapability",
    "AnimateDiffConfig",
    "attach_animatediff_to_payload",
    "build_animatediff_script_payload",
    "infer_animatediff_model_family",
    "normalize_animatediff_response",
    "parse_animatediff_capability",
    "resolve_animatediff_motion_module",
]
