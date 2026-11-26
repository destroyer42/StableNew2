"""Gateway state in SQLite: published items, the decision outbox, pairing offers and devices.

Everything here is a projection or a request (RG-100 invariants 2 and 4). It is WAL with ``synchronous=FULL`` (S9),
and retention only ever removes cached media for items whose latest decision the PC has answered.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .contract import SCHEMA_VERSION, Contract, ContractError
from .errors import GatewayError
from .media import MediaStore, MediaWriter

Clock = Callable[[], datetime]

OFFER_LIFETIME = timedelta(minutes=5)
DEFAULT_ATTEMPTS = 5
MAXIMUM_DEVICES = 50
DISCARD_UNDO = timedelta(hours=48)
KEEP_AFTER_ANSWER = timedelta(days=14)
STALE_FILE_S = 24 * 3600
_SEEN_RESOLUTION = timedelta(hours=1)

_TABLES = """
CREATE TABLE IF NOT EXISTS item (
    library_id TEXT NOT NULL, sha256 TEXT NOT NULL,
    run_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, duration_s REAL,
    display TEXT NOT NULL, ready_at TEXT, purged_at TEXT, latest_record_id TEXT,
    PRIMARY KEY (library_id, sha256)
);
CREATE INDEX IF NOT EXISTS item_run ON item (run_id, created_at, library_id);
CREATE TABLE IF NOT EXISTS item_media (
    library_id TEXT NOT NULL, sha256 TEXT NOT NULL, variant TEXT NOT NULL,
    digest TEXT NOT NULL, bytes INTEGER NOT NULL, content_type TEXT NOT NULL,
    PRIMARY KEY (library_id, sha256, variant)
);
CREATE INDEX IF NOT EXISTS item_media_digest ON item_media (digest);
CREATE TABLE IF NOT EXISTS outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL, device_id TEXT NOT NULL,
    library_id TEXT NOT NULL, sha256 TEXT NOT NULL, record TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','applied','refused','duplicate','superseded')),
    delivered_at TEXT, answered_at TEXT, acknowledgement TEXT,
    UNIQUE (device_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox (status, seq);
CREATE INDEX IF NOT EXISTS outbox_item ON outbox (library_id, sha256);
CREATE TABLE IF NOT EXISTS offer (
    offer_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
    code_salt TEXT NOT NULL, code_sha256 TEXT NOT NULL, scopes TEXT NOT NULL, label TEXT,
    expires_at TEXT NOT NULL, max_attempts INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, used_at TEXT
);
CREATE TABLE IF NOT EXISTS device (
    device_id TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, offer_id TEXT NOT NULL,
    label TEXT, scopes TEXT NOT NULL, enrolled_at TEXT NOT NULL, seen_at TEXT, revoked_at TEXT
);
"""

_ITEMS_WITH_STATE = """
SELECT item.*, outbox.record, outbox.status, outbox.acknowledgement
FROM item LEFT JOIN outbox ON outbox.record_id = item.latest_record_id
WHERE item.ready_at IS NOT NULL AND item.purged_at IS NULL
"""


@dataclass(frozen=True)
class Device:
    device_id: str
    label: str | None
    scopes: tuple[str, ...]


def utc_now() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    """Fixed-width UTC text, so SQL comparison and ordering follow time."""

    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def new_device_id() -> str:
    """A random device id that never starts with ``-``.

    ``secrets.token_urlsafe`` can start with ``-`` (about 1 in 64), which the admin command ``revoke <id>`` would read
    as an option. Every id still matches the schema's ``^[A-Za-z0-9_-]{8,64}$``.
    """
    while True:
        candidate = secrets.token_urlsafe(12)
        if not candidate.startswith("-"):
            return candidate


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_code(code: str) -> str:
    """The form the desktop hashes: uppercase, without the spaces and hyphens shown for reading."""

    return "".join(code.split()).replace("-", "").upper()


class Store:
    def __init__(
        self, database: Path, media: MediaStore, contract: Contract, clock: Clock = utc_now
    ) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.media = media
        self.contract = contract
        self.clock = clock
        with self.connection() as db:
            db.executescript(_TABLES)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.database, timeout=10, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            # Per connection, not stored in the file: a decision is on disk before the phone is told so.
            db.execute("PRAGMA synchronous=FULL")
            yield db

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    # --- publishing ---------------------------------------------------------------------------------------------

    def publish(self, manifest: dict[str, Any]) -> tuple[str, list[str]]:
        """Store a validated manifest. Returns ``(status, digests still to upload)``."""

        key = (manifest["item"]["library_id"], manifest["item"]["sha256"])
        media = manifest["media"]
        if media["original"]["sha256"] != key[1]:
            raise GatewayError(422, "item_digest_mismatch")
        display = dict(manifest.get("display", {}))
        if "seed" in display:
            display["seed"] = str(int(display["seed"]))  # beyond JavaScript's exact integers
        with self._write() as db:
            row = db.execute(
                "SELECT purged_at FROM item WHERE library_id = ? AND sha256 = ?", key
            ).fetchone()
            if row is not None and row["purged_at"] is not None:
                return "purged", []
            db.execute(
                "INSERT INTO item (library_id, sha256, run_id, kind, created_at, duration_s, display)"
                " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (library_id, sha256) DO UPDATE SET"
                " run_id = excluded.run_id, kind = excluded.kind, created_at = excluded.created_at,"
                " duration_s = excluded.duration_s, display = excluded.display",
                (
                    *key,
                    manifest["run_id"],
                    manifest["kind"],
                    stamp(_instant(manifest["created_at"])),
                    manifest.get("duration_s"),
                    json.dumps(display),
                ),
            )
            db.execute("DELETE FROM item_media WHERE library_id = ? AND sha256 = ?", key)
            missing: list[str] = []
            for variant, entry in media.items():
                digest, size = entry["sha256"], int(entry["bytes"])
                db.execute(
                    "INSERT INTO item_media VALUES (?, ?, ?, ?, ?, ?)",
                    (*key, variant, digest, size, entry["content_type"]),
                )
                stored = self.media.size(digest)
                if stored is None:
                    if digest not in missing:
                        missing.append(digest)
                elif stored != size:
                    raise GatewayError(422, "size_mismatch")
            if not missing:
                self._mark_ready(db, key)
        return ("incomplete" if missing else "ready"), missing

    def _mark_ready(self, db: sqlite3.Connection, key: tuple[str, str]) -> None:
        db.execute(
            "UPDATE item SET ready_at = COALESCE(ready_at, ?) WHERE library_id = ? AND sha256 = ?",
            (stamp(self.clock()), *key),
        )

    def upload(self, digest: str) -> MediaWriter | None:
        """A writer for a declared digest, or ``None`` when it is already stored."""

        with self.connection() as db:
            row = db.execute(
                "SELECT item_media.bytes FROM item_media JOIN item USING (library_id, sha256)"
                " WHERE item_media.digest = ? AND item.purged_at IS NULL LIMIT 1",
                (digest,),
            ).fetchone()
        if row is None:
            raise GatewayError(409, "unknown_media")
        if self.media.size(digest) is not None:
            return None
        return self.media.writer(digest, row["bytes"])

    def stored(self, digest: str) -> None:
        """Show every item that was waiting only for ``digest``."""

        with self._write() as db:
            waiting = db.execute(
                "SELECT DISTINCT library_id, sha256 FROM item_media JOIN item USING (library_id, sha256)"
                " WHERE item_media.digest = ? AND item.purged_at IS NULL AND item.ready_at IS NULL",
                (digest,),
            ).fetchall()
            for item in waiting:
                key = (item["library_id"], item["sha256"])
                needed = db.execute(
                    "SELECT digest FROM item_media WHERE library_id = ? AND sha256 = ?", key
                ).fetchall()
                if all(self.media.size(row["digest"]) is not None for row in needed):
                    self._mark_ready(db, key)

    # --- the phone's view ---------------------------------------------------------------------------------------

    def runs(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                _ITEMS_WITH_STATE + " ORDER BY item.run_id DESC, item.created_at, item.library_id"
            ).fetchall()
        runs: dict[str, dict[str, Any]] = {}
        for row in rows:
            run = runs.setdefault(
                row["run_id"],
                {
                    "run_id": row["run_id"],
                    **dict.fromkeys(("total", "undecided", "keep", "delete", "favorite"), 0),
                    **dict.fromkeys(("pending", "applied", "refused"), 0),
                    "covers": [],
                },
            )
            state, decision, _reason = _outcome(row)
            run["total"] += 1
            run[state] += 1
            if decision is not None and state != "refused":
                run[decision["verdict"]] += 1
                run["favorite"] += decision["favorite"]
            if len(run["covers"]) < 4:
                run["covers"].append({"library_id": row["library_id"], "sha256": row["sha256"]})
        return list(runs.values())

    def run_items(self, run_id: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                _ITEMS_WITH_STATE
                + " AND item.run_id = ? ORDER BY item.created_at, item.library_id",
                (run_id,),
            ).fetchall()
            variants = db.execute(
                "SELECT item_media.library_id, item_media.sha256, variant, digest FROM item_media"
                " JOIN item USING (library_id, sha256) WHERE item.run_id = ?",
                (run_id,),
            ).fetchall()
        names = {"thumb_320": "thumb", "preview_1080": "preview", "mobile_video": "video"}
        available: dict[tuple[str, str], list[str]] = {}
        for entry in variants:
            if self.media.size(entry["digest"]) is not None:
                key = (entry["library_id"], entry["sha256"])
                available.setdefault(key, []).append(names.get(entry["variant"], "original"))
        items = []
        for row in rows:
            state, decision, reason = _outcome(row)
            items.append(
                {
                    "library_id": row["library_id"],
                    "sha256": row["sha256"],
                    "kind": row["kind"],
                    "created_at": row["created_at"],
                    "duration_s": row["duration_s"],
                    "display": json.loads(row["display"]),
                    "variants": sorted(available.get((row["library_id"], row["sha256"]), [])),
                    "state": state,
                    "decision": decision,
                    "reason_code": reason,
                }
            )
        return items

    def media_file(self, library_id: str, sha256: str, variant: str) -> tuple[Path, str]:
        with self.connection() as db:
            row = db.execute(
                "SELECT item_media.digest, item_media.content_type FROM item_media"
                " JOIN item USING (library_id, sha256) WHERE item_media.library_id = ?"
                " AND item_media.sha256 = ? AND item_media.variant = ?"
                " AND item.ready_at IS NOT NULL AND item.purged_at IS NULL",
                (library_id, sha256, variant),
            ).fetchone()
        if row is None or self.media.size(row["digest"]) is None:
            raise GatewayError(404, "not_found")
        return self.media.path(row["digest"]), row["content_type"]

    # --- decisions and the outbox -------------------------------------------------------------------------------

    def decide(
        self,
        device_id: str,
        target: dict[str, str],
        decision: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, str]:
        """Record what the phone asked for. Returns ``(record_id, state)``."""

        record = {
            "record_id": str(uuid.uuid4()),
            "idempotency_key": idempotency_key,
            "device_id": device_id,
            "created_at": stamp(self.clock()),
            "target": target,
            "kind": "decision",
            "decision": decision,
        }
        try:
            self.contract.validate("outbox_record", record)
        except ContractError as error:
            raise GatewayError(422, "invalid_record") from error
        if decision["verdict"] == "delete":
            if decision["favorite"]:
                raise GatewayError(422, "favorite_with_delete")
            if "needs_fix" in decision.get("tags", []):
                raise GatewayError(422, "invalid_record")
        key = (target["library_id"], target["sha256"])
        with self._write() as db:
            # Checked again here: the request body may have arrived after a revocation (S11).
            if (
                db.execute(
                    "SELECT 1 FROM device WHERE device_id = ? AND revoked_at IS NULL", (device_id,)
                ).fetchone()
                is None
            ):
                raise GatewayError(401, "not_enrolled")
            previous = db.execute(
                "SELECT record_id, record, status FROM outbox"
                " WHERE device_id = ? AND idempotency_key = ?",
                (device_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                sent = json.loads(previous["record"])
                if sent["target"] != target or sent["decision"] != decision:
                    raise GatewayError(409, "idempotency_conflict")
                status = previous["status"]
                if status == "superseded":  # report what replaced it
                    status = db.execute(
                        "SELECT outbox.status FROM item JOIN outbox"
                        " ON outbox.record_id = item.latest_record_id"
                        " WHERE item.library_id = ? AND item.sha256 = ?",
                        key,
                    ).fetchone()["status"]
                return previous["record_id"], _state(status)
            item = db.execute(
                "SELECT latest_record_id FROM item WHERE library_id = ? AND sha256 = ?"
                " AND ready_at IS NOT NULL AND purged_at IS NULL",
                key,
            ).fetchone()
            if item is None:
                raise GatewayError(404, "unknown_item")
            # A record the PC has never seen can simply be replaced by the newer choice.
            db.execute(
                "UPDATE outbox SET status = 'superseded' WHERE record_id = ?"
                " AND status = 'pending' AND delivered_at IS NULL",
                (item["latest_record_id"],),
            )
            db.execute(
                "INSERT INTO outbox (record_id, idempotency_key, device_id, library_id, sha256,"
                " record, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (record["record_id"], idempotency_key, device_id, *key, json.dumps(record)),
            )
            db.execute(
                "UPDATE item SET latest_record_id = ? WHERE library_id = ? AND sha256 = ?",
                (record["record_id"], *key),
            )
        return record["record_id"], "pending"

    def outbox_page(self, after: int, limit: int) -> dict[str, Any]:
        with self._write() as db:
            rows = db.execute(
                "SELECT seq, record FROM outbox WHERE status = 'pending' AND seq > ?"
                " ORDER BY seq LIMIT ?",
                (after, limit + 1),
            ).fetchall()
            page = rows[:limit]
            db.executemany(
                "UPDATE outbox SET delivered_at = COALESCE(delivered_at, ?) WHERE seq = ?",
                [(stamp(self.clock()), row["seq"]) for row in page],
            )
            devices = db.execute(
                "SELECT device_id, offer_id, label, enrolled_at FROM device WHERE revoked_at IS NULL"
                " ORDER BY enrolled_at DESC LIMIT ?",
                (MAXIMUM_DEVICES,),
            ).fetchall()
        return {
            "schema_version": SCHEMA_VERSION,
            "type": "outbox_page",
            "records": [json.loads(row["record"]) for row in page],
            "next_cursor": str(page[-1]["seq"]) if len(rows) > limit else None,
            "enrolled_devices": [
                {key: row[key] for key in row.keys() if row[key] is not None} for row in devices
            ],
        }

    def acknowledge(self, acknowledgement: dict[str, Any]) -> str:
        record_id = acknowledgement["record_id"].lower()
        with self._write() as db:
            row = db.execute(
                "SELECT status FROM outbox WHERE record_id = ?", (record_id,)
            ).fetchone()
            if row is None:
                raise GatewayError(404, "unknown_record")
            if row["status"] != "pending":
                return "already_acknowledged"
            db.execute(
                "UPDATE outbox SET status = ?, answered_at = ?, acknowledgement = ?"
                " WHERE record_id = ?",
                (
                    acknowledgement["outcome"],
                    stamp(self.clock()),
                    json.dumps(acknowledgement),
                    record_id,
                ),
            )
        return "recorded"

    # --- enrollment ---------------------------------------------------------------------------------------------

    def add_offer(self, offer: dict[str, Any]) -> None:
        offer_id = offer["offer_id"].lower()
        payload = _hash(json.dumps(offer, sort_keys=True))
        now = self.clock()
        with self._write() as db:
            row = db.execute(
                "SELECT payload_sha256 FROM offer WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            if row is not None:
                if row["payload_sha256"] != payload:
                    raise GatewayError(409, "offer_conflict")
                return
            expires = _instant(offer["expires_at"])
            if expires <= now:
                raise GatewayError(422, "offer_expired")
            db.execute(
                "INSERT INTO offer (offer_id, payload_sha256, code_salt, code_sha256, scopes, label,"
                " expires_at, max_attempts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    offer_id,
                    payload,
                    offer["code_salt"],
                    offer["code_sha256"],
                    json.dumps(offer["scopes"]),
                    offer.get("device_label"),
                    stamp(min(expires, now + OFFER_LIFETIME)),
                    int(offer.get("max_attempts", DEFAULT_ATTEMPTS)),
                ),
            )

    def redeem(self, code: str, label: str | None) -> tuple[Device, str] | None:
        """Exchange a live single-use code for a new device and its secret token."""

        normalized = normalize_code(code)
        now = stamp(self.clock())
        with self._write() as db:
            live = db.execute(
                "SELECT * FROM offer WHERE used_at IS NULL AND expires_at > ?"
                " AND attempts < max_attempts",
                (now,),
            ).fetchall()
            match = None
            for offer in live:
                if hmac.compare_digest(
                    _hash(offer["code_salt"] + normalized), offer["code_sha256"]
                ):
                    match = offer
            if match is None:
                # The code does not say which offer it was meant for, so every live one is charged.
                db.executemany(
                    "UPDATE offer SET attempts = attempts + 1 WHERE offer_id = ?",
                    [(offer["offer_id"],) for offer in live],
                )
                return None
            active = db.execute("SELECT count(*) FROM device WHERE revoked_at IS NULL").fetchone()[
                0
            ]
            if active >= MAXIMUM_DEVICES:
                raise GatewayError(403, "device_limit")
            token = secrets.token_urlsafe(32)
            device = Device(
                new_device_id(),
                match["label"] or label,
                tuple(json.loads(match["scopes"])),
            )
            db.execute("UPDATE offer SET used_at = ? WHERE offer_id = ?", (now, match["offer_id"]))
            db.execute(
                "INSERT INTO device (device_id, token_sha256, offer_id, label, scopes, enrolled_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    device.device_id,
                    _hash(token),
                    match["offer_id"],
                    device.label,
                    match["scopes"],
                    now,
                ),
            )
        return device, token

    def authenticate(self, token: str) -> Device | None:
        """Read on every request, so a revocation applies to the next one (S11)."""

        now = self.clock()
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM device WHERE token_sha256 = ? AND revoked_at IS NULL",
                (_hash(token),),
            ).fetchone()
            if row is None:
                return None
            if row["seen_at"] is None or now - _instant(row["seen_at"]) > _SEEN_RESOLUTION:
                db.execute(
                    "UPDATE device SET seen_at = ? WHERE device_id = ?",
                    (stamp(now), row["device_id"]),
                )
        return Device(row["device_id"], row["label"], tuple(json.loads(row["scopes"])))

    def revoke_device(self, device_id: str) -> bool:
        with self._write() as db:
            if (
                db.execute("SELECT 1 FROM device WHERE device_id = ?", (device_id,)).fetchone()
                is None
            ):
                return False
            db.execute(
                "UPDATE device SET revoked_at = COALESCE(revoked_at, ?) WHERE device_id = ?",
                (stamp(self.clock()), device_id),
            )
        return True

    def devices(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT device_id, label, scopes, enrolled_at, seen_at, revoked_at FROM device"
                " ORDER BY enrolled_at"
            ).fetchall()
        return [{**dict(row), "scopes": json.loads(row["scopes"])} for row in rows]

    def status(self) -> dict[str, int]:
        with self.connection() as db:
            counts = {
                "items": "SELECT count(*) FROM item WHERE purged_at IS NULL",
                "pending_records": "SELECT count(*) FROM outbox WHERE status = 'pending'",
                "devices": "SELECT count(*) FROM device WHERE revoked_at IS NULL",
            }
            result = {name: db.execute(query).fetchone()[0] for name, query in counts.items()}
        result["media_bytes"] = sum(
            path.stat().st_size for path in self.media.blobs.glob("*/*") if path.is_file()
        )
        return result

    # --- retention (D4) -----------------------------------------------------------------------------------------

    def retention(self) -> dict[str, int]:
        """Drop cached media for items whose latest decision the PC answered long enough ago."""

        now = self.clock()
        with self._write() as db:
            rows = db.execute(
                "SELECT item.library_id, item.sha256, outbox.record, outbox.status, outbox.answered_at"
                " FROM item JOIN outbox ON outbox.record_id = item.latest_record_id"
                " WHERE item.purged_at IS NULL AND NOT EXISTS ("
                "   SELECT 1 FROM outbox AS other WHERE other.library_id = item.library_id"
                "   AND other.sha256 = item.sha256 AND other.status = 'pending')"
            ).fetchall()
            expired = []
            for row in rows:
                discarded = (
                    row["status"] != "refused"
                    and json.loads(row["record"])["decision"]["verdict"] == "delete"
                )
                window = DISCARD_UNDO if discarded else KEEP_AFTER_ANSWER
                if now - _instant(row["answered_at"]) >= window:
                    expired.append((row["library_id"], row["sha256"]))
            db.executemany(
                "UPDATE item SET purged_at = ? WHERE library_id = ? AND sha256 = ?",
                [(stamp(now), *key) for key in expired],
            )
            referenced = {
                row["digest"]
                for row in db.execute(
                    "SELECT digest FROM item_media JOIN item USING (library_id, sha256)"
                    " WHERE item.purged_at IS NULL"
                )
            }
            released = {
                row["digest"]
                for key in expired
                for row in db.execute(
                    "SELECT digest FROM item_media WHERE library_id = ? AND sha256 = ?", key
                )
            } - referenced
            # Under the write lock, so no publish can count on a file while it is being removed. If this stops
            # before the commit, the same items are simply purged again next time.
            removed = self.media.delete(released)
            removed += self.media.sweep(referenced, STALE_FILE_S, now.timestamp())
        return {"items_purged": len(expired), "files_removed": removed}


def _state(status: str) -> str:
    return "applied" if status == "duplicate" else status


def _outcome(row: sqlite3.Row) -> tuple[str, dict[str, Any] | None, str | None]:
    """``(state, decision, refusal reason)`` of an item joined with its latest record."""

    if row["record"] is None:
        return "undecided", None, None
    decision = json.loads(row["record"])["decision"]
    answer = json.loads(row["acknowledgement"]) if row["acknowledgement"] else {}
    reason = answer.get("reason_code") if row["status"] == "refused" else None
    return _state(row["status"]), {"tags": [], **decision}, reason
