"""ADetailer-Neo control truth (PR-REFINE-160): the arguments the pinned extension accepts, and the facts derived from them.

The managed Forge Neo runtime pins ADetailer-Neo at ``af228eba7a3f3691a25bcd1fc94aa95e600dd3e6`` (``lib_adetailer/args.py``).
That schema defines exactly the per-pass arguments below. Two of its behaviors matter for control truth:

* An argument dict that fails the schema is *dropped silently* by the extension (``get_args`` logs and ``continue``s), so a
  value outside these ranges makes a whole pass vanish without an API error.
* It exposes no per-image detection result: detections are only printed to the console. The only machine-readable trace of
  a pass in the response is the ``ADetailer model`` infotext line, which says the pass settings were accepted, not that
  anything was detected.

Everything here is pure and offline; nothing contacts a runtime. It is the single place where "supported" is defined for the
GUI card, the dispatch check and the effectiveness evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

PINNED_ADETAILER_NEO_REVISION = "af228eba7a3f3691a25bcd1fc94aa95e600dd3e6"

#: Pass-enablement defaults for newly authored ADetailer configurations only. They are never merged into a saved or
#: historical configuration, and they never touch the overall ``adetailer_enabled`` stage flag.
FRESH_PASS_DEFAULTS: Mapping[str, bool] = {"enable_face_pass": True, "enable_hands_pass": True}

MASK_FILTER_METHODS: tuple[str, ...] = ("Area", "Confidence")
MASK_MERGE_MODES: tuple[str, ...] = ("None", "Merge", "Merge and Invert")

#: Schema argument names the extension reads (everything else in a pass dict is ignored or, for a typo, a silent no-op).
SUPPORTED_ARG_KEYS: frozenset[str] = frozenset(
    {
        "ad_model",
        "ad_model_classes",
        "ad_tab_enable",
        "ad_prompt",
        "ad_negative_prompt",
        "ad_confidence",
        "ad_mask_filter_method",
        "ad_mask_k",
        "ad_mask_min_ratio",
        "ad_mask_max_ratio",
        "ad_dilate_erode",
        "ad_x_offset",
        "ad_y_offset",
        "ad_mask_merge_invert",
        "ad_mask_blur",
        "ad_denoising_strength",
        "ad_inpaint_only_masked",
        "ad_inpaint_only_masked_padding",
        "ad_use_inpaint_width_height",
        "ad_inpaint_width",
        "ad_inpaint_height",
        "ad_use_steps",
        "ad_steps",
        "ad_use_cfg_scale",
        "ad_cfg_scale",
        "ad_use_checkpoint",
        "ad_checkpoint",
        "ad_use_vae",
        "ad_vae",
        "ad_use_modules",
        "ad_modules",
        "ad_use_sampler",
        "ad_sampler",
        "ad_scheduler",
        "ad_use_noise_multiplier",
        "ad_noise_multiplier",
        "ad_restore_face",
        "ad_controlnet_model",
        "ad_controlnet_module",
        "ad_controlnet_weight",
        "ad_controlnet_guidance_start_end",
        "is_api",
    }
)

#: Historical StableNew fields that the pinned extension has no argument for. They are kept in saved data but never
#: presented as effective and never transmitted.
UNSUPPORTED_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "max_detections",
        "mask_feather",
        "adetailer_mask_feather",
        "ad_mask_feather",
        "ad_hands_mask_feather",
    }
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def schema_issues(args: Mapping[str, Any]) -> tuple[str, ...]:
    """Violations of the pinned schema in one pass dict; any of them makes the extension drop that pass silently."""

    issues: list[str] = [
        f"unsupported argument {key!r}" for key in sorted(set(args) - SUPPORTED_ARG_KEYS)
    ]

    def bounded(key: str, low: float | None, high: float | None, *, integer: bool = False) -> None:
        if key not in args:
            return
        value = _number(args[key])
        if value is None or (integer and value != int(value)):
            issues.append(f"{key} must be {'an integer' if integer else 'a number'}")
        elif (low is not None and value < low) or (high is not None and value > high):
            issues.append(f"{key}={args[key]!r} is outside [{low}, {high}]")

    bounded("ad_confidence", 0.0, 1.0)
    bounded("ad_mask_k", 0, None, integer=True)
    bounded("ad_mask_min_ratio", 0.0, 1.0)
    bounded("ad_mask_max_ratio", 0.0, 1.0)
    bounded("ad_dilate_erode", None, None, integer=True)
    bounded("ad_mask_blur", 0, None, integer=True)
    bounded("ad_denoising_strength", 0.0, 1.0)
    bounded("ad_inpaint_only_masked_padding", 0, None, integer=True)
    bounded("ad_inpaint_width", 1, None, integer=True)
    bounded("ad_inpaint_height", 1, None, integer=True)
    bounded("ad_steps", 1, 150, integer=True)
    bounded("ad_cfg_scale", 1.0, 24.0)
    if "ad_mask_filter_method" in args and args["ad_mask_filter_method"] not in MASK_FILTER_METHODS:
        issues.append(
            f"ad_mask_filter_method={args['ad_mask_filter_method']!r} is not one of {list(MASK_FILTER_METHODS)}"
        )
    if "ad_mask_merge_invert" in args and args["ad_mask_merge_invert"] not in MASK_MERGE_MODES:
        issues.append(
            f"ad_mask_merge_invert={args['ad_mask_merge_invert']!r} is not one of {list(MASK_MERGE_MODES)}"
        )
    return tuple(issues)


# ------------------------------------------------------------------------------------------------ detectors


def classify_detector(name: str) -> str:
    """``face`` / ``hand`` / ``other`` from the detector's own file naming convention (``hand_*`` vs ``face_*``)."""

    lowered = str(name or "").strip().lower()
    if "hand" in lowered:
        return "hand"
    if "face" in lowered:
        return "face"
    return "other"


def split_detectors(names: Iterable[str]) -> tuple[list[str], list[str]]:
    """``(face_options, hand_options)``; body/person and unknown detectors are valid for neither selector."""

    face: list[str] = []
    hand: list[str] = []
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        kind = classify_detector(name)
        if kind == "face" and name not in face:
            face.append(name)
        elif kind == "hand" and name not in hand:
            hand.append(name)
    return face, hand


def detector_status(selected: str, available: Sequence[str] | None, role: str) -> str:
    """``available`` | ``unavailable`` | ``wrong_role`` | ``unknown`` for one pass's selected detector.

    ``unknown`` means no trustworthy availability list exists (never treated as available *or* missing). A selected value is
    never substituted; the caller keeps it and reports this status.
    """

    name = str(selected or "").strip()
    if not name:
        return "unavailable"
    kind = classify_detector(name)
    if kind not in (role, "other"):
        return "wrong_role"
    if available is None:
        return "unknown"
    return "available" if name in set(available) else "unavailable"


__all__ = [
    "FRESH_PASS_DEFAULTS",
    "MASK_FILTER_METHODS",
    "MASK_MERGE_MODES",
    "PINNED_ADETAILER_NEO_REVISION",
    "SUPPORTED_ARG_KEYS",
    "UNSUPPORTED_CONFIG_KEYS",
    "classify_detector",
    "detector_status",
    "schema_issues",
    "split_detectors",
]
