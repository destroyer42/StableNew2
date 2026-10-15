"""PR-VID-196 workstream A: the exact prepared-source preview shares the preparation transform.

CPU-only, disposable images in ``tmp_path``; no runtime, queue or GUI.
"""

from __future__ import annotations

import hashlib
import os
import struct
import tempfile
import zlib
from pathlib import Path

import pytest
from PIL import Image, ImageFile, ImageOps

from src.video import workflow_source_preparation as preparation
from src.video.workflow_source_preparation import (
    PREVIEW_MAX_SOURCE_PIXELS,
    SourceTooLargeForPreview,
    cover_crop_box,
    prepare_declared_workflow_source,
    preview_declared_workflow_source,
    transform_declared_workflow_source,
)

POLICY = {
    "resize_policy": "cover_resize_center_crop",
    "portrait_target": {"width": 48, "height": 80},
    "landscape_target": {"width": 80, "height": 48},
    "square_orientation": "portrait",
}

# (stored width, stored height): wide, tall, square, exact target size, extreme aspect, tiny
SIZES = [(200, 90), (90, 200), (120, 120), (48, 80), (500, 40), (31, 17), (80, 48)]


def _image(tmp_path: Path, size: tuple[int, int], name: str = "source.png") -> Path:
    width, height = size
    image = Image.new("RGB", size)
    image.putdata(
        [((x * 7 + y) % 256, (y * 5 + x * 2) % 256, (x * y) % 256) for y in range(height) for x in range(width)]
    )
    path = tmp_path / name
    image.save(path)
    return path


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("size", SIZES)
def test_preview_pixels_equal_the_published_prepared_png(tmp_path, size):
    source = _image(tmp_path, size)
    preview = preview_declared_workflow_source(source_path=source, policy=POLICY)
    prepared = prepare_declared_workflow_source(
        source_path=source, output_root=tmp_path / "out", policy=POLICY
    )
    published = Path(prepared.prepared_image_path)
    with Image.open(published) as opened:
        opened.load()
        assert opened.mode == "RGB"
        assert opened.size == preview.image.size
        assert opened.tobytes() == preview.image.tobytes()
    # Pinned environment: the in-memory encoding is byte-identical to the published file.
    assert preview.to_png_bytes() == published.read_bytes()
    assert preview.geometry.prepared_dimensions == prepared.prepared_dimensions
    assert preview.geometry.target_dimensions == prepared.target_dimensions
    assert preview.geometry.source_dimensions == prepared.source_dimensions
    assert preview.geometry.orientation == prepared.orientation


@pytest.mark.parametrize("size", SIZES)
def test_transform_matches_the_accepted_pillow_fit_pixels(tmp_path, size):
    """The shared transform must keep the accepted result: EXIF transpose, RGB, LANCZOS, centred crop."""

    source = _image(tmp_path, size)
    transformed = transform_declared_workflow_source(source_path=source, policy=POLICY)
    target = transformed.geometry.target_dimensions
    with Image.open(source) as opened:
        expected = ImageOps.fit(
            ImageOps.exif_transpose(opened).convert("RGB"),
            (target["width"], target["height"]),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    assert transformed.image.size == expected.size
    assert transformed.image.tobytes() == expected.tobytes()


@pytest.mark.parametrize("size", SIZES)
def test_reported_crop_box_is_the_box_the_resize_used(tmp_path, size):
    source = _image(tmp_path, size)
    transformed = transform_declared_workflow_source(source_path=source, policy=POLICY)
    geometry = transformed.geometry
    with Image.open(source) as opened:
        rgb = opened.convert("RGB")
    again = rgb.resize(
        (geometry.prepared_dimensions["width"], geometry.prepared_dimensions["height"]),
        Image.Resampling.LANCZOS,
        box=geometry.crop_box,
    )
    assert again.tobytes() == transformed.image.tobytes()
    left, top, right, bottom = geometry.crop_box
    assert 0.0 <= left <= right <= size[0] and 0.0 <= top <= bottom <= size[1]
    # A centred crop leaves equal margins on the cropped axis.
    assert left == pytest.approx(size[0] - right)
    assert top == pytest.approx(size[1] - bottom)


def test_crop_geometry_for_a_known_case(tmp_path):
    # 60x80 into 24x40-style 0.6 ratio: width is cropped to 48, six pixels from each side.
    source = _image(tmp_path, (60, 80))
    policy = {**POLICY, "portrait_target": {"width": 24, "height": 40}}
    geometry = preview_declared_workflow_source(source_path=source, policy=policy).geometry
    assert geometry.crop_box == (6.0, 0.0, 54.0, 80.0)
    assert geometry.retained_fraction == pytest.approx(0.8)
    assert geometry.discarded_fraction == pytest.approx(0.2)
    assert geometry.orientation == "portrait" and geometry.source_orientation == "portrait"


def test_exact_ratio_discards_nothing(tmp_path):
    geometry = preview_declared_workflow_source(
        source_path=_image(tmp_path, (96, 160)), policy=POLICY
    ).geometry
    assert geometry.crop_box == (0.0, 0.0, 96.0, 160.0)
    assert geometry.discarded_fraction == 0.0


def test_cover_crop_box_is_pillows_fit_arithmetic():
    for source in [(200, 90), (90, 200), (31, 17), (5000, 3), (3, 5000), (480, 832), (833, 480)]:
        for target in [(480, 832), (832, 480), (24, 40), (7, 7)]:
            image = Image.new("RGB", source, "white")
            expected = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS)
            via_box = image.resize(target, Image.Resampling.LANCZOS, box=cover_crop_box(source, target))
            assert via_box.tobytes() == expected.tobytes()


