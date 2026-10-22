"""Labeled PNG contact sheet for a Two-Axis Grid, rendered only from recorded artifacts.

Pure Pillow: it renders ``GridModel`` (exact cell/job/artifact associations, placeholders, visibility) and never calls
generation, a queue or the backend. Output size, source size and decode memory are bounded; corrupt or oversized images
become labeled placeholders; the PNG and optional manifest are published atomically and never over a recorded artifact.
"""

from __future__ import annotations

import io
import os
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.learning.grid_results import LEGEND, GridCellModel, GridImage, GridModel
from src.utils.atomic_io import atomic_write_bytes, atomic_write_json

SHEET_SCHEMA = "stablenew.learning-grid-contact-sheet.v1"
MAX_SHEET_DIMENSION = 8192
MAX_SHEET_PIXELS = 40_000_000
MAX_SOURCE_PIXELS = 50_000_000
DEFAULT_THUMBNAIL = 256
MIN_THUMBNAIL = 64
_PAD, _GAP, _MARGIN, _ROW_LABEL = 6, 6, 20, 150
_COLUMN_HEADER, _CELL_HEAD, _CAPTION, _CELL_FOOT = 30, 18, 34, 18
_BACKGROUND, _INK, _MUTED, _SLOT = (245, 245, 245), (24, 24, 24), (96, 96, 96), (222, 222, 222)
_BORDER = {
    "completed": (60, 150, 80),
    "uncontrolled": (210, 140, 20),
    "failed": (190, 50, 50),
    "cancelled": (190, 50, 50),
    "requires_attention": (190, 50, 50),
}
_NEUTRAL = (150, 150, 150)
_TERMINAL = {"completed", "uncontrolled"}
_LOAD_ERRORS = (
    OSError,
    ValueError,
    SyntaxError,
    Image.DecompressionBombError,
    Image.DecompressionBombWarning,
)


class ContactSheetError(ValueError):
    """The sheet cannot be produced within its bounds."""


@dataclass(frozen=True)
class ExportResult:
    path: Path
    manifest_path: Path | None
    width: int
    height: int
    warnings: tuple[str, ...]


def _font(size: int) -> Any:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


def _slots(model: GridModel) -> int:
    return max(
        1, min(3, max((max(cell.planned, len(cell.images)) for cell in model.cells), default=1))
    )


def _dimensions(model: GridModel, thumb: int) -> tuple[int, int, int, int]:
    slots = _slots(model)
    cell_w = slots * thumb + (slots - 1) * _GAP + 2 * _PAD
    cell_h = _CELL_HEAD + thumb + _CAPTION + _CELL_FOOT + 2 * _PAD
    width = 2 * _MARGIN + _ROW_LABEL + model.cols * cell_w + (model.cols - 1) * _GAP
    legend = 22 + 16 * (len(LEGEND) + 1)
    height = (
        2 * _MARGIN + 74 + _COLUMN_HEADER + model.rows * cell_h + (model.rows - 1) * _GAP + legend
    )
    return width, height, cell_w, cell_h


def slot_box(
    model: GridModel, thumbnail: int, cell: GridCellModel, index: int = 0
) -> tuple[int, int, int, int]:
    """Pixel box of one sample slot in the rendered sheet (what the renderer draws and tests sample)."""
    _, _, cell_w, cell_h = _dimensions(model, thumbnail)
    x = _MARGIN + _ROW_LABEL + cell.col * (cell_w + _GAP) + _PAD + index * (thumbnail + _GAP)
    y = _MARGIN + 74 + _COLUMN_HEADER + cell.row * (cell_h + _GAP) + _PAD + _CELL_HEAD
    return x, y, x + thumbnail, y + thumbnail


def choose_thumbnail(model: GridModel, requested: int | None = None) -> int:
    thumb = max(MIN_THUMBNAIL, min(int(requested or DEFAULT_THUMBNAIL), DEFAULT_THUMBNAIL * 2))
    while thumb >= MIN_THUMBNAIL:
        width, height, _, _ = _dimensions(model, thumb)
        if (
            width <= MAX_SHEET_DIMENSION
            and height <= MAX_SHEET_DIMENSION
            and width * height <= MAX_SHEET_PIXELS
        ):
            return thumb
        thumb -= 16
    raise ContactSheetError("The grid is too large for a bounded contact sheet")


