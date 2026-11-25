"""Rebuildable, root-local SQLite projection for Operator Site browsing."""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import stat
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Condition, Event, Lock, RLock, Thread
from typing import TYPE_CHECKING, Any, cast
from weakref import ReferenceType, WeakSet, WeakValueDictionary

from src.app.site_library_query import PAGE_SIZE, SORTS, LibraryQuery
from src.app.site_media_files import SiteOutputError, inside, is_link, open_scoped
from src.app.site_rating_sync import root_identity
from src.utils.atomic_io import atomic_write_bytes

if TYPE_CHECKING:
    from src.app.site_output_library import LibraryItem, OutputLibrary

_SCHEMA = 4
_DEFAULT_PREVIEW_BYTES = 2 * 1024**3
_FACET_LIMIT = 64
_LOG = logging.getLogger(__name__)
_CACHE_MARKER = b"StableNew Output Library cache v1\n"
_DIRECTORY_LOCK = Lock()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS status (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    epoch TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL, limited INTEGER NOT NULL
);
INSERT OR IGNORE INTO status VALUES (1, lower(hex(randomblob(16))), 0, 'incomplete', 0);
CREATE TABLE IF NOT EXISTS media (
    key TEXT PRIMARY KEY,
    path TEXT NOT NULL, version TEXT NOT NULL, sidecar TEXT NOT NULL,
    kind TEXT NOT NULL, name TEXT NOT NULL, timestamp INTEGER NOT NULL,
    source TEXT NOT NULL, width INTEGER, height INTEGER, ratio TEXT,
    orientation TEXT, family TEXT, model TEXT, workflow TEXT, model_text TEXT,
    prompt TEXT NOT NULL, tags TEXT NOT NULL, seed TEXT,
    body TEXT NOT NULL, enriched INTEGER NOT NULL, folder TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS media_time ON media (timestamp DESC, key);
CREATE INDEX IF NOT EXISTS media_time_oldest ON media (timestamp, key);
CREATE INDEX IF NOT EXISTS media_name ON media (name, key);
CREATE INDEX IF NOT EXISTS media_name_desc ON media (name DESC, key);
CREATE INDEX IF NOT EXISTS media_kind_time ON media (kind, timestamp DESC, key);
CREATE INDEX IF NOT EXISTS media_source ON media (source);
CREATE INDEX IF NOT EXISTS media_folder ON media (folder);
CREATE INDEX IF NOT EXISTS media_model ON media (family, model);
CREATE INDEX IF NOT EXISTS media_workflow ON media (workflow);
CREATE INDEX IF NOT EXISTS media_dimensions ON media (width, height);
CREATE INDEX IF NOT EXISTS media_ratio ON media (ratio, orientation);
CREATE INDEX IF NOT EXISTS media_pending ON media (enriched, timestamp DESC, key);
"""

_PREVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS preview (
    key TEXT PRIMARY KEY, ready INTEGER NOT NULL, mime TEXT NOT NULL,
    data BLOB NOT NULL, digest TEXT, checksum TEXT NOT NULL,
    size INTEGER NOT NULL, touched INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS preview_lru ON preview (touched, key);
CREATE TABLE IF NOT EXISTS preview_size (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1), size INTEGER NOT NULL
);
INSERT OR IGNORE INTO preview_size VALUES (1, 0);
CREATE TRIGGER IF NOT EXISTS preview_insert AFTER INSERT ON preview
BEGIN UPDATE preview_size SET size = size + NEW.size WHERE singleton = 1; END;
CREATE TRIGGER IF NOT EXISTS preview_delete AFTER DELETE ON preview
BEGIN UPDATE preview_size SET size = size - OLD.size WHERE singleton = 1; END;
CREATE TRIGGER IF NOT EXISTS preview_update AFTER UPDATE OF size ON preview
BEGIN UPDATE preview_size SET size = size + NEW.size - OLD.size WHERE singleton = 1; END;
"""

_UPSERT = """
INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(key) DO UPDATE SET
 path=excluded.path, version=excluded.version, sidecar=excluded.sidecar, kind=excluded.kind,
 name=excluded.name, timestamp=excluded.timestamp, source=excluded.source,
 width=excluded.width, height=excluded.height, ratio=excluded.ratio, orientation=excluded.orientation,
 family=excluded.family, model=excluded.model, workflow=excluded.workflow, model_text=excluded.model_text,
 prompt=excluded.prompt, tags=excluded.tags, seed=excluded.seed, body=excluded.body, enriched=excluded.enriched, folder=excluded.folder
"""


def _cache_config() -> tuple[Path, int]:
    override = os.environ.get("STABLENEW_SITE_LIBRARY_CACHE_DIR")
    local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    base = Path(local_data) if local_data else Path.home() / ".cache"
    directory = Path(override) if override else base / "StableNew" / "output-library"
    if not directory.is_absolute():
        raise SiteOutputError("library_cache_unavailable")
    try:
        budget = int(
            os.environ.get("STABLENEW_SITE_LIBRARY_CACHE_BYTES", str(_DEFAULT_PREVIEW_BYTES))
        )
    except ValueError:
        budget = _DEFAULT_PREVIEW_BYTES
    return directory, max(0, min(16 * 1024**3, budget))


class _ObsoleteSchema(Exception):
    pass


class _Database:
    def __init__(self, directory: Path, name: str, schema: str) -> None:
        self.cache_dir = directory
        self.database = directory / name
        self.schema = schema
        self._ready = False
        self._rebuild = False
        self._generation = 0
        self._init_lock = RLock()
        self._no_connections = Condition(self._init_lock)
        self._connections = 0

    def _own_cache_directory(self) -> None:
        with _DIRECTORY_LOCK:
            parent = self.cache_dir
            while True:
                try:
                    info = parent.lstat()
                except FileNotFoundError:
                    parent = parent.parent
                    continue
                if is_link(info) or not stat.S_ISDIR(info.st_mode):
                    raise SiteOutputError("library_cache_unavailable")
                break
            if parent.resolve(strict=True) != parent:
                raise SiteOutputError("library_cache_unavailable")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            marker = self.cache_dir / ".stablenew-output-library"
            try:
                with open_scoped(self.cache_dir, marker) as stream:
                    if stream.read(len(_CACHE_MARKER) + 1) != _CACHE_MARKER:
                        raise SiteOutputError("library_cache_unavailable")
            except FileNotFoundError:
                if any(self.cache_dir.iterdir()):
                    raise SiteOutputError("library_cache_unavailable") from None
                atomic_write_bytes(marker, _CACHE_MARKER)

    def _check_cache_paths(self) -> None:
        if is_link(self.cache_dir.lstat()) or self.cache_dir.resolve(strict=True) != self.cache_dir:
            raise SiteOutputError("library_cache_unavailable")
        for suffix in ("", "-wal", "-shm", "-journal"):
            candidate = self.database.with_name(self.database.name + suffix)
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise SiteOutputError("library_cache_unavailable")

    def _connect(self) -> sqlite3.Connection:
        self._check_cache_paths()
        connection = sqlite3.connect(self.database, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA user_version").fetchone()
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    @staticmethod
    def _is_corrupt(error: sqlite3.DatabaseError) -> bool:
        code = getattr(error, "sqlite_errorcode", 0)
        return code & 255 in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)

    def _create(self) -> None:
        with closing(self._connect()) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, _SCHEMA):
                raise _ObsoleteSchema
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(self.schema)
            db.execute(f"PRAGMA user_version={_SCHEMA}")
            db.execute("SELECT name FROM sqlite_schema LIMIT 1").fetchone()

    def initialize(self) -> None:
        if self._ready:
            return
        with self._init_lock:
            if self._ready:
                return
            self._own_cache_directory()
            self._check_cache_paths()
            try:
                if self._rebuild:
                    raise _ObsoleteSchema
                self._create()
            except (sqlite3.DatabaseError, _ObsoleteSchema) as error:
                if isinstance(error, sqlite3.DatabaseError) and not self._is_corrupt(error):
                    raise
                if not self._no_connections.wait_for(lambda: self._connections == 0, timeout=2):
                    raise sqlite3.OperationalError("Derived index recovery is busy") from error
                if self._ready:
                    return
                _LOG.info("Rebuilding derived Output Library index")
                self._check_cache_paths()
                for suffix in ("", "-wal", "-shm", "-journal"):
                    self.database.with_name(self.database.name + suffix).unlink(missing_ok=True)
                self._create()
            self._rebuild = False
            self._generation += 1
            self._ready = True

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._init_lock:
            self.initialize()
            generation = self._generation
            try:
                db = self._connect()
            except sqlite3.DatabaseError as error:
                if not self._is_corrupt(error):
                    raise
                self._mark_corrupt(generation)
                self.initialize()
                generation = self._generation
                db = self._connect()
            self._connections += 1
        try:
            with closing(db), db:
                yield db
        except sqlite3.DatabaseError as error:
            if self._is_corrupt(error):
                self._mark_corrupt(generation)
            raise
        finally:
            with self._no_connections:
                self._connections -= 1
                self._no_connections.notify_all()

    def _mark_corrupt(self, generation: int) -> None:
        with self._init_lock:
            if generation == self._generation:
                self._ready = False
                self._rebuild = True


