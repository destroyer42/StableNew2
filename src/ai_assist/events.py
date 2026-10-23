"""Content-free event record (owner decision D7: no training-data capture).

A record may hold only the whitelisted fields below, and only short scalars: ids, codes, counts, a truncated digest and a
model hash prefix. Prompt text, suggestion text, file paths and asset names cannot be stored because no field can carry
them. There is no consent switch and no pair capture.

Durability model: the file is a true append-only JSON-lines log, not a rewritten file. Each record is one complete line
written with a single OS-level append, so two writers (two ``EventLog`` objects, or two processes such as the application
and a qualification harness) never overwrite each other. On POSIX that is ``O_APPEND`` plus ``fsync``. On Windows the C
runtime emulates ``O_APPEND`` by seeking and then writing, which is *not* atomic across processes, so the Windows path
opens the file with ``FILE_APPEND_DATA`` only (the kernel then positions every write at the end of file) and
``FILE_FLAG_WRITE_THROUGH`` (no separate flush is possible without write access). A crash can leave at most a torn final
line: readers skip any line that is not valid JSON, and the next append starts a fresh line. The file is bounded by size:
past ``MAX_BYTES`` it is rotated to ``<name>.1`` (one generation kept). ``src.utils.atomic_io`` provides atomic
*replacement*, which cannot express an append, so this log is the one deliberate exception to "persisted state goes
through atomic_io".
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Rotation threshold (bytes). With the 1.2 KB worst-case record this keeps well over 1000 records in two generations.
MAX_BYTES = 256 * 1024
_MAX_LINE_BYTES = 4096
_MAX_STRING = 80
_ATTEMPTS = 5
_RETRY_BACKOFF_S = 0.02
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "utc",
        "request_id",
        "kind",
        "outcome",
        "reason",
        "elapsed_ms",
        "input_chars",
        "output_chars",
        "request_digest",
        "model_sha256_prefix",
        "runtime_build_id",
        "strict_offline",
    }
)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """One lock per file within this process, shared by every ``EventLog`` object that names it."""

    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _append_posix(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_windows(path: Path, data: bytes) -> None:
    """One atomic append through a ``FILE_APPEND_DATA``-only handle (the kernel ignores the file pointer)."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    file_append_data, synchronize = 0x0004, 0x00100000
    share_all, open_always = 0x7, 4  # read | write | delete, so rotation and readers can coexist
    write_through = 0x80000000
    invalid = wintypes.HANDLE(-1).value
    handle = kernel32.CreateFileW(
        str(path), file_append_data | synchronize, share_all, None, open_always, write_through, None
    )
    if handle == invalid or handle is None:
        raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined,unused-ignore]
    try:
        written = wintypes.DWORD(0)
        if not kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined,unused-ignore]
        if written.value != len(data):
            raise OSError("short append to the AI assist event log")
    finally:
        kernel32.CloseHandle(handle)


class EventLog:
    def __init__(self, path: Path, *, max_bytes: int = MAX_BYTES) -> None:
        self._path = Path(path)
        self._rotated = self._path.with_name(self._path.name + ".1")
        self._max_bytes = max_bytes
        self._lock = _lock_for(self._path)

    @staticmethod
    def _check(record: dict[str, Any]) -> dict[str, Any]:
        unknown = set(record) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"event field not allowed: {sorted(unknown)[0]}")
        for key, value in record.items():
            if value is None or isinstance(value, (bool, int, float)):
                continue
            if isinstance(value, str) and len(value) <= _MAX_STRING:
                continue
            raise ValueError(f"event field {key} must be a short scalar")
        return dict(record) if "utc" in record else {"utc": datetime.now(UTC).isoformat(), **record}

    def append(self, record: dict[str, Any]) -> bool:
        """Append one record. Returns ``False`` (and logs) if it could not be written; never raises on I/O."""

        line = (
            json.dumps(self._check(record), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(line) > _MAX_LINE_BYTES:
            raise ValueError("event record is too large")
        with self._lock:
            for attempt in range(1, _ATTEMPTS + 1):
                try:
                    self._append_once(line)
                    break
                except PermissionError:
                    # Windows briefly denies access while an indexer, antivirus scan or another process holds the file.
                    if attempt == _ATTEMPTS:
                        logger.warning("AI assist event record could not be written", exc_info=True)
                        return False
                    time.sleep(_RETRY_BACKOFF_S * attempt)
                except OSError:
                    logger.warning("AI assist event record could not be written", exc_info=True)
                    return False
            self._rotate_if_needed()
        return True

    def _append_once(self, line: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.stat().st_size > 0 and not self._ends_with_newline():
            line = b"\n" + line  # isolate the torn final line a crash left behind
        if sys.platform == "win32":
            _append_windows(self._path, line)
        else:
            _append_posix(self._path, line)

    def _ends_with_newline(self) -> bool:
        with self._path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) == b"\n"

    def _rotate_if_needed(self) -> None:
        try:
            if self._path.stat().st_size > self._max_bytes:
                os.replace(self._path, self._rotated)
        except OSError:
            # Another process may hold the file open; skip. The next append tries again and no record is lost.
            logger.debug("AI assist event log rotation skipped", exc_info=True)

    def tail(self, count: int = 20) -> list[dict[str, Any]]:
        """The most recent valid records, oldest first. Torn or foreign lines are skipped."""

        lines: list[str] = []
        for path in (self._rotated, self._path):
            lines.extend(self._read_lines(path))
        records: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records[-count:] if count > 0 else []

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                return []
            except PermissionError:
                if attempt == _ATTEMPTS:
                    return []
                time.sleep(_RETRY_BACKOFF_S * attempt)
            except OSError:
                return []
            else:
                return [line for line in text.splitlines() if line.strip()]
        return []


__all__ = ["ALLOWED_FIELDS", "MAX_BYTES", "EventLog"]
