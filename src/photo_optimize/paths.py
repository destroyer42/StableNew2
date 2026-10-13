"""Windows extended paths for managed photo files with long provenance names."""
from __future__ import annotations

import os
from pathlib import Path


def io_path(path: Path | str, *, force: bool = False) -> Path:
    candidate = Path(path)
    if os.name != "nt":
        return candidate
    raw = str(candidate.absolute())
    if raw.startswith("\\\\?\\") or (not force and len(raw) < 240):
        return candidate
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    return Path("\\\\?\\" + raw)


def canonical_path(path: Path | str) -> Path:
    raw = str(Path(path).absolute())
    if raw.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + raw[8:])
    if raw.startswith("\\\\?\\"):
        return Path(raw[4:])
    return Path(raw)
