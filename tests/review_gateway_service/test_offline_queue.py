"""RG-160 on the gateway: requests that wait for the PC, the choice catalog that lets the phone make them, and cancel.

The gateway still decides nothing: it keeps the request, shows the PC's answer and records what the phone cancelled.
"""

from __future__ import annotations

import json
import uuid

import pytest

from .conftest import SCHEMA_VERSION
from .test_actions import RUN, confirm, prepare, summary


def queue(rig, item=None, action="fix_face", *, key=None, phone=None, **params):
    return (phone or rig.phone).post(
        "/api/actions",
        json={
            **(item or rig.item),
            "action": action,
            "params": {"step": "queue", **params},
            "idempotency_key": key or uuid.uuid4().hex,
        },
    )


def queued(rig, action="fix_face", **params) -> str:
    response = queue(rig, action=action, **params)
    assert response.status_code == 200, response.text
    return response.json()["record_id"]


def cancel(rig, record_id, phone=None):
    return (phone or rig.phone).post(f"/api/actions/{record_id}/cancel")


def pending_ids(rig) -> list[str]:
    return [record["record_id"] for record in rig.outbox()["records"]]


def record_of(rig, record_id) -> dict:
    return rig.phone.get(f"/api/actions/{record_id}").json()


def state_of_item(rig, item=None) -> str:
    return listed(rig)[(item or rig.item)["library_id"]]["state"]


def listed(rig) -> dict[str, dict]:
    items = rig.phone.get(f"/api/runs/{RUN}").json()["items"]
    return {item["library_id"]: item for item in items}


def requests(rig, phone=None) -> list[dict]:
    return (phone or rig.phone).get("/api/requests").json()["requests"]


def catalog(**changes) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "choice_catalog",
        "published_at": "2026-11-25T12:00:00Z",
        "models": [
            {"id": "0123456789abcdef", "label": "juggernautXL.safetensors", "warnings": [0]}
        ],
        "warnings": [{"code": "image_model_unqualified", "title": "Not qualified.", "why": "w"}],
        "ratios": [{"id": "1x1", "label": "Square 1:1"}],
        "video": {"available": True, "label": "Wan2.2 I2V"},
        "models_as_of": "2026-11-25T11:59:00Z",
        "image_backend_ready": True,
        "truncated": False,
        **changes,
    }


def send_catalog(rig, **changes):
    return rig.sync.put("/sync/v1/choice-catalog", json=catalog(**changes))


@pytest.fixture
def world(rig):
    rig.item = rig.publish()
    rig.device = rig.pair(scopes=("review", "queue"))
    return rig


# --- the choice catalog ---------------------------------------------------------------------------------------------


def test_health_offers_deferred_actions(world) -> None:
    assert "deferred_actions" in world.sync.get("/sync/v1/health").json()["features"]


def test_the_catalog_the_pc_sends_is_shown_to_a_queueing_phone(world, clock) -> None:
    assert world.phone.get("/api/catalog").json()["catalog"] is None
    assert send_catalog(world).status_code == 200

    body = world.phone.get("/api/catalog").json()

    assert body["catalog"]["models"][0]["label"] == "juggernautXL.safetensors"
    assert body["catalog"]["video"] == {"available": True, "label": "Wan2.2 I2V"}
    assert body["received_at"] == body["now"]


def test_a_review_only_phone_gets_no_catalog_or_requests(rig) -> None:
    send_catalog(rig)
    rig.pair()

    assert rig.phone.get("/api/catalog").status_code == 403
    assert rig.phone.get("/api/requests").status_code == 403


def test_the_catalog_needs_the_sync_secret(world) -> None:
    anonymous = world.client(world.gateway.sync_app())

    assert anonymous.put("/sync/v1/choice-catalog", json=catalog()).status_code == 401
    assert world.phone.put("/sync/v1/choice-catalog", json=catalog()).status_code in (403, 404, 405)


