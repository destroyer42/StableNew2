"""Deterministic synthetic assets, cases and by-construction labels for the harness wiring check (PR-AI-VL-220).

Every image is drawn by this module from a fixed table (no random numbers, no clock, no filesystem, no network) and encoded as
an uncompressed PNG, so the bytes, and therefore the SHA-256 pinned in the case set, are identical on every machine. The
labels follow from how the scene was drawn and are written to a separate document with labeler ``synthetic_by_construction``.

These scenes prove the harness plumbing (schemas, scoring, leak checks). They say nothing about how a model handles real
generated images; that needs existing assets with labels written by a person (``contract.validate_label_set`` refuses
anything else).
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from collections.abc import Mapping
from typing import Any

from tools.qualification.vl220 import contract

SET_ID = "vl220-synthetic-1"
CELL = 128
_BACKGROUND = (245, 245, 245)
COLORS: Mapping[str, tuple[int, int, int]] = {
    "red": (220, 40, 40),
    "green": (40, 170, 70),
    "blue": (40, 80, 220),
    "yellow": (235, 200, 30),
}


class Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._pixels = bytearray(bytes(_BACKGROUND) * (width * height))

    def _set(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self._pixels[offset : offset + 3] = bytes(color)

    def square(self, cx: int, cy: int, half: int, color: tuple[int, int, int]) -> None:
        for y in range(cy - half, cy + half + 1):
            for x in range(cx - half, cx + half + 1):
                self._set(x, y, color)

    def circle(self, cx: int, cy: int, radius: int, color: tuple[int, int, int]) -> None:
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                    self._set(x, y, color)

    def line(
        self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], thick: int = 2
    ) -> None:
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


def scene(items: list[tuple[str, str]], panels: int = 1) -> bytes:
    """Up to three shapes per panel on a fixed grid; ``items`` is a list of ``(shape, color)``."""

    canvas = Canvas(CELL * panels, CELL)
    for index, (shape, color) in enumerate(items):
        _draw_shape(canvas, shape, color, 32 + 32 * (index % 3) + (index // 3) * CELL, 64)
    return canvas.png()


def figure(arms: int = 2, legs: int = 2) -> bytes:
    """A stick figure; a wrong limb count is the synthetic stand-in for an anatomical defect."""

    canvas = Canvas(CELL, CELL)
    ink = (30, 30, 30)
    canvas.circle(64, 24, 14, ink)
    canvas.line(64, 38, 64, 82, ink)
    for index in range(arms):
        x = 28 + index * 36 if arms <= 3 else 20 + index * 28
        canvas.line(64, 50, x, 76, ink)
    for index in range(legs):
        canvas.line(64, 82, 40 + index * 48 if legs == 2 else 64, 120, ink)
    return canvas.png()


def _panels(left: list[tuple[str, str]], right: list[tuple[str, str]]) -> bytes:
    canvas = Canvas(CELL * 2, CELL)
    for panel, items in enumerate((left, right)):
        for index, (shape, color) in enumerate(items):
            _draw_shape(canvas, shape, color, 32 + 32 * index + panel * CELL, 64)
    return canvas.png()


def _name(shape: str, color: str) -> str:
    return f"{color} {shape}"


def build_synthetic_set() -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    """``(assets by id, case document, label document)``. Everything is a pure function of the tables below."""

    images: dict[str, bytes] = {}
    cases: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    def add_case(case: dict[str, Any], reference: dict[str, Any]) -> None:
        cases.append(case)
        labels.append({"case_id": case["case_id"], "reference": reference})

    adherence = [
        ([("square", "red"), ("circle", "blue")], [("square", "red"), ("circle", "green")]),
        (
            [("circle", "yellow"), ("square", "green"), ("circle", "red")],
            [("circle", "yellow"), ("square", "blue")],
        ),
        ([("square", "blue")], [("square", "blue"), ("square", "red")]),
    ]
    for index, (drawn, asked) in enumerate(adherence, start=1):
        asset = f"adh-{index}"
        images[asset] = scene(drawn)
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
        images[asset] = _panels(left, right)
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
        ("fig-ok", figure(2, 2), []),
        (
            "fig-extra-arm",
            figure(3, 2),
            [{"region": "arms", "category": "extra_limb", "severity": "major"}],
        ),
        (
            "fig-missing-leg",
            figure(2, 1),
            [{"region": "legs", "category": "missing_limb", "severity": "major"}],
        ),
        (
            "fig-two-extra-arms",
            figure(4, 2),
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
        images[f"ba-{index}-a"] = scene(first)
        images[f"ba-{index}-b"] = scene(second)
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
        images[asset] = scene(drawn)
        objects = [_name(shape, color) for shape, color in drawn]
        add_case(
            {"case_id": f"describe-{index}", "kind": contract.KIND_DESCRIBE, "asset_ids": [asset],
             "prompt": "List the objects you can see, one short name each."},
            {"objects": objects, "synonyms": {name: [name.replace(" ", "-")] for name in objects}},
        )  # fmt: skip

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
        "set_id": SET_ID,
        "assets": asset_docs,
        "cases": cases,
    }
    label_doc = {
        "schema": contract.LABELS_SCHEMA,
        "set_id": SET_ID,
        "labeler": contract.LABELER_SYNTHETIC,
        "labels": labels,
    }
    return images, case_doc, label_doc


__all__ = ["SET_ID", "Canvas", "build_synthetic_set", "figure", "scene"]
