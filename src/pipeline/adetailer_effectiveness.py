"""Versioned ADetailer effectiveness evidence (PR-REFINE-160): what was detected, what ran, what changed, what was judged.

``stablenew.adetailer-effectiveness.v1`` keeps four different outcomes apart, because none implies the next:

1. **Detection.** Did a detector report a face or hand? The pinned ADetailer-Neo exposes no machine-readable detector
   result (only console text), so Forge YOLO detections are ``unknown`` and are never inferred from a checkbox, a successful
   request, a non-empty image or StableNew's own YuNet observation (a different, CPU-side detector).
2. **Execution.** Was each pass requested, were its settings accepted by the extension (the response infotext carries an
   ``ADetailer model`` line per accepted, non-skipped pass), and did the single combined request complete?
3. **Observable image change.** A bounded pixel difference between the image sent to ADetailer and the image it returned.
   Larger is not better, and a combined two-pass difference is never attributed to one pass.
4. **Visual improvement.** Only an operator's before/after review can state it; until then it is ``unreviewed``.

Pure helpers; the only I/O is decoding the two image files for the comparison. Nothing here mutates an NJR or contacts a
runtime, and no field in this record ever says an anatomy fix succeeded.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.pipeline.adetailer_contract import schema_issues

SCHEMA = "stablenew.adetailer-effectiveness.v1"
IMAGE_DIFF_METHOD = "pil_rgb_abs_diff/1"
MAX_COMPARE_PIXELS = 64_000_000
VISUAL_OUTCOMES: tuple[str, ...] = ("unreviewed", "improved", "unchanged", "worsened", "uncertain")
FORGE_DETECTION_REASON = "the pinned ADetailer-Neo reports detections only as console text; no machine-readable detector result exists"

#: Pass settings echoed into the record (supported arguments only; prompts are deliberately omitted).
_SETTING_KEYS = (
    "ad_model",
    "ad_confidence",
    "ad_mask_filter_method",
    "ad_mask_k",
    "ad_mask_min_ratio",
    "ad_mask_max_ratio",
    "ad_dilate_erode",
    "ad_mask_blur",
    "ad_mask_merge_invert",
    "ad_inpaint_only_masked",
    "ad_inpaint_only_masked_padding",
    "ad_use_inpaint_width_height",
    "ad_inpaint_width",
    "ad_inpaint_height",
    "ad_steps",
    "ad_cfg_scale",
    "ad_denoising_strength",
    "ad_sampler",
    "ad_scheduler",
)
_MODEL_LINE = re.compile(r"ADetailer model(?: \d+(?:st|nd|rd|th))?: ([^,\n]+)")


# ------------------------------------------------------------------------------------------------ image change


def compare_images(before: Path | str | None, after: Path | str | None) -> dict[str, Any]:
    """Bounded RGB pixel difference of two image files; anything not comparable is reported as such, never as 'unchanged'."""

    result: dict[str, Any] = {
        "method": IMAGE_DIFF_METHOD,
        "status": "not_comparable",
        "reason": None,
        "identical": None,
        "changed_pixel_fraction": None,
        "mean_abs_difference": None,
        "size": None,
        "attribution": (
            "combined_post_adetailer; not attributable to a single pass; not a quality measure; the stage also runs a "
            "whole-image img2img pass at its own denoise strength (the extension's skip-img2img is off), so a "
            "difference is expected and is not evidence of a correction"
        ),
    }
    if not before or not after:
        result["reason"] = "missing input or output image reference"
        return result
    try:
        from PIL import Image, ImageChops
    except ImportError:  # pragma: no cover - Pillow is a hard dependency of the application
        result["reason"] = "Pillow is unavailable"
        return result
    before_path, after_path = Path(before), Path(after)
    if not before_path.is_file() or not after_path.is_file():
        result["reason"] = "input or output image file is missing"
        return result
    try:
        with Image.open(before_path) as first, Image.open(after_path) as second:
            if first.size != second.size:
                result["reason"] = (
                    f"dimensions differ ({first.size[0]}x{first.size[1]} vs {second.size[0]}x{second.size[1]})"
                )
                return result
            width, height = first.size
            if width * height > MAX_COMPARE_PIXELS:
                result["reason"] = "image exceeds the comparison pixel bound"
                return result
            diff = ImageChops.difference(first.convert("RGB"), second.convert("RGB"))
    except Exception as exc:  # noqa: BLE001 - a decode failure is "not comparable", never a quality verdict
        result["reason"] = f"decode failed ({type(exc).__name__})"
        return result
    result["size"] = [width, height]
    bands = diff.split()
    histogram = [sum(band.histogram()[i] for band in bands) for i in range(256)]
    total_samples = width * height * 3
    result["mean_abs_difference"] = round(
        sum(i * count for i, count in enumerate(histogram)) / total_samples, 6
    )
    if diff.getbbox() is None:
        result["identical"] = True
        result["changed_pixel_fraction"] = 0.0
    else:
        result["identical"] = False
        changed = ImageChops.lighter(ImageChops.lighter(*bands[:2]), bands[2]).point(
            lambda v: 255 if v else 0
        )
        result["changed_pixel_fraction"] = round(changed.histogram()[255] / (width * height), 6)
    result["status"] = "measured"
    return result


# ------------------------------------------------------------------------------------------------ execution


def response_infotexts(response: Any) -> list[str] | None:
    """The generation infotexts of a WebUI response, or ``None`` when the response carries none (unknown, not empty)."""

    info = response.get("info") if isinstance(response, Mapping) else None
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            return None
    texts = info.get("infotexts") if isinstance(info, Mapping) else None
    if isinstance(texts, list) and texts and all(isinstance(item, str) for item in texts):
        return list(texts)
    return None


def accepted_detectors(infotexts: Sequence[str] | None) -> list[str] | None:
    """Detector names the extension echoed as accepted passes, or ``None`` when no infotext exists."""

    if not infotexts:
        return None
    return [match.strip() for match in _MODEL_LINE.findall(infotexts[0])]


def _acknowledged(
    detector: str, requested: bool, accepted: list[str] | None, others: Sequence[str]
) -> bool | None:
    """True/False only when attributable by detector name; ``None`` when unknown or ambiguous."""

    if not requested:
        return False if accepted is not None and detector not in accepted else None
    if accepted is None:
        return None
    if detector in others:
        return None  # both passes name the same detector: one echoed line cannot be attributed to either
    return detector in accepted


def _pass_record(
    args: Mapping[str, Any],
    accepted: list[str] | None,
    other_detector: str,
    request_completed: bool,
) -> dict[str, Any]:
    requested = bool(args.get("ad_tab_enable"))
    detector = str(args.get("ad_model") or "")
    return {
        "requested_enabled": requested,
        "detector": detector,
        "settings": {key: args[key] for key in _SETTING_KEYS if key in args},
        "schema_issues": list(schema_issues(args)),
        "acknowledged_by_extension": _acknowledged(detector, requested, accepted, [other_detector])
        if requested
        else None,
        "acknowledgement_source": "response_infotext" if accepted is not None else "unavailable",
        "request_completed": bool(request_completed) if requested else None,
    }


def _yunet_record(adaptive: Mapping[str, Any] | None) -> dict[str, Any]:
    """StableNew's own CPU-side YuNet observation, kept apart from the Forge detector.

    Only an ``available`` assessment can state a count; ``unavailable``/``error`` stay unknown and are never reported as a
    confirmed absence of faces.
    """

    bundle = adaptive.get("decision_bundle") if isinstance(adaptive, Mapping) else None
    observation = bundle.get("observation") if isinstance(bundle, Mapping) else None
    assessment = observation.get("subject_assessment") if isinstance(observation, Mapping) else None
    if not isinstance(assessment, Mapping):
        return {
            "source": "stablenew_yunet",
            "status": "not_observed",
            "face_detected": None,
            "count": None,
        }
    raw_status = str(assessment.get("detection_status") or "unknown")
    count = assessment.get("detection_count")
    if raw_status == "available" and isinstance(count, int) and not isinstance(count, bool):
        return {
            "source": "stablenew_yunet",
            "status": "observed",
            "detector_id": assessment.get("detector_id"),
            "face_detected": count > 0,
            "count": count,
            "note": "a StableNew observation used for refinement policy; not evidence of what Forge's YOLO detected",
        }
    return {
        "source": "stablenew_yunet",
        "status": "unknown",
        "detector_status": raw_status,
        "detector_id": assessment.get("detector_id"),
        "face_detected": None,
        "count": None,
        "note": "the detector was unavailable or failed; this is not a confirmed absence of faces",
    }


def build_effectiveness(
    *,
    face_args: Mapping[str, Any],
    hand_args: Mapping[str, Any],
    request_completed: bool,
    input_image: Path | str | None,
    output_image: Path | str | None,
    infotexts: Sequence[str] | None = None,
    adaptive_refinement: Mapping[str, Any] | None = None,
    dispatched: bool = True,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    """The whole evidence record for one completed ADetailer stage (visual review always starts ``unreviewed``)."""

    accepted = accepted_detectors(infotexts)
    face_detector, hand_detector = (
        str(face_args.get("ad_model") or ""),
        str(hand_args.get("ad_model") or ""),
    )
    face = _pass_record(face_args, accepted, hand_detector, request_completed)
    hands = _pass_record(hand_args, accepted, face_detector, request_completed)

    def detection(detector: str, requested: bool) -> dict[str, Any]:
        return {
            "detector": detector,
            "source": "forge_adetailer_neo_yolo",
            "requested": requested,
            "status": "unknown",
            "count": None,
            "reason": FORGE_DETECTION_REASON,
        }

    return {
        "schema": SCHEMA,
        "detection": {
            "face": detection(face_detector, face["requested_enabled"]),
            "hands": detection(hand_detector, hands["requested_enabled"]),
            "stablenew_yunet": _yunet_record(adaptive_refinement),
        },
        "execution": {
            "request": {
                "dispatched": bool(dispatched),
                "completed": bool(request_completed),
                "passes_in_one_request": True,
                "skipped_reason": skipped_reason,
            },
            "face": face,
            "hands": hands,
            "attribution": (
                "one combined request: request-level completion is not independent proof of either pass; "
                "acknowledgement is the extension echoing accepted settings, not a detection"
            ),
        },
        "image_change": (
            compare_images(input_image, output_image)
            if dispatched
            else {
                "method": IMAGE_DIFF_METHOD,
                "status": "not_comparable",
                "reason": "no ADetailer request was sent, so there is no output to compare",
                "identical": None,
                "changed_pixel_fraction": None,
                "mean_abs_difference": None,
                "size": None,
            }
        ),
        "visual_review": {
            "face": "unreviewed",
            "hands": "unreviewed",
            "source": None,
            "note": "improvement is only ever an operator-reviewed conclusion; detection, completion and pixel change imply none",
        },
        "improvement_claimed": False,
    }


__all__ = [
    "FORGE_DETECTION_REASON",
    "IMAGE_DIFF_METHOD",
    "SCHEMA",
    "VISUAL_OUTCOMES",
    "accepted_detectors",
    "build_effectiveness",
    "compare_images",
    "response_infotexts",
]
