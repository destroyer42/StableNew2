"""The durable Immich upload queue and its receipts, in the gateway's one database (D3, S9).

One row per item says what Immich is still owed. It is rewritten in the same transaction as the decision or the
PC's answer that changes it, so a crash cannot leave a keep without its upload. Functions here take an open
connection; the caller owns the transaction.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .contract import SCHEMA_VERSION, Contract
from .errors import GatewayError

#: How long a Keep waits before it leaves for Immich, so a mis-tap can be taken back: the gateway never
#: removes anything from Immich.
SETTLE = timedelta(seconds=60)
BACKOFF_FIRST_S = 30
BACKOFF_LIMIT_S = 900
#: A failure that may pass is reported only after this many tries.
QUIET_ATTEMPTS = 5
RECEIPT_PAGE = 200

TABLES = """
CREATE TABLE IF NOT EXISTS immich_upload (
    library_id TEXT NOT NULL, sha256 TEXT NOT NULL, record_id TEXT NOT NULL, favorite INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','failed','done','cancelled')),
    attempts INTEGER NOT NULL, next_attempt_at TEXT NOT NULL,
    asset_id TEXT, origin TEXT, favorite_set INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (library_id, sha256)
);
CREATE INDEX IF NOT EXISTS immich_upload_due ON immich_upload (state, next_attempt_at);
CREATE TABLE IF NOT EXISTS immich_album (run_id TEXT PRIMARY KEY, album_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS immich_receipt (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT NOT NULL UNIQUE, receipt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gateway_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Claim:
    """One owed upload, as it was when the uploader picked it up."""

    library_id: str
    sha256: str
    record_id: str
    favorite: bool
    run_id: str
    created_at: str
    digest: str
    content_type: str
    asset_id: str | None
    favorite_set: bool

    @property
    def key(self) -> tuple[str, str]:
        return self.library_id, self.sha256


def initialize(db: sqlite3.Connection) -> None:
    db.executescript(TABLES)
    # Receipt cursors carry this, so a rebuilt database is read from the start again.
    db.execute(
        "INSERT OR IGNORE INTO gateway_meta VALUES ('receipt_epoch', ?)", (secrets.token_hex(8),)
    )


def reconcile(db: sqlite3.Connection, key: tuple[str, str], due: str) -> None:
    """Make the item's row match its decision in force: the newest record not refused or replaced."""

    latest = db.execute(
        "SELECT record_id, record FROM outbox WHERE library_id = ? AND sha256 = ?"
        " AND status IN ('pending','applied','duplicate') ORDER BY seq DESC LIMIT 1",
        key,
    ).fetchone()
    decision = json.loads(latest["record"])["decision"] if latest else None
    if decision is None or decision["verdict"] != "keep":
        db.execute(
            "UPDATE immich_upload SET state = 'cancelled' WHERE library_id = ? AND sha256 = ?", key
        )
        return
    db.execute(
        "INSERT INTO immich_upload (library_id, sha256, record_id, favorite, state, attempts,"
        " next_attempt_at) VALUES (?, ?, ?, ?, 'queued', 0, ?)"
        " ON CONFLICT (library_id, sha256) DO UPDATE SET record_id = excluded.record_id,"
        " favorite = excluded.favorite, state = 'queued', attempts = 0,"
        " next_attempt_at = excluded.next_attempt_at"
        " WHERE immich_upload.record_id <> excluded.record_id OR immich_upload.state = 'cancelled'",
        (*key, latest["record_id"], decision["favorite"], due),
    )


def claim(db: sqlite3.Connection, now: str) -> Claim | None:
    """The longest-due upload. A revoked phone's unanswered keep waits for the PC to judge it."""

    row = db.execute(
        "SELECT owed.library_id, owed.sha256, owed.record_id, owed.favorite, item.run_id,"
        " item.created_at, item_media.digest, item_media.content_type, owed.asset_id,"
        " owed.favorite_set"
        " FROM immich_upload AS owed JOIN item USING (library_id, sha256)"
        " JOIN item_media ON item_media.library_id = owed.library_id"
        "  AND item_media.sha256 = owed.sha256 AND item_media.variant = 'original'"
        " WHERE owed.state IN ('queued','failed') AND owed.next_attempt_at <= ?"
        " AND item.purged_at IS NULL AND NOT EXISTS ("
        "   SELECT 1 FROM outbox JOIN device USING (device_id)"
        "   WHERE outbox.record_id = owed.record_id AND outbox.status = 'pending'"
        "   AND device.revoked_at IS NOT NULL)"
        " ORDER BY owed.next_attempt_at, owed.library_id LIMIT 1",
        (now,),
    ).fetchone()
    if row is None:
        return None
    values = dict(row)
    values["favorite"] = bool(values["favorite"])
    values["favorite_set"] = bool(values["favorite_set"])
    return Claim(**values)


def send_to_back(db: sqlite3.Connection, claimed: Claim, now: str) -> None:
    """Let other due uploads go first, so one item cannot hold the head of the queue."""

    db.execute(
        "UPDATE immich_upload SET next_attempt_at = ? WHERE library_id = ? AND sha256 = ?"
        " AND record_id = ?",
        (now, *claimed.key, claimed.record_id),
    )


def remember_asset(db: sqlite3.Connection, claimed: Claim, asset_id: str, created: bool) -> None:
    """Recorded before the album and favorite steps, so a retry still reports who uploaded it."""

    db.execute(
        "UPDATE immich_upload SET asset_id = ?,"
        " origin = CASE WHEN asset_id IS ? THEN origin ELSE ? END,"
        " favorite_set = CASE WHEN asset_id IS ? THEN favorite_set ELSE 0 END"
        " WHERE library_id = ? AND sha256 = ?",
        (asset_id, asset_id, "uploaded" if created else "duplicate", asset_id, *claimed.key),
    )


def remember_favorite(db: sqlite3.Connection, claimed: Claim, favorite: bool) -> None:
    db.execute(
        "UPDATE immich_upload SET favorite_set = ? WHERE library_id = ? AND sha256 = ?",
        (favorite, *claimed.key),
    )


def album_id(db: sqlite3.Connection, run_id: str) -> str | None:
    row = db.execute("SELECT album_id FROM immich_album WHERE run_id = ?", (run_id,)).fetchone()
    return row["album_id"] if row else None


def remember_album(db: sqlite3.Connection, run_id: str, value: str | None) -> None:
    if value is None:
        db.execute("DELETE FROM immich_album WHERE run_id = ?", (run_id,))
    else:
        db.execute("INSERT OR REPLACE INTO immich_album VALUES (?, ?)", (run_id, value))


def succeed(db: sqlite3.Connection, contract: Contract, claimed: Claim, at: str) -> None:
    row = db.execute(
        "SELECT asset_id, origin FROM immich_upload WHERE library_id = ? AND sha256 = ?",
        claimed.key,
    ).fetchone()
    _report(
        db,
        contract,
        claimed,
        at,
        status=row["origin"],
        immich_asset_id=row["asset_id"],
        album=claimed.run_id,
        favorite=claimed.favorite,
    )
    # Anything decided while this was uploading keeps its own row state.
    db.execute(
        "UPDATE immich_upload SET state = 'done' WHERE library_id = ? AND sha256 = ?"
        " AND record_id = ? AND state <> 'cancelled'",
        (*claimed.key, claimed.record_id),
    )
    # The next record for this item finds it already there.
    db.execute(
        "UPDATE immich_upload SET origin = 'duplicate' WHERE library_id = ? AND sha256 = ?",
        claimed.key,
    )


def fail(
    db: sqlite3.Connection,
    contract: Contract,
    claimed: Claim,
    code: str,
    *,
    transient: bool,
    now: datetime,
    stamp: str,
    later: Any,
) -> None:
    """Back this item off, and report it unless the failure may still pass quietly.

    ``later(delay)`` is the stored form of ``now + delay``.
    """

    row = db.execute(
        "SELECT attempts, record_id, state FROM immich_upload WHERE library_id = ? AND sha256 = ?",
        claimed.key,
    ).fetchone()
    if row["record_id"] != claimed.record_id or row["state"] == "cancelled":
        return
    attempts = row["attempts"] + 1
    delay = min(BACKOFF_FIRST_S * 2 ** min(attempts - 1, 20), BACKOFF_LIMIT_S)
    db.execute(
        "UPDATE immich_upload SET state = 'failed', attempts = ?, next_attempt_at = ?"
        " WHERE library_id = ? AND sha256 = ?",
        (attempts, later(timedelta(seconds=delay)), *claimed.key),
    )
    if not transient or attempts >= QUIET_ATTEMPTS:
        report_failure(db, contract, claimed, code, stamp)


def report_failure(
    db: sqlite3.Connection, contract: Contract, claimed: Claim, code: str, at: str
) -> None:
    _report(db, contract, claimed, at, status="failed", error_code=code[:64])


def _report(
    db: sqlite3.Connection, contract: Contract, claimed: Claim, at: str, **fields: Any
) -> None:
    """Add or replace the record's receipt. A replacement gets a new place in the PC's cursor order."""

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "type": "immich_receipt",
        "record_id": claimed.record_id,
        "item": {"library_id": claimed.library_id, "sha256": claimed.sha256},
        "at": at,
        **fields,
    }
    contract.validate("immich_receipt", receipt)
    previous = db.execute(
        "SELECT receipt FROM immich_receipt WHERE record_id = ?", (claimed.record_id,)
    ).fetchone()
    if previous is not None and {**json.loads(previous["receipt"]), "at": at} == receipt:
        return
    db.execute(
        "INSERT OR REPLACE INTO immich_receipt (record_id, receipt) VALUES (?, ?)",
        (claimed.record_id, json.dumps(receipt)),
    )


def receipt_page(db: sqlite3.Connection, cursor: str) -> dict[str, Any]:
    """Receipts after ``cursor``, oldest first. ``next_cursor`` is null only when there are none."""

    epoch = db.execute("SELECT value FROM gateway_meta WHERE key = 'receipt_epoch'").fetchone()[0]
    after = 0
    if cursor:
        sent, separator, position = cursor.partition(":")
        if not (
            separator and len(sent) == len(epoch) and position.isascii() and position.isdigit()
        ):
            raise GatewayError(400, "invalid_cursor")
        if sent == epoch:
            after = min(int(position[:19]), 2**62)
    rows = db.execute(
        "SELECT seq, receipt FROM immich_receipt WHERE seq > ? ORDER BY seq LIMIT ?",
        (after, RECEIPT_PAGE),
    ).fetchall()
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "immich_receipt_page",
        "receipts": [json.loads(row["receipt"]) for row in rows],
        "next_cursor": f"{epoch}:{rows[-1]['seq']}" if rows else None,
    }


def counts(db: sqlite3.Connection) -> dict[str, int]:
    found = dict(db.execute("SELECT state, count(*) FROM immich_upload GROUP BY state").fetchall())
    return {
        "immich_waiting": found.get("queued", 0),
        "immich_failing": found.get("failed", 0),
        "immich_uploaded": found.get("done", 0),
    }
