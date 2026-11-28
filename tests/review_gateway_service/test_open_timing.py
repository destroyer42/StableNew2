"""PHONE-FAST gate: how long the phone took to open an image (``/api/timings``, ``/sync/v1/open-timings``)."""

from __future__ import annotations

import contextlib
import json
import sqlite3

import pytest
from review_gateway import timing_store

KEY = "timing-batch-0001-abcdef"
SAMPLE = {"ms": 240, "source": "network", "bytes": 88_000}


def send(phone, *, key: str = KEY, samples: list | None = None):
    body = {"idempotency_key": key, "samples": [SAMPLE] if samples is None else samples}
    return phone.post("/api/timings", json=body)


def rows(rig, query: str = "") -> dict:
    response = rig.sync.get(f"/sync/v1/open-timings{query}")
    assert response.status_code == 200, response.text
    return response.json()


def stored(rig) -> list[tuple]:
    path = rig.settings.data_dir / "timing.sqlite3"
    with contextlib.closing(sqlite3.connect(path)) as db:
        return list(db.execute("SELECT device_id, ms, source, bytes FROM open_timing ORDER BY seq"))


def test_a_paired_phone_stores_a_batch_and_the_pc_reads_it(rig) -> None:
    device_id = rig.pair()
    samples = [SAMPLE, {"ms": 12, "source": "prefetch", "bytes": None}]

    assert send(rig.phone, samples=samples).json() == {"state": "stored"}

    assert stored(rig) == [(device_id, 240, "network", 88_000), (device_id, 12, "prefetch", None)]
    at = "2026-11-25T12:00:00.000000Z"  # the gateway's clock, not the phone's
    # The PC is given no device id: the report is about open times, not about phones.
    assert rows(rig) == {
        "rows": [
            {"at": at, "ms": 240, "source": "network", "bytes": 88_000},
            {"at": at, "ms": 12, "source": "prefetch", "bytes": None},
        ],
        "next_cursor": None,
    }


def test_a_resent_batch_is_stored_once(rig) -> None:
    rig.pair()
    send(rig.phone)

    assert send(rig.phone).json() == {"state": "duplicate"}
    assert len(stored(rig)) == 1


def test_the_same_key_from_another_phone_is_its_own_batch(rig) -> None:
    rig.pair()
    other = rig.new_phone()
    rig.pair(other, code="Z8WN4P2C")
    send(rig.phone)

    assert send(other).json() == {"state": "stored"}
    assert len(stored(rig)) == 2


def test_only_a_paired_phone_may_send(rig) -> None:
    assert send(rig.phone).status_code == 401

    device_id = rig.pair()
    without_header = rig.client(rig.gateway.phone_app())
    without_header.cookies = rig.phone.cookies
    assert send(without_header).json() == {"error": "missing_header"}
    rig.gateway.store.revoke_device(device_id)
    assert send(rig.phone).status_code == 401
    assert stored(rig) == []