def test_exif_orientation_is_applied_to_pixels_and_geometry(tmp_path):
    # Stored 70x40 with orientation 6 (rotate 270 / display rotated): displayed 40x70, portrait.
    image = Image.new("RGB", (70, 40))
    image.putdata([((x * 3) % 256, (y * 9) % 256, (x + y) % 256) for y in range(40) for x in range(70)])
    exif = Image.Exif()
    exif[0x0112] = 6
    path = tmp_path / "rotated.png"
    image.save(path, exif=exif)

    transformed = transform_declared_workflow_source(source_path=path, policy=POLICY)
    geometry = transformed.geometry
    assert geometry.stored_dimensions == {"width": 70, "height": 40}
    assert geometry.source_dimensions == {"width": 40, "height": 70}
    assert geometry.exif_orientation == 6 and geometry.exif_transposed is True
    assert geometry.source_orientation == "portrait" and geometry.orientation == "portrait"
    assert geometry.target_dimensions == {"width": 48, "height": 80}

    with Image.open(path) as opened:
        expected = ImageOps.fit(
            ImageOps.exif_transpose(opened).convert("RGB"),
            (48, 80),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    assert transformed.image.tobytes() == expected.tobytes()

    prepared = prepare_declared_workflow_source(
        source_path=path, output_root=tmp_path / "out", policy=POLICY
    )
    assert prepared.source_dimensions == {"width": 40, "height": 70}
    assert Path(prepared.prepared_image_path).read_bytes() == transformed.to_png_bytes()


def test_square_source_follows_the_policy_orientation(tmp_path):
    source = _image(tmp_path, (64, 64))
    geometry = preview_declared_workflow_source(source_path=source, policy=POLICY).geometry
    assert geometry.source_orientation == "square" and geometry.orientation == "portrait"
    landscape = {**POLICY, "square_orientation": "landscape"}
    geometry = preview_declared_workflow_source(source_path=source, policy=landscape).geometry
    assert geometry.orientation == "landscape"
    assert geometry.target_dimensions == {"width": 80, "height": 48}


def test_preview_leaves_the_source_unchanged_and_writes_nothing(tmp_path, monkeypatch):
    source_dir = tmp_path / "inputs"
    source_dir.mkdir()
    source = _image(source_dir, (200, 90))
    original = source.read_bytes()
    original_stat = source.stat()
    before = _snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a preview must not touch the filesystem for writing")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "replace", forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    monkeypatch.setattr(Image.Image, "save", forbidden)

    for _ in range(3):
        preview = preview_declared_workflow_source(source_path=source, policy=POLICY)
    assert preview.image.size == (80, 48)
    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / "prepared_video_sources").exists()


def test_encoding_a_preview_is_in_memory_only(tmp_path, monkeypatch):
    source = _image(tmp_path, (200, 90))
    before = _snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)
    data = preview_declared_workflow_source(source_path=source, policy=POLICY).to_png_bytes()
    assert data.startswith(b"\x89PNG")
    assert _snapshot(tmp_path) == before


def test_no_output_root_is_created_by_a_preview(tmp_path):
    source = _image(tmp_path, (200, 90))
    output_root = tmp_path / "operator_output"
    preview_declared_workflow_source(source_path=source, policy=POLICY)
    assert not output_root.exists()
    prepare_declared_workflow_source(source_path=source, output_root=output_root, policy=POLICY)
    assert (output_root / "prepared_video_sources").is_dir()


def test_preparation_uses_the_shared_transformation(tmp_path, monkeypatch):
    source = _image(tmp_path, (200, 90))
    calls = []
    real = preparation.transform_declared_workflow_source

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(preparation, "transform_declared_workflow_source", spy)
    prepare_declared_workflow_source(source_path=source, output_root=tmp_path / "out", policy=POLICY)
    preview_declared_workflow_source(source_path=source, policy=POLICY)
    assert len(calls) == 2


