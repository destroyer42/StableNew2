"""Tiny deterministic registry-owned checkpoint fixtures; no model loading."""

import json
import struct


def checkpoint(path, *, metadata=None, payload=b"fixture"):
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)
    return path


def tensor_checkpoint(path, *, architecture="base", metadata=None):
    """Sparse, valid tensor descriptors matching the observed installed headers."""
    prefix = "model.diffusion_model."
    if architecture == "refiner":
        shapes = {
            "input_blocks.0.0.weight": [384, 4, 3, 3],
            "label_emb.0.0.weight": [1536, 2560],
            "input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [384, 1280],
            "out.2.weight": [4, 384, 3, 3],
        }
    else:
        shapes = {
            "input_blocks.0.0.weight": [320, 9 if architecture == "inpaint" else 4, 3, 3],
            "label_emb.0.0.weight": [1280, 2816],
            "input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [640, 2048],
            "input_blocks.7.1.transformer_blocks.9.attn2.to_k.weight": [1280, 2048],
            "out.2.weight": [4, 320, 3, 3],
        }
    import math

    header = {"__metadata__": metadata or {}}
    offset = 0
    for name, shape in shapes.items():
        end = offset + math.prod(shape) * 2
        header[prefix + name] = {"dtype": "F16", "shape": shape, "data_offsets": [offset, end]}
        offset = end
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(encoded)) + encoded)
        stream.truncate(8 + len(encoded) + offset)
    return path
