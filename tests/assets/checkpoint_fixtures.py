"""Tiny deterministic registry-owned checkpoint fixtures; no model loading."""

import json
import struct


def checkpoint(path, *, metadata=None, payload=b"fixture"):
    header = json.dumps({"__metadata__": metadata or {}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)
    return path
