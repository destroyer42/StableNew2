"""Bounded GGUF container inspection for the observational inventory (PR-IMG-MODELS-152).

Reads at most ``MAX_HEADER_BYTES`` from the start of a ``.gguf`` file: the magic, version, tensor count and the leading
metadata key/value block. It never reads a tensor, hashes, loads or converts anything and imports no GGUF library. What it
establishes is only what the container states about itself (``general.architecture``, ``general.file_type``); the
quantization name is reported *only* from that declared file type, never from the file name or size, and anything it cannot
parse safely is an error result, not a guess. A parsed container is still **not** proof that any backend can load it.
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
    )


__all__ = ["FILE_TYPES", "GgufEvidence", "inspect_gguf"]
