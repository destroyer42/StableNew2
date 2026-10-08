"""Bounded safetensors header evidence for AssetRegistry, never tensor loading.

The SDXL dimensions are observational architecture signatures, not model
qualification. Only the standard LDM SDXL base layout is admitted here.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

STRUCTURE_CONTRACT = "checkpoint_structure/1"
_MAX_HEADER = 64 * 1024 * 1024
# Inspection supports ordinary tensor ranks without allowing adversarial work.
_MAX_TENSOR_RANK = 64
_MAX_DIMENSION = (1 << 64) - 1
_DTYPE_BYTES = {
    "BOOL": 1,
    "U8": 1,
    "I8": 1,
    "I16": 2,
    "U16": 2,
    "F16": 2,
    "BF16": 2,
    "I32": 4,
    "U32": 4,
    "F32": 4,
    "I64": 8,
    "U64": 8,
    "F64": 8,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate header key")
        result[key] = value
    return result


def _shape_matches_extent(shape: list[int], extent: int, dtype_bytes: int) -> bool:
    """Keep every intermediate element count within the declared byte extent."""
    if extent % dtype_bytes:
        return False
    max_elements = extent // dtype_bytes
    if 0 in shape:
        return max_elements == 0
    count = 1
    for dimension in shape:
        if count > max_elements // dimension:
            return False
        count *= dimension
    return count == max_elements


def checkpoint_header_evidence(path: Path) -> dict[str, Any]:
    """Read at most a bounded JSON header, validating descriptors against file size.

    No weights, hash, scan or imports of another model detector. Missing tensor
    descriptors retain existing metadata-only semantics. Invalid descriptors
    cannot manufacture structural or metadata admission evidence.
    """
    structure: dict[str, Any] = {
        "contract": STRUCTURE_CONTRACT,
        "architecture": "unrecognized",
        "error": None,
    }
    metadata: dict[str, Any] = {}
    if path.suffix.lower() != ".safetensors":
        structure["error"] = "unsupported checkpoint format for structural recognition"
        return {"structure": structure, "metadata": metadata, "metadata_error": None}
    try:
        with path.open("rb") as stream:
            raw = stream.read(8)
            if len(raw) != 8:
                raise ValueError("truncated header length")
            size = struct.unpack("<Q", raw)[0]
            if not 0 < size <= _MAX_HEADER:
                raise ValueError("invalid or oversized header length")
            encoded = stream.read(size)
        if len(encoded) != size:
            raise ValueError("truncated header")
        header = json.loads(encoded, object_pairs_hook=_unique_object)
        if not isinstance(header, dict):
            raise ValueError("header is not an object")
        metadata = header.pop("__metadata__", {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata is not an object")
        payload_size = path.stat().st_size - 8 - size
        intervals = []
        shapes = {}
        for name, tensor in header.items():
            if not isinstance(tensor, dict):
                raise ValueError("invalid tensor descriptor")
            shape, offsets = tensor.get("shape"), tensor.get("data_offsets")
            dtype_name = tensor.get("dtype")
            dtype = _DTYPE_BYTES.get(dtype_name) if isinstance(dtype_name, str) else None
            if (
                not isinstance(shape, list)
                or len(shape) > _MAX_TENSOR_RANK
                or any(type(dim) is not int or not 0 <= dim <= _MAX_DIMENSION for dim in shape)
                or not isinstance(offsets, list)
                or len(offsets) != 2
                or any(type(offset) is not int for offset in offsets)
                or dtype is None
            ):
                raise ValueError("invalid shape, dtype or offsets")
            start, end = offsets
            if not 0 <= start <= end <= payload_size or not _shape_matches_extent(
                shape, end - start, dtype
            ):
                raise ValueError("tensor extent disagrees with shape or file size")
            intervals.append((start, end))
            shapes[name] = shape
        previous = 0
        for start, end in sorted(intervals):
            if start != previous:
                raise ValueError("tensor data has gaps or overlaps")
            previous = end
        if intervals and previous != payload_size:
            raise ValueError("tensor data does not cover payload")
        prefix = "model.diffusion_model."

        def matches(name: str, shape: list[int]) -> bool:
            return shapes.get(prefix + name) == shape

        base = (
            matches("label_emb.0.0.weight", [1280, 2816])
            and matches("input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight", [640, 2048])
            and matches("input_blocks.7.1.transformer_blocks.9.attn2.to_k.weight", [1280, 2048])
            and matches("out.2.weight", [4, 320, 3, 3])
        )
        if base and matches("input_blocks.0.0.weight", [320, 4, 3, 3]):
            structure["architecture"] = "sdxl_base"
        elif base and matches("input_blocks.0.0.weight", [320, 9, 3, 3]):
            structure["architecture"] = "sdxl_inpaint"
        elif (
            matches("input_blocks.0.0.weight", [384, 4, 3, 3])
            and matches("label_emb.0.0.weight", [1536, 2560])
            and matches("input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight", [384, 1280])
            and matches("out.2.weight", [4, 384, 3, 3])
        ):
            structure["architecture"] = "sdxl_refiner"
        elif (
            matches("input_blocks.0.0.weight", [320, 4, 3, 3])
            and matches("out.2.weight", [4, 320, 3, 3])
            and prefix + "label_emb.0.0.weight" not in shapes
        ):
            for context, architecture in ((768, "sd1"), (1024, "sd2")):
                if matches(
                    "input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight", [640, context]
                ):
                    structure["architecture"] = architecture
        # Partial or contradictory SDXL marker sets cannot be blessed by a
        # descriptive label when tensor dimensions contradict that envelope.
        if structure["architecture"] == "unrecognized" and shapes.get(
            prefix + "label_emb.0.0.weight"
        ) in ([1280, 2816], [1536, 2560]):
            structure["error"] = "incomplete or contradictory SDXL tensor signature"
    except (OSError, ValueError, TypeError, UnicodeDecodeError, struct.error):
        # Diagnostic intentionally omits local paths and raw authored metadata.
        structure["error"] = "malformed or truncated safetensors header/tensor descriptors"
    return {"structure": structure, "metadata": metadata, "metadata_error": structure["error"]}
