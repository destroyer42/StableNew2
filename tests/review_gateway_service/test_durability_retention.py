"""S9 outbox durability and D4 retention: nothing is purged before the PC has answered."""

from __future__ import annotations

import os
import shutil
from types import SimpleNamespace

from review_gateway.app import Gateway

RUN = "20261125_101500_pack"


def files(rig) -> list[str]:
    return sorted(p.name for p in rig.settings.media_dir.rglob("*") if p.is_file())


def listed(rig) -> list[str]:
    runs = rig.phone.get("/api/runs").json()["runs"]
    return [
        item["library_id"]
        for run in runs
        for item in rig.phone.get(f"/api/runs/{run['run_id']}").json()["items"]
    ]


def decided(
    rig, name: str, verdict: str = "keep", outcome: str | None = "applied", **fields
) -> dict:
    item = rig.publish(name)
    record_id = rig.decide(item, verdict).json()["record_id"]
    if outcome:
        rig.outbox()
        rig.acknowledge(record_id, outcome, **fields)
    return item


def test_every_connection_uses_wal_with_full_synchronous(rig) -> None:
    with rig.gateway.store.connection() as database:
        assert database.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert database.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL


def test_decisions_receipts_and_sessions_survive_a_restart(rig) -> None:
    item = rig.publish()
    other = rig.publish("two")
    rig.pair()
    answered = rig.decide(other).json()["record_id"]
    rig.outbox()
    rig.acknowledge(answered)
    pending = rig.decide(item).json()["record_id"]
    cookie = rig.phone.cookies["rg_session"]

    restarted = Gateway(rig.settings, clock=rig.clock)
    sync = rig.client(restarted.sync_app(), headers=rig.auth())
    phone = rig.client(
        restarted.phone_app(),
        headers={"X-Review-Gateway": "1", "Cookie": f"rg_session={cookie}"},
    )

    assert [r["record_id"] for r in sync.get("/sync/v1/outbox").json()["records"]] == [pending]
    states = {i["library_id"]: i["state"] for i in phone.get(f"/api/runs/{RUN}").json()["items"]}
    assert states == {item["library_id"]: "pending", other["library_id"]: "applied"}


def test_nothing_is_purged_before_the_pc_answers(rig) -> None:
    rig.gateway.store.undecided_days = 0  # the 30-day purge of undecided items has its own tests
    rig.pair()
    undecided = rig.publish("undecided")
    waiting = decided(rig, "waiting", "delete", outcome=None)
    before = files(rig)
    rig.clock.advance(days=400)

    summary = rig.gateway.retention()

    assert summary["items_purged"] == 0
    assert files(rig) == before
    assert sorted(listed(rig)) == sorted([undecided["library_id"], waiting["library_id"]])


def test_a_newer_unanswered_decision_holds_the_item(rig) -> None:
    rig.pair()
    item = decided(rig, "changed", "delete")
    rig.decide(item, "keep")
    rig.clock.advance(days=60)

    assert rig.gateway.retention()["items_purged"] == 0


def test_an_older_unanswered_record_also_holds_the_item(rig) -> None:
    rig.pair()
    item = rig.publish()
    rig.decide(item, "delete")
    rig.outbox()  # the PC has seen it, so the next decision is a second record
    latest = rig.decide(item, "keep").json()["record_id"]
    rig.acknowledge(latest)
    rig.clock.advance(days=60)

    assert rig.gateway.retention()["items_purged"] == 0


def test_an_applied_discard_is_purged_after_the_48_hour_undo_window(rig) -> None:
    rig.pair()
    item = decided(rig, "binned", "delete")

    rig.clock.advance(hours=47, minutes=59)
    assert rig.gateway.retention()["items_purged"] == 0
    rig.clock.advance(minutes=2)
    assert rig.gateway.retention()["items_purged"] == 1

    assert files(rig) == []
    assert listed(rig) == []
    assert (
        rig.phone.get(f"/media/{item['library_id']}/{item['sha256']}/original").status_code == 404
    )


