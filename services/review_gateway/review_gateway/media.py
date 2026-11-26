"""Content-addressed media cache. A file under ``blobs/`` is always complete and digest-verified."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from .errors import GatewayError

_DIGEST = re.compile(r"[0-9a-f]{64}")
# By default the cache shares a disk with the database; a decision must always have room to be written.
FREE_SPACE_RESERVE = 1024**3


def is_digest(value: str) -> bool:
    return _DIGEST.fullmatch(value) is not None


class MediaStore:
    def __init__(self, directory: Path) -> None:
        self.blobs = Path(directory) / "blobs"
        self.incoming = Path(directory) / "incoming"
        for path in (self.blobs, self.incoming):
            path.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        if not is_digest(digest):
            raise GatewayError(404, "not_found")
        return self.blobs / digest[:2] / digest

    def size(self, digest: str) -> int | None:
        try:
            return self.path(digest).stat().st_size
        except FileNotFoundError:
            return None

    def writer(self, digest: str, size: int) -> MediaWriter:
        if shutil.disk_usage(self.incoming).free < size + FREE_SPACE_RESERVE:
            raise GatewayError(507, "storage_unavailable")
        return MediaWriter(self, digest, size)

    def delete(self, digests: Iterable[str]) -> int:
        removed = 0
        for digest in digests:
            try:
                self.path(digest).unlink()
                removed += 1
            except FileNotFoundError:
                continue
        return removed

    def sweep(self, referenced: set[str], older_than_s: float, now: float) -> int:
        """Remove abandoned partial uploads and files no live item names, once they are old enough."""

        stale = [*self.incoming.glob("*"), *self.blobs.glob("*/*")]
        removed = 0
        for path in stale:
            if path.name in referenced:
                continue
            try:
                if now - path.stat().st_mtime < older_than_s:
                    continue
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
        return removed


class MediaWriter:
    """Stream one upload to a temporary file and publish it only if size and SHA-256 match."""

    def __init__(self, store: MediaStore, digest: str, size: int) -> None:
        self.target = store.path(digest)
        self.digest = digest
        self.size = size
        self.received = 0
        self._hash = hashlib.sha256()
        handle, name = tempfile.mkstemp(dir=store.incoming, suffix=".part")
        self._path = Path(name)
        self._stream = os.fdopen(handle, "wb")

    def write(self, data: bytes) -> None:
        self.received += len(data)
        if self.received > self.size:
            raise GatewayError(413, "size_mismatch")
        self._hash.update(data)
        self._stream.write(data)

    def commit(self) -> None:
        if self.received != self.size:
            raise GatewayError(422, "size_mismatch")
        if self._hash.hexdigest() != self.digest:
            raise GatewayError(422, "digest_mismatch")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self._path, self.target)
        _sync_directory(self.target.parent)
        # The sweep ages files by modification time.
        now = time.time()
        os.utime(self.target, (now, now))

    def discard(self) -> None:
        """Safe after ``commit``: the temporary file is gone by then."""

        self._stream.close()
        self._path.unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    handle = os.open(path, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)
