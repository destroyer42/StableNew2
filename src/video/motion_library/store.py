"""Versioned local catalog of motion-reference videos (PR-VID-MOTION-LIB-353).

The store owns exactly one thing: ``<root>/library.json`` (plus the ``managed/`` copies and ``thumbs/``
thumbnails beside it).  It is application data, deliberately distinct from the job repository and the
model registry, and it never decides what runs.

Safety rules (each has a test):

* the root must be an explicit absolute folder outside any Git working tree;
* every manifest update is a complete atomic write (``atomic_write_json``); a failed write leaves the
  previous manifest on disk *and* the previous state in memory;
* a corrupt or newer-than-supported manifest is refused and left untouched, never overwritten;
* records the running version cannot parse are kept verbatim in ``unparsed`` and written back;
* a managed copy is staged as ``<name>.<token>.partial`` and published only after its bytes hash to the
  expected SHA-256, so an interrupted import leaves at most a ``.partial`` file, which the next open
  removes; a published copy with no manifest entry is reported, never deleted;
* nothing here deletes, moves or rewrites an original video.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_replace, atomic_write_bytes, atomic_write_json
from src.video.motion_library.hashing import HASH_CHUNK_BYTES, HashCancelled
from src.video.motion_library.models import (
    ANNOTATION_FIELDS,
    LOCATOR_LINKED,
    MAX_ALIASES,
    AssetAlias,
    AssetFormatError,
    AssetLocator,
    GeneratedOrigin,
    MotionAsset,
    clean_note,
    clean_text,
    is_sha256,
    new_asset_id,
    normalize_tags,
    utc_now_iso,
)

MANIFEST_NAME = "library.json"
SCHEMA = "stablenew.motion-library"
SCHEMA_VERSION = 1
MANAGED_DIR = "managed"
THUMBS_DIR = "thumbs"
PARTIAL_SUFFIX = ".partial"
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
STALE_PARTIAL_SECONDS = 3600.0


class LibraryError(Exception):
    """Base class; the message is operator-facing."""


class LibraryRootError(LibraryError):
    pass


class LibraryCorruptError(LibraryError):
    pass


class LibraryVersionError(LibraryError):
    pass


class UnknownAssetError(LibraryError):
    pass


class SourceChangedError(LibraryError):
    """The bytes copied did not hash to the SHA-256 the caller verified moments earlier."""


class DuplicateAssetError(LibraryError):
    def __init__(self, existing_id: str) -> None:
        super().__init__("These bytes are already in the library.")
        self.existing_id = existing_id


def validate_library_root(root: str | Path) -> Path:
    """The resolved absolute library folder, or ``LibraryRootError`` (relative, a file, or inside a Git tree)."""

    text = str(root or "").strip()
    if not text:
        raise LibraryRootError("No Motion Library folder is configured.")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise LibraryRootError("The Motion Library folder must be an absolute path.")
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise LibraryRootError(f"The Motion Library folder cannot be resolved: {exc}") from exc
    if resolved.exists() and not resolved.is_dir():
        raise LibraryRootError("The Motion Library folder path is a file, not a folder.")
    if resolved.parent == resolved:
        raise LibraryRootError("The Motion Library folder cannot be a drive root.")
    for folder in (resolved, *resolved.parents):
        try:
            tracked = (folder / ".git").exists()
        except OSError:
            tracked = False
        if tracked:
            raise LibraryRootError(
                "The Motion Library folder must be outside any Git repository, so third-party "
                f"media is never committed (found a repository at {folder})."
            )
    return resolved


@dataclass(frozen=True, slots=True)
class OpenReport:
    """What opening found: records it could not read, abandoned temporaries removed, unreferenced copies."""

    issues: tuple[str, ...] = ()
    removed_partials: int = 0
    orphan_files: tuple[str, ...] = ()


@dataclass(slots=True)
class _State:
    assets: dict[str, MotionAsset] = field(default_factory=dict)
    unparsed: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class MotionLibraryStore:
    def __init__(
        self,
        root: str | Path,
        *,
        token: Callable[[], str] = lambda: uuid.uuid4().hex,
        clock: Callable[[], str] = utc_now_iso,
        stale_partial_seconds: float = STALE_PARTIAL_SECONDS,
    ) -> None:
        self._root = validate_library_root(root)
        self._token = token
        self._clock = clock
        self._stale_partial_seconds = stale_partial_seconds
        self._lock = threading.RLock()
        self._state = _State()
        self.revision = 0
        self.report = OpenReport()
        self.reload()

    # ------------------------------------------------------------------ paths

    @property
    def root(self) -> Path:
        return self._root

    @property
    def manifest_path(self) -> Path:
        return self._root / MANIFEST_NAME

    @property
    def managed_dir(self) -> Path:
        return self._root / MANAGED_DIR

    @property
    def thumbs_dir(self) -> Path:
        return self._root / THUMBS_DIR

    def asset_path(self, asset: MotionAsset) -> Path:
        """The file an asset points at.  A linked path must be absolute; a managed name must be a bare file name."""

        locator = asset.locator
        if locator.mode == LOCATOR_LINKED:
            path = Path(locator.path)
            if not path.is_absolute():
                raise LibraryError("The linked file path is not absolute.")
            return path
        name = locator.path
        if not name or name != Path(name).name or name in {".", ".."}:
            raise LibraryError("The managed file name is unsafe.")
        return self.managed_dir / name

    def thumbnail_path(self, asset: MotionAsset) -> Path | None:
        name = asset.thumbnail
        if not name or name != Path(name).name or not name.endswith(".png"):
            return None
        return self.thumbs_dir / name

    # ------------------------------------------------------------------ loading

    def reload(self) -> None:
        """Re-read the manifest from disk and run the open-time recovery."""

        with self._lock:
            state, issues = self._read_manifest()
            self._state = state
            removed = self._remove_stale_partials()
            referenced = {
                a.locator.path for a in state.assets.values() if a.locator.mode != LOCATOR_LINKED
            }
            self.report = OpenReport(
                issues=tuple(issues),
                removed_partials=removed,
                orphan_files=self._orphan_files(referenced),
            )
            self.revision += 1

    def _read_manifest(self) -> tuple[_State, list[str]]:
        path = self.manifest_path
        state = _State()
        issues: list[str] = []
        if not path.exists():
            return state, issues
        try:
            if path.stat().st_size > MAX_MANIFEST_BYTES:
                raise LibraryCorruptError(
                    "The Motion Library manifest is unreasonably large; it was not opened."
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
        except LibraryCorruptError:
            raise
        except (OSError, ValueError) as exc:
            raise LibraryCorruptError(
                f"The Motion Library manifest ({path}) is unreadable and was left untouched: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise LibraryCorruptError(
                f"{path} is not a StableNew Motion Library manifest; it was left untouched."
            )
        version = payload.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise LibraryCorruptError(f"{path} has no valid version; it was left untouched.")
        if version > SCHEMA_VERSION:
            raise LibraryVersionError(
                f"This Motion Library was written by a newer StableNew (manifest version {version}); "
                "it was opened by nobody and left untouched."
            )
        state.extra = {
            k: v for k, v in payload.items() if k not in {"schema", "version", "assets", "unparsed"}
        }
        kept_unparsed = payload.get("unparsed")
        if isinstance(kept_unparsed, list):
            state.unparsed.extend(kept_unparsed)
        seen_sha: dict[str, str] = {}
        records = payload.get("assets")
        for index, raw in enumerate(records if isinstance(records, list) else []):
            try:
                asset = MotionAsset.from_dict(raw)
            except AssetFormatError as exc:
                state.unparsed.append(raw)
                issues.append(f"Record {index + 1} could not be read and is kept unchanged: {exc}")
                continue
            if asset.asset_id in state.assets or asset.sha256 in seen_sha:
                state.unparsed.append(raw)
                issues.append(f"Record {index + 1} duplicates another asset and is kept unchanged.")
                continue
            state.assets[asset.asset_id] = asset
            seen_sha[asset.sha256] = asset.asset_id
        return state, issues

    def _remove_stale_partials(self) -> int:
        folder = self.managed_dir
        removed = 0
        if not folder.is_dir():
            return 0
        now = time.time()
        try:
            candidates = [p for p in folder.iterdir() if p.name.endswith(PARTIAL_SUFFIX)]
        except OSError:
            return 0
        for item in candidates:
            try:
                if now - item.stat().st_mtime >= self._stale_partial_seconds:
                    item.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def _orphan_files(self, referenced: set[str]) -> tuple[str, ...]:
        folder = self.managed_dir
        if not folder.is_dir():
            return ()
        try:
            names = sorted(
                p.name
                for p in folder.iterdir()
                if p.is_file() and not p.name.endswith(PARTIAL_SUFFIX)
            )
        except OSError:
            return ()
        return tuple(name for name in names if name not in referenced)

    # ------------------------------------------------------------------ queries

    def assets(self) -> tuple[MotionAsset, ...]:
        with self._lock:
            return tuple(
                sorted(self._state.assets.values(), key=lambda a: (a.imported_at, a.asset_id))
            )

    def get(self, asset_id: str) -> MotionAsset | None:
        with self._lock:
            return self._state.assets.get(str(asset_id or ""))

    def require(self, asset_id: str) -> MotionAsset:
        asset = self.get(asset_id)
        if asset is None:
            raise UnknownAssetError("That library asset no longer exists.")
        return asset

    def find_by_sha(self, sha256: str) -> MotionAsset | None:
        with self._lock:
            return next((a for a in self._state.assets.values() if a.sha256 == sha256), None)

    def find_by_path(self, path: str | Path) -> MotionAsset | None:
        """The asset whose locator or alias names ``path`` (case-insensitive on Windows)."""

        wanted = os.path.normcase(str(path))
        with self._lock:
            for asset in self._state.assets.values():
                if (
                    asset.locator.mode == LOCATOR_LINKED
                    and os.path.normcase(asset.locator.path) == wanted
                ):
                    return asset
                if any(os.path.normcase(alias.path) == wanted for alias in asset.aliases):
                    return asset
        return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._state.assets)

    # ------------------------------------------------------------------ mutations (one atomic write each)

    def new_id(self) -> str:
        with self._lock:
            while True:
                candidate = new_asset_id(self._token())
                if candidate not in self._state.assets:
                    return candidate

    def add(self, asset: MotionAsset) -> MotionAsset:
        with self._lock:
            if asset.asset_id in self._state.assets:
                raise LibraryError("That library asset id already exists.")
            existing = self.find_by_sha(asset.sha256)
            if existing is not None:
                raise DuplicateAssetError(existing.asset_id)
            if not is_sha256(asset.sha256):
                raise LibraryError("An asset needs a SHA-256.")
            self._commit({**self._state.assets, asset.asset_id: asset})
            return asset

    def annotate(self, asset_id: str, changes: Mapping[str, Any]) -> MotionAsset:
        """Apply operator annotations.  Only ``ANNOTATION_FIELDS`` are accepted; identity fields never change."""

        unknown = sorted(set(changes) - set(ANNOTATION_FIELDS))
        if unknown:
            raise LibraryError(f"These fields cannot be edited: {', '.join(unknown)}.")
        with self._lock:
            asset = self.require(asset_id)
            normalized = {name: ANNOTATION_FIELDS[name](value) for name, value in changes.items()}
            if "display_name" in normalized and not normalized["display_name"]:
                raise LibraryError("A display name cannot be empty.")
            updated = asset.with_changes(**normalized)
            self._commit({**self._state.assets, asset_id: updated})
            return updated

    def update_origin(self, asset_id: str, changes: Mapping[str, Any]) -> MotionAsset:
        """Edit the operator-judged fields of a generated clip's origin (label, achieved, artifacts, reuse)."""

        allowed = {"motion_label", "motion_achieved", "known_artifacts", "reuse_conditions"}
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise LibraryError(f"These origin fields cannot be edited: {', '.join(unknown)}.")
        with self._lock:
            asset = self.require(asset_id)
            if asset.origin is None:
                raise LibraryError(
                    "Only a StableNew-generated clip has a generating job to annotate."
                )
            merged = {**asset.origin.to_dict(), **changes}
            updated = asset.with_changes(origin=GeneratedOrigin.from_dict(merged))
            self._commit({**self._state.assets, asset_id: updated})
            return updated

    def record_duplicate(
        self,
        asset_id: str,
        *,
        path: str,
        name: str = "",
        source_reference: str = "",
        tags: Iterable[str] = (),
    ) -> MotionAsset:
        """Same bytes seen again: keep one identity, remember the extra path and union the tags."""

        with self._lock:
            asset = self.require(asset_id)
            known = {os.path.normcase(a.path) for a in asset.aliases}
            if asset.locator.mode == LOCATOR_LINKED:
                known.add(os.path.normcase(asset.locator.path))
            aliases = asset.aliases
            if os.path.normcase(path) not in known and len(aliases) < MAX_ALIASES:
                aliases = (
                    *aliases,
                    AssetAlias(
                        path=path,
                        name=clean_text(name, 120),
                        source_reference=clean_text(source_reference),
                        added_at=self._clock(),
                    ),
                )
            merged_tags = normalize_tags([*asset.tags, *tags])
            if aliases == asset.aliases and merged_tags == asset.tags:
                return asset
            updated = asset.with_changes(aliases=aliases, tags=merged_tags)
            self._commit({**self._state.assets, asset_id: updated})
            return updated

    def attach_origin(self, asset_id: str, origin: GeneratedOrigin) -> MotionAsset:
        """Same bytes came from a StableNew job: keep it as the origin when there is none, otherwise note it."""

        with self._lock:
            asset = self.require(asset_id)
            if asset.origin is None:
                updated = asset.with_changes(origin=origin)
            elif asset.origin.job_id != origin.job_id:
                note = f"Same bytes also recorded from StableNew job {origin.job_id}."
                if note in asset.provenance_notes:
                    return asset
                updated = asset.with_changes(
                    provenance_notes=clean_note(
                        " ".join(filter(None, (asset.provenance_notes, note)))
                    )
                )
            else:
                return asset
            self._commit({**self._state.assets, asset_id: updated})
            return updated

    def relink(self, asset_id: str, locator: AssetLocator) -> MotionAsset:
        """Point an asset at a new location (the old linked path stays as an alias).  The caller has already
        verified the bytes hash to ``asset.sha256``."""

        with self._lock:
            asset = self.require(asset_id)
            aliases = asset.aliases
            previous = asset.locator.path
            if (
                asset.locator.mode == LOCATOR_LINKED
                and os.path.normcase(previous) != os.path.normcase(locator.path)
                and all(os.path.normcase(a.path) != os.path.normcase(previous) for a in aliases)
                and len(aliases) < MAX_ALIASES
            ):
                aliases = (
                    *aliases,
                    AssetAlias(path=previous, name=Path(previous).stem, added_at=self._clock()),
                )
            updated = asset.with_changes(locator=locator, aliases=aliases)
            self._commit({**self._state.assets, asset_id: updated})
            return updated

    def _commit(self, assets: dict[str, MotionAsset]) -> None:
        payload = {
            **self._state.extra,
            "schema": SCHEMA,
            "version": SCHEMA_VERSION,
            "assets": [
                a.to_dict()
                for a in sorted(assets.values(), key=lambda a: (a.imported_at, a.asset_id))
            ],
            "unparsed": list(self._state.unparsed),
        }
        atomic_write_json(self.manifest_path, payload, indent=2, ensure_ascii=False)
        self._state.assets = assets
        self.revision += 1

    # ------------------------------------------------------------------ files the library owns

    def copy_into_managed(
        self,
        source: str | Path,
        *,
        expected_sha256: str,
        suffix: str,
        cancel: threading.Event | None = None,
    ) -> tuple[str, int, int]:
        """Copy ``source`` into ``managed/<sha><suffix>``; returns ``(name, size_bytes, mtime_ns)``.

        The copy is hashed while it is written and published only when it equals ``expected_sha256``, so a
        source that changed after it was verified is refused.  The original is only ever opened for reading.
        """

        if not is_sha256(expected_sha256):
            raise LibraryError("A managed copy needs the verified SHA-256 of its source.")
        suffix = suffix.lower() if suffix.startswith(".") and suffix[1:].isalnum() else ""
        folder = self.managed_dir
        folder.mkdir(parents=True, exist_ok=True)
        final = folder / f"{expected_sha256}{suffix}"
        partial = folder / f"{final.name}.{self._token()[:8]}{PARTIAL_SUFFIX}"
        digest = hashlib.sha256()
        try:
            with Path(source).open("rb") as reader, partial.open("wb") as writer:
                for chunk in iter(lambda: reader.read(HASH_CHUNK_BYTES), b""):
                    if cancel is not None and cancel.is_set():
                        raise HashCancelled()
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if digest.hexdigest() != expected_sha256:
                raise SourceChangedError(
                    "The source file changed while it was being copied; nothing was imported."
                )
            atomic_replace(partial, final)
        except BaseException:
            try:
                partial.unlink()
            except OSError:
                pass
            raise
        stat = final.stat()
        return final.name, stat.st_size, stat.st_mtime_ns

    def store_thumbnail(self, sha256: str, png_bytes: bytes) -> str:
        """Write ``thumbs/<sha>.png`` (content-addressed; an existing one is kept) and return its name."""

        name = f"{sha256}.png"
        target = self.thumbs_dir / name
        if not target.exists():
            atomic_write_bytes(target, png_bytes)
        return name


__all__ = [
    "MANAGED_DIR",
    "MANIFEST_NAME",
    "PARTIAL_SUFFIX",
    "SCHEMA",
    "SCHEMA_VERSION",
    "THUMBS_DIR",
    "DuplicateAssetError",
    "LibraryCorruptError",
    "LibraryError",
    "LibraryRootError",
    "LibraryVersionError",
    "MotionLibraryStore",
    "OpenReport",
    "SourceChangedError",
    "UnknownAssetError",
    "validate_library_root",
]
