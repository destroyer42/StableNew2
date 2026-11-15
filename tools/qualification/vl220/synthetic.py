"""Deterministic synthetic assets, cases and by-construction labels for the harness wiring check (PR-AI-VL-220).

Every image is drawn by this module from a fixed table (no random numbers, no clock, no filesystem, no network) and encoded as
an uncompressed PNG, so the bytes, and therefore the SHA-256 pinned in the case set, are identical on every machine. The
labels follow from how the scene was drawn and are written to a separate document with labeler ``synthetic_by_construction``.

These scenes prove the harness plumbing (schemas, scoring, leak checks). They say nothing about how a model handles real
generated images; that needs existing assets with labels written by a person (``contract.validate_label_set`` refuses
anything else).
"""

from __future__ import annotations

import copy
import functools
import hashlib
import struct
import zlib
from collections.abc import Mapping
from typing import Any

from tools.qualification.vl220 import contract

SET_ID = "vl220-synthetic-1"
#: The same deterministic scenes drawn four times larger (512 x 512 per cell): a second set with its own pins (PR-AI-VL-222).
SET_ID_512 = "vl220-synthetic-512-1"
#: The 512-pixel scenes with a varied adherence table (PR-AI-VL-223, defect H7): in the first two sets every adherence case
#: asks "first element true, second false", so a constant answer scored 1.0. Here the four cases cover all four patterns.
SET_ID_512_VARIED = "vl220-synthetic-512-2"
CELL = 128
#: Set id to the integer factor every coordinate and size of the 128-pixel scene table is multiplied by.
BUILTIN_SCALES: Mapping[str, int] = {SET_ID: 1, SET_ID_512: 4, SET_ID_512_VARIED: 4}
_BACKGROUND = (245, 245, 245)
COLORS: Mapping[str, tuple[int, int, int]] = {
    "red": (220, 40, 40),
    "green": (40, 170, 70),
    "blue": (40, 80, 220),
    "yellow": (235, 200, 30),
}


class Canvas:
    """Pixel canvas. Drawing arguments are in 128-pixel scene units; ``scale`` multiplies them (1 reproduces the first set)."""

    def __init__(self, width: int, height: int, scale: int = 1) -> None:
        self.width = width
        self.height = height
        self.scale = scale
        self._pixels = bytearray(bytes(_BACKGROUND) * (width * height))

    def _set(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self._pixels[offset : offset + 3] = bytes(color)

    def square(self, cx: int, cy: int, half: int, color: tuple[int, int, int]) -> None:
        cx, cy, half = cx * self.scale, cy * self.scale, half * self.scale
        for y in range(cy - half, cy + half + 1):
            for x in range(cx - half, cx + half + 1):
                self._set(x, y, color)

    def circle(self, cx: int, cy: int, radius: int, color: tuple[int, int, int]) -> None:
        cx, cy, radius = cx * self.scale, cy * self.scale, radius * self.scale
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                    self._set(x, y, color)

    def line(
        self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], thick: int = 2
    ) -> None:
        x0, y0, x1, y1, thick = (value * self.scale for value in (x0, y0, x1, y1, thick))
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            x = x0 + (x1 - x0) * step // steps
            y = y0 + (y1 - y0) * step // steps
            for dy in range(-thick, thick + 1):
                for dx in range(-thick, thick + 1):
                    self._set(x + dx, y + dy, color)

    def png(self) -> bytes:
        """Uncompressed (stored-block) PNG: deterministic across zlib builds."""

        row = self.width * 3
        raw = b"".join(
            b"\x00" + bytes(self._pixels[y * row : (y + 1) * row]) for y in range(self.height)
        )

        def chunk(tag: bytes, data: bytes) -> bytes:
            body = tag + data
            return (
                struct.pack(">I", len(data))
                + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 0))
            + chunk(b"IEND", b"")
        )


def _draw_shape(canvas: Canvas, shape: str, color: str, cx: int, cy: int) -> None:
    if shape == "square":
        canvas.square(cx, cy, 20, COLORS[color])
    else:
        canvas.circle(cx, cy, 22, COLORS[color])