@pytest.mark.parametrize(
    "changes",
    [
        {"models": [{"id": "a1", "label": "C:\\models\\x.safetensors", "warnings": []}]},
        {"models": [{"id": "a1", "label": "sdxl/x.safetensors", "warnings": []}]},
        {"models": [{"id": "a1", "label": "x", "warnings": [], "path": "x"}]},
        {"models": [{"id": "a1", "label": "x" * 121, "warnings": []}]},
        {"models": [{"id": f"m{n}", "label": "x", "warnings": []} for n in range(201)]},
        {"warnings": [{"code": "c", "title": "in D:\\Forge"}]},
        {"warnings": [{"code": "c", "title": "t"} for _ in range(21)]},
        {"video": {"available": True, "label": "a/b"}},
        {"ratios": [{"id": "1x1", "label": "x"}] * 17},
        {"folder": "somewhere"},
    ],
)
def test_the_catalog_is_closed_bounded_and_takes_no_paths(world, changes) -> None:
    assert send_catalog(world, **changes).status_code == 422
    assert world.phone.get("/api/catalog").json()["catalog"] is None


def test_a_catalog_over_the_transport_limit_is_refused(world) -> None:
    huge = [{"code": "c", "title": "t", "why": "w" * 300, "fix": "f" * 300}] * 20
    models = [{"id": f"m{n}", "label": "x" * 120, "warnings": [0] * 8} for n in range(200)]
    payload = json.dumps(catalog(models=models, warnings=huge, ratios=[]))
    assert len(payload) < 64 * 1024  # the schema's own bounds stay inside the limit
    padded = payload + " " * (64 * 1024)

    assert world.sync.put("/sync/v1/choice-catalog", content=padded).status_code == 413


# --- is the PC there? -----------------------------------------------------------------------------------------------


def test_the_status_says_when_the_pc_last_asked_for_requests(world, clock) -> None:
    before = world.phone.get("/api/status").json()
    assert (before["pc_seen_at"], before["image_backend_ready"], before["waiting"]) == (
        None,
        None,
        0,
    )

    world.outbox()
    seen = world.phone.get("/api/status").json()
    clock.advance(minutes=10)
    later = world.phone.get("/api/status").json()

    assert seen["pc_seen_at"] == seen["now"]
    assert later["pc_seen_at"] == seen["pc_seen_at"] != later["now"]
    world.outbox()
    assert world.phone.get("/api/status").json()["pc_seen_at"] == later["now"]


def test_the_status_counts_this_phones_waiting_requests(world) -> None:
    send_catalog(world, image_backend_ready=False)
    queued(world)
    other = world.new_phone()
    world.pair(other, code="M4N8P2QR", scopes=("review", "queue"))

    mine = world.phone.get("/api/status").json()

    assert (mine["waiting"], mine["image_backend_ready"]) == (1, False)
    assert other.get("/api/status").json()["waiting"] == 0


# --- the deferred step ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action, params",
    [
        ("fix_face", {}),
        ("more_like_this", {"count": 4}),
        ("another_model", {"choice": "0123456789abcdef"}),
        ("aspect_ratio", {"choice": "1x1"}),
        ("prompt_tweak", {"text": "smiling"}),
        ("make_video", {}),
        ("make_video", {"text": "turns to the window"}),
    ],
)
def test_a_deferred_request_waits_in_the_outbox(world, action, params) -> None:
    record_id = queued(world, action, **params)

    [record] = world.outbox()["records"]
    assert record["record_id"] == record_id
    assert record["action_request"] == {"action": action, "params": {"step": "queue", **params}}


@pytest.mark.parametrize(
    "action, params",
    [
        ("another_model", {}),
        ("aspect_ratio", {}),
        ("prompt_tweak", {}),
        ("fix_face", {"choice": "x"}),
        ("fix_face", {"count": 2}),
        ("fix_face", {"summary_revision": "ab" * 32}),
        ("fix_face", {"prepared_record": str(uuid.uuid4())}),
        ("rerun_clip", {}),
    ],
)
def test_a_deferred_request_is_a_closed_list(world, action, params) -> None:
    assert queue(world, action=action, **params).status_code == 422


def test_a_deferred_request_needs_the_queue_grant(rig) -> None:
    item = rig.publish()
    rig.pair()

    assert queue(rig, item).status_code == 403


