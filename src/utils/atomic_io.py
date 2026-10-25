"""Crash-safe small-file writes (temp file in the same directory, fsync, atomic replace).

A plain ``Path.write_text`` truncates the target first, so a hard reset or power loss in the middle of the write leaves a
zero-filled or partial file (observed in real Learning ``session.json`` data). These helpers either fully publish the new
content or leave the previous file untouched. Standard library only; no import-time side effects.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

#: Windows briefly denies ``os.replace`` while an indexer, antivirus or another reader holds the destination open.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_S = 0.05


def _replace_with_retry(source: str, target: Path) -> None:
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_BACKOFF_S * attempt)


def atomic_write_text(path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8") -> Path:
    """Write ``text`` so readers only ever see the old or the complete new content. Raises ``OSError`` on failure."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f"{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes) -> Path:
    """Binary twin of :func:`atomic_write_text` (the target is never left truncated). Raises ``OSError`` on failure."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f"{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def atomic_write_json(path: str | os.PathLike[str], payload: Any, **dumps_kwargs: Any) -> Path:
    """Serialize first (a non-serializable payload never touches the file), then publish atomically."""

    return atomic_write_text(path, json.dumps(payload, **dumps_kwargs))


def atomic_publish_json(path: str | os.PathLike[str], payload: Any, **dumps_kwargs: Any) -> Path:
    """Publish a complete new immutable file, refusing an existing destination atomically.

    Windows no-replace rename, or a POSIX same-directory hard link, exposes the fully
    fsynced staging file in one operation and fails if another publisher won.
    """
    target = Path(path)
    text = json.dumps(payload, **dumps_kwargs)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f"{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "nt":
            # Windows rename is atomic and refuses an existing target (POSIX rename replaces it).
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
