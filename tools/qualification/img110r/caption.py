"""The single fixed structured JSON caption used by every PR-IMG-110R run.

Ideogram 4 is trained on structured JSON captions (``docs/prompting.md`` of the official
repository); a plain-text prompt is off-distribution.  This caption follows the documented
schema and key order so the official ``CaptionVerifier`` accepts it without a remote
magic-prompt call.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

FIXED_CAPTION: dict[str, Any] = {
    "high_level_description": (
        "A studio photograph of a blue ceramic teapot and a lemon on a wooden table beside a "
        "small hand-lettered sign that reads OPEN."
    ),
    "style_description": {
        "aesthetics": "calm, warm, minimal still life",
        "lighting": "soft window light from the left, gentle shadows",
        "photo": "50mm lens, shallow depth of field, eye-level",
        "medium": "photograph",
        "color_palette": ["#2F5D8A", "#F2D14B", "#8B5E3C", "#F4EFE6"],
    },
    "compositional_deconstruction": {
        "background": (
            "A plain off-white plaster wall behind a worn oak tabletop, softly out of focus, "
            "lit by pale daylight."
        ),
        "elements": [
            {
                "type": "obj",
                "bbox": [280, 180, 800, 560],
                "desc": (
                    "A glossy blue ceramic teapot with a curved spout, a round lid and a thin "
                    "handle, standing on the oak table."
                ),
            },
            {
                "type": "obj",
                "bbox": [600, 620, 800, 800],
                "desc": "A whole bright yellow lemon with a small green leaf resting on the table.",
            },
            {
                "type": "text",
                "bbox": [140, 560, 280, 900],
                "text": "OPEN",
                "desc": "Black hand-painted capital letters on a small cream wooden sign.",
            },
        ],
    },
}

_STYLE_ORDER_PHOTO = ["aesthetics", "lighting", "photo", "medium", "color_palette"]
_ELEMENT_ORDER = {
    "obj": ["type", "bbox", "desc", "color_palette"],
    "text": ["type", "bbox", "text", "desc", "color_palette"],
}


def caption_json(caption: dict[str, Any] | None = None) -> str:
    """Serialise exactly as the official guide prescribes (compact, non-ASCII preserved)."""

    return json.dumps(caption or FIXED_CAPTION, separators=(",", ":"), ensure_ascii=False)


def caption_sha256(caption: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(caption_json(caption).encode("utf-8")).hexdigest()


def shape_problems(caption: dict[str, Any]) -> list[str]:
    """Deterministic subset of the official schema rules (key order, hex colours, bbox range).

    The authoritative check is the official ``CaptionVerifier`` executed inside the reference
    environment on every run; this function only guards against accidental edits in CI.
    """

    problems: list[str] = []
    top = list(caption)
    if top != ["high_level_description", "style_description", "compositional_deconstruction"]:
        problems.append(f"unexpected top-level keys {top}")
    style = caption.get("style_description", {})
    keys = list(style)
    if keys != _STYLE_ORDER_PHOTO:
        problems.append(f"style key order {keys}")
    palettes = list(style.get("color_palette", []))
    deconstruction = caption.get("compositional_deconstruction", {})
    if list(deconstruction) != ["background", "elements"]:
        problems.append("compositional_deconstruction must be background then elements")
    for element in deconstruction.get("elements", []):
        expected = [k for k in _ELEMENT_ORDER[element["type"]] if k in element]
        if list(element) != expected:
            problems.append(f"element key order {list(element)}")
        bbox = element.get("bbox")
        if bbox and not (len(bbox) == 4 and all(0 <= v <= 1000 for v in bbox)):
            problems.append(f"bbox out of range {bbox}")
        palettes += element.get("color_palette", [])
    for colour in palettes:
        if not (len(colour) == 7 and colour[0] == "#" and colour == colour.upper()):
            problems.append(f"colour {colour} is not uppercase #RRGGBB")
    return problems