def test_a_deferred_request_never_expires_and_keeps_the_media(world, clock) -> None:
    record_id = queued(world, "make_video")
    clock.advance(days=400)
    world.gateway.store.retention()

    assert pending_ids(world) == [record_id]
    assert listed(world)[world.item["library_id"]]["variants"]


def test_resending_the_same_request_is_one_record(world) -> None:
    key = uuid.uuid4().hex
    first = queue(world, key=key).json()
    again = queue(world, key=key).json()

    assert first == again
    assert len(pending_ids(world)) == 1


# --- cancel ---------------------------------------------------------------------------------------------------------


def test_a_request_the_pc_never_saw_is_cancelled_outright(world) -> None:
    key = uuid.uuid4().hex
    record_id = queue(world, key=key).json()["record_id"]

    assert cancel(world, record_id).json() == {"record_id": record_id, "state": "cancelled"}

    assert pending_ids(world) == []
    shown = record_of(world, record_id)
    assert (shown["state"], shown["delivered"], shown["too_late"]) == ("cancelled", False, False)
    assert queue(world, key=key).json()["state"] == "cancelled"  # a resend does not revive it


def test_a_delivered_request_says_the_cancel_was_sent(world) -> None:
    record_id = queued(world)
    world.outbox()

    assert cancel(world, record_id).json()["state"] == "cancel_sent"

    assert pending_ids(world) == []
    assert record_of(world, record_id)["delivered"] is True


def test_an_answer_that_arrives_after_the_cancel_is_recorded(world) -> None:
    record_id = queued(world)
    world.outbox()
    cancel(world, record_id)

    answered = world.acknowledge(record_id, "applied", receipt={"job_ids": ["job-1"]})

    assert answered.json() == {"status": "recorded"}
    shown = record_of(world, record_id)
    assert (shown["state"], shown["too_late"]) == ("applied", True)
    assert shown["receipt"]["job_ids"] == ["job-1"]
    assert state_of_item(world) == "rework"


def test_a_refusal_that_arrives_after_the_cancel_changes_nothing(world) -> None:
    record_id = queued(world)
    world.outbox()
    cancel(world, record_id)

    world.acknowledge(record_id, "refused", reason_code="unknown_item")

    assert record_of(world, record_id)["state"] == "cancelled"


def test_a_delivered_confirm_cannot_be_cancelled(world) -> None:
    prepared = prepare(world, world.item).json()["record_id"]
    sent = confirm(world, world.item, prepared).json()["record_id"]
    world.outbox()

    assert cancel(world, sent).json()["state"] == "delivered"
    assert sent in pending_ids(world)


def test_a_confirm_the_pc_never_saw_can_be_cancelled(world) -> None:
    prepared = prepare(world, world.item).json()["record_id"]
    sent = confirm(world, world.item, prepared).json()["record_id"]

    assert cancel(world, sent).json()["state"] == "cancelled"


def test_a_left_behind_prepare_can_be_cancelled(world) -> None:
    prepared = prepare(world, world.item).json()["record_id"]

    assert cancel(world, prepared).json()["state"] == "cancelled"
    assert pending_ids(world) == []


def test_cancelling_an_answered_request_reports_its_answer(world) -> None:
    record_id = queued(world)
    world.outbox()
    world.acknowledge(record_id, "refused", reason_code="unknown_item")

    assert cancel(world, record_id).json()["state"] == "refused"


def test_only_the_phone_that_asked_can_cancel(world) -> None:
    record_id = queued(world)
    other = world.new_phone()
    world.pair(other, code="M4N8P2QR", scopes=("review", "queue"))

    assert cancel(world, record_id, phone=other).status_code == 404
    assert cancel(world, str(uuid.uuid4())).status_code == 404
    assert cancel(world, "not-a-record").status_code == 404
    assert pending_ids(world) == [record_id]


def test_cancel_needs_the_header_every_api_call_needs(world) -> None:
    record_id = queued(world)
    world.phone.headers.pop("X-Review-Gateway")

    assert cancel(world, record_id).status_code == 403


