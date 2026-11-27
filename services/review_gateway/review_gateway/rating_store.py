"""Rating tasks, the phone's answers and the submissions owed to the PC (RG-170).

A second projection and outbox beside the review one, with the same rules (RG-100 invariants 2 and 4): the PC publishes
a task and its media; the phone saves answers per item and submits them once; the submission stays pending until the PC
applies or refuses it. Nothing here knows which arm a clip came from. Rating media has its own directory, so review
retention never sees it and rating retention never touches review media.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .contract import SCHEMA_VERSION
from .errors import GatewayError
from .media import MediaStore, MediaWriter
from .store import KEEP_AFTER_ANSWER, STALE_FILE_S, Store, stamp

WITHDRAWN_WINDOW = timedelta(hours=48)
#: A technical bound on the tasks listed at once, not a quota: far above a person's backlog.
MAXIMUM_TASKS = 200
SUBMISSION_PAGE = 20
_SCORES = frozenset("12345")
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{16,128}")

_TABLES = """
CREATE TABLE IF NOT EXISTS rating_task (
    task_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, shape TEXT NOT NULL,
    state TEXT NOT NULL, ready_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rating_media (
    task_id TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, content_type TEXT NOT NULL,
    PRIMARY KEY (task_id, sha256)
);
CREATE INDEX IF NOT EXISTS rating_media_digest ON rating_media (sha256);
CREATE TABLE IF NOT EXISTS rating_answer (
    task_id TEXT NOT NULL, item_id TEXT NOT NULL, clip_id TEXT NOT NULL,
    answer_values TEXT NOT NULL, notes TEXT NOT NULL, device_id TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (task_id, item_id, clip_id)
);
CREATE TABLE IF NOT EXISTS rating_submission (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL,
    device_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, answers TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','applied','refused')),
    answered_at TEXT, acknowledgement TEXT,
    UNIQUE (device_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS rating_submission_task ON rating_submission (task_id, seq);
"""


def _shape(manifest: dict[str, Any]) -> str:
    """What the saved answers depend on: a task id may be re-titled or re-encoded, never reshaped."""

    return json.dumps(
        [
            manifest["kind"],
            [
                [c["criterion_id"], c["type"], [o["value"] for o in c.get("options", [])]]
                for c in manifest["criteria"]
            ],
            [
                [item["item_id"], [clip["clip_id"] for clip in item.get("clips", [])]]
                for item in manifest["items"]
            ],
        ]
    )


def _media_of(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for item in manifest["items"]:
        if "reference" in item:
            entries.append(item["reference"])
        entries.extend(clip["media"] for clip in item.get("clips", []))
    return entries


def _check_manifest(manifest: dict[str, Any]) -> None:
    """The rules the schema cannot state: unique ids and a clip count that suits the kind."""

    kind = manifest["kind"]
    criteria = [c["criterion_id"] for c in manifest["criteria"]]
    items = [item["item_id"] for item in manifest["items"]]
    if len(set(criteria)) != len(criteria) or len(set(items)) != len(items):
        raise GatewayError(422, "duplicate_id")
    for item in manifest["items"]:
        clips = [clip["clip_id"] for clip in item.get("clips", [])]
        if len(set(clips)) != len(clips):
            raise GatewayError(422, "duplicate_id")
        wanted = {"pairs": len(clips) == 2, "scores": len(clips) >= 1, "ranking": len(clips) >= 2}
        if not wanted.get(kind, True):
            raise GatewayError(422, "invalid_clips")
    types = {"pairs": "choice", "ranking": "rank"}
    for criterion in manifest["criteria"]:
        kind_of = criterion["type"]
        if kind_of == "enum" and "options" not in criterion:
            raise GatewayError(422, "invalid_criterion")
        if kind in types and kind_of != types[kind]:
            raise GatewayError(422, "invalid_criterion")
        if kind == "scores" and kind_of not in ("score", "enum"):
            raise GatewayError(422, "invalid_criterion")
        if kind == "choice" and kind_of != "enum":
            raise GatewayError(422, "invalid_criterion")


def _valid_value(criterion: dict[str, Any], value: Any, clips: list[str]) -> bool:
    if not isinstance(value, str):
        return False
    kind = criterion["type"]
    if kind == "score":
        return value in _SCORES
    if kind == "enum":
        return value in {option["value"] for option in criterion["options"]}
    if kind == "choice":
        return value == "tie" or value in clips
    # rank: every clip exactly once, best first, ">" between places and "=" within one.
    return value == "tie" or sorted(re.split(r"[>=]", value)) == sorted(clips)


def _units(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    """What is answered: each clip of a score sheet, otherwise each item."""

    if manifest["kind"] == "scores":
        return [
            (item["item_id"], clip["clip_id"])
            for item in manifest["items"]
            for clip in item["clips"]
        ]
    return [(item["item_id"], "") for item in manifest["items"]]


class RatingStore:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.contract = store.contract
        self.media = MediaStore(store.media.blobs.parent / "rating")
        with store.connection() as db:
            db.executescript(_TABLES)

    def _now(self) -> str:
        return stamp(self.store.clock())

    # --- publishing (sync side) ---------------------------------------------------------------------------------

    def publish(self, manifest: dict[str, Any]) -> tuple[str, list[str]]:
        """Store a validated task. Returns ``(status, digests still to upload)``."""

        _check_manifest(manifest)
        task_id, shape, now = manifest["task_id"], _shape(manifest), self._now()
        with self.store.write() as db:
            row = db.execute(
                "SELECT shape FROM rating_task WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is not None and row["shape"] != shape:
                used = db.execute(
                    "SELECT 1 FROM rating_answer WHERE task_id = ? UNION ALL"
                    " SELECT 1 FROM rating_submission WHERE task_id = ? LIMIT 1",
                    (task_id, task_id),
                ).fetchone()
                if used is not None:
                    raise GatewayError(409, "task_conflict")
            db.execute(
                "INSERT INTO rating_task (task_id, manifest, shape, state, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (task_id) DO UPDATE SET"
                " manifest = excluded.manifest, shape = excluded.shape,"
                " updated_at = CASE WHEN state = excluded.state THEN updated_at"
                " ELSE excluded.updated_at END, state = excluded.state",
                (task_id, json.dumps(manifest), shape, manifest["state"], now, now),
            )
            db.execute("DELETE FROM rating_media WHERE task_id = ?", (task_id,))
            missing: list[str] = []
            for entry in _media_of(manifest):
                digest, size = entry["sha256"], int(entry["bytes"])
                db.execute(
                    "INSERT OR IGNORE INTO rating_media VALUES (?, ?, ?, ?)",
                    (task_id, digest, size, entry["content_type"]),
                )
                stored = self.media.size(digest)
                if stored is None:
                    if digest not in missing:
                        missing.append(digest)
                elif stored != size:
                    raise GatewayError(422, "size_mismatch")
            if manifest["state"] != "open":
                missing = []  # a finished or withdrawn task asks for no bytes
            if not missing:
                db.execute(
                    "UPDATE rating_task SET ready_at = COALESCE(ready_at, ?) WHERE task_id = ?",
                    (now, task_id),
                )
        return ("incomplete" if missing else "ready"), missing

    def upload(self, digest: str) -> MediaWriter | None:
        """A writer for a declared digest, or ``None`` when it is already stored."""

        with self.store.connection() as db:
            row = db.execute(
                "SELECT bytes FROM rating_media WHERE sha256 = ? LIMIT 1", (digest,)
            ).fetchone()
        if row is None:
            raise GatewayError(409, "unknown_media")
        if self.media.size(digest) is not None:
            return None
        return self.media.writer(digest, row["bytes"])

    def pending_submissions(self) -> dict[str, Any]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT * FROM rating_submission WHERE status = 'pending' ORDER BY seq LIMIT ?",
                (SUBMISSION_PAGE,),
            ).fetchall()
        return {
            "schema_version": SCHEMA_VERSION,
            "type": "rating_submission_page",
            "submissions": [
                {
                    "submission_id": row["submission_id"],
                    "task_id": row["task_id"],
                    "device_id": row["device_id"],
                    "created_at": row["created_at"],
                    "answers": json.loads(row["answers"]),
                }
                for row in rows
            ],
        }

    def acknowledge(self, acknowledgement: dict[str, Any]) -> str:
        submission_id = acknowledgement["submission_id"].lower()
        with self.store.write() as db:
            row = db.execute(
                "SELECT status FROM rating_submission WHERE submission_id = ?", (submission_id,)
            ).fetchone()
            if row is None:
                raise GatewayError(404, "unknown_record")
            if row["status"] != "pending":
                return "already_acknowledged"
            db.execute(
                "UPDATE rating_submission SET status = ?, answered_at = ?, acknowledgement = ?"
                " WHERE submission_id = ?",
                (
                    acknowledgement["outcome"],
                    self._now(),
                    json.dumps(acknowledgement),
                    submission_id,
                ),
            )
        return "recorded"

    # --- the phone's view ---------------------------------------------------------------------------------------

    def _latest(self, db: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
        return db.execute(
            "SELECT * FROM rating_submission WHERE task_id = ? ORDER BY seq DESC LIMIT 1",
            (task_id,),
        ).fetchone()

    def _answers(self, db: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT * FROM rating_answer WHERE task_id = ? ORDER BY item_id, clip_id", (task_id,)
        ).fetchall()
        return [
            {
                "item_id": row["item_id"],
                "clip_id": row["clip_id"],
                "values": json.loads(row["answer_values"]),
                "notes": row["notes"],
            }
            for row in rows
        ]

    def _summary(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        manifest = json.loads(row["manifest"])
        answers = self._answers(db, row["task_id"])
        given = {(a["item_id"], a["clip_id"]): a["values"] for a in answers}
        required = [c["criterion_id"] for c in manifest["criteria"] if c["required"]]
        units = _units(manifest)
        answered = sum(
            all(criterion in given.get(unit, {}) for criterion in required) for unit in units
        )
        latest = self._latest(db, row["task_id"])
        status = latest["status"] if latest is not None else None
        if row["state"] == "done" or status == "applied":
            state = "done"
        elif status == "pending":
            state = "submitted"
        elif status == "refused":
            state = "refused"
        else:
            state = "partly" if answers else "open"
        summary = {
            "task_id": row["task_id"],
            "title": manifest["title"],
            "kind": manifest["kind"],
            "state": state,
            "answered": answered,
            "total": len(units),
            "created_at": manifest["created_at"],
        }
        if "note" in manifest:
            summary["note"] = manifest["note"]
        if latest is not None and latest["acknowledgement"]:
            answer = json.loads(latest["acknowledgement"])
            if state == "refused":
                summary["reason_code"] = answer.get("reason_code")
            if "reveal" in answer:
                summary["reveal"] = answer["reveal"]
        return summary

    def _visible(self, db: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM rating_task WHERE task_id = ? AND ready_at IS NOT NULL"
            " AND state <> 'withdrawn'",
            (task_id,),
        ).fetchone()
        if row is None:
            raise GatewayError(404, "not_found")
        return row

    def tasks(self) -> dict[str, Any]:
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT * FROM rating_task WHERE ready_at IS NOT NULL AND state <> 'withdrawn'"
                " ORDER BY created_at DESC, task_id LIMIT ?",
                (MAXIMUM_TASKS,),
            ).fetchall()
            tasks = [self._summary(db, row) for row in rows]
        for task in tasks:
            task.pop("reveal", None)  # shown inside the task only
        waiting = sum(task["state"] in ("open", "partly", "refused") for task in tasks)
        return {"tasks": tasks, "waiting": waiting}

    def task(self, task_id: str) -> dict[str, Any]:
        with self.store.connection() as db:
            row = self._visible(db, task_id)
            manifest = json.loads(row["manifest"])
            shown = {
                **self._summary(db, row),
                "instructions": manifest.get("instructions", ""),
                "criteria": manifest["criteria"],
                "items": manifest["items"],
                "answers": self._answers(db, task_id),
            }
        return shown

    def _editable(self, db: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        row = self._visible(db, task_id)
        latest = self._latest(db, task_id)
        if row["state"] != "open" or (latest is not None and latest["status"] != "refused"):
            raise GatewayError(409, "already_submitted")
        return json.loads(row["manifest"])

    def _require_device(self, db: sqlite3.Connection, device_id: str) -> None:
        # Checked inside the write: the body may have arrived after a revocation (S11).
        if (
            db.execute(
                "SELECT 1 FROM device WHERE device_id = ? AND revoked_at IS NULL", (device_id,)
            ).fetchone()
            is None
        ):
            raise GatewayError(401, "not_enrolled")

    def save_answer(self, device_id: str, task_id: str, answer: dict[str, Any]) -> None:
        """Replace one item's (or one clip's) answers; an empty answer clears it."""

        item_id, clip_id = answer["item_id"], answer["clip_id"]
        values, notes = answer["values"], answer.get("notes", "")
        with self.store.write() as db:
            self._require_device(db, device_id)
            manifest = self._editable(db, task_id)
            item = next((i for i in manifest["items"] if i["item_id"] == item_id), None)
            if item is None or (item_id, clip_id) not in _units(manifest):
                raise GatewayError(422, "invalid_answer")
            clips = [clip["clip_id"] for clip in item.get("clips", [])]
            criteria = {c["criterion_id"]: c for c in manifest["criteria"]}
            for name, value in values.items():
                if name not in criteria or not _valid_value(criteria[name], value, clips):
                    raise GatewayError(422, "invalid_answer")
            if not values and not notes:
                db.execute(
                    "DELETE FROM rating_answer WHERE task_id = ? AND item_id = ? AND clip_id = ?",
                    (task_id, item_id, clip_id),
                )
                return
            db.execute(
                "INSERT INTO rating_answer VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (task_id, item_id, clip_id) DO UPDATE SET"
                " answer_values = excluded.answer_values, notes = excluded.notes,"
                " device_id = excluded.device_id, updated_at = excluded.updated_at",
                (task_id, item_id, clip_id, json.dumps(values), notes, device_id, self._now()),
            )

    def submit(self, device_id: str, task_id: str, idempotency_key: str) -> tuple[str, str]:
        """Freeze the answers into one request for the PC. Returns ``(submission_id, state)``."""

        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise GatewayError(422, "invalid_record")
        with self.store.write() as db:
            self._require_device(db, device_id)
            previous = db.execute(
                "SELECT submission_id, task_id, status FROM rating_submission"
                " WHERE device_id = ? AND idempotency_key = ?",
                (device_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["task_id"] != task_id:
                    raise GatewayError(409, "idempotency_conflict")
                state = "submitted" if previous["status"] == "pending" else previous["status"]
                return previous["submission_id"], state
            manifest = self._editable(db, task_id)
            answers = self._answers(db, task_id)
            given = {(a["item_id"], a["clip_id"]): a["values"] for a in answers}
            required = [c["criterion_id"] for c in manifest["criteria"] if c["required"]]
            if not answers or any(
                criterion not in given.get(unit, {})
                for unit in _units(manifest)
                for criterion in required
            ):
                raise GatewayError(422, "incomplete")
            submission_id = str(uuid.uuid4())
            record = {
                "submission_id": submission_id,
                "task_id": task_id,
                "device_id": device_id,
                "created_at": self._now(),
                "answers": answers,
            }
            self.contract.validate("rating_submission", record)
            db.execute(
                "INSERT INTO rating_submission (submission_id, task_id, device_id,"
                " idempotency_key, answers, created_at, status)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (
                    submission_id,
                    task_id,
                    device_id,
                    idempotency_key,
                    json.dumps(answers),
                    record["created_at"],
                ),
            )
        return submission_id, "submitted"

    def media_file(self, task_id: str, digest: str) -> tuple[Path, str]:
        with self.store.connection() as db:
            self._visible(db, task_id)
            row = db.execute(
                "SELECT content_type FROM rating_media WHERE task_id = ? AND sha256 = ?",
                (task_id, digest),
            ).fetchone()
        if row is None or self.media.size(digest) is None:
            raise GatewayError(404, "not_found")
        return self.media.path(digest), row["content_type"]

    # --- retention (D4's windows) -------------------------------------------------------------------------------

    def retention(self) -> dict[str, int]:
        """Drop tasks finished 14 days ago or withdrawn 48 hours ago. A task owed to the PC always stays."""

        now: datetime = self.store.clock()
        with self.store.write() as db:
            expired = []
            for row in db.execute("SELECT task_id, state, updated_at FROM rating_task").fetchall():
                latest = self._latest(db, row["task_id"])
                if latest is not None and latest["status"] == "pending":
                    continue
                if row["state"] == "withdrawn":
                    since, window = row["updated_at"], WITHDRAWN_WINDOW
                elif latest is not None and latest["status"] == "applied":
                    since, window = latest["answered_at"], KEEP_AFTER_ANSWER
                elif row["state"] == "done":
                    since, window = row["updated_at"], KEEP_AFTER_ANSWER
                else:
                    continue
                if now - datetime.fromisoformat(since) >= window:
                    expired.append((row["task_id"],))
            for table in ("rating_task", "rating_media", "rating_answer", "rating_submission"):
                db.executemany(f"DELETE FROM {table} WHERE task_id = ?", expired)
            referenced = {row["sha256"] for row in db.execute("SELECT sha256 FROM rating_media")}
            # Under the write lock, so no publish can count on a file while it is being removed.
            removed = self.media.sweep(referenced, STALE_FILE_S, now.timestamp())
        return {"rating_tasks_purged": len(expired), "rating_files_removed": removed}