class PreviewCache(_Database):
    def __init__(self, directory: Path, budget: int) -> None:
        super().__init__(directory, "previews.sqlite3", _PREVIEW_SCHEMA)
        self.budget = budget
        self.lock = Lock()

    def put_preview(
        self,
        key: str,
        ready: bool,
        mime: str,
        data: bytes,
        digest: str | None,
        checksum: str,
        touched: int,
    ) -> None:
        # The minimum charge also bounds cached failures and SQLite row overhead.
        size = len(data) + 256
        if size > self.budget:
            if self.budget < 256:
                return
            ready, mime, data, digest = False, "", b"", None
            checksum = hashlib.sha256(b"").hexdigest()
            size = 256
        with self.connection() as db:
            db.execute(
                "INSERT INTO preview VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET"
                " ready=excluded.ready, mime=excluded.mime, data=excluded.data, digest=excluded.digest,"
                " checksum=excluded.checksum, size=excluded.size, touched=excluded.touched",
                (key, ready, mime, data, digest, checksum, size, touched),
            )
            self._evict(db)

    def _evict(self, db: sqlite3.Connection) -> None:
        excess = db.execute("SELECT size FROM preview_size").fetchone()[0] - self.budget
        while excess > 0:
            rows = list(db.execute("SELECT key, size FROM preview ORDER BY touched, key LIMIT 128"))
            victims = []
            for key, size in rows:
                victims.append((key,))
                excess -= size
                if excess <= 0:
                    break
            db.executemany("DELETE FROM preview WHERE key = ?", victims)
            if not rows:
                raise sqlite3.DatabaseError("Invalid preview cache size")
        db.execute("PRAGMA incremental_vacuum(16)")

    def enforce_budget(self) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._evict(db)

    def preview_states(self, keys: list[str]) -> dict[str, str]:
        if not keys or not self.budget:
            return {}
        parameters = ",".join("?" for _ in keys)
        with self.connection() as db:
            return {
                key: "ready" if ready else "placeholder"
                for key, ready in db.execute(
                    f"SELECT key, ready FROM preview WHERE key IN ({parameters}) AND size <= ?",
                    [*keys, self.budget],
                )
            }

    def preview(self, key: str, *, touch: int | None = None) -> sqlite3.Row | None:
        if self.budget <= 0:
            return None
        with self.connection() as db:
            record = cast(
                sqlite3.Row | None,
                db.execute("SELECT * FROM preview WHERE key = ?", (key,)).fetchone(),
            )
            # Coarse access times avoid writing the same cache row on every repeated request.
            if record is not None and record["size"] <= self.budget and touch is not None:
                if touch - record["touched"] >= 60:
                    db.execute("UPDATE preview SET touched = ? WHERE key = ?", (touch, key))
                return record
            return record if record is not None and record["size"] <= self.budget else None