def scene(items: list[tuple[str, str]], panels: int = 1, scale: int = 1) -> bytes:
    """Up to three shapes per panel on a fixed grid; ``items`` is a list of ``(shape, color)``."""

    canvas = Canvas(CELL * scale * panels, CELL * scale, scale)
    for index, (shape, color) in enumerate(items):
        _draw_shape(canvas, shape, color, 32 + 32 * (index % 3) + (index // 3) * CELL, 64)
    return canvas.png()


def figure(arms: int = 2, legs: int = 2, scale: int = 1) -> bytes:
    """A stick figure; a wrong limb count is the synthetic stand-in for an anatomical defect."""

    canvas = Canvas(CELL * scale, CELL * scale, scale)
    ink = (30, 30, 30)
    canvas.circle(64, 24, 14, ink)
    canvas.line(64, 38, 64, 82, ink)
    for index in range(arms):
        x = 28 + index * 36 if arms <= 3 else 20 + index * 28
        canvas.line(64, 50, x, 76, ink)
    for index in range(legs):
        canvas.line(64, 82, 40 + index * 48 if legs == 2 else 64, 120, ink)
    return canvas.png()


def _panels(left: list[tuple[str, str]], right: list[tuple[str, str]], scale: int = 1) -> bytes:
    canvas = Canvas(CELL * scale * 2, CELL * scale, scale)
    for panel, items in enumerate((left, right)):
        for index, (shape, color) in enumerate(items):
            _draw_shape(canvas, shape, color, 32 + 32 * index + panel * CELL, 64)
    return canvas.png()


def _name(shape: str, color: str) -> str:
    return f"{color} {shape}"


def build_synthetic_set(
    set_id: str = SET_ID,
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    """``(assets by id, case document, label document)`` of a built-in set; a pure function of the tables below.

    ``SET_ID`` (128 pixels) is byte-identical to what the first supervised run used; ``SET_ID_512`` draws the same scenes four
    times larger and adds a closed object vocabulary to its ``describe`` cases. The result is cached and returned as copies."""

    if set_id not in BUILTIN_SCALES:
        raise KeyError(set_id)
    images, cases, labels = _build(set_id)
    return dict(images), copy.deepcopy(cases), copy.deepcopy(labels)


def object_names() -> list[str]:
    """Every ``"<color> <shape>"`` name a scene could contain (the closed vocabulary of the larger set), sorted."""

    return sorted(_name(shape, color) for shape in ("square", "circle") for color in COLORS)


#: ``(drawn, asked)`` per adherence case. The first table is the one of the first two sets (every case: first true, second false).
_ADHERENCE: list[tuple[list[tuple[str, str]], list[tuple[str, str]]]] = [
    ([("square", "red"), ("circle", "blue")], [("square", "red"), ("circle", "green")]),
    (
        [("circle", "yellow"), ("square", "green"), ("circle", "red")],
        [("circle", "yellow"), ("square", "blue")],
    ),
    ([("square", "blue")], [("square", "blue"), ("square", "red")]),
]
#: The varied table: (true, false), (false, true), (true, true), (false, false). Every answer pattern appears once, so no
#: constant answer can score above one half per element.
_ADHERENCE_VARIED: list[tuple[list[tuple[str, str]], list[tuple[str, str]]]] = [
    ([("square", "red"), ("circle", "blue")], [("square", "red"), ("circle", "green")]),
    ([("circle", "blue"), ("square", "red")], [("circle", "green"), ("square", "red")]),
    (
        [("circle", "yellow"), ("square", "green"), ("circle", "red")],
        [("circle", "yellow"), ("square", "green")],
    ),
    ([("square", "blue")], [("square", "red"), ("circle", "green")]),
]


@functools.cache
def _build(set_id: str) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    scale = BUILTIN_SCALES[set_id]
    images: dict[str, bytes] = {}
    cases: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    def add_case(case: dict[str, Any], reference: dict[str, Any]) -> None:
        cases.append(case)
        labels.append({"case_id": case["case_id"], "reference": reference})

    adherence = _ADHERENCE_VARIED if set_id == SET_ID_512_VARIED else _ADHERENCE
    for index, (drawn, asked) in enumerate(adherence, start=1):
        asset = f"adh-{index}"
        images[asset] = scene(drawn, scale=scale)
        elements = [
            {"id": f"e{n}", "text": f"a {_name(shape, color)} is visible"}
            for n, (shape, color) in enumerate(asked, 1)
        ]
        answers = {f"e{n}": (shape, color) in drawn for n, (shape, color) in enumerate(asked, 1)}
        add_case(
            {"case_id": f"adherence-{index}", "kind": contract.KIND_ADHERENCE, "asset_ids": [asset],
             "prompt": "For each element, say whether it is visible in the image.", "elements": elements},
            {"answers": answers},
        )  # fmt: skip

    consistency = [
        ([("square", "red"), ("circle", "blue")], [("square", "red"), ("circle", "blue")]),
        ([("square", "red"), ("circle", "blue")], [("square", "red"), ("circle", "green")]),
    ]
    for index, (left, right) in enumerate(consistency, start=1):
        asset = f"con-{index}"
        images[asset] = _panels(left, right, scale)
        elements = [
            {"id": f"s{n}", "text": f"subject {n} looks the same in both panels"} for n in (1, 2)
        ]
        answers = {f"s{n}": left[n - 1] == right[n - 1] for n in (1, 2)}
        add_case(
            {"case_id": f"consistency-{index}", "kind": contract.KIND_CONSISTENCY, "asset_ids": [asset],
             "prompt": "The image has a left and a right panel. Say whether each subject is unchanged.",
             "elements": elements},
            {"answers": answers},
        )  # fmt: skip

    defects = [
        ("fig-ok", figure(2, 2, scale), []),
        (
            "fig-extra-arm",
            figure(3, 2, scale),
            [{"region": "arms", "category": "extra_limb", "severity": "major"}],
        ),
        (
            "fig-missing-leg",
            figure(2, 1, scale),
            [{"region": "legs", "category": "missing_limb", "severity": "major"}],
        ),
        (
            "fig-two-extra-arms",
            figure(4, 2, scale),
            [{"region": "arms", "category": "extra_limb", "severity": "major"}],
        ),
    ]
    for index, (asset, data, findings) in enumerate(defects, start=1):
        images[asset] = data
        add_case(
            {"case_id": f"defect-{index}", "kind": contract.KIND_DEFECT, "asset_ids": [asset],
             "prompt": "List every anatomical defect of the figure. An empty list means none."},
            {"findings": findings},
        )  # fmt: skip

    wanted = [("square", "red"), ("circle", "blue"), ("square", "green")]
    pairs = [
        ("complete-first", wanted, wanted[:2], "a"),
        ("complete-second", wanted[:2], wanted, "b"),
    ]
    for index, (name, first, second, preferred) in enumerate(pairs, start=1):
        images[f"ba-{index}-a"] = scene(first, scale=scale)
        images[f"ba-{index}-b"] = scene(second, scale=scale)
        listed = ", ".join(_name(shape, color) for shape, color in wanted)
        add_case(
            {"case_id": f"before-after-{index}-{name}", "kind": contract.KIND_BEFORE_AFTER,
             "asset_ids": [f"ba-{index}-a", f"ba-{index}-b"],
             "prompt": f"Image a and image b were made for: {listed}. Which one is more useful, or is it a tie?"},
            {"preferred": preferred},
        )  # fmt: skip

    describe = [([("square", "red"), ("circle", "yellow")], 1), ([("circle", "green")], 2)]
    for drawn, index in describe:
        asset = f"des-{index}"
        images[asset] = scene(drawn, scale=scale)
        objects = [_name(shape, color) for shape, color in drawn]
        case: dict[str, Any] = {
            "case_id": f"describe-{index}", "kind": contract.KIND_DESCRIBE, "asset_ids": [asset],
            "prompt": "List the objects you can see, one short name each.",
        }  # fmt: skip
        if scale != 1:
            case["vocabulary"] = object_names()
        add_case(
            case,
            {"objects": objects, "synonyms": {name: [name.replace(" ", "-")] for name in objects}},
        )

    asset_docs = [
        {
            "asset_id": asset_id,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "origin": contract.ORIGIN_SYNTHETIC,
            "media_type": "image/png",
        }
        for asset_id, data in sorted(images.items())
    ]
    case_doc = {
        "schema": contract.CASES_SCHEMA,
        "set_id": set_id,
        "assets": asset_docs,
        "cases": cases,
    }
    label_doc = {
        "schema": contract.LABELS_SCHEMA,
        "set_id": set_id,
        "labeler": contract.LABELER_SYNTHETIC,
        "labels": labels,
    }
    return images, case_doc, label_doc


__all__ = [
    "BUILTIN_SCALES",
    "SET_ID",
    "SET_ID_512",
    "SET_ID_512_VARIED",
    "Canvas",
    "build_synthetic_set",
    "figure",
    "object_names",
    "scene",
]