def test_preparation_keeps_name_stage_config_and_replay_fields(tmp_path):
    source = _image(tmp_path, (200, 90))
    prepared = prepare_declared_workflow_source(
        source_path=source, output_root=tmp_path / "out", policy=POLICY
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    expected_name = f"{digest}_80x48_cover_resize_center_crop.png"
    assert Path(prepared.prepared_image_path).name == expected_name
    assert set(prepared.to_stage_config()) == {
        "original_source_path",
        "prepared_image_path",
        "source_dimensions",
        "target_dimensions",
        "prepared_dimensions",
        "orientation",
        "policy",
        "orientation_rule",
    }
    assert prepared.policy == "cover_resize_center_crop"


def test_preview_errors_match_preparation_errors(tmp_path):
    missing = tmp_path / "missing.png"
    for call in (
        lambda: preview_declared_workflow_source(source_path=missing, policy=POLICY),
        lambda: prepare_declared_workflow_source(
            source_path=missing, output_root=tmp_path / "out", policy=POLICY
        ),
    ):
        with pytest.raises(ValueError, match="source image does not exist"):
            call()
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image at all")
    with pytest.raises(ValueError, match="Failed to open video workflow source image"):
        preview_declared_workflow_source(source_path=corrupt, policy=POLICY)
    good = _image(tmp_path, (20, 20))
    with pytest.raises(ValueError, match="unsupported resize policy"):
        preview_declared_workflow_source(source_path=good, policy={"resize_policy": "stretch"})
    assert not os.path.exists(tmp_path / "out")


# ------------------------------------------------------------------ preview-only input budget


def _header_only_png(width: int, height: int) -> bytes:
    """A 65-byte PNG whose header claims ``width`` x ``height``: size metadata with no pixel data."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])  # PNG signature
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )


def test_a_header_claiming_a_huge_image_is_declined_before_any_pixel_is_decoded(
    tmp_path, monkeypatch
):
    path = tmp_path / "claims_72_megapixels.png"
    path.write_bytes(_header_only_png(9000, 8000))
    assert path.stat().st_size < 200  # the size comes from the header, not from pixel data
    assert 9000 * 8000 > PREVIEW_MAX_SOURCE_PIXELS

    decodes: list[tuple[int, int]] = []
    transposes: list[bool] = []
    real_load = ImageFile.ImageFile.load
    real_transpose = ImageOps.exif_transpose

    def counting_load(self, *args, **kwargs):
        decodes.append(self.size)
        return real_load(self, *args, **kwargs)

    def counting_transpose(*args, **kwargs):
        transposes.append(True)
        return real_transpose(*args, **kwargs)

    monkeypatch.setattr(ImageFile.ImageFile, "load", counting_load)
    monkeypatch.setattr(ImageOps, "exif_transpose", counting_transpose)

    with pytest.raises(SourceTooLargeForPreview) as raised:
        preview_declared_workflow_source(source_path=path, policy=POLICY)
    assert decodes == [] and transposes == []  # not even EXIF (PNG EXIF reads would decode)
    message = str(raised.value)
    assert isinstance(raised.value, ValueError)
    assert "9000x8000" in message and "72 megapixels" in message
    assert "64-megapixel" in message and "Queueing is unaffected" in message

    # Without the budget the same file *is* decoded: that is the work the budget avoids.
    with pytest.raises(ValueError, match="Failed to open video workflow source image"):
        transform_declared_workflow_source(source_path=path, policy=POLICY)
    assert decodes == [(9000, 8000)]


def test_the_budget_is_inclusive_and_parity_holds_at_the_boundary(tmp_path):
    source = _image(tmp_path, (60, 80))  # 4800 pixels
    at_budget = preview_declared_workflow_source(
        source_path=source, policy=POLICY, max_source_pixels=4800
    )
    prepared = prepare_declared_workflow_source(
        source_path=source, output_root=tmp_path / "out", policy=POLICY
    )
    assert at_budget.to_png_bytes() == Path(prepared.prepared_image_path).read_bytes()
    with pytest.raises(SourceTooLargeForPreview):
        preview_declared_workflow_source(source_path=source, policy=POLICY, max_source_pixels=4799)


def test_the_default_budget_is_the_named_constant(tmp_path, monkeypatch):
    assert PREVIEW_MAX_SOURCE_PIXELS == 64_000_000
    source = _image(tmp_path, (60, 80))
    monkeypatch.setattr(preparation, "PREVIEW_MAX_SOURCE_PIXELS", 4799)
    with pytest.raises(SourceTooLargeForPreview):
        preview_declared_workflow_source(source_path=source, policy=POLICY)
    monkeypatch.setattr(preparation, "PREVIEW_MAX_SOURCE_PIXELS", 4800)
    assert preview_declared_workflow_source(source_path=source, policy=POLICY).image.size == (48, 80)


def test_an_image_above_the_preview_budget_is_still_prepared_normally(tmp_path, monkeypatch):
    source = _image(tmp_path, (200, 90))
    monkeypatch.setattr(preparation, "PREVIEW_MAX_SOURCE_PIXELS", 1000)  # 18,000 px is "oversized"
    with pytest.raises(SourceTooLargeForPreview):
        preview_declared_workflow_source(source_path=source, policy=POLICY)
    prepared = prepare_declared_workflow_source(
        source_path=source, output_root=tmp_path / "out", policy=POLICY
    )
    unbudgeted = transform_declared_workflow_source(source_path=source, policy=POLICY)
    assert prepared.prepared_dimensions == {"width": 80, "height": 48}
    assert Path(prepared.prepared_image_path).read_bytes() == unbudgeted.to_png_bytes()
    # Declining a preview wrote nothing of its own.
    assert [p.name for p in (tmp_path / "out" / "prepared_video_sources").iterdir()] == [
        Path(prepared.prepared_image_path).name
    ]