class LibraryIndex(_Database):
    def __init__(self, root: Path, identity: str, previews: PreviewCache) -> None:
        super().__init__(previews.cache_dir, f"{identity}.sqlite3", _SCHEMA_SQL)
        self.root = root
        self.identity = identity
        self.previews = previews
        self.worker_lock = Lock()
        self.clients: WeakSet[OutputLibrary] = WeakSet()
        self.scanning = self.running = self.worker_error = False
        self.wake = Event()
        self.refresh = Event()
        self.requested: OrderedDict[str, tuple[ReferenceType[OutputLibrary], LibraryItem]] = (
            OrderedDict()
        )
        self.cancel: Event | None = None
        self.thread: Thread | None = None

    def check_root(self) -> None:
        inside(self.root, self.root)
        if root_identity(self.root) != self.identity:
            raise SiteOutputError("output_folder_changed")

    @staticmethod
    def bump(db: sqlite3.Connection) -> None:
        db.execute("UPDATE status SET revision = revision + 1 WHERE singleton = 1")

    def write_rows(self, db: sqlite3.Connection, rows: Sequence[tuple[Any, ...]]) -> None:
        if rows:
            db.executemany(_UPSERT, rows)
            self.bump(db)

    def get(self, key: str) -> sqlite3.Row | None:
        with self.connection() as db:
            return cast(
                sqlite3.Row | None,
                db.execute("SELECT * FROM media WHERE key = ?", (key,)).fetchone(),
            )

    def query(
        self, query: LibraryQuery, *, facets: bool, revision: Callable[[str, int], str]
    ) -> tuple[list[sqlite3.Row], int, str, str, bool, bool, dict[str, Any]]:
        where, params = query.where()
        with self.connection() as db:
            db.execute("BEGIN")
            epoch, current, state, limited = db.execute(
                "SELECT epoch, revision, state, limited FROM status"
            ).fetchone()
            token = revision(epoch, current)
            if query.offset and query.revision != token:
                raise SiteOutputError("stale_library_page")
            rows = list(
                db.execute(
                    f"SELECT * FROM media{where} ORDER BY {SORTS[query.sort]} LIMIT ? OFFSET ?",
                    [*params, PAGE_SIZE, query.offset],
                )
            )
            total = db.execute(f"SELECT count(*) FROM media{where}", params).fetchone()[0]
            pending = db.execute("SELECT 1 FROM media WHERE enriched = 0 LIMIT 1").fetchone()
            values = self._facets(db, where, params) if facets else {}
        return rows, total, token, state, bool(limited), pending is not None, values

    @staticmethod
    def _facets(db: sqlite3.Connection, where: str, params: list[object]) -> dict[str, Any]:
        result = {}
        for name, columns in {
            "source": "source",
            "model_family": "family",
            "model": "model",
            "workflow": "workflow",
            "dimensions": "width, height",
            "aspect_ratio": "ratio",
            "orientation": "orientation",
        }.items():
            rows = list(
                db.execute(
                    f"SELECT {columns}, count(*) FROM media{where} GROUP BY {columns}"
                    f" ORDER BY count(*) DESC, {columns} LIMIT ?",
                    [*params, _FACET_LIMIT + 1],
                )
            )
            result[name] = {
                "values": [
                    {
                        "value": list(row[:-1]) if len(row) > 2 and row[0] is not None else row[0],
                        "count": row[-1],
                    }
                    for row in rows[:_FACET_LIMIT]
                ],
                "limited": len(rows) > _FACET_LIMIT,
            }
        return result


_SHARED_LOCK = Lock()
_SHARED: WeakValueDictionary[Path, LibraryIndex] = WeakValueDictionary()
_PREVIEWS: WeakValueDictionary[Path, PreviewCache] = WeakValueDictionary()


def index_for(root: Path) -> LibraryIndex:
    directory, budget = _cache_config()
    identity = root_identity(root)
    if directory.is_relative_to(root):
        raise SiteOutputError("library_cache_unavailable")
    database = directory / f"{identity}.sqlite3"
    with _SHARED_LOCK:
        index = _SHARED.get(database)
        if index is None:
            previews = _PREVIEWS.get(directory)
            if previews is None:
                previews = PreviewCache(directory, budget)
                _PREVIEWS[directory] = previews
            index = LibraryIndex(root, identity, previews)
            _SHARED[database] = index
        return index
