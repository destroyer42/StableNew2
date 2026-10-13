"""OpenPose library safety envelope (PR-IMG-CNET-210): resolution, bounded read, validation, thumbnails."""

from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from src.conditioning import openpose_library as lib
from tests.conditioning.openpose_fixtures_210 import jpeg_bytes, make_library, png_bytes


def test_library_root_is_models_openpose_under_the_configured_webui_root(tmp_path: Path) -> None:
    assert lib.library_root(tmp_path) == tmp_path / "models" / "OpenPose"
    assert lib.library_root(None) is None
    assert lib.library_root("  ") is None


def test_nested_images_resolve_and_are_read_once_with_identity_from_the_same_bytes(tmp_path: Path) -> None:
    data = png_bytes(200, 300)
    library = make_library(tmp_path, {"Standing/relaxed.png": data})

    resolved, image = lib.read_library_image(library, "Standing/relaxed.png")

    assert resolved == (library / "Standing" / "relaxed.png").resolve()
    assert image.data == data and image.sha256 == hashlib.sha256(data).hexdigest()
    assert (image.width, image.height, image.image_format, image.size) == (200, 300, "PNG", len(data))


def test_jpeg_is_accepted(tmp_path: Path) -> None:
    library = make_library(tmp_path, {"a.jpg": jpeg_bytes(128, 128)})

    _path, image = lib.read_library_image(library, "a.jpg")

    assert image.image_format == "JPEG"


@pytest.mark.parametrize(
    ("identity", "code"),
    [
        ("../secret.png", lib.CODE_ESCAPE),
        ("Standing/../../secret.png", lib.CODE_ESCAPE),
        ("/etc/passwd.png", lib.CODE_ESCAPE),
        ("C:/Windows/a.png", lib.CODE_ESCAPE),
        ("Standing/relaxed.txt", lib.CODE_UNSUPPORTED),
        ("Standing/absent.png", lib.CODE_MISSING),
    ],
)
def test_invalid_or_missing_identities_fail_with_a_stable_code(tmp_path: Path, identity: str, code: str) -> None:
    library = make_library(tmp_path, {"Standing/relaxed.png": png_bytes()})

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.resolve_library_file(library, identity)

    assert caught.value.code == code


def test_missing_library_folder_is_reported_not_crashed(tmp_path: Path) -> None:
    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.resolve_library_file(tmp_path / "models" / "OpenPose", "a.png")
    assert caught.value.code == lib.CODE_NO_LIBRARY
    with pytest.raises(lib.OpenPoseInputError) as unconfigured:
        lib.resolve_library_file(None, "a.png")
    assert unconfigured.value.code == lib.CODE_NO_LIBRARY


def test_a_directory_named_like_an_image_is_not_a_file(tmp_path: Path) -> None:
    library = make_library(tmp_path, {})
    (library / "folder.png").mkdir()

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.resolve_library_file(library, "folder.png")

    assert caught.value.code == lib.CODE_MISSING


def test_a_link_that_leaves_the_library_is_refused(tmp_path: Path) -> None:
    library = make_library(tmp_path, {})
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes())
    link = library / "escape.png"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.resolve_library_file(library, "escape.png")

    assert caught.value.code == lib.CODE_ESCAPE


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are Windows-only")
def test_a_directory_junction_that_leaves_the_library_is_refused(tmp_path: Path) -> None:
    import subprocess

    library = make_library(tmp_path, {})
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "a.png").write_bytes(png_bytes())
    junction = library / "Linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip("directory junctions are unavailable")

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.resolve_library_file(library, "Linked/a.png")

    assert caught.value.code == lib.CODE_ESCAPE


def test_oversized_files_are_refused_before_decoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lib, "MAX_FILE_BYTES", 1024)
    library = make_library(tmp_path, {"big.png": b"\x89PNG" + b"0" * 4096})

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.read_library_image(library, "big.png")

    assert caught.value.code == lib.CODE_OVERSIZED


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", lib.CODE_MALFORMED),
        (b"not an image at all", lib.CODE_MALFORMED),
        (png_bytes()[:40], lib.CODE_MALFORMED),  # truncated
        (png_bytes(16, 16), lib.CODE_DIMENSIONS),
        (png_bytes(64, 5000), lib.CODE_DIMENSIONS),
    ],
)
def test_malformed_or_out_of_envelope_images_are_refused(tmp_path: Path, data: bytes, code: str) -> None:
    library = make_library(tmp_path, {"bad.png": data})

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.read_library_image(library, "bad.png")

    assert caught.value.code == code


def test_an_unsupported_image_format_with_an_image_extension_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80)).save(buffer, format="GIF")
    library = make_library(tmp_path, {"sneaky.png": buffer.getvalue()})

    with pytest.raises(lib.OpenPoseInputError) as caught:
        lib.read_library_image(library, "sneaky.png")

    assert caught.value.code == lib.CODE_MALFORMED


def test_thumbnail_is_a_bounded_png(tmp_path: Path) -> None:
    thumbnail = lib.thumbnail_png(png_bytes(800, 400), max_side=100)

    with Image.open(io.BytesIO(thumbnail)) as image:
        assert image.format == "PNG" and max(image.size) <= 100
