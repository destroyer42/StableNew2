"""Incremental discovery for one approved Output root."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from threading import Event
from time import time_ns
from typing import Any

from src.app.site_library_index import LibraryIndex
from src.app.site_library_query import SEARCH_LIMIT
from src.app.site_media_files import MEDIA_TYPES, SiteOutputError, inside, is_link

_ENTRY_LIMIT = 250_000
_SETTLE_NS = 800_000_000
_BATCH_SIZE = 128
_HIDDEN = ".stablenew-library"


def version_of(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def manifest_path(path: Path) -> Path:
    return path.parent / "manifests" / (path.stem + ".json")


def _temporary(name: str) -> bool:
    stem = Path(name).stem.casefold()
    return name.startswith(".") or stem.endswith((".tmp", ".partial", ".part", ".metadata_tmp"))


class Reconciliation:
    def __init__(self, index: LibraryIndex) -> None:
        self.index = index
        self.directories: dict[Path, int] = {}
        self.unsettled: dict[str, tuple[tuple[int, ...], int]] = {}

    def inventory(
        self,
        cancel: Event,
        ensure_active: Callable[[], None],
        basic: Callable[[Path, str, tuple[int, ...], str], tuple[Any, ...]],
        *,
        full: bool,
    ) -> str:
        """Commit bounded batches. Prune an inventory only after a successful walk."""
        root = self.index.root
        self.index.check_root()
        known = self.directories
        targets = [root] if full else []
        error = False
        limited = False
        if not full:
            for folder, stamp in known.items():
                if cancel.is_set():
                    return "incomplete"
                try:
                    info = folder.lstat()
                    if is_link(info) or info.st_mtime_ns != stamp:
                        targets.append(folder)
                        if folder.name == "manifests":
                            targets.append(folder.parent)
                except FileNotFoundError:
                    targets.append(folder.parent)
                except OSError:
                    error = True
            targets.extend((root / relative).parent for relative in self.unsettled)
        if not targets:
            return "error" if error else "complete"

        checked: set[Path] = set()
        updated: dict[Path, int] = {}
        now = time_ns()
        visited = 0
        count = 0
        rows: list[tuple[Any, ...]] = []
        seen: list[tuple[str]] = []
        with self.index.connection() as db:
            db.execute("CREATE TEMP TABLE seen (key TEXT PRIMARY KEY) WITHOUT ROWID")
            versions = (
                {
                    row["path"]: (row["version"], row["sidecar"], row["key"])
                    for row in db.execute("SELECT key, path, version, sidecar FROM media")
                }
                if full
                else {}
            )
            if full:
                db.execute("UPDATE status SET state = 'reconciling'")
                db.commit()

            def flush() -> None:
                ensure_active()
                if rows:
                    inside(root, folder)
                    if not os.path.samestat(folder_info, folder.stat()):
                        raise SiteOutputError("media_changed")
                    for row in rows:
                        info = os.lstat(root / row[1])
                        if is_link(info) or json.dumps(version_of(info)) != row[2]:
                            raise SiteOutputError("media_changed")
                self.index.write_rows(db, rows)
                db.executemany("INSERT OR IGNORE INTO seen VALUES (?)", seen)
                db.commit()
                rows.clear()
                seen.clear()

            while targets and not limited:
                if cancel.is_set():
                    return "incomplete"
                ensure_active()
                folder = targets.pop()
                if folder in checked:
                    continue
                checked.add(folder)
                if not full:
                    db.execute("DELETE FROM seen")
                try:
                    inside(root, folder)
                    folder_info = folder.lstat()
                    updated[folder] = folder_info.st_mtime_ns
                    sidecars = self._sidecars(folder)
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if cancel.is_set():
                                return "incomplete"
                            visited += 1
                            if visited > _ENTRY_LIMIT or count >= SEARCH_LIMIT:
                                limited = True
                                break
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() != _HIDDEN:
                                    info = entry.stat(follow_symlinks=False)
                                    child = Path(entry.path)
                                    if not is_link(info) and (full or child not in known):
                                        targets.append(child)
                                continue
                            mime = MEDIA_TYPES.get(Path(entry.name).suffix.lower())
                            if mime is None or _temporary(entry.name):
                                continue
                            info = os.lstat(entry.path)
                            if is_link(info) or not stat.S_ISREG(info.st_mode):
                                continue
                            count += 1
                            path = Path(entry.path)
                            relative = path.relative_to(root).as_posix()
                            version = version_of(info)
                            version_json = json.dumps(version)
                            sidecar = sidecars.get(os.path.normcase(path.stem), "")
                            existing = (
                                versions.get(relative)
                                if full
                                else db.execute(
                                    "SELECT version, sidecar, key FROM media WHERE key = ?",
                                    (key_for(relative),),
                                ).fetchone()
                            )
                            if existing is not None and tuple(existing)[:2] == (
                                version_json,
                                sidecar,
                            ):
                                self.unsettled.pop(relative, None)
                                seen.append((existing[2],))
                            elif self._stable(relative, version, now):
                                record = basic(path, mime, version, sidecar)
                                rows.append(record)
                                seen.append((record[0],))
                            elif existing is not None:
                                seen.append((existing[2],))
                            if len(rows) >= _BATCH_SIZE or len(seen) >= 2 * _BATCH_SIZE:
                                flush()
                        flush()
                    if (
                        not full
                        and not limited
                        and folder.lstat().st_mtime_ns == folder_info.st_mtime_ns
                    ):
                        ensure_active()
                        inside(root, folder)
                        removed = db.execute(
                            "DELETE FROM media WHERE folder = ? AND key NOT IN (SELECT key FROM seen)",
                            (folder.relative_to(root).as_posix(),),
                        )
                        if removed.rowcount:
                            self.index.bump(db)
                        db.commit()
                except FileNotFoundError:
                    rows.clear()
                    seen.clear()
                    # Retain indexed records after a race. The next full pass prunes them.
                    if full or folder == root:
                        error = True
                except (OSError, SiteOutputError):
                    rows.clear()
                    seen.clear()
                    error = True
            if cancel.is_set():
                return "incomplete"
            flush()
            if full and not limited and not error:
                ensure_active()
                removed = db.execute("DELETE FROM media WHERE key NOT IN (SELECT key FROM seen)")
                if removed.rowcount:
                    self.index.bump(db)
                for relative in tuple(self.unsettled):
                    if (root / relative).parent not in updated:
                        self.unsettled.pop(relative, None)
            if full:
                db.execute("UPDATE status SET limited = ?", (limited,))
            if not error:
                if full:
                    self.directories = updated
                else:
                    known.update(updated)
                    for folder in checked - updated.keys():
                        known.pop(folder, None)
        return "error" if error else "incomplete" if limited else "complete"

    @staticmethod
    def _sidecars(folder: Path) -> dict[str, str]:
        manifests = folder / "manifests"
        try:
            if is_link(manifests.lstat()):
                return {}
            with os.scandir(manifests) as entries:
                return {
                    os.path.normcase(Path(entry.name).stem): json.dumps(version_of(info))
                    for entry in entries
                    if Path(entry.name).suffix.lower() == ".json"
                    and stat.S_ISREG((info := os.lstat(entry.path)).st_mode)
                    and not is_link(info)
                }
        except FileNotFoundError:
            return {}

    def _stable(self, relative: str, version: tuple[int, ...], now: int) -> bool:
        if relative not in self.unsettled and now - max(version[3], version[4]) >= 2 * _SETTLE_NS:
            return True
        previous, first = self.unsettled.get(relative, ((), now))
        if version == previous:
            if now - first >= _SETTLE_NS:
                self.unsettled.pop(relative)
                return True
        else:
            self.unsettled[relative] = version, now
        return False


def key_for(relative: str) -> str:
    return hashlib.sha256(os.path.normcase(relative).encode()).hexdigest()[:32]
