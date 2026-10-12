"""Shared deterministic fixtures for the PR-IMG-CNET-210 OpenPose conditioning tests (no GPU, no network)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def png_bytes(width: int = 128, height: int = 192, color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    """A small valid PNG whose bytes depend only on its arguments (so tests can reason about identity)."""

    image = Image.new("RGB", (width, height), color)
    for x in range(0, width, 7):  # a deterministic stripe so different colours cannot collide by accident
        image.putpixel((x, 0), (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg_bytes(width: int = 96, height: int = 96) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 100, 50)).save(buffer, format="JPEG")
    return buffer.getvalue()


def make_library(webui_root: Path, files: dict[str, bytes]) -> Path:
    """Create ``<webui_root>/models/OpenPose`` with the given relative files and return the library folder."""

    library = webui_root / "models" / "OpenPose"
    library.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = library / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return library


_CONTROLNET_SHAPES = {
    "sdxl": {
        "down_blocks.1.attentions.0.transformer_blocks.0.attn2.to_k.weight": [8, 2048],
        "add_embedding.linear_1.weight": [8, 2816],
    },
    "sdxl_original_layout": {
        "input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [8, 2048],
        "label_emb.0.0.weight": [8, 2816],
    },
    "sd15": {"input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [8, 768]},
    "sd2": {"input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [8, 1024]},
    "unknown": {"adapter.body.0.weight": [8, 8]},
    "contradictory": {
        "input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [8, 768],
        "label_emb.0.0.weight": [8, 2816],
    },
}


def write_controlnet_weights(path: Path, family: str = "sdxl") -> Path:
    """A tiny, structurally valid safetensors file whose header shapes identify ``family`` (no real weights)."""

    import json
    import math
    import struct

    header: dict = {"__metadata__": {}}
    offset = 0
    for name, shape in _CONTROLNET_SHAPES[family].items():
        end = offset + math.prod(shape) * 2
        header[name] = {"dtype": "F16", "shape": shape, "data_offsets": [offset, end]}
        offset = end
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(encoded)) + encoded)
        stream.write(bytes(offset))
    return path
