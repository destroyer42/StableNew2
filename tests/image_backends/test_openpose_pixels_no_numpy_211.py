"""Pillow-only pixel identity, including exhaustive pinned Forge float32 alpha reference bytes."""

from __future__ import annotations

import builtins
import hashlib
import io

import pytest
from PIL import Image

from src.image_backends.openpose_output import _pixels


@pytest.fixture(autouse=True)
def _numpy_unavailable(monkeypatch):
    original = builtins.__import__

    def no_numpy(name, *args, **kwargs):
        if name == "numpy" or name.startswith("numpy."):
            raise ModuleNotFoundError(
                "NumPy deliberately unavailable for this regression", name=name
            )
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_numpy)


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_rgb_and_opaque_rgba_keep_exact_rgb_bytes(mode) -> None:
    rgb = bytes((0, 51, 255, 12, 34, 56))
    image = Image.frombytes("RGB", (2, 1), rgb).convert(mode)
    assert _pixels(_png(image)) == ((2, 1), hashlib.sha256(rgb).hexdigest())


def test_transparent_pixels_ignore_hidden_color_and_become_white() -> None:
    image = Image.frombytes("RGBA", (2, 1), bytes((255, 0, 0, 0, 0, 51, 255, 0)))
    assert _pixels(_png(image)) == ((2, 1), hashlib.sha256(bytes([255] * 6)).hexdigest())


def test_all_channel_alpha_byte_pairs_match_frozen_forge_reference() -> None:
    rgba = bytes(
        value
        for alpha in range(256)
        for channel in range(256)
        for value in (channel, channel, channel, alpha)
    )
    image = Image.frombytes("RGBA", (256, 256), rgba)
    # Independently captured from pinned HWC3's NumPy float32 expression before removing the dependency.
    # Covers every channel/alpha pair, including 405 values differing from rational integer floor.
    assert _pixels(_png(image)) == (
        (256, 256),
        "af1f7a5c38ec1113b47a968bd93444a02070873e46118f86db886cecb8d9067d",
    )


def test_partially_transparent_channels_preserve_float32_truncation_not_pillow_rounding() -> None:
    image = Image.frombytes("RGBA", (1, 1), bytes((0, 51, 255, 65)))
    expected = bytes((189, 202, 254))
    assert _pixels(_png(image)) == ((1, 1), hashlib.sha256(expected).hexdigest())


@pytest.mark.parametrize("width,height", [(257, 513), (65537, 2)])
@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_hash_chunks_preserve_row_major_identity_across_boundaries(width, height, mode) -> None:
    rgb = bytes(value for i in range(width * height) for value in (i % 251, i % 127, i % 61))
    image = Image.frombytes("RGB", (width, height), rgb).convert(mode)
    assert _pixels(_png(image)) == ((width, height), hashlib.sha256(rgb).hexdigest())


def test_palette_transparency_keeps_forge_white_semantics() -> None:
    image = Image.new("P", (2, 1), 0)
    image.putpalette([10, 20, 30, 50, 60, 70] + [0] * (768 - 6))
    image.putpixel((1, 0), 1)
    image.info["transparency"] = 0
    assert _pixels(_png(image)) == (
        (2, 1),
        hashlib.sha256(bytes((255, 255, 255, 50, 60, 70))).hexdigest(),
    )
