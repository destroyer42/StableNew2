"""Outpainting canvas geometry, mask truth and original-pixel preservation (pure Pillow, CPU only)."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from src.pipeline import outpaint_canvas as canvas

W, H = 64, 72


def _original_image(width: int = W, height: int = H) -> Image.Image:
    image = Image.new("RGB", (width, height))
    image.putdata(
        [
            ((x * 3) % 256, (y * 5) % 256, (x + y * 7) % 256)
            for y in range(height)
            for x in range(width)
        ]
    )
    return image


def _png(image: Image.Image, **kwargs) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", **kwargs)
    return stream.getvalue()


@pytest.fixture
def original_bytes() -> bytes:
    return _png(_original_image())


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).copy()


@pytest.mark.parametrize(
    "extents,expanded,origin",
    [
        (canvas.Extents(left=16), (W + 16, H), (16, 0)),
        (canvas.Extents(right=24), (W + 24, H), (0, 0)),
        (canvas.Extents(top=8), (W, H + 8), (0, 8)),
        (canvas.Extents(bottom=32), (W, H + 32), (0, 0)),
        (canvas.Extents(left=8, right=16, top=24, bottom=8), (W + 24, H + 32), (8, 24)),
    ],
)
def test_geometry_places_the_original_at_exactly_left_top(
    original_bytes, extents, expanded, origin
):
    prepared = canvas.prepare_outpaint_canvas(original_bytes, extents)
    image = _decode(prepared.expanded_png)
    assert image.size == expanded == prepared.geometry.expanded_size
    assert prepared.geometry.original_origin == origin
    left, top = origin
    original = _original_image()
    assert image.crop((left, top, left + W, top + H)).tobytes() == original.tobytes()
    assert prepared.record["original_bbox"] == {
        "left": left,
        "top": top,
        "right": left + W,
        "bottom": top + H,
    }
    assert prepared.record["expanded_size"] == {"width": expanded[0], "height": expanded[1]}


def test_empty_area_replicates_boundary_pixels_including_corners(original_bytes):
    extents = canvas.Extents(left=8, right=16, top=24, bottom=8)
    image = _decode(canvas.prepare_outpaint_canvas(original_bytes, extents).expanded_png)
    original = _original_image()
    assert image.getpixel((0, 24 + 10)) == original.getpixel((0, 10))
    assert image.getpixel((8 + W + 15, 24 + 10)) == original.getpixel((W - 1, 10))
    assert image.getpixel((8 + 5, 0)) == original.getpixel((5, 0))
    assert image.getpixel((8 + 5, 24 + H + 7)) == original.getpixel((5, H - 1))
    assert image.getpixel((0, 0)) == original.getpixel((0, 0))
    assert image.getpixel((image.width - 1, image.height - 1)) == original.getpixel((W - 1, H - 1))
    assert prepared_record(original_bytes, extents)["padding_policy"] == "edge_replicate.v1"


def prepared_record(original_bytes, extents):
    return canvas.prepare_outpaint_canvas(original_bytes, extents).record


def test_mask_is_black_over_the_original_and_white_everywhere_else(original_bytes):
    extents = canvas.Extents(left=8, right=16, top=24, bottom=8)
    prepared = canvas.prepare_outpaint_canvas(original_bytes, extents)
    mask = _decode(prepared.mask_png)
    expanded = _decode(prepared.expanded_png)
    assert mask.mode == "L" and mask.size == expanded.size
    assert mask.getextrema() == (0, 255)
    assert mask.crop((8, 24, 8 + W, 24 + H)).getextrema() == (0, 0)
    white = sum(1 for value in mask.getdata() if value == 255)
    assert (
        white == mask.width * mask.height - W * H
    )  # no interior edit, no gray feathering baked in
    assert set(mask.getdata()) == {0, 255}


def test_preparation_is_deterministic_for_fixed_inputs(original_bytes):
    extents = canvas.Extents(left=8, bottom=16)
    first = canvas.prepare_outpaint_canvas(original_bytes, extents)
    second = canvas.prepare_outpaint_canvas(original_bytes, extents)
    assert first.expanded_png == second.expanded_png
    assert first.mask_png == second.mask_png
    assert first.record == second.record


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({}, "at least one"),
        ({"left": -8}, "negative"),
        ({"right": 4}, "multiple of 8"),
        ({"left": True}, "whole number"),
        ({"top": 8.0}, "whole number"),
        ({"bottom": 4096}, "supported"),
    ],
)
def test_invalid_extents_are_refused_not_adjusted(original_bytes, kwargs, message):
    with pytest.raises(ValueError, match=message):
        canvas.prepare_outpaint_canvas(original_bytes, canvas.Extents(**kwargs))


def test_misaligned_geometry_is_refused_and_the_alignment_rule_is_inspectable():
    odd = _png(_original_image(65, 71))
    with pytest.raises(ValueError, match="multiple of 8"):
        canvas.prepare_outpaint_canvas(odd, canvas.Extents(left=8))
    aligned = canvas.aligned_extents((65, 71), canvas.Extents(left=8))
    assert aligned == canvas.Extents(left=8, right=7, top=0, bottom=1)
    prepared = canvas.prepare_outpaint_canvas(odd, aligned)
    assert prepared.geometry.expanded_size == (80, 72)
    assert canvas.aligned_extents((64, 72), canvas.Extents(left=8)) == canvas.Extents(left=8)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\ntruncated"])
def test_corrupt_original_is_refused(data):
    with pytest.raises(ValueError):
        canvas.prepare_outpaint_canvas(data, canvas.Extents(left=8))


def test_resource_pressure_bands_mirror_the_executor_stage_assessment(monkeypatch):
    from src.pipeline.executor import Pipeline
    from src.utils import StructuredLogger

    monkeypatch.setattr("src.pipeline.executor.collect_gpu_snapshot", lambda: None)
    pipeline = Pipeline(client=object(), structured_logger=StructuredLogger())
    for width, height, steps in [
        (1024, 1024, 20),
        (2816, 2560, 20),
        (3200, 3200, 20),
        (2816, 2560, 60),
        (4096, 4096, 20),
    ]:
        expected = pipeline._assess_stage_pressure(
            stage_name="img2img", width=width, height=height, steps=steps
        )["status"]
        assert canvas.assess_pressure(width, height, steps).status == expected


def test_unsafe_pressure_refuses_geometry():
    huge = _png(Image.new("RGB", (64, 64)))
    assert canvas.assess_pressure(4096, 3200, 20).status == "unsafe"
    with pytest.raises(ValueError, match="supported|pressure|too large"):
        canvas.plan_geometry((4096, 2048), canvas.Extents(bottom=1200), steps=20)
    assert huge  # fixture sanity


def test_alpha_is_flattened_over_white_and_recorded():
    rgba = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
    rgba.putpixel((0, 0), (0, 0, 255, 255))
    prepared = canvas.prepare_outpaint_canvas(_png(rgba), canvas.Extents(right=8))
    expanded = _decode(prepared.expanded_png)
    assert expanded.getpixel((1, 1)) == (255, 255, 255)
    assert expanded.getpixel((0, 0)) == (0, 0, 255)
    assert prepared.record["color_normalization"] == canvas.COLOR_NORMALIZATION


def test_exif_orientation_is_applied_before_geometry():
    image = Image.new("RGB", (128, 64), "red")
    exif = Image.Exif()
    exif[0x0112] = 6
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif)
    prepared = canvas.prepare_outpaint_canvas(stream.getvalue(), canvas.Extents(left=8))
    assert prepared.record["original_size"] == {"width": 64, "height": 128}


def test_unsupported_color_modes_are_refused():
    sixteen = Image.new("I;16", (64, 64))
    with pytest.raises(ValueError, match="color mode"):
        canvas.prepare_outpaint_canvas(_png(sixteen), canvas.Extents(left=8))


# ----------------------------------------------------------- original-pixel preservation


def _backend_result(
    prepared, *, inside=(250, 0, 250), outside=(10, 200, 10), size=None, mode="RGB"
):
    width, height = size or prepared.geometry.expanded_size
    image = Image.new("RGB", (width, height), outside)
    left, top = prepared.geometry.original_origin
    image.paste(Image.new("RGB", _original_image().size, inside), (left, top))
    return image.convert(mode)


def test_preservation_restores_original_pixels_and_keeps_generated_exterior(original_bytes):
    extents = canvas.Extents(left=8, right=16, top=24, bottom=8)
    prepared = canvas.prepare_outpaint_canvas(original_bytes, extents)
    backend = _backend_result(prepared)
    final, evidence = canvas.preserve_original(_png(backend), original_bytes, prepared.record)
    result = _decode(final)
    left, top = prepared.geometry.original_origin
    assert result.size == prepared.geometry.expanded_size and result.mode == "RGB"
    assert result.crop((left, top, left + W, top + H)).tobytes() == _original_image().tobytes()
    assert result.getpixel((0, 0)) == (10, 200, 10)
    assert result.getpixel((result.width - 1, result.height - 1)) == (10, 200, 10)
    exterior = sum(1 for p in result.getdata() if p == (10, 200, 10))
    assert exterior == result.width * result.height - W * H
    assert evidence["preservation_applied"] is True
    assert evidence["original_bbox"] == prepared.record["original_bbox"]
    assert evidence["policy"] == canvas.PRESERVATION_POLICY
    assert len(evidence["original_sha256"]) == 64 and evidence["result_size"] == {
        "width": result.width,
        "height": result.height,
    }


def test_preservation_accepts_data_urls_and_rgba_results_deterministically(original_bytes):
    prepared = canvas.prepare_outpaint_canvas(original_bytes, canvas.Extents(right=8))
    backend = _backend_result(prepared, mode="RGBA")
    encoded = "data:image/png;base64," + base64.b64encode(_png(backend)).decode()
    first, _ = canvas.preserve_original(encoded, original_bytes, prepared.record)
    second, _ = canvas.preserve_original(_png(backend), original_bytes, prepared.record)
    assert first == second and _decode(first).mode == "RGB"


@pytest.mark.parametrize("size", [(W, H), (W + 7, H), (W + 8, H + 1), (4, 4)])
def test_wrong_sized_backend_result_is_refused(original_bytes, size):
    prepared = canvas.prepare_outpaint_canvas(original_bytes, canvas.Extents(right=8))
    with pytest.raises(ValueError, match="size"):
        canvas.preserve_original(
            _png(_backend_result(prepared, size=size)), original_bytes, prepared.record
        )


def test_corrupt_backend_result_and_swapped_original_are_refused(original_bytes):
    prepared = canvas.prepare_outpaint_canvas(original_bytes, canvas.Extents(right=8))
    with pytest.raises(ValueError):
        canvas.preserve_original(b"broken", original_bytes, prepared.record)
    other = _png(Image.new("RGB", (W, H), "green"))
    with pytest.raises(ValueError, match="original"):
        canvas.preserve_original(_png(_backend_result(prepared)), other, prepared.record)
    forged = dict(prepared.record)
    forged["original_bbox"] = {"left": 1, "top": 0, "right": W + 1, "bottom": H}
    with pytest.raises(ValueError):
        canvas.preserve_original(_png(_backend_result(prepared)), original_bytes, forged)


def test_derivation_check_rejects_forged_records_and_substituted_pixels(original_bytes):
    prepared = canvas.prepare_outpaint_canvas(original_bytes, canvas.Extents(left=8, bottom=8))
    canvas.verify_derivation(
        prepared.record, original_bytes, prepared.expanded_png, prepared.mask_png
    )
    forged = {**prepared.record, "extents": {"left": 0, "right": 0, "top": 0, "bottom": 8}}
    with pytest.raises(ValueError, match="record|derive"):
        canvas.verify_derivation(forged, original_bytes, prepared.expanded_png, prepared.mask_png)
    tampered = _decode(prepared.expanded_png)
    tampered.putpixel((20, 20), (1, 2, 3))
    with pytest.raises(ValueError, match="expanded"):
        canvas.verify_derivation(prepared.record, original_bytes, _png(tampered), prepared.mask_png)
    widened = Image.new("L", _decode(prepared.mask_png).size, 255)
    with pytest.raises(ValueError, match="mask"):
        canvas.verify_derivation(
            prepared.record, original_bytes, prepared.expanded_png, _png(widened)
        )