def load_thumbnail(path: str, size: int) -> Image.Image:
    """Bounded decode shared by the sheet and the interactive grid; raises on corrupt/oversized/bomb images."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if source.size[0] * source.size[1] > MAX_SOURCE_PIXELS:
                raise ContactSheetError("image is too large to thumbnail safely")
            source.draft("RGB", (size, size))
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((size, size), Image.Resampling.LANCZOS, reducing_gap=2.0)
    return image


def _caption(index: int, image: GridImage) -> str:
    parts = [f"Sample {index + 1}"]
    if image.seed is not None:
        parts.append(f"Seed {image.seed}")
    if image.rating:
        parts.append(f"{image.rating}/5")
    return " | ".join(parts)


def render_contact_sheet(
    model: GridModel, *, thumbnail: int | None = None
) -> tuple[Image.Image, tuple[str, ...]]:
    thumb = choose_thumbnail(model, thumbnail)
    width, height, cell_w, cell_h = _dimensions(model, thumb)
    sheet = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    title, body, small = _font(20), _font(14), _font(11)
    problems: list[str] = []
    text_w = width - 2 * _MARGIN
    draw.text((_MARGIN, _MARGIN), _fit(draw, model.title, title, text_w), fill=_INK, font=title)
    draw.text(
        (_MARGIN, _MARGIN + 26), _fit(draw, model.subtitle, body, text_w), fill=_INK, font=body
    )
    draw.text(
        (_MARGIN, _MARGIN + 48),
        _fit(
            draw,
            f"Columns: {model.x_variable} | Rows: {model.y_variable} | images {model.completed_total}/{model.planned_total}",
            body,
            text_w,
        ),
        fill=_MUTED,
        font=body,
    )
    left = _MARGIN + _ROW_LABEL
    top = _MARGIN + 74
    for col, label in enumerate(model.x_labels):
        x = left + col * (cell_w + _GAP)
        draw.text(
            (x + _PAD, top + 4), _fit(draw, label, body, cell_w - 2 * _PAD), fill=_INK, font=body
        )
    top += _COLUMN_HEADER
    slots = _slots(model)
    for row, label in enumerate(model.y_labels):
        y = top + row * (cell_h + _GAP)
        draw.text(
            (_MARGIN, y + cell_h // 2 - 8),
            _fit(draw, label, body, _ROW_LABEL - 8),
            fill=_INK,
            font=body,
        )
    for cell in model.cells:
        x = left + cell.col * (cell_w + _GAP)
        y = top + cell.row * (cell_h + _GAP)
        _draw_cell(sheet, draw, cell, x, y, cell_w, cell_h, thumb, slots, (body, small), problems)
    legend_y = top + model.rows * (cell_h + _GAP) + 4
    draw.text(
        (_MARGIN, legend_y),
        "Legend (ratings are manual operator ratings only)",
        fill=_INK,
        font=body,
    )
    for line, (name, meaning) in enumerate(LEGEND, start=1):
        draw.text(
            (_MARGIN, legend_y + 6 + 16 * line),
            _fit(draw, f"{name}: {meaning}", small, text_w),
            fill=_MUTED,
            font=small,
        )
    return sheet, tuple(problems)


def _draw_cell(
    sheet: Image.Image,
    draw: ImageDraw.ImageDraw,
    cell: GridCellModel,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
    thumb: int,
    slots: int,
    fonts: tuple[Any, Any],
    problems: list[str],
) -> None:
    body, small = fonts
    border = _BORDER.get(cell.status, _NEUTRAL)
    draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline=border, width=2)
    status = cell.status.replace("_", " ")
    heading = f"{cell.label} | {status}" + (
        " | UNCONTROLLED" if cell.uncontrolled and cell.status != "uncontrolled" else ""
    )
    draw.text(
        (x + _PAD, y + _PAD), _fit(draw, heading, small, cell_w - 2 * _PAD), fill=_INK, font=small
    )
    slot_y = y + _PAD + _CELL_HEAD
    if not cell.images:
        draw.rectangle((x + _PAD, slot_y, x + cell_w - _PAD - 1, slot_y + thumb - 1), fill=_SLOT)
        text = cell.placeholder or "No images"
        draw.text(
            (x + _PAD + 8, slot_y + thumb // 2 - 8),
            _fit(draw, text, body, cell_w - 2 * _PAD - 16),
            fill=_MUTED,
            font=body,
        )
    for index in range(slots):
        slot_x = x + _PAD + index * (thumb + _GAP)
        if cell.images and index >= len(cell.images):
            draw.rectangle((slot_x, slot_y, slot_x + thumb - 1, slot_y + thumb - 1), fill=_SLOT)
            if cell.status in _TERMINAL:
                draw.text(
                    (slot_x + 6, slot_y + thumb // 2 - 7), "Missing sample", fill=_MUTED, font=small
                )
            continue
        if index >= len(cell.images):
            continue
        image = cell.images[index]
        draw.rectangle((slot_x, slot_y, slot_x + thumb - 1, slot_y + thumb - 1), fill=_SLOT)
        note = "Artifact missing"
        picture = None
        if image.available:
            try:
                picture = load_thumbnail(image.path, thumb)
            except _LOAD_ERRORS as exc:
                note = "Unreadable image"
                problems.append(f"{cell.cell_id} sample {index + 1}: {type(exc).__name__}")
        if picture is None:
            draw.text((slot_x + 6, slot_y + thumb // 2 - 7), note, fill=_MUTED, font=small)
        else:
            sheet.paste(
                picture,
                (slot_x + (thumb - picture.width) // 2, slot_y + (thumb - picture.height) // 2),
            )
            picture.close()
        draw.text(
            (slot_x, slot_y + thumb + 3),
            _fit(draw, _caption(index, image), small, thumb),
            fill=_INK,
            font=small,
        )
    footer = (
        f"{cell.completed}/{cell.planned} images | {cell.rating_summary}"
        if cell.rating_summary
        else f"{cell.completed}/{cell.planned} images"
    )
    draw.text(
        (x + _PAD, y + cell_h - _PAD - 14),
        _fit(draw, footer, small, cell_w - 2 * _PAD),
        fill=_MUTED,
        font=small,
    )


def build_manifest(
    model: GridModel, sheet_name: str, size: tuple[int, int], problems: Iterable[str]
) -> dict[str, Any]:
    """Coordinates, jobs, statuses and artifact references; no image bytes. Hidden grids list no artifact paths."""
    return {
        "schema": SHEET_SCHEMA,
        "experiment_id": model.experiment_id,
        "snapshot_sha256": model.snapshot_sha256,
        "sheet": {"file": sheet_name, "width": size[0], "height": size[1]},
        "x_axis": {"variable": model.x_variable, "labels": list(model.x_labels)},
        "y_axis": {"variable": model.y_variable, "labels": list(model.y_labels)},
        "hidden_by_visibility_policy": model.hidden,
        "problems": list(problems),
        "cells": [
            {
                "cell_id": cell.cell_id,
                "row": cell.row,
                "col": cell.col,
                "label": cell.label,
                "job_id": cell.job_id,
                "status": cell.status,
                "uncontrolled": cell.uncontrolled,
                "placeholder": cell.placeholder,
                "artifacts": [
                    {
                        "sample_index": image.sample_index,
                        "path": image.path,
                        "seed": image.seed,
                        "rating": image.rating,
                        "available": image.available,
                    }
                    for image in cell.images
                ],
            }
            for cell in model.cells
        ],
    }


def _key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


def export_contact_sheet(
    model: GridModel,
    destination: str | os.PathLike[str],
    *,
    overwrite: bool = False,
    manifest: bool = True,
    thumbnail: int | None = None,
    protected_paths: Iterable[str] = (),
) -> ExportResult:
    """Render and atomically publish the PNG (and manifest). Never overwrites without ``overwrite`` or an artifact."""
    target = Path(destination)
    if target.suffix.lower() != ".png":
        raise ContactSheetError("The contact sheet must be saved as a .png file")
    if not target.parent.is_dir():
        raise ContactSheetError(f"Output folder does not exist: {target.parent}")
    if target.is_dir():
        raise ContactSheetError("Choose a file name, not a folder")
    protected = {_key(path) for path in protected_paths} | {
        _key(image.path) for cell in model.cells for image in cell.images
    }
    manifest_path = target.with_suffix(".json") if manifest else None
    for output in (target, manifest_path):
        if output is None:
            continue
        if _key(output) in protected:
            raise ContactSheetError("The destination is a recorded artifact; choose another file")
        if output.exists() and not overwrite:
            raise FileExistsError(str(output))
    sheet, problems = render_contact_sheet(model, thumbnail=thumbnail)
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    size = sheet.size
    sheet.close()
    atomic_write_bytes(target, buffer.getvalue())
    if manifest_path is not None:
        atomic_write_json(
            manifest_path,
            build_manifest(model, target.name, size, problems),
            indent=2,
            sort_keys=True,
        )
    return ExportResult(target, manifest_path, size[0], size[1], problems)
