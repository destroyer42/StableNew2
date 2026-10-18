"""Read-only, paged and filtered history queries over the ``jobs`` table.

This adds no table, index, column or lifecycle effect. Results are ordered newest first by ``(created_at DESC,
rowid ASC)``, which is exactly the order of ``idx_jobs_created_at`` (its entries carry the rowid), so a position is
a stable keyset cursor even when many jobs share a creation time.

Filters that no index serves (status, pack, text) are applied to bounded *windows* of that ordered scan. A query
therefore costs at most ``max_examined`` rows of work no matter how rare the match is, and reports whether the
unexamined remainder can still be searched (``HistoryPage.exhausted``). Text matches ``payload_summary`` (the first
64 characters of the positive prompt and the base model), not the full prompt; searching every prompt needs the
index migration, which is a separate, backup-first decision.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime

from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
DEFAULT_MAX_EXAMINED = 2000
_MIN_WINDOW = 200
_ID_CHUNK = 400


@dataclass(frozen=True)
class HistoryCursor:
    """The position of the last row a page examined; the next page starts strictly after it."""

    created_at: str
    rowid: int


@dataclass(frozen=True)
class HistoryQuery:
    """What to find. Every field narrows the result; the default finds everything, newest first."""

    statuses: frozenset[JobStatus] = field(default_factory=frozenset)
    created_from: datetime | None = None
    created_before: datetime | None = None
    pack_id: str | None = None
    text: str = ""
    limit: int = DEFAULT_PAGE_SIZE
    max_examined: int = DEFAULT_MAX_EXAMINED
    cursor: HistoryCursor | None = None

    @property
    def terms(self) -> tuple[str, ...]:
        return tuple(_ascii_lower(term) for term in self.text.split())

    @property
    def needs_row_filter(self) -> bool:
        return bool(self.statuses or self.pack_id or self.terms)


@dataclass(frozen=True)
class HistoryPage:
    """One page of matches plus where to continue.

    ``next_cursor`` is where the next page starts; ``exhausted`` is true only when the whole ordered range was
    examined, so ``exhausted=False`` with few entries means "searched ``examined`` rows, older jobs remain".
    """

    entries: tuple[JobHistoryEntry, ...]
    next_cursor: HistoryCursor | None
    exhausted: bool
    examined: int


def _ascii_lower(value: str) -> str:
    # SQLite's lower() folds ASCII only, so fold the needle the same way or a non-ASCII term never matches.
    return "".join(char.lower() if char.isascii() else char for char in value)


def _bound(value: datetime) -> str:
    return (value.replace(tzinfo=None) if value.tzinfo is not None else value).isoformat()


def _read_positions(
    connection: sqlite3.Connection,
    query: HistoryQuery,
    cursor: HistoryCursor | None,
    size: int,
) -> list[HistoryCursor]:
    clauses: list[str] = []
    parameters: list[object] = []
    if query.created_from is not None:
        clauses.append("created_at >= ?")
        parameters.append(_bound(query.created_from))
    if query.created_before is not None:
        clauses.append("created_at < ?")
        parameters.append(_bound(query.created_before))
    if cursor is not None:
        clauses.append("(created_at < ? OR (created_at = ? AND rowid > ?))")
        parameters.extend([cursor.created_at, cursor.created_at, cursor.rowid])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT created_at, rowid AS rid FROM jobs{where} ORDER BY created_at DESC, rowid ASC LIMIT ?",
        (*parameters, size),
    ).fetchall()
    return [HistoryCursor(created_at=str(row["created_at"]), rowid=int(row["rid"])) for row in rows]


def _matching_rowids(
    connection: sqlite3.Connection, query: HistoryQuery, positions: Sequence[HistoryCursor]
) -> set[int]:
    clauses: list[str] = []
    parameters: list[object] = []
    if query.statuses:
        statuses = sorted(status.value for status in query.statuses)
        clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
        parameters.extend(statuses)
    if query.pack_id:
        clauses.append("prompt_pack_id = ?")
        parameters.append(query.pack_id)
    for term in query.terms:
        clauses.append("instr(lower(payload_summary), ?) > 0")
        parameters.append(term)
    extra = "".join(f" AND {clause}" for clause in clauses)
    hits: set[int] = set()
    for start in range(0, len(positions), _ID_CHUNK):
        chunk = [position.rowid for position in positions[start : start + _ID_CHUNK]]
        marks = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"SELECT rowid AS rid FROM jobs WHERE rowid IN ({marks}){extra}", (*chunk, *parameters)
        ).fetchall()
        hits.update(int(row["rid"]) for row in rows)
    return hits


def _fetch_entries(
    connection: sqlite3.Connection,
    matched: Sequence[HistoryCursor],
    hydrate: Callable[[sqlite3.Row], JobHistoryEntry],
) -> tuple[JobHistoryEntry, ...]:
    by_rowid: dict[int, sqlite3.Row] = {}
    for start in range(0, len(matched), _ID_CHUNK):
        chunk = [position.rowid for position in matched[start : start + _ID_CHUNK]]
        marks = ",".join("?" for _ in chunk)
        for row in connection.execute(
            f"SELECT rowid AS rid, * FROM jobs WHERE rowid IN ({marks})", tuple(chunk)
        ).fetchall():
            by_rowid[int(row["rid"])] = row
    return tuple(
        hydrate(by_rowid[position.rowid]) for position in matched if position.rowid in by_rowid
    )


def run_history_query(
    connection: sqlite3.Connection,
    query: HistoryQuery,
    hydrate: Callable[[sqlite3.Row], JobHistoryEntry],
    lock: AbstractContextManager[object] | None = None,
) -> HistoryPage:
    """Run ``query`` against ``connection`` without writing; ``hydrate`` turns a ``jobs`` row into an entry.

    ``lock`` guards the shared connection and is held per window (never across a whole query), so a long search
    cannot delay a queue transition by more than one window's work.
    """

    guard = lock if lock is not None else nullcontext()

    limit = min(max(1, int(query.limit)), MAX_PAGE_SIZE)
    budget = max(limit, int(query.max_examined))
    window = min(budget, max(limit * 4, _MIN_WINDOW)) if query.needs_row_filter else limit
    matched: list[HistoryCursor] = []
    cursor = query.cursor
    examined = 0
    exhausted = False
    while len(matched) < limit and examined < budget:
        size = min(window, budget - examined)
        with guard:
            # One extra position proves whether anything remains after this window.
            positions = _read_positions(connection, query, cursor, size + 1)
            more = len(positions) > size
            positions = positions[:size]
            hits = (
                _matching_rowids(connection, query, positions)
                if query.needs_row_filter and positions
                else {position.rowid for position in positions}
            )
        consumed_all = True
        for position in positions:
            examined += 1
            cursor = position
            if position.rowid in hits:
                matched.append(position)
                if len(matched) == limit:
                    consumed_all = position is positions[-1]
                    break
        if not more and consumed_all:
            exhausted = True
            break
    with guard:
        entries = _fetch_entries(connection, matched, hydrate)
    return HistoryPage(
        entries=entries,
        next_cursor=cursor,
        exhausted=exhausted,
        examined=examined,
    )


__all__ = [
    "DEFAULT_MAX_EXAMINED",
    "DEFAULT_PAGE_SIZE",
    "HistoryCursor",
    "HistoryPage",
    "HistoryQuery",
    "MAX_PAGE_SIZE",
    "run_history_query",
]
