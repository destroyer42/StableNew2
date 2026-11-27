"""Local state of the review gateway sync worker (RG-120): its protected settings and its durable ledger.

* ``GatewaySettingsStore`` keeps the gateway address, the pinned TLS certificate fingerprint and the per-installation
  sync secret encrypted for the current Windows user (DPAPI, the same mechanism as the Operator Site phone grant).
* ``SyncLedger`` is a small SQLite file: what was published (library id, file version, SHA-256, relative path kept
  only on this PC), the outcome of every outbox record (so a retry is answered from the ledger, never applied twice),
  pairing offers, enrolled and revoked devices, the items a phone Discard archived, Immich receipts and counters.

Nothing here is an authority over jobs or review: review judgments live in the Learning evidence file, files live in
the Output folder. The ledger can be deleted; the worker then re-publishes and re-checks everything.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from src.app.review_gateway_protocol import ActionInput
from src.app.site_phone_credentials import protect_for_current_user, unprotect_for_current_user
from src.utils.atomic_io import atomic_write_bytes

FINGERPRINT = re.compile(r"[0-9a-f]{64}")
SYNC_SECRET = re.compile(r"[A-Za-z0-9_-]{32,128}")
_HOST_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
DEFAULT_PORT = 9443
_SETTINGS_LIMIT = 16384


def _local_state_dir() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local.is_absolute():
        raise OSError("Windows local application data is unavailable")
    return local / "StableNew" / "review-gateway"


def parse_address(text: str) -> tuple[str, int]:
    """``host`` or ``host:port`` (an IPv6 literal in brackets), optionally written as the ``https://host:port`` sync
    URL the gateway installer prints (one trailing ``/`` allowed). No other scheme, no path, user or query."""

    value = text.strip()
    if value[:8].lower() == "https://":
        value = value[8:]
        if value.endswith("/"):
            value = value[:-1]
    if not value or len(value) > 255 or any(char in value for char in "/\\@?#% \t"):
        raise ValueError("Enter the gateway address as host:port or https://host:port.")
    port = DEFAULT_PORT
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest:
            if not rest.startswith(":"):
                raise ValueError("Enter the gateway address as host:port or https://host:port.")
            port = _port(rest[1:])
        ipaddress.IPv6Address(host)
        return host, port
    if value.count(":") == 1:
        value, port_text = value.split(":")
        port = _port(port_text)
    try:
        ipaddress.ip_address(value)
        return value, port
    except ValueError:
        pass
    labels = value.rstrip(".").split(".")
    if not all(_HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Enter the gateway address as host:port or https://host:port.")
    return value.rstrip(".").lower(), port


def _port(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ValueError("The gateway port must be a number from 1 to 65535.")
    return int(text)


def normalize_fingerprint(text: str) -> str:
    value = text.strip().replace(":", "").replace(" ", "").lower()
    if not FINGERPRINT.fullmatch(value):
        raise ValueError("The certificate fingerprint must be 64 hexadecimal characters (SHA-256).")
    return value


@dataclass(frozen=True, repr=False)
class GatewaySettings:
    host: str
    port: int
    fingerprint: str
    secret: str

    def __repr__(self) -> str:  # never print the secret
        return f"GatewaySettings(host={self.host!r}, port={self.port})"

    @property
    def address(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @classmethod
    def build(cls, address: str, fingerprint: str, secret: str) -> GatewaySettings:
        host, port = parse_address(address)
        if not SYNC_SECRET.fullmatch(secret.strip()):
            raise ValueError("The sync secret must be 32 to 128 letters, digits, '-' or '_'.")
        return cls(host, port, normalize_fingerprint(fingerprint), secret.strip())


class GatewaySettingsStore:
    """DPAPI-protected settings file; ``protect``/``unprotect`` are injectable for hermetic tests."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        protect: Callable[[bytes], bytes] = protect_for_current_user,
        unprotect: Callable[[bytes], bytes] = unprotect_for_current_user,
    ) -> None:
        self._path = path
        self._protect = protect
        self._unprotect = unprotect

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else _local_state_dir() / "settings.dpapi"

    def load(self) -> GatewaySettings | None:
        try:
            with self.path.open("rb") as source:
                encrypted = source.read(_SETTINGS_LIMIT + 1)
        except FileNotFoundError:
            return None
        if len(encrypted) > _SETTINGS_LIMIT:
            raise ValueError("Invalid review gateway settings")
        try:
            value = json.loads(self._unprotect(encrypted))
            if not isinstance(value, dict) or set(value) != {
                "host",
                "port",
                "fingerprint",
                "secret",
            }:
                raise ValueError("Invalid review gateway settings")
            address = f"[{value['host']}]" if ":" in str(value["host"]) else str(value["host"])
            return GatewaySettings.build(
                f"{address}:{int(value['port'])}", str(value["fingerprint"]), str(value["secret"])
            )
        except (TypeError, KeyError, ValueError) as error:
            raise ValueError("Invalid review gateway settings") from error

    def save(self, settings: GatewaySettings) -> None:
        payload = json.dumps(
            {
                "host": settings.host,
                "port": settings.port,
                "fingerprint": settings.fingerprint,
                "secret": settings.secret,
            },
            ensure_ascii=True,
        ).encode()
        atomic_write_bytes(self.path, self._protect(payload))

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS published (
    library_id TEXT PRIMARY KEY, version TEXT NOT NULL, rel_path TEXT NOT NULL, sha256 TEXT NOT NULL,
    kind TEXT NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS published_digest ON published (sha256);
-- PHONE-FAST: images whose phone rendition has been sent (a table, so an older app's inserts still work).
CREATE TABLE IF NOT EXISTS renditions (library_id TEXT PRIMARY KEY);
-- PHONE-FAST: which admitted job reworks which item, and which published result came from which original.
CREATE TABLE IF NOT EXISTS rework_jobs (job_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rework_result (
    library_id TEXT PRIMARY KEY, original_id TEXT NOT NULL, original_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY, idempotency_key TEXT, outcome TEXT NOT NULL, reason TEXT NOT NULL,
    receipt TEXT NOT NULL, ack_sent INTEGER NOT NULL, at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS records_key ON records (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY, scopes TEXT NOT NULL, label TEXT NOT NULL, expires_at TEXT NOT NULL,
    payload TEXT NOT NULL, sent INTEGER NOT NULL, device_id TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY, offer_id TEXT NOT NULL, scopes TEXT NOT NULL, label TEXT NOT NULL,
    enrolled_at TEXT NOT NULL, revoked_at TEXT, revocation_sent INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS discards (
    library_id TEXT NOT NULL, sha256 TEXT NOT NULL, rel_path TEXT NOT NULL, record_id TEXT NOT NULL,
    PRIMARY KEY (library_id, sha256)
);
CREATE TABLE IF NOT EXISTS immich (
    record_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL,
    asset_id TEXT NOT NULL, album TEXT NOT NULL, favorite INTEGER, error_code TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_prepares (
    record_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, library_id TEXT NOT NULL, sha256 TEXT NOT NULL,
    action TEXT NOT NULL, seeds INTEGER, revision TEXT NOT NULL, at TEXT NOT NULL,
    admitted_by TEXT, receipt TEXT, options TEXT
);
"""


def _add_prepare_options(db: sqlite3.Connection) -> None:
    """RG-140 slice 2: a prepare remembers its choice and text; a ledger from slice 1 gains the column."""

    columns = {row[1] for row in db.execute("PRAGMA table_info(action_prepares)")}
    if "options" not in columns:
        db.execute("ALTER TABLE action_prepares ADD COLUMN options TEXT")


@dataclass(frozen=True)
class Device:
    device_id: str
    offer_id: str
    scopes: tuple[str, ...]
    label: str
    enrolled_at: str
    revoked_at: str | None
    revocation_sent: bool

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass(frozen=True)
class RecordOutcome:
    record_id: str
    outcome: str
    reason: str
    receipt: dict[str, Any]
    ack_sent: bool


_QUEUE_DEFAULT_KEY = "rg140_queue_default"


def _grant_queue_once(db: sqlite3.Connection) -> None:
    """Owner decision 2026-11-26 (RG-140 Q4): queueing is on by default, phones paired before RG-140 included.

    Runs once per ledger; afterwards a phone's queueing is whatever the desktop last set (``set_device_queue``).
    """

    if db.execute("SELECT 1 FROM meta WHERE key = ?", (_QUEUE_DEFAULT_KEY,)).fetchone():
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        for row in db.execute("SELECT device_id, scopes FROM devices").fetchall():
            scopes = json.loads(row[1])
            if "review" in scopes and "queue" not in scopes:
                db.execute(
                    "UPDATE devices SET scopes = ? WHERE device_id = ?",
                    (json.dumps([*scopes, "queue"]), row[0]),
                )
        db.execute("INSERT INTO meta VALUES (?, ?)", (_QUEUE_DEFAULT_KEY, "1"))
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")


class SyncLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else _local_state_dir() / "ledger.sqlite3"
        self._lock = RLock()
        self._db: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(
                self.path, timeout=5, check_same_thread=False, isolation_level=None
            )
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript(_LEDGER_SCHEMA)
            _add_prepare_options(db)
            _grant_queue_once(db)
            self._db = db
        return self._db

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = self._connection()
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _read(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._connection().execute(sql, params))

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # -- meta ------------------------------------------------------------------------------------------------------

    def get_meta(self, key: str, default: str = "") -> str:
        rows = self._read("SELECT value FROM meta WHERE key = ?", (key,))
        return str(rows[0]["value"]) if rows else default

    def set_meta(self, values: Mapping[str, str]) -> None:
        with self._transaction() as db:
            db.executemany(
                "INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                list(values.items()),
            )

    # -- publish ---------------------------------------------------------------------------------------------------

    def published(self, library_id: str) -> sqlite3.Row | None:
        rows = self._read("SELECT * FROM published WHERE library_id = ?", (library_id,))
        return rows[0] if rows else None

    def mark_published(
        self,
        library_id: str,
        version: str,
        rel_path: str,
        sha256: str,
        kind: str,
        state: str,
        at: str,
    ) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO published VALUES (?,?,?,?,?,?,?) ON CONFLICT(library_id) DO UPDATE SET"
                " version=excluded.version, rel_path=excluded.rel_path, sha256=excluded.sha256,"
                " kind=excluded.kind, state=excluded.state, at=excluded.at",
                (library_id, version, rel_path, sha256, kind, state, at),
            )

    def published_many(self, library_ids: Sequence[str]) -> dict[str, sqlite3.Row]:
        """The publish rows of up to a page of items, in one read."""

        if not library_ids:
            return {}
        marks = ",".join("?" * len(library_ids))
        rows = self._read(
            f"SELECT * FROM published WHERE library_id IN ({marks})", tuple(library_ids)
        )
        return {str(row["library_id"]): row for row in rows}

    def mark_missing(self, rows: Sequence[tuple[str, str, str, str]], at: str) -> None:
        """``(library_id, version, rel_path, kind)`` of rows whose file is gone, in one transaction."""

        with self._transaction() as db:
            db.executemany(
                "INSERT INTO published (library_id, version, rel_path, sha256, kind, state, at)"
                " VALUES (?, ?, ?, '', ?, 'missing', ?) ON CONFLICT (library_id) DO UPDATE SET"
                " version = excluded.version, state = excluded.state, at = excluded.at"
                " WHERE published.state <> 'published'",
                [(key, version, path, kind, at) for key, version, path, kind in rows],
            )

    def published_after(self, rowid: int, limit: int) -> list[sqlite3.Row]:
        """``(rowid, library_id, rel_path, kind)`` of sent items, oldest ledger row first."""

        return self._read(
            "SELECT rowid, library_id, rel_path, kind FROM published"
            " WHERE rowid > ? AND state = 'published' ORDER BY rowid LIMIT ?",
            (rowid, limit),
        )

    def set_rendition(self, library_id: str) -> None:
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO renditions VALUES (?)", (library_id,))

    def without_rendition(self, limit: int) -> list[str]:
        """Published images not yet sent with a phone rendition, newest first."""

        rows = self._read(
            "SELECT library_id FROM published WHERE state = 'published' AND kind = 'image'"
            " AND library_id NOT IN (SELECT library_id FROM renditions) ORDER BY at DESC LIMIT ?",
            (limit,),
        )
        return [str(row["library_id"]) for row in rows]

    def remember_rework(self, job_ids: Sequence[str], library_id: str, sha256: str) -> None:
        with self._transaction() as db:
            db.executemany(
                "INSERT OR REPLACE INTO rework_jobs VALUES (?, ?, ?)",
                [(job_id, library_id, sha256) for job_id in job_ids],
            )

    def has_rework(self) -> bool:
        return bool(self._read("SELECT 1 FROM rework_jobs LIMIT 1"))

    def rework_original(self, job_id: str) -> tuple[str, str] | None:
        """``(library_id, sha256)`` of the item this job reworks."""

        rows = self._read("SELECT library_id, sha256 FROM rework_jobs WHERE job_id = ?", (job_id,))
        return (str(rows[0]["library_id"]), str(rows[0]["sha256"])) if rows else None

    def remember_result(self, library_id: str, original_id: str, original_sha256: str) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO rework_result VALUES (?, ?, ?)",
                (library_id, original_id, original_sha256),
            )

    def rework_original_of(self, library_id: str) -> tuple[str, str] | None:
        rows = self._read(
            "SELECT original_id, original_sha256 FROM rework_result WHERE library_id = ?",
            (library_id,),
        )
        return (str(rows[0][0]), str(rows[0][1])) if rows else None

    def publish_counts(self) -> dict[str, int]:
        rows = self._read("SELECT state, count(*) AS n FROM published GROUP BY state")
        return {str(row["state"]): int(row["n"]) for row in rows}

    # -- records ---------------------------------------------------------------------------------------------------

    def outcome(self, record_id: str) -> RecordOutcome | None:
        rows = self._read("SELECT * FROM records WHERE record_id = ?", (record_id,))
        return self._outcome(rows[0]) if rows else None

    def outcome_for_key(self, idempotency_key: str) -> RecordOutcome | None:
        rows = self._read("SELECT * FROM records WHERE idempotency_key = ?", (idempotency_key,))
        return self._outcome(rows[0]) if rows else None

    @staticmethod
    def _outcome(row: sqlite3.Row) -> RecordOutcome:
        return RecordOutcome(
            str(row["record_id"]),
            str(row["outcome"]),
            str(row["reason"]),
            json.loads(row["receipt"]),
            bool(row["ack_sent"]),
        )

    def record_outcome(
        self,
        record_id: str,
        idempotency_key: str | None,
        outcome: str,
        reason: str,
        receipt: Mapping[str, Any],
        at: str,
    ) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,0,?)",
                (record_id, idempotency_key, outcome, reason, json.dumps(dict(receipt)), at),
            )

    def unsent_acknowledgements(self, limit: int = 500) -> list[RecordOutcome]:
        rows = self._read("SELECT * FROM records WHERE ack_sent = 0 ORDER BY at LIMIT ?", (limit,))
        return [self._outcome(row) for row in rows]

    def mark_ack_sent(self, record_id: str) -> None:
        with self._transaction() as db:
            db.execute("UPDATE records SET ack_sent = 1 WHERE record_id = ?", (record_id,))

    def refusal_count(self) -> int:
        rows = self._read("SELECT count(*) AS n FROM records WHERE outcome = 'refused'")
        return int(rows[0]["n"])

    def recent_refusals(self, limit: int = 20) -> list[tuple[str, str]]:
        rows = self._read(
            "SELECT at, reason FROM records WHERE outcome = 'refused' ORDER BY at DESC LIMIT ?",
            (limit,),
        )
        return [(str(row["at"]), str(row["reason"])) for row in rows]

    # -- discards (keep after a phone delete restores the archived file) -------------------------------------------

    def remember_discard(self, library_id: str, sha256: str, rel_path: str, record_id: str) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO discards VALUES (?,?,?,?) ON CONFLICT(library_id, sha256) DO UPDATE SET"
                " rel_path=excluded.rel_path, record_id=excluded.record_id",
                (library_id, sha256, rel_path, record_id),
            )

    def discarded_path(self, library_id: str, sha256: str) -> str | None:
        rows = self._read(
            "SELECT rel_path FROM discards WHERE library_id = ? AND sha256 = ?",
            (library_id, sha256),
        )
        return str(rows[0]["rel_path"]) if rows else None

    def forget_discard(self, library_id: str, sha256: str) -> None:
        with self._transaction() as db:
            db.execute(
                "DELETE FROM discards WHERE library_id = ? AND sha256 = ?", (library_id, sha256)
            )

    # -- phone actions (RG-140) ------------------------------------------------------------------------------------

    def remember_prepare(
        self,
        record_id: str,
        device_id: str,
        library_id: str,
        sha256: str,
        action: str,
        seeds: int | None,
        revision: str,
        at: str,
        *,
        options: Mapping[str, str] | None = None,
    ) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO action_prepares (record_id, device_id, library_id, sha256,"
                " action, seeds, revision, at, options) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    device_id,
                    library_id,
                    sha256,
                    action,
                    seeds,
                    revision,
                    at,
                    json.dumps(dict(options)) if options else None,
                ),
            )

    def prepared(self, record_id: str) -> sqlite3.Row | None:
        rows = self._read("SELECT * FROM action_prepares WHERE record_id = ?", (record_id,))
        return rows[0] if rows else None

    @staticmethod
    def prepare_options(row: sqlite3.Row) -> ActionInput:
        """The choice and text a prepare was made with (none for slice-1 prepares)."""

        stored = json.loads(row["options"]) if row["options"] else {}
        return ActionInput(str(stored.get("choice") or ""), str(stored.get("text") or ""))

    def mark_prepare_admitted(
        self, record_id: str, confirm_id: str, receipt: Mapping[str, Any]
    ) -> None:
        """One admission per prepare (S8): a later confirm of the same prepare gets this receipt."""

        with self._transaction() as db:
            db.execute(
                "UPDATE action_prepares SET admitted_by = ?, receipt = ?"
                " WHERE record_id = ? AND admitted_by IS NULL",
                (confirm_id, json.dumps(dict(receipt)), record_id),
            )

    # -- pairing and devices ---------------------------------------------------------------------------------------

    def add_offer(
        self, offer_id: str, scopes: tuple[str, ...], label: str, expires_at: str, payload: str
    ) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO offers VALUES (?,?,?,?,?,0,NULL)",
                (offer_id, json.dumps(list(scopes)), label, expires_at, payload),
            )

    def unsent_offers(self) -> list[tuple[str, str, str]]:
        """``(offer_id, payload, expires_at)`` of offers not yet delivered to the gateway."""

        rows = self._read("SELECT offer_id, payload, expires_at FROM offers WHERE sent = 0")
        return [(str(row["offer_id"]), str(row["payload"]), str(row["expires_at"])) for row in rows]

    def mark_offer_sent(self, offer_id: str, *, dead: bool = False) -> None:
        """Delivered (or, ``dead``, refused or expired: no device can ever be bound to it)."""

        with self._transaction() as db:
            db.execute(
                "UPDATE offers SET sent = 1, payload = '',"
                " device_id = CASE WHEN ? THEN '' ELSE device_id END WHERE offer_id = ?",
                (int(dead), offer_id),
            )

    def bind_device(self, device_id: str, offer_id: str, label: str, enrolled_at: str) -> bool:
        """Record an enrollment the gateway reported; only for an offer this PC issued and has not bound yet."""

        with self._transaction() as db:
            existing = db.execute(
                "SELECT offer_id FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if existing is not None:
                return bool(existing["offer_id"] == offer_id)
            offer = db.execute(
                "SELECT scopes, label, device_id FROM offers WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            if offer is None or offer["device_id"] is not None:
                return False
            db.execute("UPDATE offers SET device_id = ? WHERE offer_id = ?", (device_id, offer_id))
            db.execute(
                "INSERT INTO devices VALUES (?,?,?,?,?,NULL,0)",
                (device_id, offer_id, offer["scopes"], label or str(offer["label"]), enrolled_at),
            )
            return True

    def device(self, device_id: str) -> Device | None:
        rows = self._read("SELECT * FROM devices WHERE device_id = ?", (device_id,))
        return self._device(rows[0]) if rows else None

    def devices(self) -> list[Device]:
        return [
            self._device(row) for row in self._read("SELECT * FROM devices ORDER BY enrolled_at")
        ]

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            str(row["device_id"]),
            str(row["offer_id"]),
            tuple(json.loads(row["scopes"])),
            str(row["label"]),
            str(row["enrolled_at"]),
            None if row["revoked_at"] is None else str(row["revoked_at"]),
            bool(row["revocation_sent"]),
        )

    def set_device_queue(self, device_id: str, allowed: bool) -> bool:
        """Grant or withdraw one phone's queueing (D6 as amended 2026-11-26); its review scope is untouched."""

        with self._transaction() as db:
            row = db.execute(
                "SELECT scopes FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row is None:
                return False
            scopes = [scope for scope in json.loads(row["scopes"]) if scope != "queue"]
            if allowed:
                scopes.append("queue")
            db.execute(
                "UPDATE devices SET scopes = ? WHERE device_id = ?", (json.dumps(scopes), device_id)
            )
            return True

    def revoke_device(self, device_id: str, at: str) -> bool:
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE devices SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (at, device_id),
            )
            return cursor.rowcount == 1

    def retain_active_devices(self, active: set[str], at: str) -> int:
        """The gateway lists every active device: one it no longer lists was revoked there (S11)."""

        with self._transaction() as db:
            known = [
                str(row["device_id"])
                for row in db.execute("SELECT device_id FROM devices WHERE revoked_at IS NULL")
            ]
            gone = [device_id for device_id in known if device_id not in active]
            db.executemany(
                "UPDATE devices SET revoked_at = ?, revocation_sent = 1 WHERE device_id = ?",
                [(at, device_id) for device_id in gone],
            )
            return len(gone)

    def unsent_revocations(self) -> list[tuple[str, str]]:
        rows = self._read(
            "SELECT device_id, revoked_at FROM devices WHERE revoked_at IS NOT NULL AND revocation_sent = 0"
        )
        return [(str(row["device_id"]), str(row["revoked_at"])) for row in rows]

    def mark_revocation_sent(self, device_id: str) -> None:
        with self._transaction() as db:
            db.execute("UPDATE devices SET revocation_sent = 1 WHERE device_id = ?", (device_id,))

    # -- Immich receipts -------------------------------------------------------------------------------------------

    def store_immich_receipt(
        self,
        record_id: str,
        library_id: str,
        sha256: str,
        status: str,
        asset_id: str,
        album: str,
        favorite: bool | None,
        error_code: str,
        at: str,
    ) -> None:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO immich VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET"
                " status=excluded.status, asset_id=excluded.asset_id, album=excluded.album,"
                " favorite=excluded.favorite, error_code=excluded.error_code, at=excluded.at",
                (
                    record_id,
                    library_id,
                    sha256,
                    status,
                    asset_id,
                    album,
                    None if favorite is None else int(favorite),
                    error_code,
                    at,
                ),
            )

    def immich_receipt(self, record_id: str) -> sqlite3.Row | None:
        rows = self._read("SELECT * FROM immich WHERE record_id = ?", (record_id,))
        return rows[0] if rows else None
