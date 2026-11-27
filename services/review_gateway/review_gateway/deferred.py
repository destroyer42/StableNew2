"""RG-160: requests that wait for the PC, cancelling them, and what the PC last told the phone it may choose.

Called by ``store.Store`` inside its own connection or write lock. As everywhere in the gateway, nothing here decides
anything: a waiting request is an ordinary outbox record, cancelling takes it out of what the PC is sent, and the
choice catalog is shown to the phone and never used to accept or refuse a request.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

#: The outbox step of a request made while the PC is away.
QUEUE_STEP = "queue"
#: How long an answered or cancelled request stays in the phone's waiting list. Unanswered ones always stay.
ANSWERED_SHOWN = timedelta(days=7)
#: The PC asks for the outbox every few seconds; its "last seen" time is written no more often than this.
_SEEN_EVERY = timedelta(seconds=15)
_LIST_LIMIT = 1200

_TABLE = """
CREATE TABLE IF NOT EXISTS pc_note (name TEXT PRIMARY KEY, payload TEXT NOT NULL, received_at TEXT NOT NULL)
"""
_UPSERT = (
    "INSERT INTO pc_note VALUES (?, ?, ?) ON CONFLICT (name) DO UPDATE SET"
    " payload = excluded.payload, received_at = excluded.received_at"
)
_STEP = "json_extract(record, '$.action_request.params.step')"
_WAITING = f"kind = 'action_request' AND status = 'pending' AND {_STEP} = '{QUEUE_STEP}'"


def initialize(db: sqlite3.Connection) -> None:
    db.execute(_TABLE)
    columns = {row[1] for row in db.execute("PRAGMA table_info(outbox)")}
    if "cancelled_at" not in columns:
        db.execute("ALTER TABLE outbox ADD COLUMN cancelled_at TEXT")


def _stamped(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _note(db: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return db.execute("SELECT payload, received_at FROM pc_note WHERE name = ?", (name,)).fetchone()


def pc_seen(db: sqlite3.Connection, now: datetime, text: str) -> None:
    """The PC has just asked for the outbox."""

    row = _note(db, "seen")
    if row is None or now - _stamped(row["received_at"]) >= _SEEN_EVERY:
        db.execute(_UPSERT, ("seen", "", text))


def set_catalog(db: sqlite3.Connection, catalog: dict[str, Any], text: str) -> None:
    db.execute(_UPSERT, ("catalog", json.dumps(catalog), text))


def catalog(db: sqlite3.Connection) -> tuple[dict[str, Any] | None, str | None]:
    """The latest choice catalog without its envelope, and when it arrived."""

    row = _note(db, "catalog")
    if row is None:
        return None, None
    body = json.loads(row["payload"])
    body.pop("schema_version", None)
    body.pop("type", None)
    return body, row["received_at"]


def presence(db: sqlite3.Connection) -> dict[str, Any]:
    """When the PC was last there, and whether its image backend then listed its models."""

    seen = _note(db, "seen")
    latest, received_at = catalog(db)
    return {
        "pc_seen_at": seen["received_at"] if seen else None,
        "image_backend_ready": latest["image_backend_ready"] if latest else None,
        "catalog_at": received_at,
    }


def waiting_count(db: sqlite3.Connection, device_id: str) -> int:
    return db.execute(
        f"SELECT count(*) FROM outbox WHERE {_WAITING} AND device_id = ?", (device_id,)
    ).fetchone()[0]


def waiting_actions(db: sqlite3.Connection) -> dict[tuple[str, str], list[str]]:
    """The actions waiting for the PC, by item, in the order made."""

    found: dict[tuple[str, str], list[str]] = {}
    for row in db.execute(
        "SELECT library_id, sha256, json_extract(record, '$.action_request.action') AS action"
        f" FROM outbox WHERE {_WAITING} ORDER BY seq"
    ):
        found.setdefault((row["library_id"], row["sha256"]), []).append(row["action"])
    return found


def listed(db: sqlite3.Connection, device_id: str, now: str) -> list[sqlite3.Row]:
    """This phone's deferred requests, newest first: every waiting one, and the recently finished ones."""

    before = (_stamped(now) - ANSWERED_SHOWN).isoformat(timespec="microseconds")
    return db.execute(
        "SELECT record, status, acknowledgement, delivered_at, cancelled_at FROM outbox"
        f" WHERE device_id = ? AND kind = 'action_request' AND {_STEP} = '{QUEUE_STEP}'"
        " AND (status = 'pending' OR COALESCE(answered_at, cancelled_at) >= ?)"
        " ORDER BY seq DESC LIMIT ?",
        (device_id, before.replace("+00:00", "Z"), _LIST_LIMIT),
    ).fetchall()


def cancel(db: sqlite3.Connection, device_id: str, record_id: str, now: str) -> str | None:
    """Cancel one of this phone's requests. ``None`` when it is not one of them.

    ``cancelled``: the PC never had it. ``cancel_sent``: it had, so its answer may still arrive. ``delivered``: a
    confirm the PC already has is left alone, because it may be admitting it. Otherwise the request's own state.
    """

    row = db.execute(
        f"SELECT status, delivered_at, cancelled_at, {_STEP} AS step FROM outbox"
        " WHERE record_id = ? AND device_id = ? AND kind = 'action_request'",
        (record_id, device_id),
    ).fetchone()
    if row is None:
        return None
    if row["status"] != "pending":
        if row["status"] == "superseded":
            return "cancel_sent" if row["delivered_at"] else "cancelled"
        return "applied" if row["status"] == "duplicate" else row["status"]
    if row["delivered_at"] and row["step"] == "confirm":
        return "delivered"
    db.execute(
        "UPDATE outbox SET status = 'superseded', cancelled_at = ? WHERE record_id = ?",
        (now, record_id),
    )
    return "cancel_sent" if row["delivered_at"] else "cancelled"


def cancel_for_delete(db: sqlite3.Connection, key: tuple[str, str], now: str) -> None:
    """A Delete archives the source, so nothing waiting for it could run."""

    db.execute(
        "UPDATE outbox SET status = 'superseded', cancelled_at = ?"
        f" WHERE library_id = ? AND sha256 = ? AND {_WAITING}",
        (now, *key),
    )
