"""PR-IMG-120: Ideogram 4 caption verification (official CaptionVerifier semantics) and prompt mapping."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from src.image_backends.ideogram4_caption import (
    MODE_AUTHORED,
    MODE_AUTOMATIC,
    CaptionError,
    is_authored_caption,
    resolve_caption,
    serialize_caption,
    verify_caption,
    verify_caption_text,
)
from tools.qualification.img110r.caption import FIXED_CAPTION, caption_json

VALID = {
    "high_level_description": "A blue teapot.",
    "style_description": {
        "aesthetics": "calm",
        "lighting": "soft",
        "photo": "50mm",
        "medium": "photograph",
        "color_palette": ["#2F5D8A"],
    },
    "compositional_deconstruction": {
        "background": "A wall.",
        "elements": [
            {
                "type": "obj",
                "bbox": [0, 0, 500, 500],
                "desc": "A teapot.",
                "color_palette": ["#FFFFFF"],
            },
            {"type": "text", "text": "OPEN", "desc": "A sign."},
        ],
    },
}


def _with(path: list[str | int], value: object) -> dict:
    caption = copy.deepcopy(VALID)
    target = caption
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return caption


def test_valid_and_110r_captions_pass_and_serialize_like_the_official_guide() -> None:
    assert verify_caption(VALID) == []
    assert verify_caption(FIXED_CAPTION) == []
    # Byte-identical to the 110R serialization (compact separators, literal non-ASCII).
    assert serialize_caption(FIXED_CAPTION) == caption_json()
    assert (
        serialize_caption(
            {
                "high_level_description": "café",
                "compositional_deconstruction": {"background": "", "elements": []},
            }
        ).count("café")
        == 1
    )


def test_minimal_caption_passes_and_deconstruction_is_required() -> None:
    assert (
        verify_caption({"compositional_deconstruction": {"background": "", "elements": []}}) == []
    )
    assert verify_caption({"high_level_description": "x"}) == [
        "root: 'compositional_deconstruction' must exist"
    ]
    assert verify_caption([1]) == ["root: expected a JSON object (dict), got list"]


@pytest.mark.parametrize(
    ("caption", "fragment"),
    [
        ({**VALID, "extra": 1}, "unknown keys ['extra']"),
        (_with(["high_level_description"], 3), "high_level_description: expected a string"),
        (_with(["style_description"], "x"), "style_description: expected a dict"),
        (_with(["style_description", "art_style"], "oil"), "contains both 'photo' and 'art_style'"),
        (
            {**VALID, "style_description": {"aesthetics": "a", "lighting": "b", "medium": "c"}},
            "expected one of 'photo'",
        ),
        (
            {
                **VALID,
                "style_description": {
                    "lighting": "b",
                    "aesthetics": "a",
                    "photo": "p",
                    "medium": "c",
                },
            },
            "style_description: key order",
        ),
        (_with(["style_description", "color_palette"], ["#abcdef"]), "is not a valid #RRGGBB"),
        (_with(["style_description", "color_palette"], ["#FFFFFF"] * 17), "too many colors (17)"),
        (_with(["compositional_deconstruction"], {"elements": []}), "'background' must exist"),
        (_with(["compositional_deconstruction", "background"], 1), "background: expected a string"),
        (_with(["compositional_deconstruction"], {"background": ""}), "'elements' must exist"),
        (_with(["compositional_deconstruction"], {"elements": [], "background": ""}), "key order"),
        (_with(["compositional_deconstruction", "elements"], {}), "elements: expected a list"),
        (
            _with(["compositional_deconstruction", "elements", 0, "type"], "shape"),
            "'type' must be one of",
        ),
        (
            _with(["compositional_deconstruction", "elements", 0], {"bbox": [0, 0, 1, 1]}),
            "'type' must exist",
        ),
        (
            _with(["compositional_deconstruction", "elements", 0, "bbox"], [0, 0, 1]),
            "expected [ymin, xmin, ymax, xmax]",
        ),
        (
            _with(["compositional_deconstruction", "elements", 0, "bbox"], [0, 0, 1.5, 1]),
            "all values must be int",
        ),
        (
            _with(["compositional_deconstruction", "elements", 0, "bbox"], [0, 0, 1001, 1]),
            "values must be in [0, 1000]",
        ),
        (
            _with(["compositional_deconstruction", "elements", 0, "bbox"], [9, 0, 1, 1]),
            "ymin (9) > ymax (1)",
        ),
        (
            _with(["compositional_deconstruction", "elements", 0, "bbox"], [0, 9, 1, 1]),
            "xmin (9) > xmax (1)",
        ),
        (
            _with(
                ["compositional_deconstruction", "elements", 0, "color_palette"], ["#FFFFFF"] * 6
            ),
            "too many colors (6)",
        ),
        (
            _with(
                ["compositional_deconstruction", "elements", 1],
                {"type": "text", "desc": "d", "text": "t"},
            ),
            "elements[1]: key order",
        ),
        (
            _with(
                ["compositional_deconstruction", "elements", 1],
                {"type": "obj", "desc": "d", "text": "t"},
            ),
            "not allowed in this context",
        ),
    ],
)
def test_every_official_rule_is_enforced(caption: dict, fragment: str) -> None:
    findings = verify_caption(caption)
    assert any(fragment in finding for finding in findings), findings


def test_raw_text_checks_json_and_ascii_escapes() -> None:
    assert verify_caption_text(json.dumps(VALID)) == []
    assert verify_caption_text("{nope")[0].startswith("invalid JSON")
    escaped = json.dumps(
        {
            "high_level_description": "café",
            "compositional_deconstruction": {"background": "", "elements": []},
        },
        ensure_ascii=True,
    )
    assert "non-ASCII unicode escape" in verify_caption_text(escaped)[0]


def test_automatic_mapping_is_minimal_valid_and_deterministic() -> None:
    first = resolve_caption("  A red bicycle leaning on a brick wall  ")
    second = resolve_caption("  A red bicycle leaning on a brick wall  ")
    assert first == second
    assert first.mode == MODE_AUTOMATIC
    assert first.caption == {
        "high_level_description": "A red bicycle leaning on a brick wall",
        "compositional_deconstruction": {"background": "", "elements": []},
    }
    assert first.sha256 == hashlib.sha256(first.caption_json.encode("utf-8")).hexdigest()
    assert first.to_manifest()["caption_mapping_version"] == 1


def test_authored_caption_is_used_verbatim_and_never_rewritten() -> None:
    text = json.dumps(VALID, ensure_ascii=False, indent=2)
    resolved = resolve_caption(text)
    assert resolved.mode == MODE_AUTHORED and is_authored_caption(text)
    assert resolved.caption == VALID
    assert resolved.caption_json == serialize_caption(VALID)


@pytest.mark.parametrize(
    ("prompt", "fragment"),
    [
        ("", "needs a positive prompt"),
        ("   ", "needs a positive prompt"),
        (json.dumps({"high_level_description": "x"}), "compositional_deconstruction' must exist"),
        ("{not json at all", "not a valid JSON object"),
        ("a cat <lora:style:0.8>", "LoRA, hypernetwork or embedding"),
        ("a cat, embedding:bad_hands", "LoRA, hypernetwork or embedding"),
        ("x" * 20_001, "limited to 20000 characters"),
    ],
)
def test_refusals_name_the_problem(prompt: str, fragment: str) -> None:
    with pytest.raises(CaptionError, match=None) as raised:
        resolve_caption(prompt)
    assert fragment in str(raised.value)
