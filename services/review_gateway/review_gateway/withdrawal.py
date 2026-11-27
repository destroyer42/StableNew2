"""The PC takes an item back out of the Review inbox (RG-170: eval clips that should never have been there).

Withdrawing records no decision, tells Immich nothing and removes nothing from it. An item with an unanswered record, or
with a keeper Immich does not have yet, is left as it is and reported ``kept``; the PC asks again later. The cached
media goes with the next retention sweep, like any purged item's.
"""

from __future__ import annotations

import json

from .store import Store, stamp


def withdraw(store: Store, library_id: str, sha256: str) -> str:
    """``withdrawn``, ``kept`` or ``unknown``."""

    key = (library_id, sha256)
    with store.write() as db:
        item = db.execute(
            "SELECT purged_at, latest_record_id FROM item WHERE library_id = ? AND sha256 = ?", key
        ).fetchone()
        if item is None:
            return "unknown"
        if item["purged_at"] is not None:
            return "withdrawn"
        if db.execute(
            "SELECT 1 FROM outbox WHERE library_id = ? AND sha256 = ? AND status = 'pending'", key
        ).fetchone():
            return "kept"
        upload = db.execute(
            "SELECT state FROM immich_upload WHERE library_id = ? AND sha256 = ?", key
        ).fetchone()
        state = upload["state"] if upload else None
        latest = db.execute(
            "SELECT record, status FROM outbox WHERE record_id = ?", (item["latest_record_id"],)
        ).fetchone()
        keeper = (
            latest is not None
            and latest["status"] != "refused"
            and json.loads(latest["record"])["decision"]["verdict"] == "keep"
        )
        if state in ("queued", "failed") or (keeper and state != "done"):
            return "kept"
        db.execute(
            "UPDATE item SET purged_at = ? WHERE library_id = ? AND sha256 = ?",
            (stamp(store.clock()), *key),
        )
    return "withdrawn"
