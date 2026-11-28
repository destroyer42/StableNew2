"""How long the phone took to open an image (the PHONE-FAST gate): a small, capped table in a file of its own.

A row is when the gateway received it, which enrolled phone sent it, the milliseconds, where the bytes came from and
how many there were. Nothing here names an item, a path, a prompt or an address. It is ``timing.sqlite3``, beside the
review database and never part of it: losing it loses only measurements, and a deploy that rolls back (which compares
``gateway.sqlite3``'s tables before restoring it) is not affected.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from .store import Clock, stamp

KEPT = timedelta(days=30)
MAXIMUM_ROWS = 100_000
#: Rows in one page of the PC's read: about 0.5 MB, well inside the client's response bound.
PAGE = 5000

_TABLES = """
CREATE TABLE IF NOT EXISTS open_timing (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, device_id TEXT NOT NULL, batch TEXT NOT NULL,
    ms INTEGER NOT NULL, source TEXT NOT NULL, bytes INTEGER
);
CREATE INDEX IF NOT EXISTS open_timing_batch ON open_timing (device_id, batch);
CREATE INDEX IF NOT EXISTS open_timing_at ON open_timing (at);
"""


class TimingStore:
    def __init__(self, database: Path, clock: Clock) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._connection() as db:
            db.executescript(_TABLES)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.database, timeout=10, isolation_level=None)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            yield db

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _oldest_kept(self) -> str:
        return stamp(self.clock() - KEPT)

    def _prune(self, db: sqlite3.Connection) -> int:
        removed = db.execute(
            "DELETE FROM open_timing WHERE at < ?", (self._oldest_kept(),)
        ).rowcount
        # The newest MAXIMUM_ROWS stay: everything from the first row beyond them goes.
        removed += db.execute(
            "DELETE FROM open_timing WHERE seq <="
            " (SELECT seq FROM open_timing ORDER BY seq DESC LIMIT 1 OFFSET ?)",
            (MAXIMUM_ROWS,),
        ).rowcount
        return removed

    def add(self, device_id: str, batch: str, samples: list[dict[str, Any]]) -> str:
        """Store a checked batch once. Returns ``stored``, or ``duplicate`` for a batch sent again."""

        now = stamp(self.clock())
        with self._write() as db:
            sent = db.execute(
                "SELECT 1 FROM open_timing WHERE device_id = ? AND batch = ? LIMIT 1",
                (device_id, batch),
            ).fetchone()
            if sent is not None:
                return "duplicate"
            db.executemany(
                "INSERT INTO open_timing (at, device_id, batch, ms, source, bytes)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(now, device_id, batch, s["ms"], s["source"], s["bytes"]) for s in samples],
            )
            self._prune(db)
        return "stored"

    def page(self, after: int) -> dict[str, Any]:
        """Rows after row number ``after``, oldest first, without the device they came from."""

        with self._connection() as db:
            found = db.execute(
                "SELECT seq, at, ms, source, bytes FROM open_timing WHERE seq > ? AND at >= ?"
                " ORDER BY seq LIMIT ?",
                (after, self._oldest_kept(), PAGE + 1),
            ).fetchall()
        shown = found[:PAGE]
        return {
            "rows": [
                {"at": at, "ms": ms, "source": source, "bytes": size}
                for _seq, at, ms, source, size in shown
            ],
            "next_cursor": shown[-1][0] if len(found) > PAGE else None,
        }

    def retention(self) -> dict[str, int]:
        with self._write() as db:
            return {"timing_rows_purged": self._prune(db)}
