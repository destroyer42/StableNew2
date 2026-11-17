"""Bounded video snapshots for range playback over the existing Site relay."""

from __future__ import annotations

import hashlib
import secrets
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import BinaryIO

from src.app.site_media_files import SiteOutputError, open_scoped

CHUNK_LIMIT = 8 * 1024 * 1024
VIDEO_LIMIT = 512 * 1024 * 1024
_PLAY_SECONDS = 180


@dataclass
class Playback:
    stream: BinaryIO
    size: int
    mime: str
    expires: float


class VideoPlayback:
    def __init__(self, root: Path, active: Callable[[], None]) -> None:
        self.root = root
        self.active = active
        self._lock = Lock()
        self._prepare_lock = Lock()
        self._items: dict[str, Playback] = {}

    def _prune(self, *, limit: int) -> None:
        for identifier, item in list(self._items.items()):
            if item.expires <= time.monotonic() or len(self._items) > limit:
                self._items.pop(identifier).stream.close()

    def close(self) -> None:
        with self._lock:
            self._prune(limit=0)

    def prepare(self, path: Path, mime: str, expected: str | None) -> dict[str, object]:
        if mime not in ("video/mp4", "video/webm"):
            raise SiteOutputError("unsupported_media")
        with self._prepare_lock:
            return self._prepare(path, mime, expected)

    def _prepare(self, path: Path, mime: str, expected: str | None) -> dict[str, object]:
        snapshot: BinaryIO = tempfile.TemporaryFile()
        try:
            digest = hashlib.sha256()
            with open_scoped(self.root, path) as source:
                if not 0 < source.seek(0, 2) <= VIDEO_LIMIT:
                    raise SiteOutputError("media_too_large")
                source.seek(0)
                first = source.read(16)
                valid = (
                    first[4:8] == b"ftyp"
                    if mime == "video/mp4"
                    else first.startswith(b"\x1a\x45\xdf\xa3")
                )
                if not valid:
                    raise SiteOutputError("unsupported_media")
                source.seek(0)
                while data := source.read(CHUNK_LIMIT):
                    self.active()
                    if snapshot.tell() + len(data) > VIDEO_LIMIT:
                        raise SiteOutputError("media_too_large")
                    snapshot.write(data)
                    digest.update(data)
            if expected is not None and digest.hexdigest() != expected:
                raise SiteOutputError("media_changed")
            size = snapshot.tell()
            identifier = secrets.token_hex(16)
            with self._lock:
                self.active()
                self._prune(limit=1)
                self._items[identifier] = Playback(
                    snapshot, size, mime, time.monotonic() + _PLAY_SECONDS
                )
            return {"id": identifier, "size": size, "mime": mime}
        except BaseException:
            snapshot.close()
            raise

    def chunk(self, identifier: str, start: int, length: int) -> tuple[str, bytes]:
        with self._lock:
            self.active()
            self._prune(limit=2)
            item = self._items.get(identifier)
            if item is None:
                raise SiteOutputError("playback_expired")
            if not 0 <= start < item.size or not 0 < length <= CHUNK_LIMIT:
                raise SiteOutputError("invalid_range")
            item.stream.seek(start)
            item.expires = time.monotonic() + _PLAY_SECONDS
            return item.mime, item.stream.read(min(length, item.size - start))
