"""Ideogram 4 structured-caption verification and prompt mapping (PR-IMG-120, owner decision 2).

Ideogram 4 is trained on structured JSON captions; plain text is off its preferred distribution. This module is the one
place StableNew turns a positive prompt into the caption the model receives:

* **authored**: a prompt that parses as a JSON object is the operator's caption. It must pass verification, otherwise the
  work is refused with the findings; it is never rewritten.
* **automatic**: any other prompt becomes the minimal valid caption ``{"high_level_description": <text>,
  "compositional_deconstruction": {"background": "", "elements": []}}``.

``verify_caption`` / ``verify_caption_text`` implement the rules of the official ``CaptionVerifier``
(``ideogram4/caption_verifier.py`` of ideogram-oss/ideogram4 @ 990fe1c4). The code is an independent implementation of
those rules, not a copy. StableNew treats every finding as a refusal, matching the official pipeline's default
``raise_on_caption_issues=True``.

The mapping is versioned (``CAPTION_MAPPING_VERSION``) and pure: the same positive prompt always yields the same caption,
so a frozen NJR prompt fully determines what the model receives and replay re-derives it exactly. Nothing here performs
I/O or imports a model library.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CAPTION_MAPPING_VERSION = 1
MODE_AUTHORED = "authored"
MODE_AUTOMATIC = "automatic"

_TOP_LEVEL_KEYS = frozenset(
    {"high_level_description", "style_description", "compositional_deconstruction"}
)
_STYLE_KEYS = frozenset({"aesthetics", "lighting", "photo", "art_style", "medium", "color_palette"})
_STYLE_ORDER_PHOTO = ("aesthetics", "lighting", "photo", "medium", "color_palette")
_STYLE_ORDER_NON_PHOTO = ("aesthetics", "lighting", "medium", "art_style", "color_palette")
_DECONSTRUCTION_ORDER = ("background", "elements")
_ELEMENT_KEYS = frozenset({"type", "bbox", "text", "desc", "color_palette"})
_ELEMENT_ORDER = {
    "obj": ("type", "bbox", "desc", "color_palette"),
    "text": ("type", "bbox", "text", "desc", "color_palette"),
}
#: Keys that appear in the expected order only when the caption carries them.
_OPTIONAL_ORDERED = frozenset({"bbox", "color_palette"})
_BBOX_MIN, _BBOX_MAX = 0, 1000
_STYLE_PALETTE_MAX = 16
_ELEMENT_PALETTE_MAX = 5
_HEX_DIGITS = frozenset("0123456789ABCDEF")
#: ``\uXXXX`` escapes of non-ASCII code points (U+0080 and above).
_NON_ASCII_ESCAPE = re.compile(
    r"\\u(?:00[89a-fA-F][0-9a-fA-F]|0[1-9a-fA-F][0-9a-fA-F]{2}|[1-9a-fA-F][0-9a-fA-F]{3})"
)
#: Tokens that are StableNew/WebUI authoring syntax, not prose: never sent to Ideogram.
_FOREIGN_TOKEN = re.compile(r"<\s*(?:lora|lyco|hypernet)\s*:|embedding\s*:", re.IGNORECASE)
MAX_PROMPT_CHARS = 20_000


class CaptionError(ValueError):
    """A prompt cannot become a valid Ideogram 4 caption; ``findings`` lists every problem."""

    def __init__(self, message: str, findings: Sequence[str] = ()) -> None:
        super().__init__(message if not findings else f"{message}: " + "; ".join(findings))
        self.findings = tuple(findings)


@dataclass(frozen=True, slots=True)
class CaptionResolution:
    """What the model receives for one positive prompt (recorded in the image manifest)."""

    mode: str
    caption: Mapping[str, Any]
    caption_json: str
    sha256: str
    mapping_version: int = CAPTION_MAPPING_VERSION

    def to_manifest(self) -> dict[str, Any]:
        return {
            "caption_mode": self.mode,
            "caption_json": self.caption_json,
            "caption_sha256": self.sha256,
            "caption_mapping_version": self.mapping_version,
        }


# -- verification -----------------------------------------------------------------------------------------------


def _unknown_keys(
    obj: Mapping[str, Any], known: frozenset[str], path: str, findings: list[str]
) -> None:
    unknown = [key for key in obj if key not in known]
    if unknown:
        findings.append(f"{path}: unknown keys {unknown} (not in schema)")


def _key_order(
    obj: Mapping[str, Any], expected: Sequence[str], path: str, findings: list[str]
) -> None:
    present = tuple(key for key in obj if key in expected)
    if present != tuple(expected):
        findings.append(f"{path}: key order is {present}, expected {tuple(expected)}")
    extra = [key for key in obj if key not in expected]
    if extra:
        findings.append(f"{path}: keys {extra} are not allowed in this context")


def _expected_order(order: Sequence[str], obj: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(key for key in order if key not in _OPTIONAL_ORDERED or key in obj)


def _palette(palette: Any, path: str, limit: int, findings: list[str]) -> None:
    if not isinstance(palette, list):
        findings.append(f"{path}: expected a list")
        return
    if len(palette) > limit:
        findings.append(f"{path}: too many colors ({len(palette)}), expected at most {limit}")
        return
    for index, colour in enumerate(palette):
        if not (
            isinstance(colour, str)
            and len(colour) == 7
            and colour[0] == "#"
            and set(colour[1:]) <= _HEX_DIGITS
        ):
            findings.append(f"{path}[{index}]: '{colour}' is not a valid #RRGGBB hex color")


def _style(style: Any, findings: list[str]) -> None:
    if not isinstance(style, dict):
        findings.append("style_description: expected a dict")
        return
    _unknown_keys(style, _STYLE_KEYS, "style_description", findings)
    has_photo, has_art = "photo" in style, "art_style" in style
    if has_photo == has_art:
        findings.append(
            "style_description: contains both 'photo' and 'art_style'; expected exactly one"
            if has_photo
            else "style_description: expected one of 'photo' (for photo captions) or 'art_style' (for non-photo captions)"
        )
        return
    order = _STYLE_ORDER_PHOTO if has_photo else _STYLE_ORDER_NON_PHOTO
    _key_order(style, _expected_order(order, style), "style_description", findings)
    if "color_palette" in style:
        _palette(
            style["color_palette"], "style_description.color_palette", _STYLE_PALETTE_MAX, findings
        )


def _bbox(index: int, bbox: Any, findings: list[str]) -> None:
    path = f"elements[{index}].bbox"
    if not isinstance(bbox, list) or len(bbox) != 4:
        findings.append(f"{path}: expected [ymin, xmin, ymax, xmax]")
        return
    # ``bool`` is an ``int`` subclass; a JSON caption never carries one, so reject it explicitly.
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in bbox):
        findings.append(f"{path}: all values must be int")
        return
    ymin, xmin, ymax, xmax = bbox
    if not all(_BBOX_MIN <= value <= _BBOX_MAX for value in bbox):
        findings.append(f"{path}: values must be in [{_BBOX_MIN}, {_BBOX_MAX}], got {bbox}")
    if ymin > ymax:
        findings.append(f"{path}: ymin ({ymin}) > ymax ({ymax})")
    if xmin > xmax:
        findings.append(f"{path}: xmin ({xmin}) > xmax ({xmax})")


def _element(index: int, element: Any, findings: list[str]) -> None:
    path = f"elements[{index}]"
    if not isinstance(element, dict):
        findings.append(f"{path}: expected a dict")
        return
    _unknown_keys(element, _ELEMENT_KEYS, path, findings)
    if "type" not in element:
        findings.append(f"{path}: 'type' must exist")
        return
    kind = element.get("type")
    if kind not in _ELEMENT_ORDER:
        findings.append(f"{path}: 'type' must be one of {sorted(_ELEMENT_ORDER)}")
        return
    _key_order(element, _expected_order(_ELEMENT_ORDER[kind], element), path, findings)
    if "bbox" in element:
        _bbox(index, element["bbox"], findings)
    if "color_palette" in element:
        _palette(element["color_palette"], f"{path}.color_palette", _ELEMENT_PALETTE_MAX, findings)


def _deconstruction(value: Any, findings: list[str]) -> None:
    if not isinstance(value, dict):
        findings.append("compositional_deconstruction: expected a dict")
        return
    if "background" not in value:
        findings.append("compositional_deconstruction: 'background' must exist")
        return
    if not isinstance(value["background"], str):
        findings.append(
            f"compositional_deconstruction.background: expected a string, got {type(value['background']).__name__}"
        )
        return
    if "elements" not in value:
        findings.append("compositional_deconstruction: 'elements' must exist")
        return
    _key_order(value, _DECONSTRUCTION_ORDER, "compositional_deconstruction", findings)
    elements = value["elements"]
    if not isinstance(elements, list):
        findings.append("compositional_deconstruction.elements: expected a list")
        return
    for index, element in enumerate(elements):
        _element(index, element, findings)


def verify_caption(caption: Any) -> list[str]:
    """Every schema finding for a parsed caption (empty when it passes)."""

    findings: list[str] = []
    if not isinstance(caption, dict):
        return [f"root: expected a JSON object (dict), got {type(caption).__name__}"]
    _unknown_keys(caption, _TOP_LEVEL_KEYS, "root", findings)
    if "high_level_description" in caption and not isinstance(
        caption["high_level_description"], str
    ):
        findings.append(
            f"high_level_description: expected a string, got {type(caption['high_level_description']).__name__}"
        )
    if "style_description" in caption:
        _style(caption["style_description"], findings)
    if "compositional_deconstruction" in caption:
        _deconstruction(caption["compositional_deconstruction"], findings)
    else:
        findings.append("root: 'compositional_deconstruction' must exist")
    return findings


def ascii_escape_findings(raw_text: str) -> list[str]:
    """Flag ``\\uXXXX`` escapes of non-ASCII characters in text that has no literal non-ASCII (``ensure_ascii=True``)."""

    matches = _NON_ASCII_ESCAPE.findall(raw_text)
    if not matches or any(ord(char) > 0x7F for char in raw_text):
        return []
    return [
        f"raw text: found {len(matches)} non-ASCII unicode escape(s) and no literal non-ASCII characters; "
        "write the caption with literal UTF-8 characters (json.dumps(..., ensure_ascii=False))"
    ]


def verify_caption_text(raw_text: str) -> list[str]:
    """Every finding for a raw JSON caption string (escape check, then JSON, then schema)."""

    findings = ascii_escape_findings(raw_text)
    try:
        caption = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return [*findings, f"invalid JSON: {exc}"]
    return findings + verify_caption(caption)


# -- serialization and mapping ----------------------------------------------------------------------------------


def serialize_caption(caption: Mapping[str, Any]) -> str:
    """Compact, key order preserved, non-ASCII literal: exactly the official guide's serialization."""

    return json.dumps(caption, separators=(",", ":"), ensure_ascii=False)


