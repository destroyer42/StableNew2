"""Contact-sheet placement, provenance, visibility, bounds and atomic export with known-pixel fixtures."""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from PIL import Image

from src.learning import grid_contact_sheet as sheet_module
from src.learning.grid_contact_sheet import (
    MAX_SHEET_DIMENSION,
    ContactSheetError,
    build_manifest,
    choose_thumbnail,
    export_contact_sheet,
    render_contact_sheet,
    slot_box,
)
from src.learning.grid_results import HIDDEN, MISSING, build_grid_model
from tests.learning_v2.test_two_axis_grid_270 import grid_controller, grid_experiment

THUMB = 96


def color_for(row, col, sample=0):
    return (40 + 70 * col + 20 * sample, 30 + 80 * row, 200 - 40 * col - 30 * sample)


def solid(path, color, size=(40, 40)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def completed_grid(tmp_path, *, images=1, prompt="portrait, detailed", skip=()):
    controller = grid_controller(grid_experiment(images=images, prompt=prompt))
    plan = controller.learning_state.plan
    for variant in plan:
        row, col = divmod(plan.index(variant), 3)
        if (row, col) in skip:
            continue
        variant.status = "completed"
        variant.job_id = f"job-{row}-{col}"
        variant.image_refs = [
            solid(tmp_path / f"r{row}c{col}s{s}.png", color_for(row, col, s)) for s in range(images)
        ]
        variant.completed_images = images
        variant.execution_metadata = {
            "controlled_evidence_valid": True,
            "actual_all_seeds": [1000 + s for s in range(images)],
        }
    return controller


def model_for(controller, ratings=None, mode="nsfw"):
    return build_grid_model(
        controller.learning_state.current_experiment,
        controller.learning_state.plan,
        ratings or {},
        visibility_mode=mode,
    )


def center(image, box):
    x0, y0, x1, y1 = box
    return image.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))


def test_every_image_is_drawn_at_its_own_row_and_column(tmp_path):
    model = model_for(completed_grid(tmp_path))
    sheet, problems = render_contact_sheet(model, thumbnail=THUMB)
    assert (
        problems == ()
        and sheet.size[0] <= MAX_SHEET_DIMENSION
        and sheet.size[1] <= MAX_SHEET_DIMENSION
    )
    for cell in model.cells:
        assert center(sheet, slot_box(model, THUMB, cell)) == color_for(cell.row, cell.col)
    assert [cell.label for cell in model.cells[:3]] == [
        "CFG 5.0 | Steps 20",
        "CFG 7.0 | Steps 20",
        "CFG 9.0 | Steps 20",
    ]
    assert model.x_labels == ("CFG 5.0", "CFG 7.0", "CFG 9.0") and model.y_labels == (
        "Steps 20",
        "Steps 30",
        "Steps 40",
    )


def test_axis_headers_and_row_labels_are_drawn(tmp_path):
    model = model_for(completed_grid(tmp_path))
    sheet, _ = render_contact_sheet(model, thumbnail=THUMB)
    background = sheet_module._BACKGROUND
    x0, y0, _, _ = slot_box(model, THUMB, model.cells[0])
    header = sheet.crop((x0, y0 - 70, x0 + 90, y0 - 24))
    label_column = sheet.crop((20, y0, 150, y0 + THUMB))
    assert any(pixel != background for pixel in header.getdata())
    assert any(pixel != background for pixel in label_column.getdata())


def test_samples_keep_deterministic_order_seed_and_rating_labels(tmp_path):
    controller = completed_grid(tmp_path, images=2)
    refs = controller.learning_state.plan[4].image_refs
    model = model_for(controller, {refs[1]: {"overall_rating": 4}})
    cell = model.cells[4]
    assert [(image.sample_index, image.seed, image.rating) for image in cell.images] == [
        (0, 1000, None),
        (1, 1001, 4),
    ]
    sheet, _ = render_contact_sheet(model, thumbnail=THUMB)
    assert center(sheet, slot_box(model, THUMB, cell, 0)) == color_for(1, 1, 0)
    assert center(sheet, slot_box(model, THUMB, cell, 1)) == color_for(1, 1, 1)
    assert sheet_module._caption(1, cell.images[1]) == "Sample 2 | Seed 1001 | 4/5"
    assert sheet_module._caption(0, cell.images[0]) == "Sample 1 | Seed 1000"
    assert "rated" in cell.rating_summary and "4.0" in cell.rating_summary


