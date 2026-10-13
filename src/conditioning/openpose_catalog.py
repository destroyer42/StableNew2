"""Registry-backed listing of the OpenPose reference library for the editor (PR-IMG-CNET-210).

``AssetRegistry`` stays the single local file-identity authority; this module only projects its ``OPENPOSE_IMAGE``
records into relative library identities for the picker. ``cached_listing`` reads the persisted snapshot and never scans;
``refresh_listing`` performs the (incremental, fingerprint-cached) scan. Both are worker-side: neither belongs on Tk.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.assets import AssetKind, AssetRegistry


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    #: Library-relative POSIX identity (what a PromptPack slot stores).
    identity: str
    size: int
    sha256: str

    @property
    def folder(self) -> str:
        return self.identity.rsplit("/", 1)[0] if "/" in self.identity else ""


@dataclass(frozen=True, slots=True)
class LibraryListing:
    entries: tuple[LibraryEntry, ...] = ()
    #: Whether a WebUI root is configured at all (without it there is no library to list).
    configured: bool = False
    #: Whether ``models/OpenPose`` exists on disk right now.
    folder_exists: bool = False
    error: str = ""

    @property
    def identities(self) -> frozenset[str]:
        return frozenset(entry.identity for entry in self.entries)


def _entries(snapshot: Any) -> tuple[LibraryEntry, ...]:
    found: dict[str, LibraryEntry] = {}
    for record in snapshot.records_for(AssetKind.OPENPOSE_IMAGE):
        for location in record.locations:
            if location.kind is not AssetKind.OPENPOSE_IMAGE:
                continue
            try:
                identity = location.path.relative_to(location.root).as_posix()
            except ValueError:
                continue
            found[identity] = LibraryEntry(identity, int(location.byte_size), record.sha256)
    return tuple(sorted(found.values(), key=lambda entry: entry.identity.lower()))


def _library_folder(registry: AssetRegistry) -> Path | None:
    for kind, path in registry.supported_roots():
        if kind is AssetKind.OPENPOSE_IMAGE:
            return path
    return None


def _listing(registry: AssetRegistry, snapshot: Any) -> LibraryListing:
    folder = _library_folder(registry)
    return LibraryListing(
        entries=_entries(snapshot),
        configured=folder is not None,
        folder_exists=bool(folder is not None and folder.is_dir()),
    )


def cached_listing(registry: AssetRegistry) -> LibraryListing:
    """The last persisted listing; never scans or hashes."""

    return _listing(registry, registry.cached_snapshot())


def refresh_listing(
    registry: AssetRegistry, *, cancelled: Callable[[], bool] | None = None
) -> LibraryListing:
    """Scan the library (cached by size/mtime) and return the fresh listing."""

    folder = _library_folder(registry)
    if folder is None:
        return LibraryListing()
    if not folder.is_dir():
        # Nothing to scan and nothing is written: the cache keeps whatever it had and is reconciled by the next scan of
        # an existing library (a scan always replaces this kind's entries).
        return LibraryListing(configured=True, folder_exists=False)
    result = registry.refresh(kinds={AssetKind.OPENPOSE_IMAGE}, cancelled=cancelled)
    return _listing(registry, result.snapshot)


def filter_entries(entries: Iterable[LibraryEntry], query: str) -> list[LibraryEntry]:
    """Case-insensitive, whitespace-separated AND search over the relative identity (file name and folders)."""

    terms = [term for term in str(query or "").lower().split() if term]
    if not terms:
        return list(entries)
    return [entry for entry in entries if all(term in entry.identity.lower() for term in terms)]


def controlnet_folder(registry: AssetRegistry) -> Path | None:
    """The ControlNet weights folder the registry already knows (``AssetKind.CONTROLNET``)."""

    for kind, path in registry.supported_roots():
        if kind is AssetKind.CONTROLNET:
            return path
    return None


__all__ = [
    "LibraryEntry",
    "LibraryListing",
    "cached_listing",
    "controlnet_folder",
    "filter_entries",
    "refresh_listing",
]
