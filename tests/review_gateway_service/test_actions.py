"""RG-140 phone actions on the gateway: two-step outbox requests under a separate queue grant (D6, S4, S8, S12).

The gateway records what the phone asked for and shows the PC's answer; it never compiles, admits or decides.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

RUN = "20261125_101500_pack"
REVISION = "ab" * 32


def prepare(rig, item, action="fix_face", *, key=None, phone=None, **params):
    return (phone or rig.phone).post(
        "/api/actions",
        json={
            **item,
            "action": action,
            "params": {"step": "prepare", **params},
            "idempotency_key": key or uuid.uuid4().hex,
        },
    )


def confirm(rig, item, prepared, action="fix_face", *, revision=REVISION, key=None):
    return rig.phone.post(
        "/api/actions",
        json={
            **item,
            "action": action,
            "params": {
                "step": "confirm",
                "prepared_record": prepared,
                "summary_revision": revision,
            },
            "idempotency_key": key or uuid.uuid4().hex,
        },
    )


def summary(action="fix_face", **changes):
    return {
        "action": action,
        "revision": REVISION,
        "title": "Fix face",
        "lines": ["ADetailer face pass on this image", "Checkpoint juggernautXL.safetensors"],
        "job_count": 1,
        "queue_position": "next",
        "warnings": [
            {
                "code": "image_model_family_unverified",
                "subject": "juggernautXL.safetensors",
                "title": "Unclassified checkpoint.",
                "why": "<b>not</b> markup",
                "fix": "Classify it.",
            }
        ],
        "expires_at": "2026-11-25T12:30:00Z",
        **changes,
    }


@pytest.fixture
def queue_rig(rig):
    rig.item = rig.publish()
    rig.device = rig.pair(scopes=("review", "queue"))
    return rig


def test_a_review_only_phone_cannot_request_an_action(rig) -> None:
    item = rig.publish()
    rig.pair()

    response = prepare(rig, item)

    assert response.status_code == 403
    assert response.json() == {"error": "not_granted"}
    assert rig.outbox()["records"] == []


def test_the_decision_route_still_refuses_action_shaped_bodies(queue_rig) -> None:
    body = {**queue_rig.item, "action": "fix_face", "idempotency_key": "k" * 20}

    response = queue_rig.phone.post("/api/decisions", json={**body, "kind": "action_request"})

    assert response.status_code == 403
    assert queue_rig.outbox()["records"] == []


def test_a_prepare_becomes_an_outbox_request_and_leaves_the_decision_alone(queue_rig) -> None:
    response = prepare(queue_rig, queue_rig.item, "more_like_this", count=4)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "pending"
    [record] = queue_rig.outbox()["records"]
    assert record["kind"] == "action_request"
    assert record["device_id"] == queue_rig.device
    assert record["target"] == queue_rig.item
    assert record["action_request"] == {
        "action": "more_like_this",
        "params": {"step": "prepare", "count": 4},
    }
    [item] = queue_rig.phone.get(f"/api/runs/{RUN}").json()["items"]
    assert item["state"] == "undecided"


@pytest.mark.parametrize(
    "action, params",
    [
        ("rm_rf", {"step": "prepare"}),
        ("rerun_clip", {"step": "prepare"}),  # N8: reserved, it will call V1's shared functions
        ("continue_clip", {"step": "prepare"}),
        ("fix_face", {"step": "prepare", "count": 2}),  # count belongs to more_like_this
        ("fix_face", {"step": "prepare", "choice": "2x3"}),  # choice belongs to slice-2 pickers
        ("make_video", {"step": "prepare", "choice": "2x3"}),
        ("another_model", {"step": "prepare", "text": "smiling"}),  # text belongs to tweak/video
        ("prompt_tweak", {"step": "prepare"}),  # the words are required
        ("prompt_tweak", {"step": "prepare", "text": "a\nb"}),
        ("prompt_tweak", {"step": "prepare", "text": "smiling\n"}),
        ("prompt_tweak", {"step": "prepare", "text": "x" * 201}),
        ("aspect_ratio", {"step": "prepare", "choice": "../x"}),
        (
            "another_model",
            {
                "step": "confirm",
                "choice": "m1",
                "prepared_record": str(uuid.uuid4()),
                "summary_revision": REVISION,
            },
        ),
        ("more_like_this", {"step": "prepare", "count": 9}),
        ("fix_face", {}),
        ("fix_face", {"step": "run"}),
        ("fix_face", {"step": "confirm", "prepared_record": str(uuid.uuid4())}),
        ("fix_face", {"step": "prepare", "prepared_record": str(uuid.uuid4())}),
        ("fix_face", {"step": "prepare", "strength": 1}),
    ],
)
def test_actions_and_params_are_a_closed_list(queue_rig, action, params) -> None:
    response = queue_rig.phone.post(
        "/api/actions",
        json={**queue_rig.item, "action": action, "params": params, "idempotency_key": "k" * 20},
    )

    assert response.status_code == 422, response.text
    assert queue_rig.outbox()["records"] == []


@pytest.mark.parametrize(
    "action, params",
    [
        ("another_model", {"step": "prepare"}),
        ("another_model", {"step": "prepare", "choice": "3f2a9c0d11e4b5a6"}),
        ("aspect_ratio", {"step": "prepare", "choice": "16x9"}),
        ("prompt_tweak", {"step": "prepare", "text": "smiling, golden hour"}),
        ("make_video", {"step": "prepare"}),
        ("make_video", {"step": "prepare", "text": "she turns to the window"}),
    ],
)
def test_slice_two_actions_become_outbox_requests(queue_rig, action, params) -> None:
    response = prepare(queue_rig, queue_rig.item, action, **params)

    assert response.status_code == 200, response.text
    [record] = queue_rig.outbox()["records"]
    assert record["action_request"] == {"action": action, "params": {"step": "prepare", **params}}


def test_a_list_of_choices_from_the_pc_is_shown(queue_rig) -> None:
    record_id = prepare(queue_rig, queue_rig.item, "another_model").json()["record_id"]
    queue_rig.outbox()
    choices = {
        "action": "another_model",
        "items": [
            {"id": "3f2a9c0d11e4b5a6", "label": "juggernautXL.safetensors", "current": True},
            {"id": "77aa00bb11cc22dd", "label": "<b>pony</b>XL.safetensors"},
        ],
    }

    assert queue_rig.acknowledge(record_id, receipt={"choices": choices}).is_success

    answered = queue_rig.phone.get(f"/api/actions/{record_id}").json()
    assert (answered["state"], answered["receipt"]) == ("applied", {"choices": choices})
    bad = prepare(queue_rig, queue_rig.item, "another_model").json()["record_id"]
    queue_rig.outbox()
    broken = {**choices, "items": [{"id": "C:\\models", "label": "x"}]}
    assert queue_rig.acknowledge(bad, receipt={"choices": broken}).status_code == 422


def test_unknown_fields_and_unknown_items_are_refused(queue_rig) -> None:
    body = {
        **queue_rig.item,
        "action": "fix_face",
        "params": {"step": "prepare"},
        "idempotency_key": "k" * 20,
    }
    assert queue_rig.phone.post("/api/actions", json={**body, "path": "C:/x"}).status_code == 422
    other = {**body, "sha256": "0" * 64}
    assert queue_rig.phone.post("/api/actions", json=other).status_code == 404


def test_a_video_item_has_no_slice_one_actions(rig) -> None:
    clip = rig.publish("clip", kind="video")
    rig.pair(scopes=("review", "queue"))

    response = prepare(rig, clip)

    assert response.status_code == 422
    assert response.json() == {"error": "not_an_image"}


def test_a_resent_request_is_the_same_record_and_a_reused_key_conflicts(queue_rig) -> None:
    first = prepare(queue_rig, queue_rig.item, key="same-key-0123456789").json()
    again = prepare(queue_rig, queue_rig.item, key="same-key-0123456789").json()
    other = prepare(queue_rig, queue_rig.item, "fix_hands", key="same-key-0123456789")
    as_decision = queue_rig.decide(queue_rig.item, key="same-key-0123456789")

    assert again == first
    assert other.status_code == 409
    assert as_decision.status_code == 409
    assert len(queue_rig.outbox()["records"]) == 1


def test_the_pc_answer_is_shown_only_to_the_phone_that_asked(queue_rig) -> None:
    record_id = prepare(queue_rig, queue_rig.item).json()["record_id"]
    queue_rig.outbox()
    pending = queue_rig.phone.get(f"/api/actions/{record_id}").json()
    assert pending["state"] == "pending"
    assert pending["receipt"] is None

    assert queue_rig.acknowledge(record_id, receipt={"action_summary": summary()}).is_success, (
        "the summary travels in the acknowledgement receipt"
    )

    answered = queue_rig.phone.get(f"/api/actions/{record_id}").json()
    assert answered["state"] == "applied"
    assert answered["action"] == "fix_face"
    assert answered["step"] == "prepare"
    assert answered["receipt"]["action_summary"]["warnings"][0]["why"] == "<b>not</b> markup"
    other_phone = queue_rig.new_phone()
    queue_rig.pair(other_phone, code="Q2W3E4R5", scopes=("review", "queue"))
    assert other_phone.get(f"/api/actions/{record_id}").status_code == 404
    assert queue_rig.phone.get("/api/actions/not-a-uuid").status_code == 404


def test_a_confirm_carries_the_prepare_and_its_receipt_lists_the_jobs(queue_rig) -> None:
    prepared = prepare(queue_rig, queue_rig.item).json()["record_id"]
    queue_rig.outbox()
    queue_rig.acknowledge(prepared, receipt={"action_summary": summary()})

    confirmed = confirm(queue_rig, queue_rig.item, prepared).json()["record_id"]
    record = next(r for r in queue_rig.outbox()["records"] if r["record_id"] == confirmed)
    assert record["action_request"]["params"] == {
        "step": "confirm",
        "prepared_record": prepared,
        "summary_revision": REVISION,
    }
    queue_rig.acknowledge(confirmed, receipt={"job_ids": ["a" * 32], "action_summary": summary()})

    listed = queue_rig.phone.get(
        "/api/actions",
        params={"library_id": queue_rig.item["library_id"], "sha256": queue_rig.item["sha256"]},
    ).json()["actions"]
    assert [entry["record_id"] for entry in listed] == [confirmed, prepared]
    assert listed[0]["receipt"]["job_ids"] == ["a" * 32]


def test_a_refusal_reason_from_the_pc_is_shown(queue_rig) -> None:
    record_id = prepare(queue_rig, queue_rig.item).json()["record_id"]
    queue_rig.outbox()
    queue_rig.acknowledge(
        record_id,
        "refused",
        reason_code="action_unavailable",
        receipt={"detail": "detector_unavailable"},
    )

    answered = queue_rig.phone.get(f"/api/actions/{record_id}").json()
    assert answered["state"] == "refused"
    assert answered["reason_code"] == "action_unavailable"
    assert answered["receipt"] == {"detail": "detector_unavailable"}


def test_a_malformed_summary_from_the_pc_is_refused(queue_rig) -> None:
    record_id = prepare(queue_rig, queue_rig.item).json()["record_id"]
    queue_rig.outbox()

    bad = queue_rig.acknowledge(
        record_id, receipt={"action_summary": summary(queue_position="first")}
    )

    assert bad.status_code == 422


def test_there_is_no_daily_quota_only_a_bound_on_unanswered_requests(
    queue_rig, monkeypatch
) -> None:
    """Owner decision 2026-11-26: no quota on phone work. Only a runaway-retry bound on unanswered requests."""

    from review_gateway import store

    assert store.MAX_PENDING_ACTIONS >= 1000  # far above a person's use
    monkeypatch.setattr(store, "MAX_PENDING_ACTIONS", 3)
    for _ in range(3):
        assert prepare(queue_rig, queue_rig.item).status_code == 200
    refused = prepare(queue_rig, queue_rig.item)
    assert refused.status_code == 429
    assert refused.json() == {"error": "too_many_pending"}

    for record in queue_rig.outbox()["records"]:
        queue_rig.acknowledge(record["record_id"], "refused", reason_code="action_unavailable")
    for _ in range(3):  # answered requests never count, however many there were today
        assert prepare(queue_rig, queue_rig.item).status_code == 200


def test_answering_an_action_never_touches_the_keep_or_its_upload(queue_rig) -> None:
    keep = queue_rig.decide(queue_rig.item, "keep", favorite=True).json()["record_id"]
    action = prepare(queue_rig, queue_rig.item).json()["record_id"]
    queue_rig.outbox()

    assert queue_rig.acknowledge(action, receipt={"action_summary": summary()}).is_success

    with queue_rig.gateway.store.connection() as db:
        owed = db.execute("SELECT record_id, state, favorite FROM immich_upload").fetchone()
    assert (owed["record_id"], owed["state"], owed["favorite"]) == (keep, "queued", 1)
    [item] = queue_rig.phone.get(f"/api/runs/{RUN}").json()["items"]
    assert item["state"] == "pending"
    assert item["decision"]["verdict"] == "keep"


def test_a_pending_action_keeps_the_cached_media(queue_rig) -> None:
    record = queue_rig.decide(queue_rig.item, "delete").json()["record_id"]
    queue_rig.outbox()
    queue_rig.acknowledge(record)
    prepare(queue_rig, queue_rig.item)
    queue_rig.clock.advance(days=3)

    assert queue_rig.gateway.store.retention()["items_purged"] == 0


def test_a_revoked_phone_cannot_request_an_action(queue_rig) -> None:
    queue_rig.gateway.store.revoke_device(queue_rig.device)

    assert prepare(queue_rig, queue_rig.item).status_code == 401


def test_an_outbox_from_before_rg140_is_migrated(tmp_path, clock) -> None:
    """A deployed RG-130 database has no kind column; opening it adds one and keeps its decisions."""

    from tests.review_gateway_service.conftest import Rig

    data = tmp_path / "data"
    data.mkdir()
    database = data / "gateway.sqlite3"
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL, device_id TEXT NOT NULL,
                library_id TEXT NOT NULL, sha256 TEXT NOT NULL, record TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending','applied','refused','duplicate','superseded')),
                delivered_at TEXT, answered_at TEXT, acknowledgement TEXT,
                UNIQUE (device_id, idempotency_key)
            );
            INSERT INTO outbox (record_id, idempotency_key, device_id, library_id, sha256, record, status)
            VALUES ('11111111-1111-4111-8111-111111111111', 'old-key-0123456789', 'device-old',
                    'lib-old_____', 'aa', '{"kind": "decision"}', 'applied');
            CREATE TABLE device (
                device_id TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, offer_id TEXT NOT NULL,
                label TEXT, scopes TEXT NOT NULL, enrolled_at TEXT NOT NULL, seen_at TEXT, revoked_at TEXT
            );
            INSERT INTO device VALUES ('owner-phone-1', 'h1', 'o1', 'Pixel', '["review"]',
                                       '2026-11-26T09:00:00Z', NULL, NULL);
            """
        )

    rig = Rig(tmp_path, clock)
    try:
        assert rig.gateway.store.database == database
        with rig.gateway.store.connection() as db:
            row = db.execute("SELECT kind FROM outbox").fetchone()
            scopes = db.execute("SELECT scopes FROM device").fetchone()["scopes"]
        assert row["kind"] == "decision"
        # Owner decision 2026-11-26 (Q4): a phone paired before RG-140 can queue without pairing again.
        assert scopes == '["review", "queue"]'
        with (
            rig.gateway.store.write() as db
        ):  # a later review-only choice is not undone by reopening
            db.execute("UPDATE device SET scopes = '[\"review\"]'")
        from review_gateway.store import Store

        Store(database, rig.gateway.store.media, rig.gateway.contract)  # opened again
        with rig.gateway.store.connection() as db:
            assert db.execute("SELECT scopes FROM device").fetchone()["scopes"] == '["review"]'
    finally:
        rig.close()