def test_missing_failed_and_uncontrolled_cells_keep_position_with_placeholders(tmp_path):
    controller = completed_grid(tmp_path, skip={(0, 1), (2, 2)})
    plan = controller.learning_state.plan
    plan[1].status, plan[1].job_id = "failed", "job-failed"
    plan[8].status, plan[8].job_id = "queued", "job-queued"
    plan[3].execution_metadata["controlled_evidence_valid"] = False
    plan[3].status = "uncontrolled"
    os.unlink(plan[5].image_refs[0])
    model = model_for(controller)
    assert model.cells[1].placeholder == "Failed" and model.cells[8].placeholder == "Queued"
    assert model.cells[5].placeholder == MISSING and model.cells[3].uncontrolled
    sheet, _ = render_contact_sheet(model, thumbnail=THUMB)
    for index in (1, 5, 8):
        assert center(sheet, slot_box(model, THUMB, model.cells[index])) != color_for(
            *divmod(index, 3)
        )
    assert center(sheet, slot_box(model, THUMB, model.cells[4])) == color_for(1, 1)
    assert [cell.job_id for cell in model.cells][4] == "job-1-1"


def test_no_neighbouring_artifact_is_substituted(tmp_path):
    controller = completed_grid(tmp_path)
    plan = controller.learning_state.plan
    plan[0].image_refs = [
        str(tmp_path / "r0c0s0-renamed.png")
    ]  # recorded file is gone; the neighbour exists
    model = model_for(controller)
    assert model.cells[0].images[0].available is False and model.cells[0].placeholder == MISSING
    sheet, _ = render_contact_sheet(model, thumbnail=THUMB)
    assert center(sheet, slot_box(model, THUMB, model.cells[0])) not in {
        color_for(0, 1),
        color_for(1, 0),
    }


