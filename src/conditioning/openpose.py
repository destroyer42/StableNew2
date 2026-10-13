"""The ``openpose.v1`` PromptPack conditioning contract (PR-IMG-CNET-210).

One optional, versioned, structured declaration per PromptPack slot (``controlnet_openpose``) says "condition this
slot's base SDXL generation on this pre-rendered OpenPose image". This module is the only definition of its shape:
authored declaration, validation, defaults and the canonical identity of a library image. It is pure (no I/O, no Tk, no
backend), so the editor, compiler, executor and tests all agree on the same rules.

The declaration is conditioning *input*, not prompt text. It never contains image bytes: it names a library image by its
relative identity, and the compiler later freezes that image's verified SHA-256 and a job-owned snapshot (see
``openpose_snapshot``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CONTRACT = "openpose.v1"
#: PromptPack slot key and (frozen) NJR config key. The word "controlnet" is deliberate: exact-profile targets already
#: refuse any enabled key that contains it, so an unsupported target can never silently drop this conditioning.
SLOT_FIELD = "controlnet_openpose"

PREPROCESSOR_NONE = "None"
CONTROL_MODES = ("Balanced", "My prompt is more important", "ControlNet is more important")
RESIZE_MODES = ("Just Resize", "Crop and Resize", "Resize and Fill")

DEFAULT_WEIGHT = 1.0
DEFAULT_GUIDANCE_START = 0.0
DEFAULT_GUIDANCE_END = 1.0
DEFAULT_CONTROL_MODE = CONTROL_MODES[0]
DEFAULT_RESIZE_MODE = "Resize and Fill"
MIN_WEIGHT = 0.0
MAX_WEIGHT = 2.0

#: Library image formats (case-insensitive extensions). Anything else is not an OpenPose library image.
SUPPORTED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
MAX_IDENTITY_LENGTH = 512

_KEYS = frozenset(
    {
        "contract",
        "enabled",
        "asset",
        "model",
        "weight",
        "guidance_start",
        "guidance_end",
        "control_mode",
        "resize_mode",
        "preprocessor",
    }
)


class ConditioningError(ValueError):
    """A conditioning input or dispatch refusal. Executors let it propagate verbatim instead of reporting "no images"."""


class OpenPoseDeclarationError(ValueError):
    """The declaration cannot be honored as written. ``problems`` lists every defect, never the image contents."""

    def __init__(self, problems: tuple[str, ...] | list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class OpenPoseSelection:
    """One validated slot declaration (authored intent; nothing here is verified against a file yet)."""

    asset: str
    enabled: bool = True
    model: str = ""
    weight: float = DEFAULT_WEIGHT
    guidance_start: float = DEFAULT_GUIDANCE_START
    guidance_end: float = DEFAULT_GUIDANCE_END
    control_mode: str = DEFAULT_CONTROL_MODE
    resize_mode: str = DEFAULT_RESIZE_MODE
    preprocessor: str = PREPROCESSOR_NONE

    def to_dict(self) -> dict[str, Any]:
        """The canonical persisted declaration (the exact JSON shape a PromptPack slot carries)."""

        return {
            "contract": CONTRACT,
            "enabled": bool(self.enabled),
            "asset": self.asset,
            "model": self.model,
            "weight": float(self.weight),
            "guidance_start": float(self.guidance_start),
            "guidance_end": float(self.guidance_end),
            "control_mode": self.control_mode,
            "resize_mode": self.resize_mode,
            "preprocessor": self.preprocessor,
        }


def normalize_asset_identity(value: Any) -> str:
    """The canonical library-relative identity (POSIX separators) or ``ValueError``.

    Accepts only a relative path inside the library: no drive/stream colon, no absolute root, no ``.``/``..``/empty
    segment, no control character, and a supported image extension. Backslashes are folded to ``/`` so a Windows-authored
    pack names the same image as a POSIX one. Containment against the real directory is a separate, filesystem check.
    """

    if not isinstance(value, str):
        raise ValueError("asset must be a library-relative path string")
    text = value.strip().replace("\\", "/")
    if not text:
        raise ValueError("asset is empty")
    if len(text) > MAX_IDENTITY_LENGTH:
        raise ValueError("asset path is too long")
    if text.startswith("/") or ":" in text:
        raise ValueError("asset must be relative to the OpenPose library (no absolute path or drive)")
    if any(ord(char) < 32 for char in text):
        raise ValueError("asset contains a control character")
    segments = text.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ValueError("asset must not contain empty, '.' or '..' path segments")
        if segment != segment.rstrip(" ."):
            raise ValueError("asset path segments must not end with a space or a dot")
    dot = segments[-1].rfind(".")
    extension = segments[-1][dot:].lower() if dot >= 0 else ""
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"asset must be one of {allowed}")
    return "/".join(segments)


def _number(raw: Mapping[str, Any], key: str, default: float, problems: list[str]) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        problems.append(f"{key} must be a finite number")
        return default
    return float(value)


def declaration_problems(raw: Any) -> tuple[str, ...]:
    """Every reason ``raw`` is not an executable ``openpose.v1`` declaration (empty when it is one)."""

    return _parse(raw)[1]


def parse_declaration(raw: Any) -> OpenPoseSelection:
    """Strictly validate one persisted/edited declaration; raises ``OpenPoseDeclarationError`` listing every defect."""

    selection, problems = _parse(raw)
    if problems or selection is None:
        raise OpenPoseDeclarationError(problems or ("declaration is not an object",))
    return selection


def _parse(raw: Any) -> tuple[OpenPoseSelection | None, tuple[str, ...]]:
    if not isinstance(raw, Mapping):
        return None, ("controlnet_openpose must be an object",)
    problems: list[str] = []
    unknown = sorted(str(key) for key in raw if key not in _KEYS)
    if unknown:
        problems.append("unsupported field(s): " + ", ".join(unknown))
    if raw.get("contract") != CONTRACT:
        problems.append(f"contract must be '{CONTRACT}'")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        problems.append("enabled must be true or false")
        enabled = False
    asset = ""
    try:
        asset = normalize_asset_identity(raw.get("asset"))
    except ValueError as exc:
        problems.append(str(exc))
    model = raw.get("model", "")
    if not isinstance(model, str):
        problems.append("model must be a string")
        model = ""
    weight = _number(raw, "weight", DEFAULT_WEIGHT, problems)
    start = _number(raw, "guidance_start", DEFAULT_GUIDANCE_START, problems)
    end = _number(raw, "guidance_end", DEFAULT_GUIDANCE_END, problems)
    if not MIN_WEIGHT <= weight <= MAX_WEIGHT:
        problems.append(f"weight must be between {MIN_WEIGHT:g} and {MAX_WEIGHT:g}")
    if not (0.0 <= start <= 1.0 and 0.0 <= end <= 1.0):
        problems.append("guidance_start and guidance_end must be between 0 and 1")
    elif not start < end:
        problems.append("guidance_start must be lower than guidance_end")
    control_mode = raw.get("control_mode", DEFAULT_CONTROL_MODE)
    if control_mode not in CONTROL_MODES:
        problems.append("control_mode must be one of: " + ", ".join(CONTROL_MODES))
    resize_mode = raw.get("resize_mode", DEFAULT_RESIZE_MODE)
    if resize_mode not in RESIZE_MODES:
        problems.append("resize_mode must be one of: " + ", ".join(RESIZE_MODES))
    preprocessor = raw.get("preprocessor", PREPROCESSOR_NONE)
    if preprocessor != PREPROCESSOR_NONE:
        problems.append(
            "preprocessor must be 'None': automatic pose detection is not supported, supply a rendered OpenPose map"
        )
    if problems:
        return None, tuple(problems)
    return (
        OpenPoseSelection(
            asset=asset,
            enabled=enabled,
            model=model.strip(),
            weight=weight,
            guidance_start=start,
            guidance_end=end,
            control_mode=str(control_mode),
            resize_mode=str(resize_mode),
            preprocessor=PREPROCESSOR_NONE,
        ),
        (),
    )


def declaration_enabled(raw: Any) -> bool:
    """Whether a raw slot value *asks* for conditioning, without validating it (tolerant: never raises)."""

    return isinstance(raw, Mapping) and raw.get("enabled", True) is True


def new_declaration(asset: str, *, model: str = "") -> dict[str, Any]:
    """A fresh, default-valued declaration for a chosen library image (validated; the picker's starting point)."""

    return OpenPoseSelection(asset=normalize_asset_identity(asset), model=str(model or "")).to_dict()


__all__ = [
    "CONTRACT",
    "ConditioningError",
    "CONTROL_MODES",
    "DEFAULT_CONTROL_MODE",
    "DEFAULT_GUIDANCE_END",
    "DEFAULT_GUIDANCE_START",
    "DEFAULT_RESIZE_MODE",
    "DEFAULT_WEIGHT",
    "MAX_WEIGHT",
    "MIN_WEIGHT",
    "OpenPoseDeclarationError",
    "OpenPoseSelection",
    "PREPROCESSOR_NONE",
    "RESIZE_MODES",
    "SLOT_FIELD",
    "SUPPORTED_EXTENSIONS",
    "declaration_enabled",
    "declaration_problems",
    "new_declaration",
    "normalize_asset_identity",
    "parse_declaration",
]
