"""Bounded GGUF container inspection for the observational inventory (PR-IMG-MODELS-152).

Reads at most ``MAX_HEADER_BYTES`` from the start of a ``.gguf`` file: the magic, version, tensor count and the leading
metadata key/value block. It never reads a tensor, hashes, loads or converts anything and imports no GGUF library. What it
establishes is only what the container states about itself (``general.architecture``, ``general.file_type``); the
quantization name is reported *only* from that declared file type, never from the file name or size, and anything it cannot
parse safely is an error result, not a guess. A parsed container is still **not** proof that any backend can load it.

PR-IMG-FLUX-130 adds the tensor-info table that follows the key/value block (names, dims and tensor types; never tensor
data), read from the same bounded prefix. Dims are reported in the safetensors order (slowest first; GGUF stores them
fastest first), so the one structural classifier can read both containers. A table that does not fit the bound or does not
parse is ``tensor_table_error``: the container facts above still stand and nothing structural is guessed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_HEADER_BYTES = 1024 * 1024
MAX_KV_COUNT = 4096
MAX_STRING_BYTES = 64 * 1024
MAX_ARRAY_ELEMENTS = 1 << 20
SUPPORTED_VERSIONS = (2, 3)
MAX_TENSOR_COUNT = 1 << 16
MAX_TENSOR_DIMS = 8

#: ggml tensor type ids -> names (per-tensor storage type, distinct from the file type above).
TENSOR_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1", 8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K",
    12: "Q4_K", 13: "Q5_K", 14: "Q6_K", 15: "Q8_K", 24: "I8", 25: "I16", 26: "I32", 27: "I64", 28: "F64", 30: "BF16",
}

#: llama.cpp ``LLAMA_FTYPE`` values that name a quantization (container-declared ``general.file_type``).
FILE_TYPES = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    7: "Q8_0",
    8: "Q5_0",
    9: "Q5_1",
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    32: "BF16",
}
_SCALARS = {
    0: ("B", 1),
    1: ("b", 1),
    2: ("H", 2),
    3: ("h", 2),
    4: ("I", 4),
    5: ("i", 4),
    6: ("f", 4),
    7: ("?", 1),
    10: ("Q", 8),
    11: ("q", 8),
    12: ("d", 8),
}
_STRING, _ARRAY = 8, 9


@dataclass(frozen=True)
class GgufEvidence:
    """``format present, content unverified`` unless the bounded header parsed cleanly."""

    parsed: bool = False
    version: int | None = None
    tensor_count: int | None = None
    architecture: str | None = None
    file_type: int | None = None
    quantization: str | None = None  # from the declared file type only
    metadata_keys: tuple[str, ...] = ()
    error: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    #: Tensor name -> shape in safetensors order (empty when the table was not read).
    tensor_shapes: dict[str, list[int]] = field(default_factory=dict)
    #: Tensor name -> ggml storage type name (``TENSOR_TYPES``; ``T<id>`` for an unlisted id).
    tensor_types: dict[str, str] = field(default_factory=dict)
    tensor_table_error: str | None = None


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if count < 0 or end > len(self.data):
            raise ValueError("metadata block exceeds the bounded header read")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def unpack(self, fmt: str, size: int) -> Any:
        return struct.unpack("<" + fmt, self.take(size))[0]

    def string(self) -> str:
        length = self.unpack("Q", 8)
        if length > MAX_STRING_BYTES:
            raise ValueError("oversized metadata string")
        return self.take(length).decode("utf-8", errors="replace")

    def value(self, kind: int) -> Any:
        if kind in _SCALARS:
            fmt, size = _SCALARS[kind]
            return self.unpack(fmt, size)
        if kind == _STRING:
            return self.string()
        if kind == _ARRAY:
            inner, count = self.unpack("I", 4), self.unpack("Q", 8)
            if count > MAX_ARRAY_ELEMENTS or inner == _ARRAY:
                raise ValueError("unsupported or oversized metadata array")
            if inner in _SCALARS:
                self.take(
                    _SCALARS[inner][1] * count
                )  # skip: arrays are never needed and never materialized
            elif inner == _STRING:
                for _ in range(count):
                    self.string()
            else:
                raise ValueError("unknown metadata array element type")
            return None
        raise ValueError("unknown metadata value type")


def inspect_gguf(path: Path) -> GgufEvidence:
    """Bounded container evidence for one ``.gguf`` file; never raises."""

    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_HEADER_BYTES)
    except OSError:
        return GgufEvidence(error="unreadable file")
    if data[:4] != b"GGUF":
        return GgufEvidence(error="not a GGUF container (bad magic)")
    try:
        reader = _Reader(data[4:])
        version = reader.unpack("I", 4)
        if version not in SUPPORTED_VERSIONS:
            return GgufEvidence(version=version, error=f"unsupported GGUF version {version}")
        tensor_count = reader.unpack("Q", 8)
        kv_count = reader.unpack("Q", 8)
        if kv_count > MAX_KV_COUNT:
            return GgufEvidence(
                version=version,
                tensor_count=tensor_count,
                error="metadata key count is implausible",
            )
        found: dict[str, Any] = {}
        keys: list[str] = []
        for _ in range(kv_count):
            key = reader.string()
            value = reader.value(reader.unpack("I", 4))
            keys.append(key)
            if key in (
                "general.architecture",
                "general.file_type",
                "general.quantization_version",
                "general.name",
            ):
                found[key] = value
    except (ValueError, struct.error):
        return GgufEvidence(error="malformed or truncated GGUF header")
    shapes: dict[str, list[int]] = {}
    types: dict[str, str] = {}
    table_error: str | None = None
    try:
        if tensor_count > MAX_TENSOR_COUNT:
            raise ValueError("tensor count is implausible")
        for _ in range(tensor_count):
            name = reader.string()
            dims = reader.unpack("I", 4)
            if dims > MAX_TENSOR_DIMS or name in shapes:
                raise ValueError("invalid tensor descriptor")
            shape = [reader.unpack("Q", 8) for _ in range(dims)]
            kind = reader.unpack("I", 4)
            reader.unpack("Q", 8)  # data offset: never followed
            shapes[name] = list(reversed(shape))
            types[name] = TENSOR_TYPES.get(kind, f"T{kind}")
    except (ValueError, struct.error):
        shapes, types = {}, {}
        table_error = "tensor table exceeds the bounded header read or is malformed"
    file_type = found.get("general.file_type")
    file_type = file_type if isinstance(file_type, int) else None
    return GgufEvidence(
        parsed=True,
        version=version,
        tensor_count=int(tensor_count),
        architecture=found.get("general.architecture")
        if isinstance(found.get("general.architecture"), str)
        else None,
        file_type=file_type,
        quantization=FILE_TYPES.get(file_type) if file_type is not None else None,
        metadata_keys=tuple(keys),
        facts={"quantization_version": found.get("general.quantization_version")},
        tensor_shapes=shapes,
        tensor_types=types,
        tensor_table_error=table_error,
    )


__all__ = ["FILE_TYPES", "TENSOR_TYPES", "GgufEvidence", "inspect_gguf"]