# --- the original image ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action, params, expected",
    [
        ("fix_hands", {}, "rework"),
        ("another_model", {"choice": "x1"}, "rework"),
        ("make_video", {}, "undecided"),
        ("more_like_this", {}, "undecided"),
    ],
)
def test_a_waiting_request_marks_the_image(world, action, params, expected) -> None:
    queued(world, action, **params)

    shown = listed(world)[world.item["library_id"]]

    assert shown["state"] == expected
    assert shown["waiting"] == [action]


def test_a_cancelled_fix_returns_the_image(world) -> None:
    record_id = queued(world)
    cancel(world, record_id)

    shown = listed(world)[world.item["library_id"]]
    assert (shown["state"], shown["waiting"]) == ("undecided", [])


def test_deleting_an_image_cancels_its_waiting_requests(world) -> None:
    fix = queued(world)
    clip = queued(world, "make_video")
    world.outbox()
    unseen = queued(world, "more_like_this")

    assert world.decide(world.item, "delete").status_code == 200

    assert [record["kind"] for record in world.outbox()["records"]] == ["decision"]
    assert [record_of(world, one)["state"] for one in (fix, clip, unseen)] == ["cancelled"] * 3
    assert record_of(world, fix)["delivered"] is True


def test_keeping_an_image_leaves_its_waiting_requests(world) -> None:
    record_id = queued(world, "make_video")
    world.decide(world.item, "keep")

    assert record_id in pending_ids(world)


def test_a_waiting_request_holds_off_the_undecided_purge(world, clock) -> None:
    queued(world, "make_video")
    clock.advance(days=60)

    assert world.gateway.store.retention()["items_purged"] == 0


# --- the waiting list -----------------------------------------------------------------------------------------------


def test_the_waiting_list_shows_this_phones_deferred_requests(world, clock) -> None:
    send_catalog(world, image_backend_ready=False)
    waiting = queued(world, "another_model", choice="0123456789abcdef")
    prepare(world, world.item)  # an online step is not part of the list
    done = queued(world, "make_video", text="waves")
    world.outbox()
    clock.advance(minutes=1)
    world.acknowledge(
        done, "applied", receipt={"job_ids": ["j1"], "action_summary": summary("make_video")}
    )

    body = world.phone.get("/api/requests").json()

    assert body["image_backend_ready"] is False
    assert body["pc_seen_at"] and body["now"] and body["catalog_at"]
    by_id = {entry["record_id"]: entry for entry in body["requests"]}
    assert set(by_id) == {waiting, done}
    assert by_id[waiting]["state"] == "pending"
    assert by_id[waiting]["choice"] == "0123456789abcdef"
    assert by_id[waiting]["delivered"] is True
    assert by_id[done]["text"] == "waves"
    assert by_id[done]["receipt"]["action_summary"]["warnings"]


def test_answered_requests_leave_the_list_after_seven_days_but_waiting_ones_stay(
    world, clock
) -> None:
    waiting = queued(world)
    done = queued(world, "make_video")
    dropped = queued(world, "more_like_this")
    cancel(world, dropped)
    world.outbox()
    world.acknowledge(done, "applied", receipt={"job_ids": ["j1"]})

    clock.advance(days=6)
    assert {entry["record_id"] for entry in requests(world)} == {waiting, done, dropped}
    clock.advance(days=2)
    assert [entry["record_id"] for entry in requests(world)] == [waiting]


def test_a_database_from_before_rg160_gains_the_cancel_column(world) -> None:
    store = world.gateway.store
    with store.write() as db:
        db.execute("ALTER TABLE outbox DROP COLUMN cancelled_at")
    type(store)(store.database, store.media, store.contract, store.clock)

    record_id = queued(world)
    assert cancel(world, record_id).json()["state"] == "cancelled"


def test_the_compare_view_says_what_is_waiting_for_the_original(world) -> None:
    # "Keep rework" deletes the original, so the phone must be able to warn about its waiting request.
    queued(world, "make_video")
    queued(world)
    manifest, blobs = world.manifest("result", run_id="20261125_120000_Reprocess")
    manifest["parent"] = world.item
    for digest in world.sync.post("/sync/v1/items", json=manifest).json()["missing"]:
        assert world.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest]).is_success

    result = listed(world)[manifest["item"]["library_id"]]

    assert result["compare"]["waiting"] == ["make_video", "fix_face"]
