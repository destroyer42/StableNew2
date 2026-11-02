"""Bounded, cancellable file hashing for the Motion Library.

A video is never read into memory: it is hashed (or copied while hashing) one fixed-size chunk at a
time, and a set ``cancel`` event stops the loop between chunks.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

HASH_CHUNK_BYTES = 1024 * 1024


class HashCancelled(Exception):
    """The cancel event was set between chunks."""


def sha256_file(path: str | Path, cancel: threading.Event | None = None) -> str:
    """Hex SHA-256 of ``path``.  Raises ``OSError`` for an unreadable file and ``HashCancelled`` on cancel."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            if cancel is not None and cancel.is_set():
                raise HashCancelled()
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["HASH_CHUNK_BYTES", "HashCancelled", "sha256_file"]