def test_aspect_ratio_is_preserved(tmp_path):
    controller = completed_grid(tmp_path)
    controller.learning_state.plan[0].image_refs = [
        solid(tmp_path / "wide.png", (200, 20, 20), (200, 100))
    ]
    model = model_for(controller)
    sheet, _ = render_contact_sheet(model, thumbnail=THUMB)
    x0, y0, x1, y1 = slot_box(model, THUMB, model.cells[0])
    assert sheet.getpixel(((x0 + x1) // 2, (y0 + y1) // 2)) == (200, 20, 20)
    assert (
        sheet.getpixel(((x0 + x1) // 2, y0 + 3)) == sheet_module._SLOT
    )  # letterboxed, not stretched
    assert sheet.getpixel(((x0 + x1) // 2, y1 - 3)) == sheet_module._SLOT


def test_sfw_mode_hides_thumbnails_paths_and_prompt_derived_text(tmp_path):
    controller = completed_grid(tmp_path, prompt="nude portrait, detailed")
    model = model_for(controller, mode="sfw")
    assert model.hidden and all(
        cell.placeholder == HIDDEN and not cell.images for cell in model.cells
    )
    sheet, _ = render_contact_sheet(model, thumbnail=THUMB)
    colors = {
        sheet.getpixel((b[0] + 2, b[1] + 2))
        for b in (slot_box(model, THUMB, c) for c in model.cells)
    }
    assert colors == {sheet_module._SLOT}
    manifest = json.dumps(build_manifest(model, "x.png", sheet.size, ()))
    assert (
        "nude" not in manifest
        and '.png"' not in manifest.replace('"x.png"', "")
        and "[Hidden in SFW mode]" in model.title
    )
    assert "nude" not in (model.title + model.subtitle)
    visible = model_for(completed_grid(tmp_path / ".." / tmp_path.name), mode="sfw")
    assert not visible.hidden and visible.cells[0].images


def test_sheet_dimensions_are_bounded_and_oversized_requests_are_reduced():
    class Fake:
        rows, cols = 4, 4
        cells = ()

    assert choose_thumbnail(Fake(), 10_000) >= sheet_module.MIN_THUMBNAIL
    width, height, _, _ = sheet_module._dimensions(Fake(), choose_thumbnail(Fake(), 10_000))
    assert (
        width <= MAX_SHEET_DIMENSION
        and height <= MAX_SHEET_DIMENSION
        and width * height <= sheet_module.MAX_SHEET_PIXELS
    )


def test_corrupt_oversized_and_bomb_images_become_placeholders(tmp_path, monkeypatch):
    controller = completed_grid(tmp_path)
    plan = controller.learning_state.plan
    (tmp_path / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    plan[0].image_refs = [str(tmp_path / "bad.png")]
    (tmp_path / "empty.png").write_bytes(b"")
    plan[1].image_refs = [str(tmp_path / "empty.png")]
    model = model_for(controller)
    sheet, problems = render_contact_sheet(model, thumbnail=THUMB)
    assert len(problems) == 2 and center(
        sheet, slot_box(model, THUMB, model.cells[2])
    ) == color_for(0, 2)
    monkeypatch.setattr(sheet_module, "MAX_SOURCE_PIXELS", 100)
    _, problems = render_contact_sheet(model_for(completed_grid(tmp_path)), thumbnail=THUMB)
    assert len(problems) == 9
    monkeypatch.undo()
    for index, size in enumerate(
        ((9500, 9500), (14000, 14000))
    ):  # decompression warning, then hard bomb error
        Image.new("1", size).save(tmp_path / f"bomb{index}.png")
    bombs = completed_grid(tmp_path)
    bombs.learning_state.plan[0].image_refs = [str(tmp_path / "bomb0.png")]
    bombs.learning_state.plan[1].image_refs = [str(tmp_path / "bomb1.png")]
    sheet, problems = render_contact_sheet(model_for(bombs), thumbnail=THUMB)
    assert len(problems) == 2 and sheet.size[0] <= MAX_SHEET_DIMENSION


def test_export_is_atomic_refuses_silent_overwrite_and_never_touches_artifacts(
    tmp_path, monkeypatch
):
    controller = completed_grid(tmp_path)
    model = model_for(controller)
    artifacts = {
        ref: hashlib.sha256(open(ref, "rb").read()).hexdigest()
        for v in controller.learning_state.plan
        for ref in v.image_refs
    }
    out = tmp_path / "sheet.png"
    result = export_contact_sheet(model, out, thumbnail=THUMB)
    assert result.path == out and Image.open(out).size == (result.width, result.height)
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["schema"] == sheet_module.SHEET_SCHEMA and len(manifest["cells"]) == 9
    first = manifest["cells"][4]
    assert (first["row"], first["col"], first["job_id"], first["status"]) == (
        1,
        1,
        "job-1-1",
        "completed",
    )
    assert first["artifacts"][0]["path"] == controller.learning_state.plan[4].image_refs[0]
    before = out.read_bytes()
    with pytest.raises(FileExistsError):
        export_contact_sheet(model, out, thumbnail=THUMB)
    assert out.read_bytes() == before
    monkeypatch.setattr(
        sheet_module,
        "atomic_write_bytes",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        export_contact_sheet(model, out, overwrite=True, thumbnail=THUMB)
    assert out.read_bytes() == before
    monkeypatch.undo()
    export_contact_sheet(model, out, overwrite=True, thumbnail=THUMB)
    with pytest.raises(ContactSheetError):
        export_contact_sheet(
            model, controller.learning_state.plan[0].image_refs[0], overwrite=True, manifest=False
        )
    with pytest.raises(ContactSheetError):
        export_contact_sheet(model, tmp_path / "sheet.jpg")
    with pytest.raises(ContactSheetError):
        export_contact_sheet(model, tmp_path / "missing" / "sheet.png")
    assert artifacts == {
        ref: hashlib.sha256(open(ref, "rb").read()).hexdigest() for ref in artifacts
    }
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_failed_replace_leaves_previous_sheet_and_no_temp_file(tmp_path, monkeypatch):
    model = model_for(completed_grid(tmp_path))
    out = tmp_path / "sheet.png"
    export_contact_sheet(model, out, thumbnail=THUMB, manifest=False)
    before = out.read_bytes()
    monkeypatch.setattr(
        "src.utils.atomic_io.os.replace",
        lambda *a, **k: (_ for _ in ()).throw(PermissionError("locked")),
    )
    monkeypatch.setattr("src.utils.atomic_io.time.sleep", lambda *_: None)
    with pytest.raises(PermissionError):
        export_contact_sheet(model, out, overwrite=True, thumbnail=THUMB, manifest=False)
    assert out.read_bytes() == before and not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
