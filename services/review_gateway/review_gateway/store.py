"""Gateway state in SQLite: items, the outbox, pairing offers, devices, owed Immich uploads and the PC's status.

Everything here is a projection or a request (RG-100 invariants 2 and 4). It is WAL with ``synchronous=FULL`` (S9),
and retention only ever removes cached media for items whose latest decision the PC has answered, and never a kept
item's before Immich has it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import deferred, upload_queue
from .contract import SCHEMA_VERSION, Contract, ContractError
from .errors import GatewayError
from .media import MediaStore, MediaWriter

Clock = Callable[[], datetime]
_LOG = logging.getLogger("review_gateway")

OFFER_LIFETIME = timedelta(minutes=5)
DEFAULT_ATTEMPTS = 5
MAXIMUM_DEVICES = 50
DISCARD_UNDO = timedelta(hours=48)
KEEP_AFTER_ANSWER = timedelta(days=14)
STALE_FILE_S = 24 * 3600
_SEEN_RESOLUTION = timedelta(hours=1)
#: The phone inbox's group key for a named batch (N5); every other group is an output run folder name.
BATCH_GROUP = "batch:"
#: PHONE-FAST: not a group but every item still to be reviewed, across all groups (no run folder name looks like it).
#: ``all:<source>`` is the same within one review section.
STREAM = "all"
#: PHONE-FAST review sections, in the order the phone lists them. An item without one counts as "other".
SOURCES = ("pipeline", "learning", "reprocess", "video", "testing", "other")
_SOURCE = "COALESCE(item.source, 'other')"
#: RG-140 slices 1 and 2. The schema reserves the others (N8's clip actions); the PC refuses anything it does not
#: implement, so an older PC answers a slice-2 request with ``invalid_record``.
PHONE_ACTIONS = frozenset(
    {
        "fix_face",
        "fix_hands",
        "fix_both",
        "more_like_this",
        "another_model",
        "aspect_ratio",
        "prompt_tweak",
        "make_video",
        "continue_clip",
    }
)
#: RG-140: not a quota (the owner set none, 2026-11-26). A technical bound on one phone's *unanswered* action requests,
#: far above a person's use (a whole 300-item batch fixed while the PC sleeps fits). It protects the outbox and the PC's
#: next sync from a phone stuck resending in a loop with fresh keys; answered requests never count.
MAX_PENDING_ACTIONS = 1000
#: RG-140 slice 1. The schema reserves the others for later slices; the PC refuses anything it does not implement.
SLICE_ONE_ACTIONS = frozenset({"fix_face", "fix_hands", "fix_both", "more_like_this"})
#: PHONE-FAST: actions that make one replacement of an image (the PC's ``REWORK_ACTIONS``). Once one is queued the
#: original counts as reviewed until the owner compares the two.
REWORK_ACTIONS = ("fix_face", "fix_hands", "fix_both", "another_model", "aspect_ratio")
_VARIANT_NAMES = {"thumb_320": "thumb", "preview_1080": "preview", "mobile_video": "video"}
#: LAUNCH-UPDATE-2: how many of its own update requests an admin phone is shown.
ADMIN_HISTORY = 5

_TABLES = """
CREATE TABLE IF NOT EXISTS item (
    library_id TEXT NOT NULL, sha256 TEXT NOT NULL,
    run_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, duration_s REAL,
    display TEXT NOT NULL, ready_at TEXT, purged_at TEXT, latest_record_id TEXT,
    batch_id TEXT, batch TEXT, parent_library_id TEXT, parent_sha256 TEXT,
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
    kind TEXT NOT NULL DEFAULT 'decision', created_at TEXT,
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
CREATE TABLE IF NOT EXISTS pc_status (
    id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, received_at TEXT NOT NULL
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
        self,
        database: Path,
        media: MediaStore,
        contract: Contract,
        clock: Clock = utc_now,
        *,
        undecided_days: int = 30,
        cache_warn_bytes: int = 20 * 1024**3,
    ) -> None:
        self.undecided_days = undecided_days
        self.cache_warn_bytes = cache_warn_bytes
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.media = media
        self.contract = contract
        self.clock = clock
        with self.connection() as db:
            db.executescript(_TABLES)
            _migrate(db)
            deferred.initialize(db)
            upload_queue.initialize(db)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.database, timeout=10, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            # Per connection, not stored in the file: a decision is on disk before the phone is told so.
            db.execute("PRAGMA synchronous=FULL")
            yield db

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
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
        batch = manifest.get("batch")
        parent = manifest.get("parent") or {}
        made_from = manifest.get("input") or {}
        with self.write() as db:
            row = db.execute(
                "SELECT purged_at, parent_library_id, parent_sha256 FROM item"
                " WHERE library_id = ? AND sha256 = ?",
                key,
            ).fetchone()
            if row is not None and row["purged_at"] is not None:
                return "purged", []
            run_id = manifest["run_id"]
            batch_id = batch["batch_id"].lower() if batch else None
            batch_text = json.dumps(batch) if batch else None
            source = manifest.get("source")
            # A rework result sits beside its original: it joins the original's batch, or its run folder group, and
            # its review section.
            origin = db.execute(
                "SELECT run_id, batch_id, batch, source FROM item WHERE library_id = ? AND sha256 = ?",
                (
                    parent.get("library_id") or (row["parent_library_id"] if row else None),
                    parent.get("sha256") or (row["parent_sha256"] if row else None),
                ),
            ).fetchone()
            if origin is not None:
                run_id, batch_id, batch_text = origin["run_id"], origin["batch_id"], origin["batch"]
                source = origin["source"] or source
            db.execute(
                "INSERT INTO item (library_id, sha256, run_id, kind, created_at, duration_s, display,"
                " batch_id, batch, parent_library_id, parent_sha256, source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (library_id, sha256) DO UPDATE SET"
                " run_id = excluded.run_id, kind = excluded.kind, created_at = excluded.created_at,"
                " duration_s = excluded.duration_s, display = excluded.display,"
                " batch_id = excluded.batch_id, batch = excluded.batch,"
                " parent_library_id = COALESCE(excluded.parent_library_id, parent_library_id),"
                " parent_sha256 = COALESCE(excluded.parent_sha256, parent_sha256),"
                " source = COALESCE(excluded.source, source)",
                (
                    *key,
                    run_id,
                    manifest["kind"],
                    stamp(_instant(manifest["created_at"])),
                    manifest.get("duration_s"),
                    json.dumps(display),
                    batch_id,
                    batch_text,
                    parent.get("library_id"),
                    parent.get("sha256"),
                    source,
                ),
            )
            if made_from or manifest.get("input_missing"):
                db.execute(
                    "UPDATE item SET input_library_id = ?, input_sha256 = ?, input_missing = ?"
                    " WHERE library_id = ? AND sha256 = ?",
                    (
                        made_from.get("library_id"),
                        made_from.get("sha256"),
                        0 if made_from else 1,
                        *key,
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

        with self.write() as db:
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

    def withdraw(self, library_ids: list[str]) -> int:
        """Stop showing items that should never have been published (PHONE-FAST). Returns how many.

        Not a decision: nothing is recorded in the outbox or sent to Immich, and an item with a decision or a request
        the PC has not refused stays as it is. A withdrawn item is purged, so publishing it again does nothing.
        """

        now = stamp(self.clock())
        marks = ",".join("?" * len(library_ids))
        with self.write() as db:
            keys = [
                (row["library_id"], row["sha256"])
                for row in db.execute(
                    f"SELECT library_id, sha256 FROM item WHERE library_id IN ({marks})"
                    " AND purged_at IS NULL AND NOT EXISTS ("
                    "   SELECT 1 FROM outbox WHERE outbox.library_id = item.library_id"
                    "   AND outbox.sha256 = item.sha256"
                    "   AND outbox.status NOT IN ('refused', 'superseded'))",
                    library_ids,
                )
            ]
            db.executemany(
                "UPDATE item SET purged_at = ? WHERE library_id = ? AND sha256 = ?",
                [(now, *key) for key in keys],
            )
            self._release(db, keys)
        return len(keys)

    def _release(self, db: sqlite3.Connection, purged: list[tuple[str, str]]) -> int:
        """Remove the cached files only the just purged items used, and stale unreferenced ones. Call under the
        write lock, so no publish can count on a file while it is being removed."""

        referenced = {
            row["digest"]
            for row in db.execute(
                "SELECT digest FROM item_media JOIN item USING (library_id, sha256)"
                " WHERE item.purged_at IS NULL"
            )
        }
        released = {
            row["digest"]
            for key in purged
            for row in db.execute(
                "SELECT digest FROM item_media WHERE library_id = ? AND sha256 = ?", key
            )
        } - referenced
        removed = self.media.delete(released)
        return removed + self.media.sweep(referenced, STALE_FILE_S, self.clock().timestamp())

    # --- the phone's view ---------------------------------------------------------------------------------------

    def label_sources(self, items: list[tuple[str, str]]) -> int:
        """Name the review sections of items published without one (PHONE-FAST). Returns how many it named."""

        with self.write() as db:
            named = db.executemany(
                "UPDATE item SET source = ? WHERE library_id = ? AND source IS NULL",
                [(source, library_id) for library_id, source in items],
            ).rowcount
            # A rework result belongs to its original's section, whatever folder the PC wrote it to.
            db.execute(
                "UPDATE item SET source = COALESCE((SELECT original.source FROM item AS original"
                " WHERE original.library_id = item.parent_library_id"
                " AND original.sha256 = item.parent_sha256), source)"
                " WHERE parent_library_id IS NOT NULL"
            )
        return named

    def sections(self, seen: dict[str, str]) -> dict[str, Any]:
        """Each review section that holds anything: how many items are left to review, and how many arrived since
        the phone last opened it (``seen``, by section; a section never opened counts what is left to review)."""

        with self.connection() as db:
            rows = db.execute(_ITEMS_WITH_STATE).fetchall()
            reworked = _reworked(db)
        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            source = row["source"] or "other"
            count = counts.setdefault(source, {"total": 0, "unreviewed": 0, "new": 0})
            state, _decision, _reason = _item_state(row, reworked)
            todo = state in ("undecided", "refused")
            count["total"] += 1
            count["unreviewed"] += todo
            since = seen.get(source)
            count["new"] += row["ready_at"] > since if since else todo
        return {
            "now": stamp(self.clock()),
            "sections": [{"id": name, **counts[name]} for name in SOURCES if name in counts],
        }

    def runs(self, source: str | None = None) -> list[dict[str, Any]]:
        """The inbox: one group per named batch (N5), and per output run folder for everything else.

        A group's ``run_id`` is what the phone opens: the run folder, or ``batch:<batch_id>``. Groups come newest
        activity first (their latest item), then by that key. ``source`` limits it to one review section.
        """

        where, values = (f" AND {_SOURCE} = ?", (source,)) if source else ("", ())
        with self.connection() as db:
            rows = db.execute(
                _ITEMS_WITH_STATE
                + where
                + " ORDER BY item.run_id DESC, item.created_at, item.library_id",
                values,
            ).fetchall()
            reworked = _reworked(db)
        runs: dict[str, dict[str, Any]] = {}
        latest: dict[str, str] = {}
        for row in rows:
            batch = json.loads(row["batch"]) if row["batch_id"] else None
            group = f"{BATCH_GROUP}{row['batch_id']}" if batch else row["run_id"]
            run = runs.setdefault(
                group,
                {
                    "run_id": group,
                    "kind": "batch" if batch else "run",
                    "name": batch["name"] if batch else None,
                    **dict.fromkeys(("total", "undecided", "keep", "delete", "favorite"), 0),
                    **dict.fromkeys(("pending", "applied", "refused", "rework"), 0),
                    "covers": [],
                },
            )
            latest[group] = max(latest.get(group, ""), row["created_at"])
            state, decision, _reason = _item_state(row, reworked)
            run["total"] += 1
            run[state] += 1
            if decision is not None and state != "refused":
                run[decision["verdict"]] += 1
                run["favorite"] += decision["favorite"]
            if len(run["covers"]) < 4:
                run["covers"].append({"library_id": row["library_id"], "sha256": row["sha256"]})
        return sorted(
            runs.values(), key=lambda run: (latest[run["run_id"]], run["run_id"]), reverse=True
        )

    def group_name(self, run_id: str) -> str | None:
        """The batch name of a ``batch:<id>`` group (``None`` for a run folder or an unknown batch)."""

        batch_id = run_id.removeprefix(BATCH_GROUP)
        if batch_id == run_id:
            return None
        with self.connection() as db:
            row = db.execute(
                "SELECT batch FROM item WHERE batch_id = ? AND ready_at IS NOT NULL"
                " AND purged_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (batch_id.lower(),),
            ).fetchone()
        return json.loads(row["batch"])["name"] if row is not None else None

    def run_items(self, run_id: str) -> list[dict[str, Any]]:
        batch_id = run_id.removeprefix(BATCH_GROUP)
        stream, _, source = run_id.partition(":")
        if run_id == STREAM:
            where, value = "? = ''", ""
        elif stream == STREAM:
            where, value = f"{_SOURCE} = ?", source
        elif batch_id != run_id:
            where, value = "item.batch_id = ?", batch_id.lower()
        else:
            where, value = "item.run_id = ? AND item.batch_id IS NULL", run_id
        with self.connection() as db:
            rows = db.execute(
                _ITEMS_WITH_STATE + f" AND {where} ORDER BY item.created_at, item.library_id",
                (value,),
            ).fetchall()
            variants = db.execute(
                "SELECT item_media.library_id, item_media.sha256, variant, digest FROM item_media"
                f" JOIN item USING (library_id, sha256) WHERE {where}",
                (value,),
            ).fetchall()
            reworked = _reworked(db)
            waiting = deferred.waiting_actions(db)
            originals = {
                (row["library_id"], row["sha256"]): self._original(
                    db, row["parent_library_id"], row["parent_sha256"], reworked, waiting
                )
                for row in rows
                if row["parent_library_id"]
            }
            for row in rows:
                if row["input_library_id"] and not row["parent_library_id"]:
                    originals[(row["library_id"], row["sha256"])] = self._input_of(
                        db, row, reworked, waiting
                    )
        available = self._available(variants)
        items = []
        for row in rows:
            state, decision, reason = _item_state(row, reworked)
            # A result still to be judged is shown beside what it was made from, or says that is not here.
            open_result = state in ("undecided", "refused")
            original = originals.get((row["library_id"], row["sha256"])) if open_result else None
            had_input = bool(row["input_library_id"] or row["input_missing"])
            items.append(
                {
                    "library_id": row["library_id"],
                    "sha256": row["sha256"],
                    "kind": row["kind"],
                    "created_at": row["created_at"],
                    "duration_s": row["duration_s"],
                    "display": json.loads(row["display"]),
                    "batch": json.loads(row["batch"]) if row["batch_id"] else None,
                    "variants": sorted(available.get((row["library_id"], row["sha256"]), [])),
                    "state": state,
                    "decision": decision,
                    "reason_code": reason,
                    # RG-160: requests for this image still waiting for the PC.
                    "waiting": waiting.get((row["library_id"], row["sha256"]), []),
                    "compare": original,
                    "original_missing": open_result and had_input and original is None,
                }
            )
        if stream == STREAM:
            return _stream(items, rows)
        return items

    def phone_status(self, device_id: str = "") -> dict[str, Any]:
        """What every review phone shows: whether the PC is there, its queue and how large the cache is."""

        with self.connection() as db:
            status = db.execute(
                "SELECT payload, received_at FROM pc_status WHERE id = 1"
            ).fetchone()
            size = _cached_bytes(db)
            presence = deferred.presence(db)
            waiting = deferred.waiting_count(db, device_id)
        queue = json.loads(status["payload"])["queue"] if status else None
        return {
            "now": stamp(self.clock()),
            "pc_seen_at": presence["pc_seen_at"],
            "image_backend_ready": presence["image_backend_ready"],
            "waiting": waiting,
            "pc": {**queue, "received_at": status["received_at"]} if queue else None,
            "cache": {
                "bytes": size,
                "warn_bytes": self.cache_warn_bytes,
                "over": bool(self.cache_warn_bytes) and size > self.cache_warn_bytes,
            },
        }

    def _available(self, variants: list[sqlite3.Row]) -> dict[tuple[str, str], list[str]]:
        available: dict[tuple[str, str], list[str]] = {}
        for entry in variants:
            if self.media.size(entry["digest"]) is not None:
                key = (entry["library_id"], entry["sha256"])
                name = _VARIANT_NAMES.get(entry["variant"], "original")
                available.setdefault(key, []).append(name)
        return available

    def _original(
        self,
        db: sqlite3.Connection,
        library_id: str,
        sha256: str,
        reworked: set[tuple[str, str]],
        waiting: dict[tuple[str, str], list[str]],
    ) -> dict[str, Any] | None:
        """A result's original while it is still on the gateway and not deleted."""

        key = (library_id, sha256)
        row = db.execute(
            _ITEMS_WITH_STATE + " AND item.library_id = ? AND item.sha256 = ?", key
        ).fetchone()
        if row is None:
            return None
        state, decision, _reason = _item_state(row, reworked)
        if decision is not None and decision["verdict"] == "delete" and state != "refused":
            return None
        variants = db.execute(
            "SELECT library_id, sha256, variant, digest FROM item_media"
            " WHERE library_id = ? AND sha256 = ?",
            key,
        ).fetchall()
        return {
            "library_id": library_id,
            "sha256": sha256,
            "kind": row["kind"],
            "variants": sorted(self._available(variants).get(key, [])),
            "state": state,
            "decision": decision,
            "waiting": waiting.get(
                key, []
            ),  # RG-160: "Keep rework" deletes it, so the phone warns first
        }

    def _input_of(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
        reworked: set[tuple[str, str]],
        waiting: dict[tuple[str, str], list[str]],
    ) -> dict[str, Any] | None:
        """The image a desk job made this one from, as ``_original``. The PC may name it by its file's digest when
        it was sent as other bytes (metadata paths removed), so the library id then finds it."""

        found = db.execute(
            "SELECT sha256 FROM item WHERE library_id = ? AND ready_at IS NOT NULL AND purged_at IS NULL"
            " ORDER BY sha256 = ? DESC, ready_at DESC LIMIT 1",
            (row["input_library_id"], row["input_sha256"]),
        ).fetchone()
        if found is None:
            return None
        original = self._original(db, row["input_library_id"], found["sha256"], reworked, waiting)
        return {**original, "desk": True} if original else None

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
        with self.write() as db:
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
                if sent["target"] != target or sent.get("decision") != decision:
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
                " record, status, kind, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', 'decision', ?)",
                (
                    record["record_id"],
                    idempotency_key,
                    device_id,
                    *key,
                    json.dumps(record),
                    record["created_at"],
                ),
            )
            db.execute(
                "UPDATE item SET latest_record_id = ? WHERE library_id = ? AND sha256 = ?",
                (record["record_id"], *key),
            )
            if decision["verdict"] == "delete":
                deferred.cancel_for_delete(db, key, record["created_at"])
            self._reconcile_upload(db, key)
        return record["record_id"], "pending"

    # --- action requests (RG-140) --------------------------------------------------------------------------------

    def request_action(
        self,
        device_id: str,
        target: dict[str, str],
        action_request: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, str]:
        """Record a phone action request (prepare, confirm or RG-160's queue). Returns ``(record_id, state)``.

        It is only a request: it never becomes the item's decision and never touches Immich. The PC compiles,
        decides and answers it (invariants 2 and 4).
        """

        now = self.clock()
        record = {
            "record_id": str(uuid.uuid4()),
            "idempotency_key": idempotency_key,
            "device_id": device_id,
            "created_at": stamp(now),
            "target": target,
            "kind": "action_request",
            "action_request": action_request,
        }
        try:
            self.contract.validate("outbox_record", record)
        except ContractError as error:
            raise GatewayError(422, "invalid_record") from error
        if action_request["action"] not in PHONE_ACTIONS:
            raise GatewayError(422, "invalid_record")
        key = (target["library_id"], target["sha256"])
        with self.write() as db:
            # Checked inside the write: the body may have arrived after a revocation or a re-pair (S11).
            device = db.execute(
                "SELECT scopes FROM device WHERE device_id = ? AND revoked_at IS NULL", (device_id,)
            ).fetchone()
            if device is None:
                raise GatewayError(401, "not_enrolled")
            if "queue" not in json.loads(device["scopes"]):
                raise GatewayError(403, "not_granted")
            previous = db.execute(
                "SELECT record_id, record, status, cancelled_at FROM outbox"
                " WHERE device_id = ? AND idempotency_key = ?",
                (device_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                sent = json.loads(previous["record"])
                if sent["target"] != target or sent.get("action_request") != action_request:
                    raise GatewayError(409, "idempotency_conflict")
                return previous["record_id"], _action_state(previous)
            item = db.execute(
                "SELECT kind FROM item WHERE library_id = ? AND sha256 = ?"
                " AND ready_at IS NOT NULL AND purged_at IS NULL",
                key,
            ).fetchone()
            if item is None:
                raise GatewayError(404, "unknown_item")
            # V1-6: continuing a clip is the one action on a video, and it takes nothing else.
            if action_request["action"] == "continue_clip":
                if item["kind"] != "video":
                    raise GatewayError(422, "invalid_record")
            elif item["kind"] != "image":
                raise GatewayError(422, "not_an_image")
            pending = db.execute(
                "SELECT count(*) FROM outbox WHERE device_id = ? AND kind = 'action_request'"
                " AND status = 'pending'",
                (device_id,),
            ).fetchone()[0]
            if pending >= MAX_PENDING_ACTIONS:
                raise GatewayError(429, "too_many_pending")
            db.execute(
                "INSERT INTO outbox (record_id, idempotency_key, device_id, library_id, sha256,"
                " record, status, kind, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', 'action_request', ?)",
                (
                    record["record_id"],
                    idempotency_key,
                    device_id,
                    *key,
                    json.dumps(record),
                    record["created_at"],
                ),
            )
        return record["record_id"], "pending"

    def action_record(self, device_id: str, record_id: str) -> dict[str, Any] | None:
        """One of this device's action requests with the PC's answer; ``None`` for anyone else's."""

        with self.connection() as db:
            row = db.execute(
                "SELECT record, status, acknowledgement, delivered_at, cancelled_at FROM outbox"
                " WHERE record_id = ? AND device_id = ? AND kind = 'action_request'",
                (record_id, device_id),
            ).fetchone()
        return _action_view(row) if row is not None else None

    def item_actions(self, device_id: str, target: dict[str, str]) -> list[dict[str, Any]]:
        """This device's recent action requests for one item, newest first."""

        with self.connection() as db:
            rows = db.execute(
                "SELECT record, status, acknowledgement, delivered_at, cancelled_at FROM outbox"
                " WHERE device_id = ? AND library_id = ? AND sha256 = ? AND kind = 'action_request'"
                " ORDER BY seq DESC LIMIT 20",
                (device_id, target["library_id"], target["sha256"]),
            ).fetchall()
        return [_action_view(row) for row in rows]

    # --- requests that wait for the PC (RG-160) ----------------------------------------------------------------

    def cancel_action(self, device_id: str, record_id: str) -> str | None:
        """Cancel one of this device's requests (``deferred.cancel``); ``None`` for anyone else's."""

        with self.write() as db:
            return deferred.cancel(db, device_id, record_id, stamp(self.clock()))

    def deferred_requests(self, device_id: str) -> dict[str, Any]:
        """This device's waiting list, with whether the PC is there."""

        now = stamp(self.clock())
        with self.connection() as db:
            rows = deferred.listed(db, device_id, now)
            presence = deferred.presence(db)
        return {"now": now, **presence, "requests": [_action_view(row) for row in rows]}

    def set_choice_catalog(self, catalog: dict[str, Any]) -> None:
        with self.write() as db:
            deferred.set_catalog(db, catalog, stamp(self.clock()))

    def choice_catalog(self) -> dict[str, Any]:
        with self.connection() as db:
            catalog, received_at = deferred.catalog(db)
        return {"catalog": catalog, "received_at": received_at, "now": stamp(self.clock())}

    # --- remote update (LAUNCH-UPDATE-2) -----------------------------------------------------------------------

    def set_pc_status(self, status: dict[str, Any]) -> None:
        """Keep the latest validated ``pc_status``; it is only ever shown to admin phones."""

        with self.write() as db:
            db.execute(
                "INSERT INTO pc_status VALUES (1, ?, ?) ON CONFLICT (id) DO UPDATE SET"
                " payload = excluded.payload, received_at = excluded.received_at",
                (json.dumps(status), stamp(self.clock())),
            )

    def admin_view(self, device_id: str) -> dict[str, Any]:
        """What an admin phone shows: the PC's last status and this phone's recent update requests."""

        with self.connection() as db:
            status = db.execute(
                "SELECT payload, received_at FROM pc_status WHERE id = 1"
            ).fetchone()
            rows = db.execute(
                "SELECT record, status, acknowledgement FROM outbox WHERE device_id = ?"
                " AND kind = 'admin_request' ORDER BY seq DESC LIMIT ?",
                (device_id, ADMIN_HISTORY),
            ).fetchall()
        return {
            "pc_status": json.loads(status["payload"]) if status else None,
            "received_at": status["received_at"] if status else None,
            "now": stamp(self.clock()),
            "requests": [_admin_view(row) for row in rows],
        }

    def admin_record(self, device_id: str, record_id: str) -> dict[str, Any] | None:
        """One of this device's update requests with the PC's answer; ``None`` for anyone else's."""

        with self.connection() as db:
            row = db.execute(
                "SELECT record, status, acknowledgement FROM outbox WHERE record_id = ?"
                " AND device_id = ? AND kind = 'admin_request'",
                (record_id, device_id),
            ).fetchone()
        return _admin_view(row) if row is not None else None

    def request_update(
        self, device_id: str, admin_request: dict[str, Any], idempotency_key: str
    ) -> tuple[str, str]:
        """Record an admin phone's update request. Returns ``(record_id, state)``.

        Only a request (invariant 4): the PC checks the grant against its own ledger, its own switch and its own
        fetch of origin, and answers. The gateway refuses early what the PC would refuse anyway: a phone without the
        ``admin`` grant, and a commit other than the ``origin/main`` the PC last reported (``status_changed``).
        """

        record = {
            "record_id": str(uuid.uuid4()),
            "idempotency_key": idempotency_key,
            "device_id": device_id,
            "created_at": stamp(self.clock()),
            "kind": "admin_request",
            "admin_request": admin_request,
        }
        try:
            self.contract.validate("outbox_record", record)
        except ContractError as error:
            raise GatewayError(422, "invalid_record") from error
        with self.write() as db:
            # Checked inside the write: the body may have arrived after a revocation (S11).
            device = db.execute(
                "SELECT scopes FROM device WHERE device_id = ? AND revoked_at IS NULL", (device_id,)
            ).fetchone()
            if device is None:
                raise GatewayError(401, "not_enrolled")
            if "admin" not in json.loads(device["scopes"]):
                raise GatewayError(403, "not_granted")
            previous = db.execute(
                "SELECT record_id, record, status FROM outbox"
                " WHERE device_id = ? AND idempotency_key = ?",
                (device_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if json.loads(previous["record"]).get("admin_request") != admin_request:
                    raise GatewayError(409, "idempotency_conflict")
                return previous["record_id"], _state(previous["status"])
            status = db.execute("SELECT payload FROM pc_status WHERE id = 1").fetchone()
            shown = json.loads(status["payload"])["checkout"] if status else {}
            if shown.get("origin_main_sha") != admin_request["expected_sha"]:
                raise GatewayError(409, "status_changed")
            waiting = db.execute(
                "SELECT record_id, delivered_at FROM outbox WHERE device_id = ?"
                " AND kind = 'admin_request' AND status = 'pending'",
                (device_id,),
            ).fetchall()
            if any(row["delivered_at"] is not None for row in waiting):
                raise GatewayError(409, "update_pending")  # the PC has it; its answer comes first
            # A request the PC has never seen is simply replaced by the newer one.
            db.executemany(
                "UPDATE outbox SET status = 'superseded' WHERE record_id = ?",
                [(row["record_id"],) for row in waiting],
            )
            db.execute(
                "INSERT INTO outbox (record_id, idempotency_key, device_id, library_id, sha256,"
                " record, status, kind, created_at)"
                " VALUES (?, ?, ?, '', '', ?, 'pending', 'admin_request', ?)",
                (
                    record["record_id"],
                    idempotency_key,
                    device_id,
                    json.dumps(record),
                    record["created_at"],
                ),
            )
        return record["record_id"], "pending"

    def outbox_page(self, after: int, limit: int) -> dict[str, Any]:
        with self.write() as db:
            now = self.clock()
            deferred.pc_seen(db, now, stamp(now))
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
        with self.write() as db:
            row = db.execute(
                "SELECT library_id, sha256, status, kind, delivered_at, cancelled_at FROM outbox"
                " WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise GatewayError(404, "unknown_record")
            # RG-160: the PC had it before the phone cancelled and admitted it anyway; the phone must be told.
            too_late = (
                row["status"] == "superseded"
                and row["cancelled_at"] is not None
                and row["delivered_at"] is not None
                and acknowledgement["outcome"] != "refused"
            )
            if row["status"] != "pending" and not too_late:
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
            if row["kind"] != "admin_request":  # an admin request names no item
                self._reconcile_upload(db, (row["library_id"], row["sha256"]))
        return "recorded"

    # --- Immich (D3) --------------------------------------------------------------------------------------------

    def _reconcile_upload(self, db: sqlite3.Connection, key: tuple[str, str]) -> None:
        upload_queue.reconcile(db, key, stamp(self.clock() + upload_queue.SETTLE))

    def immich_receipts(self, cursor: str) -> dict[str, Any]:
        with self.connection() as db:
            return upload_queue.receipt_page(db, cursor)

    # --- enrollment ---------------------------------------------------------------------------------------------

    def add_offer(self, offer: dict[str, Any]) -> None:
        offer_id = offer["offer_id"].lower()
        payload = _hash(json.dumps(offer, sort_keys=True))
        now = self.clock()
        with self.write() as db:
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
        with self.write() as db:
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
        with self.write() as db:
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
            result.update(upload_queue.counts(db))
        result["media_bytes"] = sum(
            path.stat().st_size for path in self.media.blobs.glob("*/*") if path.is_file()
        )
        return result

    # --- retention (D4) -----------------------------------------------------------------------------------------

    def retention(self) -> dict[str, int]:
        """Drop cached media for items whose latest decision the PC answered long enough ago.

        Kept media also waits for Immich: nothing is purged while an upload is owed (RG-130).
        """

        now = self.clock()
        with self.write() as db:
            rows = db.execute(
                "SELECT item.library_id, item.sha256, outbox.record, outbox.status,"
                " outbox.answered_at, owed.state AS upload"
                " FROM item JOIN outbox ON outbox.record_id = item.latest_record_id"
                " LEFT JOIN immich_upload AS owed ON owed.library_id = item.library_id"
                "  AND owed.sha256 = item.sha256"
                " WHERE item.purged_at IS NULL AND NOT EXISTS ("
                "   SELECT 1 FROM outbox AS other WHERE other.library_id = item.library_id"
                "   AND other.sha256 = item.sha256 AND other.status = 'pending')"
            ).fetchall()
            expired = []
            for row in rows:
                verdict = None
                if row["status"] != "refused":
                    verdict = json.loads(row["record"])["decision"]["verdict"]
                if row["upload"] in ("queued", "failed") or (
                    verdict == "keep" and row["upload"] != "done"
                ):
                    continue
                discarded = verdict == "delete"
                window = DISCARD_UNDO if discarded else KEEP_AFTER_ANSWER
                if now - _instant(row["answered_at"]) >= window:
                    expired.append((row["library_id"], row["sha256"]))
            expired += self._stale_undecided(db, now)
            # An original stays while a result made from it is still to be judged beside it.
            wanted = {
                library_id
                for row in db.execute(
                    "SELECT parent_library_id, input_library_id FROM item"
                    " WHERE purged_at IS NULL AND ready_at IS NOT NULL AND latest_record_id IS NULL"
                )
                for library_id in row
                if library_id
            }
            expired = [key for key in expired if key[0] not in wanted]
            db.executemany(
                "UPDATE item SET purged_at = ? WHERE library_id = ? AND sha256 = ?",
                [(stamp(now), *key) for key in expired],
            )
            size = _cached_bytes(db)
            # If this stops before the commit, the same items are simply purged again next time.
            removed = self._release(db, expired)
        if self.cache_warn_bytes and size > self.cache_warn_bytes:
            _LOG.warning(
                "the media cache holds %d MB, over its %d MB warning level",
                size // 1_000_000,
                self.cache_warn_bytes // 1_000_000,
            )
        return {"items_purged": len(expired), "files_removed": removed}

    def _stale_undecided(self, db: sqlite3.Connection, now: datetime) -> list[tuple[str, str]]:
        """Items nobody has decided, older than ``undecided_days``, with no request waiting for the PC (PHONE-FAST).

        Any action request restarts the clock, so a rework's original outlives the wait for its result.
        """

        if not self.undecided_days:
            return []
        before = stamp(now - timedelta(days=self.undecided_days))
        return [
            (row["library_id"], row["sha256"])
            for row in db.execute(
                "SELECT library_id, sha256 FROM item WHERE purged_at IS NULL"
                " AND latest_record_id IS NULL AND ready_at < ? AND NOT EXISTS ("
                "   SELECT 1 FROM outbox WHERE outbox.library_id = item.library_id"
                "   AND outbox.sha256 = item.sha256 AND (outbox.status = 'pending'"
                "   OR COALESCE(outbox.answered_at, outbox.created_at) >= ?))",
                (before, before),
            )
        ]


def _stream(items: list[dict[str, Any]], rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """The items still to review, the group with the newest activity first, oldest first within a group."""

    groups = {(row["library_id"], row["sha256"]): row["batch_id"] or row["run_id"] for row in rows}
    latest: dict[str, str] = {}
    for row in rows:
        group = groups[(row["library_id"], row["sha256"])]
        latest[group] = max(latest.get(group, ""), row["created_at"])
    todo = [item for item in items if item["state"] in ("undecided", "refused")]
    todo.sort(key=lambda item: (item["created_at"], item["library_id"]))
    todo.sort(
        key=lambda item: (
            latest[groups[(item["library_id"], item["sha256"])]],
            groups[(item["library_id"], item["sha256"])],
        ),
        reverse=True,
    )
    return todo


def _cached_bytes(db: sqlite3.Connection) -> int:
    """The size of the media the items still use, from their manifests (shared files counted once)."""

    return db.execute(
        "SELECT COALESCE(SUM(bytes), 0) FROM (SELECT MAX(item_media.bytes) AS bytes FROM item_media"
        " JOIN item USING (library_id, sha256) WHERE item.purged_at IS NULL GROUP BY digest)"
    ).fetchone()[0]


def _migrate(db: sqlite3.Connection) -> None:
    """Add what RG-140 needs to an outbox made before it; every earlier record was a decision."""

    columns = {row[1] for row in db.execute("PRAGMA table_info(outbox)")}
    if "kind" not in columns:
        db.execute("ALTER TABLE outbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'decision'")
        # Owner decision 2026-11-26 (RG-140 Q4): queueing is on by default, including phones paired before it
        # existed, so they need no new pairing. Runs once: only a database without the kind column gets here.
        for device_id, scopes in db.execute("SELECT device_id, scopes FROM device").fetchall():
            granted = json.loads(scopes)
            if "review" in granted and "queue" not in granted:
                db.execute(
                    "UPDATE device SET scopes = ? WHERE device_id = ?",
                    (json.dumps([*granted, "queue"]), device_id),
                )
    if "created_at" not in columns:
        db.execute("ALTER TABLE outbox ADD COLUMN created_at TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS outbox_device_kind ON outbox (device_id, kind, seq)")
    # The batch an item was queued in (N5), for grouping the inbox; items published before it have none.
    item_columns = {row[1] for row in db.execute("PRAGMA table_info(item)")}
    for column in ("batch_id", "batch"):
        if column not in item_columns:
            db.execute(f"ALTER TABLE item ADD COLUMN {column} TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS item_batch ON item (batch_id, created_at, library_id)")
    # PHONE-FAST: the image a desk job made an item from, or that it cannot be found.
    if "input_missing" not in item_columns:
        db.execute("ALTER TABLE item ADD COLUMN input_missing INTEGER")
    # PHONE-FAST: the original a rework result was made from, the item's review section and its desk input.
    for column in (
        "parent_library_id",
        "parent_sha256",
        "source",
        "input_library_id",
        "input_sha256",
    ):
        if column not in item_columns:
            db.execute(f"ALTER TABLE item ADD COLUMN {column} TEXT")


def _action_view(row: sqlite3.Row) -> dict[str, Any]:
    record = json.loads(row["record"])
    answer = json.loads(row["acknowledgement"]) if row["acknowledgement"] else {}
    request = record["action_request"]
    params = request["params"]
    return {
        "record_id": record["record_id"],
        "library_id": record["target"]["library_id"],
        "sha256": record["target"]["sha256"],
        "action": request["action"],
        "step": params["step"],
        "choice": params.get("choice"),
        "text": params.get("text"),
        "count": params.get("count"),
        "created_at": record["created_at"],
        "state": _action_state(row),
        "delivered": row["delivered_at"] is not None,
        "too_late": row["cancelled_at"] is not None and row["status"] in ("applied", "duplicate"),
        "reason_code": answer.get("reason_code") if row["status"] == "refused" else None,
        "receipt": answer.get("receipt"),
    }


def _admin_view(row: sqlite3.Row) -> dict[str, Any]:
    record = json.loads(row["record"])
    answer = json.loads(row["acknowledgement"]) if row["acknowledgement"] else {}
    return {
        "record_id": record["record_id"],
        "expected_sha": record["admin_request"]["expected_sha"],
        "created_at": record["created_at"],
        "state": _state(row["status"]),
        "reason_code": answer.get("reason_code") if row["status"] == "refused" else None,
        "update": (answer.get("receipt") or {}).get("update"),
    }


def _state(status: str) -> str:
    return "applied" if status == "duplicate" else status


def _action_state(row: sqlite3.Row) -> str:
    if row["status"] == "superseded" and row["cancelled_at"] is not None:
        return "cancelled"
    return _state(row["status"])


def _reworked(db: sqlite3.Connection) -> set[tuple[str, str]]:
    """Items with a queued rework: a confirm (or a one-step ``queue``, RG-160) the PC has not refused and the phone has
    not cancelled. Derived from the outbox, so an older PC counts."""

    marks = ",".join("?" * len(REWORK_ACTIONS))
    rows = db.execute(
        "SELECT library_id, sha256 FROM outbox WHERE kind = 'action_request'"
        " AND status NOT IN ('refused', 'superseded')"
        " AND json_extract(record, '$.action_request.params.step') IN ('confirm', 'queue')"
        f" AND json_extract(record, '$.action_request.action') IN ({marks})",
        REWORK_ACTIONS,
    ).fetchall()
    return {(row["library_id"], row["sha256"]) for row in rows}


def _item_state(
    row: sqlite3.Row, reworked: set[tuple[str, str]]
) -> tuple[str, dict[str, Any] | None, str | None]:
    """``_outcome``, except that an undecided item sent for rework counts as reviewed."""

    state, decision, reason = _outcome(row)
    if state in ("undecided", "refused") and (row["library_id"], row["sha256"]) in reworked:
        return "rework", decision, None
    return state, decision, reason


def _outcome(row: sqlite3.Row) -> tuple[str, dict[str, Any] | None, str | None]:
    """``(state, decision, refusal reason)`` of an item joined with its latest record."""

    if row["record"] is None:
        return "undecided", None, None
    decision = json.loads(row["record"])["decision"]
    answer = json.loads(row["acknowledgement"]) if row["acknowledgement"] else {}
    reason = answer.get("reason_code") if row["status"] == "refused" else None
    return _state(row["status"]), {"tags": [], **decision}, reason
