"""Explicit relink of a moved, renamed or restored file (PR-VID-MOTION-LIB-353).

A file at a different path is never assumed to be the original.  Relinking hashes the candidate and accepts
it only when it equals the asset's recorded SHA-256; otherwise the operator is told to import it as a new
asset.  The previous location stays on the record as an alias, so no path history is lost.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from src.video.motion_library.hashing import HashCancelled, sha256_file
from src.video.motion_library.importer import SUPPORTED_SUFFIXES
from src.video.motion_library.models import LOCATOR_LINKED, AssetLocator
from src.video.motion_library.store import LibraryError, MotionLibraryStore


@dataclass(frozen=True, slots=True)
class RelinkOutcome:
    ok: bool
    reason: str = ""


def relink_asset(
    store: MotionLibraryStore,
    asset_id: str,
    new_path: str | Path,
    *,
    cancel: threading.Event | None = None,
) -> RelinkOutcome:
    asset = store.get(asset_id)
    if asset is None:
        return RelinkOutcome(False, "That library asset no longer exists.")
    candidate = Path(str(new_path or "")).expanduser()
    if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
        return RelinkOutcome(False, "Choose a supported video file (.mp4, .webm, .mov, .mkv).")
    try:
        if not candidate.is_file():
            return RelinkOutcome(False, "The chosen file does not exist.")
        candidate = candidate.resolve()
        before = candidate.stat()
        digest = sha256_file(candidate, cancel)
        after = candidate.stat()
    except HashCancelled:
        return RelinkOutcome(False, "Relink was cancelled.")
    except OSError as exc:
        return RelinkOutcome(False, f"The chosen file cannot be read: {exc}")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        return RelinkOutcome(
            False, "The file changed while it was being read; try again when it is settled."
        )
    if digest != asset.sha256:
        return RelinkOutcome(
            False,
            "That file's bytes differ from the original clip, so it was not relinked. "
            "Import it as a new asset instead.",
        )
    try:
        store.relink(
            asset_id, AssetLocator(LOCATOR_LINKED, str(candidate), after.st_size, after.st_mtime_ns)
        )
    except (LibraryError, OSError) as exc:
        return RelinkOutcome(False, f"The library could not be updated: {exc}")
    return RelinkOutcome(True)


__all__ = ["RelinkOutcome", "relink_asset"]