def _parse_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def is_authored_caption(prompt: str) -> bool:
    """Whether a positive prompt is an operator-authored caption (a JSON object), by content alone."""

    return _parse_object(str(prompt or "")) is not None


def automatic_caption(text: str) -> dict[str, Any]:
    return {
        "high_level_description": text,
        "compositional_deconstruction": {"background": "", "elements": []},
    }


def resolve_caption(prompt: str) -> CaptionResolution:
    """Map one positive prompt to the caption Ideogram 4 receives, or raise ``CaptionError``."""

    text = str(prompt or "")
    if not text.strip():
        raise CaptionError("Ideogram 4 needs a positive prompt or a JSON caption")
    if len(text) > MAX_PROMPT_CHARS:
        raise CaptionError(f"Ideogram 4 prompts are limited to {MAX_PROMPT_CHARS} characters")
    authored = _parse_object(text)
    if authored is not None:
        findings = ascii_escape_findings(text) + verify_caption(authored)
        if findings:
            raise CaptionError(
                "The JSON caption does not follow the Ideogram 4 caption schema", findings
            )
        caption, mode = authored, MODE_AUTHORED
    else:
        if text.lstrip().startswith("{"):
            raise CaptionError(
                "The prompt starts with '{' but is not a valid JSON object; write a valid JSON caption or plain text"
            )
        if _FOREIGN_TOKEN.search(text):
            raise CaptionError(
                "Ideogram 4 does not support LoRA, hypernetwork or embedding tokens in the prompt"
            )
        caption, mode = automatic_caption(text.strip()), MODE_AUTOMATIC
        findings = verify_caption(caption)
        if findings:  # pragma: no cover - the automatic caption is valid by construction
            raise CaptionError("Internal caption mapping error", findings)
    serialized = serialize_caption(caption)
    return CaptionResolution(
        mode=mode,
        caption=caption,
        caption_json=serialized,
        sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )


__all__ = [
    "CAPTION_MAPPING_VERSION",
    "MODE_AUTHORED",
    "MODE_AUTOMATIC",
    "CaptionError",
    "CaptionResolution",
    "ascii_escape_findings",
    "automatic_caption",
    "is_authored_caption",
    "resolve_caption",
    "serialize_caption",
    "verify_caption",
    "verify_caption_text",
]
