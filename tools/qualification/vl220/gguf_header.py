"""A bounded, read-only reader for the metadata header of a GGUF file (PR-AI-VL-220).

It parses only the key/value block at the start of the file and keeps a short allow-list of scalar and string keys. It never
maps tensors, never loads a model, imports no inference library and runs no binary: the file is opened for reading and a
limited number of bytes are consumed. A malformed or oversized header raises :class:`GgufHeaderError`; callers treat that as
"not the file that was pinned".
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

GGUF_MAGIC = b"GGUF"
SUPPORTED_VERSIONS = frozenset({2, 3})
MAX_HEADER_BYTES = 64 * 1024 * 1024
MAX_KV_COUNT = 4096
MAX_KEY_BYTES = 256
MAX_STRING_BYTES = 1024 * 1024

#: Keys worth keeping; everything else in the block is skipped without being stored.
KEPT_KEYS: frozenset[str] = frozenset(
    {
        "general.architecture",
        "general.type",
        "general.name",
        "general.file_type",
        "general.license.name",
        "general.base_model.0.name",
        "lfm3.embedding_length",
        "lfm3.context_length",
        "gemma4.embedding_length",
        "gemma4.context_length",
        "clip.has_vision_encoder",
        "clip.has_audio_encoder",
        "clip.vision.projector_type",
        "clip.vision.projection_dim",
        "clip.vision.image_size",
        "clip.vision.patch_size",
    }
)

_FIXED_SIZES: Mapping[int, int] = {
    0: 1,
    1: 1,
    2: 2,
    3: 2,
    4: 4,
    5: 4,
    6: 4,
    7: 1,
    10: 8,
    11: 8,
    12: 8,
}
_FIXED_FORMATS: Mapping[int, str] = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    7: "<?",
    10: "<Q",
    11: "<q",
    12: "<d",
}
_TYPE_STRING = 8
_TYPE_ARRAY = 9


class GgufHeaderError(ValueError):
    """The file is not a GGUF the reader can bound-check."""


@dataclass(frozen=True, slots=True)
class GgufHeader:
    version: int
    tensor_count: int
    kv_count: int
    metadata: Mapping[str, str | int | float | bool]

    @property
    def architecture(self) -> str:
        return str(self.metadata.get("general.architecture", ""))

    @property
    def projector_type(self) -> str:
        return str(self.metadata.get("clip.vision.projector_type", ""))


class _Budget:
    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self._used = 0

    def read(self, count: int) -> bytes:
        if count < 0:
            raise GgufHeaderError("negative read")
        self._used += count
        if self._used > MAX_HEADER_BYTES:
            raise GgufHeaderError("header exceeds the read budget")
        data = self._handle.read(count)
        if len(data) != count:
            raise GgufHeaderError("truncated header")
        return data

    def skip(self, count: int) -> None:
        if count < 0:
            raise GgufHeaderError("negative skip")
        self._used += count
        if self._used > MAX_HEADER_BYTES:
            raise GgufHeaderError("header exceeds the read budget")
        self._handle.seek(count, 1)

    def unpack(self, fmt: str) -> tuple[object, ...]:
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))


def _read_string(budget: _Budget, *, keep: bool) -> str:
    (length,) = budget.unpack("<Q")
    if not isinstance(length, int) or length > MAX_STRING_BYTES:
        raise GgufHeaderError("string too long")
    if not keep:
        budget.skip(length)
        return ""
    return budget.read(length).decode("utf-8", errors="replace")


def _read_scalar(
    budget: _Budget, value_type: int, *, keep: bool
) -> str | int | float | bool | None:
    if value_type == _TYPE_STRING:
        text = _read_string(budget, keep=keep)
        return text if keep else None
    fmt = _FIXED_FORMATS.get(value_type)
    if fmt is None:
        raise GgufHeaderError(f"unsupported value type {value_type}")
    if not keep:
        budget.skip(_FIXED_SIZES[value_type])
        return None
    (value,) = budget.unpack(fmt)
    if isinstance(value, (bool, int, float)):
        return value
    raise GgufHeaderError("unexpected scalar")


def _skip_array(budget: _Budget) -> None:
    (element_type,) = budget.unpack("<I")
    (length,) = budget.unpack("<Q")
    if not isinstance(element_type, int) or not isinstance(length, int):
        raise GgufHeaderError("bad array header")
    if element_type == _TYPE_ARRAY:
        raise GgufHeaderError("nested arrays are not supported")
    if element_type == _TYPE_STRING:
        if length > MAX_HEADER_BYTES // 8:
            raise GgufHeaderError("array too long")
        for _ in range(length):
            _read_string(budget, keep=False)
        return
    size = _FIXED_SIZES.get(element_type)
    if size is None:
        raise GgufHeaderError(f"unsupported array element type {element_type}")
    budget.skip(size * length)


def read_header(path: str | Path) -> GgufHeader:
    """Read the metadata block of ``path``. Opens the file read-only and consumes at most ``MAX_HEADER_BYTES``."""

    try:
        with open(path, "rb") as handle:
            budget = _Budget(handle)
            if budget.read(4) != GGUF_MAGIC:
                raise GgufHeaderError("not a GGUF file")
            version, tensor_count, kv_count = budget.unpack("<IQQ")
            if not isinstance(version, int) or version not in SUPPORTED_VERSIONS:
                raise GgufHeaderError(f"unsupported GGUF version {version}")
            if not isinstance(kv_count, int) or not isinstance(tensor_count, int):
                raise GgufHeaderError("bad counts")
            if kv_count > MAX_KV_COUNT:
                raise GgufHeaderError("too many metadata entries")
            metadata: dict[str, str | int | float | bool] = {}
            for _ in range(kv_count):
                (key_length,) = budget.unpack("<Q")
                if not isinstance(key_length, int) or not 0 < key_length <= MAX_KEY_BYTES:
                    raise GgufHeaderError("bad key length")
                key = budget.read(key_length).decode("utf-8", errors="replace")
                (value_type,) = budget.unpack("<I")
                if not isinstance(value_type, int):
                    raise GgufHeaderError("bad value type")
                if value_type == _TYPE_ARRAY:
                    _skip_array(budget)
                    continue
                keep = key in KEPT_KEYS
                value = _read_scalar(budget, value_type, keep=keep)
                if keep and value is not None:
                    metadata[key] = value
            return GgufHeader(version, tensor_count, kv_count, metadata)
    except OSError as exc:
        raise GgufHeaderError(f"cannot read file: {exc.__class__.__name__}") from exc
    except struct.error as exc:
        raise GgufHeaderError("malformed header") from exc


__all__ = ["GgufHeader", "GgufHeaderError", "KEPT_KEYS", "read_header"]