def test_each_listener_has_only_its_own_route(rig) -> None:
    rig.pair()

    assert rig.phone.get("/sync/v1/open-timings").status_code == 404
    assert rig.phone.get("/api/timings").status_code == 405
    assert send(rig.sync).status_code == 404
    unsigned = rig.client(rig.gateway.sync_app())
    assert unsigned.get("/sync/v1/open-timings").status_code == 401
    wrong = rig.client(rig.gateway.sync_app(), headers={"Authorization": "Bearer nonsense"})
    assert wrong.get("/sync/v1/open-timings").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"samples": [SAMPLE]},
        {"idempotency_key": KEY},
        {"idempotency_key": KEY, "samples": [SAMPLE], "label": "Pixel"},
        {"idempotency_key": "short", "samples": [SAMPLE]},
        {"idempotency_key": KEY + "!", "samples": [SAMPLE]},
        {"idempotency_key": KEY + "\n", "samples": [SAMPLE]},
        {"idempotency_key": 12345678901234567, "samples": [SAMPLE]},
        {"idempotency_key": KEY, "samples": []},
        {"idempotency_key": KEY, "samples": {"0": SAMPLE}},
        {"idempotency_key": KEY, "samples": [SAMPLE] * 101},
        {"idempotency_key": KEY, "samples": [SAMPLE, None]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "library_id": "lib-one_____"}]},
        {"idempotency_key": KEY, "samples": [{"ms": 1, "source": "cache"}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "ms": -1}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "ms": 600_001}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "ms": 1.5}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "ms": True}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "ms": "12"}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "source": "disk"}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "source": ["cache"]}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "bytes": -1}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "bytes": 10**30}]},
        {"idempotency_key": KEY, "samples": [{**SAMPLE, "bytes": "88000"}]},
    ],
)
def test_a_batch_that_is_not_exactly_timings_is_refused_whole(rig, body) -> None:
    rig.pair()

    response = rig.phone.post("/api/timings", json=body)

    assert response.status_code == 422, response.text
    assert response.json() == {"error": "invalid_record"}
    assert stored(rig) == []


def test_a_body_that_is_not_json_or_is_too_large_is_refused(rig) -> None:
    rig.pair()
    huge = {"idempotency_key": KEY, "samples": [SAMPLE], "padding": "x" * 20_000}

    assert rig.phone.post("/api/timings", content=b"[1]").status_code == 400
    assert rig.phone.post("/api/timings", content=b'{"ms": NaN}').status_code == 400
    assert rig.phone.post("/api/timings", content=json.dumps(huge)).status_code == 413
    assert stored(rig) == []


def test_the_newest_rows_are_kept_when_the_table_is_full(rig, monkeypatch) -> None:
    monkeypatch.setattr(timing_store, "MAXIMUM_ROWS", 3)
    rig.pair()
    for number in range(5):
        send(rig.phone, key=f"timing-batch-{number:04}-abcdef", samples=[{**SAMPLE, "ms": number}])

    assert [row["ms"] for row in rows(rig)["rows"]] == [2, 3, 4]
    assert [row[1] for row in stored(rig)] == [2, 3, 4]


def test_rows_older_than_thirty_days_are_not_read_and_are_removed(rig) -> None:
    rig.pair()
    send(rig.phone)
    rig.clock.advance(days=30, seconds=1)

    assert rows(rig)["rows"] == []
    assert rig.gateway.retention()["timing_rows_purged"] == 1
    assert stored(rig) == []


def test_a_new_batch_also_removes_expired_rows(rig) -> None:
    rig.pair()
    send(rig.phone)
    rig.clock.advance(days=31)

    send(rig.phone, key="timing-batch-0002-abcdef")

    assert len(stored(rig)) == 1


def test_the_pc_reads_a_long_table_in_pages(rig, monkeypatch) -> None:
    monkeypatch.setattr(timing_store, "PAGE", 2)
    rig.pair()
    send(rig.phone, samples=[{**SAMPLE, "ms": number} for number in range(5)])

    seen, cursor = [], 0
    while cursor is not None:
        page = rows(rig, f"?cursor={cursor}")
        assert len(page["rows"]) <= 2
        seen += [row["ms"] for row in page["rows"]]
        cursor = page["next_cursor"]

    assert seen == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("cursor", ["-1", "x", "1.5", str(2**63)])
def test_a_cursor_that_is_not_a_row_number_is_refused(rig, cursor) -> None:
    response = rig.sync.get(f"/sync/v1/open-timings?cursor={cursor}")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_cursor"}


def test_timings_leave_the_review_database_as_it_was(rig) -> None:
    rig.pair()
    send(rig.phone)

    # Their own file: a deploy that rolls back compares gateway.sqlite3's tables before restoring it.
    with contextlib.closing(sqlite3.connect(rig.settings.data_dir / "gateway.sqlite3")) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert not [name for name in names if "timing" in name]