def test_kept_and_refused_items_stay_for_14_days_after_the_answer(rig) -> None:
    rig.pair()
    decided(rig, "kept")
    decided(rig, "refused", "delete", outcome="refused", reason_code="archive_failed")
    rig.confirm_uploads()  # a kept item also waits for Immich (test_immich_upload.py)

    rig.clock.advance(days=13, hours=23)
    assert rig.gateway.retention()["items_purged"] == 0
    rig.clock.advance(hours=2)
    assert rig.gateway.retention()["items_purged"] == 2
    assert files(rig) == []


def test_media_shared_with_a_live_item_is_not_deleted(rig) -> None:
    rig.pair()
    shared = b"identical-thumbnail"
    first = rig.publish("first", extra={"thumb_320": shared})
    second = rig.publish("second", extra={"thumb_320": shared})
    record_id = rig.decide(first, "delete").json()["record_id"]
    rig.acknowledge(record_id)
    rig.clock.advance(days=3)

    rig.gateway.retention()

    response = rig.phone.get(f"/media/{second['library_id']}/{second['sha256']}/thumb")
    assert response.content == shared


def test_republishing_a_purged_item_does_not_bring_it_back(rig) -> None:
    rig.pair()
    decided(rig, "binned", "delete")
    rig.clock.advance(days=3)
    rig.gateway.retention()
    manifest, _ = rig.manifest("binned")

    response = rig.sync.post("/sync/v1/items", json=manifest)

    assert response.json() == {"status": "purged", "missing": []}
    assert listed(rig) == []


def test_media_lost_from_disk_is_asked_for_again(rig) -> None:
    rig.publish()
    manifest, blobs = rig.manifest("one")
    lost = manifest["media"]["thumb_320"]["sha256"]
    next(p for p in rig.settings.media_dir.rglob(lost)).unlink()

    response = rig.sync.post("/sync/v1/items", json=manifest)

    assert response.json() == {"status": "incomplete", "missing": [lost]}
    assert rig.sync.put(f"/sync/v1/media/{lost}", content=blobs[lost]).status_code == 201


def test_stale_partial_uploads_and_unreferenced_files_are_swept(rig) -> None:
    rig.publish()
    kept = files(rig)
    partial = rig.settings.media_dir / "incoming" / "left-over.part"
    orphan = rig.settings.media_dir / "blobs" / "ff" / ("f" * 64)
    for path in (partial, orphan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        old = rig.clock().timestamp() - 90_000
        os.utime(path, (old, old))

    summary = rig.gateway.retention()

    assert summary["files_removed"] == 2
    assert files(rig) == kept


def test_a_repeated_upload_shows_an_item_a_failed_update_left_hidden(rig) -> None:
    manifest, blobs = rig.manifest("one")
    rig.sync.post("/sync/v1/items", json=manifest)
    digests = list(blobs)
    for digest in digests[:-1]:
        rig.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest])
    last = digests[-1]
    writer = rig.gateway.store.upload(last)
    writer.write(blobs[last])
    writer.commit()  # the file landed, then the process stopped before the item was marked ready
    rig.pair()
    assert listed(rig) == []

    assert rig.sync.put(f"/sync/v1/media/{last}", content=blobs[last]).status_code == 200

    assert len(listed(rig)) == 1


def test_uploads_stop_before_the_disk_that_holds_decisions_fills(rig, monkeypatch) -> None:
    manifest, blobs = rig.manifest("one")
    rig.sync.post("/sync/v1/items", json=manifest)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=1000))
    digest, data = next(iter(blobs.items()))

    response = rig.sync.put(f"/sync/v1/media/{digest}", content=data)

    assert response.status_code == 507
    assert response.json() == {"error": "storage_unavailable"}
    assert files(rig) == []
