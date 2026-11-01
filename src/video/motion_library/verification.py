"""Is the file an asset points at still the file that was imported?  (PR-VID-MOTION-LIB-353)

Two levels, so browsing stays cheap and use stays strict:

* ``quick_check`` costs one ``stat``: it compares size and modification time with what the locator
  recorded.  It never hashes and never decodes, so a catalog of any size can be classified while the
  operator filters.  ``unverified`` means "the timestamp moved; the bytes may be the same".
* ``verify_content`` hashes the whole file in bounded chunks and compares with the recorded SHA-256.
  Selecting an asset for a job always uses this; a mismatch is ``changed`` and is never accepted as the
  original -- the operator must import the new file, or explicitly relink a file that hashes the same.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from src.video.motion_library.hashing import HashCancelled, sha256_file
from src.video.motion_library.models import MotionAsset

FILE_OK = "ok"
FILE_UNVERIFIED = "unverified"
FILE_MISSING = "missing"
FILE_CHANGED = "changed"
FILE_UNREADABLE = "unreadable"
FILE_CANCELLED = "cancelled"

_MESSAGES = {
    FILE_OK: "File verified against its recorded SHA-256.",
    FILE_UNVERIFIED: "The file's modified time differs from the import; it is verified before use.",
    FILE_MISSING: "The file is missing. Relink it to the same bytes, or import the new file.",
    FILE_CHANGED: "The file no longer matches its recorded SHA-256. It is not the original clip.",
    FILE_UNREADABLE: "The file cannot be read.",
    FILE_CANCELLED: "Verification was cancelled.",
}


@dataclass(frozen=True, slots=True)
class FileCheck:
    state: str
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.state == FILE_OK

    @property
    def message(self) -> str:
        return self.detail or _MESSAGES.get(self.state, self.state)


def quick_check(asset: MotionAsset, path: Path) -> FileCheck:
    """Cheap presence/size/timestamp classification; never ``ok`` because nothing was hashed."""

    try:
        if not path.is_file():
            return FileCheck(FILE_MISSING)
        stat = path.stat()
    except OSError:
        return FileCheck(FILE_UNREADABLE)
    recorded = asset.locator
    if recorded.size_bytes is not None and recorded.size_bytes != stat.st_size:
        return FileCheck(
            FILE_CHANGED, "The file's size differs from the import; it is not the original clip."
        )
    if recorded.mtime_ns is not None and recorded.mtime_ns != stat.st_mtime_ns:
        return FileCheck(FILE_UNVERIFIED)
    return FileCheck(FILE_UNVERIFIED, "Not yet verified this session.")


def verify_content(
    asset: MotionAsset, path: Path, cancel: threading.Event | None = None
) -> FileCheck:
    """Hash ``path`` and compare with ``asset.sha256``."""

    try:
        if not path.is_file():
            return FileCheck(FILE_MISSING)
        actual = sha256_file(path, cancel)
    except HashCancelled:
        return FileCheck(FILE_CANCELLED)
    except OSError:
        return FileCheck(FILE_UNREADABLE)
    return FileCheck(FILE_OK) if actual == asset.sha256 else FileCheck(FILE_CHANGED)


__all__ = [
    "FILE_CANCELLED",
    "FILE_CHANGED",
    "FILE_MISSING",
    "FILE_OK",
    "FILE_UNREADABLE",
    "FILE_UNVERIFIED",
    "FileCheck",
    "quick_check",
    "verify_content",
]
