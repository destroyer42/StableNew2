"""Scan one logical sink stream without saving markers or raw matches."""

from __future__ import annotations

import hashlib
import re
from typing import BinaryIO

MARKER = re.compile(rb"[A-Za-z0-9_-]{16,128}")
CHUNK = 64 * 1024


def scan(stream: BinaryIO, marker: bytes) -> dict[str, object]:
    """Count exact byte matches, including across read boundaries."""
    if MARKER.fullmatch(marker) is None:
        raise ValueError("expected a bounded synthetic marker")
    digest = hashlib.sha256(marker).hexdigest()
    tail = b""
    scanned = 0
    matches = 0
    try:
        while True:
            block = stream.read(CHUNK)
            if not isinstance(block, bytes):
                raise OSError("sink read did not return bytes")
            if not block:
                break
            scanned += len(block)
            combined = tail + block
            start = 0
            while (found := combined.find(marker, start)) >= 0:
                matches += 1
                start = found + 1
            tail = combined[-(len(marker) - 1) :]
    except OSError:
        return {
            "marker_sha256": digest,
            "bytes_read": scanned,
            "matches": matches,
            "complete": False,
        }
    return {"marker_sha256": digest, "bytes_read": scanned, "matches": matches, "complete": True}
