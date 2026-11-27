"""LAUNCH-UPDATE-2 on the gateway: the ``pc_status`` publish, the ``admin`` grant and the ``admin_request`` record.

The gateway only shows the PC's status to admin phones and records their update requests; the PC decides (RG-100
invariants 2 and 4). The sync route is on the sync listener only (S2, covered by ``test_sync_api``'s route list).
"""

from __future__ import annotations

import uuid

import pytest

from tests.review_gateway_service.conftest import SCHEMA_VERSION

HEAD = "a" * 40
MAIN = "b" * 40
OTHER = "c" * 40


def status(rig, **changes) -> dict:
    body = {
        "schema_version": SCHEMA_VERSION,
        "type": "pc_status",
        "published_at": rig.clock.stamp(),
        "checkout": {
            "head_sha": HEAD,
            "origin_main_sha": MAIN,
            "commits_behind": 3,
            "fetched_at": rig.clock.stamp(),
        },
        "queue": {"state": "running", "queued": 2},
        "remote_update_enabled": True,
        "update": {"state": "idle"},
    }
    body.update(changes)
    return body


def request(rig, sha: str = MAIN, *, key: str | None = None, phone=None, **extra):
    return (phone or rig.phone).post(
        "/api/admin/updates",
        json={
            "action": "update_and_restart",
            "expected_sha": sha,
            "idempotency_key": key or uuid.uuid4().hex,
            **extra,
        },
    )


@pytest.fixture
def admin_rig(rig):
    rig.device = rig.pair(scopes=("review", "queue", "admin"))
    assert rig.sync.put("/sync/v1/pc-status", json=status(rig)).status_code == 200
    return rig


def test_the_status_is_validated_and_kept(rig) -> None:
    for bad in (
        {"checkout": {"head_sha": "main"}},
        {"checkout": {"head_sha": HEAD, "message": "Merge pull request"}},
        {"queue": {"state": "running", "queued": 2, "job": "C:/out/x.png"}},
        {"path": "C:/StableNew-main"},
        {"schema_version": "stablenew.review-gateway-sync.v2"},
    ):
        assert rig.sync.put("/sync/v1/pc-status", json=status(rig, **bad)).status_code == 422

    assert rig.sync.put("/sync/v1/pc-status", json=status(rig)).status_code == 200
    newer = status(rig, queue={"state": "idle", "queued": 0})
    assert rig.sync.put("/sync/v1/pc-status", json=newer).status_code == 200
    rig.pair(scopes=("review", "queue", "admin"))
    assert rig.phone.get("/api/admin").json()["pc_status"] == newer


@pytest.mark.parametrize("scopes", [("review",), ("review", "queue")])
def test_a_phone_without_the_admin_grant_sees_and_sends_nothing(rig, scopes) -> None:
    rig.pair(scopes=scopes)
    rig.sync.put("/sync/v1/pc-status", json=status(rig))

    assert rig.phone.get("/api/admin").status_code == 403
    assert request(rig).status_code == 403
    assert rig.phone.get(f"/api/admin/updates/{uuid.uuid4()}").status_code == 403
    assert rig.outbox()["records"] == []
    assert "admin" not in rig.phone.get("/api/session").json()["scopes"]


def test_an_unpaired_caller_is_refused(rig) -> None:
    assert rig.phone.get("/api/admin").status_code == 401
    assert request(rig).status_code == 401


def test_an_admin_request_reaches_the_pc_without_a_target(admin_rig) -> None:
    rig = admin_rig
    assert rig.phone.get("/api/session").json()["scopes"] == ["review", "queue", "admin"]

    sent = request(rig)

    assert sent.status_code == 200 and sent.json()["state"] == "pending"
    (record,) = rig.outbox()["records"]
    assert record["kind"] == "admin_request" and "target" not in record
    assert record["admin_request"] == {"action": "update_and_restart", "expected_sha": MAIN}
    assert record["device_id"] == rig.device
    rig.gateway.contract.validate("outbox_record", record)


@pytest.mark.parametrize(
    "body",
    [
        {"expected_sha": MAIN.upper()},
        {"expected_sha": MAIN[:12]},
        {"expected_sha": "origin/main"},
        {"expected_sha": f"--upload-pack={MAIN}"},
        {"expected_sha": 12345},
        {"action": "deploy"},
    ],
)
def test_a_malformed_request_is_refused(admin_rig, body) -> None:
    rig = admin_rig
    payload = {
        "action": "update_and_restart",
        "expected_sha": MAIN,
        "idempotency_key": uuid.uuid4().hex,
        **body,
    }

    assert rig.phone.post("/api/admin/updates", json=payload).status_code == 422
    assert rig.outbox()["records"] == []


def test_extra_fields_are_refused(admin_rig) -> None:
    assert request(admin_rig, ref="main").status_code == 422
    assert request(admin_rig, library_id="lib-00000001").status_code == 422


def test_a_commit_other_than_the_reported_main_is_refused_early(admin_rig, rig) -> None:
    response = request(admin_rig, OTHER)

    assert (response.status_code, response.json()["error"]) == (409, "status_changed")
    assert admin_rig.outbox()["records"] == []


def test_without_any_status_nothing_can_be_requested(rig) -> None:
    rig.pair(scopes=("review", "queue", "admin"))

    assert rig.phone.get("/api/admin").json()["pc_status"] is None
    assert request(rig).status_code == 409


def test_one_request_at_a_time_and_an_unseen_one_is_replaced(admin_rig) -> None:
    rig = admin_rig
    first = request(rig).json()["record_id"]
    second = request(rig).json()["record_id"]

    page = rig.outbox()["records"]
    assert [record["record_id"] for record in page] == [second]  # the unseen first one was replaced
    views = {
        view["record_id"]: view["state"] for view in rig.phone.get("/api/admin").json()["requests"]
    }
    assert views == {first: "superseded", second: "pending"}

    third = request(rig)  # the PC now has the second one
    assert (third.status_code, third.json()["error"]) == (409, "update_pending")


def test_a_resent_request_is_the_same_record(admin_rig) -> None:
    rig = admin_rig
    key = uuid.uuid4().hex
    first = request(rig, key=key).json()
    rig.outbox()

    assert request(rig, key=key).json() == first
    rig.sync.put(
        "/sync/v1/pc-status",
        json=status(rig, checkout={"head_sha": HEAD, "origin_main_sha": OTHER}),
    )
    assert request(rig, OTHER, key=key).status_code == 409  # same key, different body


def test_the_pc_answer_is_shown_with_the_health(admin_rig) -> None:
    rig = admin_rig
    record_id = request(rig).json()["record_id"]
    rig.outbox()
    receipt = {
        "update": {
            "status": "applied",
            "source": "remote",
            "old_sha": HEAD,
            "new_sha": MAIN,
            "health": "unconfirmed",
            "finished_at": rig.clock.stamp(),
        }
    }

    assert rig.acknowledge(record_id, receipt=receipt).status_code == 200

    view = rig.phone.get(f"/api/admin/updates/{record_id}").json()
    assert view["state"] == "applied" and view["update"]["health"] == "unconfirmed"
    assert rig.outbox()["records"] == []


def test_a_refusal_is_shown_with_its_reason(admin_rig) -> None:
    rig = admin_rig
    record_id = request(rig).json()["record_id"]
    rig.outbox()
    update = {"status": "refused", "reason_code": "target_moved", "target_sha": OTHER}

    response = rig.acknowledge(
        record_id, "refused", reason_code="target_moved", receipt={"update": update}
    )

    assert response.status_code == 200
    (view,) = rig.phone.get("/api/admin").json()["requests"]
    assert (view["state"], view["reason_code"], view["update"]) == (
        "refused",
        "target_moved",
        update,
    )


def test_an_acknowledgement_with_text_in_the_receipt_is_refused(admin_rig) -> None:
    rig = admin_rig
    record_id = request(rig).json()["record_id"]
    rig.outbox()
    receipt = {"update": {"status": "refused", "reason_code": "merge_failed", "detail": "C:/x"}}

    assert (
        rig.acknowledge(
            record_id, "refused", reason_code="merge_failed", receipt=receipt
        ).status_code
        == 422
    )


def test_a_revoked_admin_phone_is_refused(admin_rig) -> None:
    rig = admin_rig
    assert rig.sync.post(
        "/sync/v1/device-revocations",
        json={
            "schema_version": SCHEMA_VERSION,
            "type": "device_revocation",
            "device_id": rig.device,
            "revoked_at": rig.clock.stamp(),
        },
    ).is_success

    assert request(rig).status_code == 401
    assert rig.phone.get("/api/admin").status_code == 401


def test_another_phones_request_is_not_shown(admin_rig) -> None:
    rig = admin_rig
    record_id = request(rig).json()["record_id"]
    other = rig.new_phone()
    rig.pair(other, code="M3PX7QDA", scopes=("review", "queue", "admin"))

    assert other.get(f"/api/admin/updates/{record_id}").status_code == 404
    assert other.get("/api/admin").json()["requests"] == []


def test_admin_requests_leave_decisions_and_retention_alone(admin_rig) -> None:
    rig = admin_rig
    item = rig.publish()
    record_id = request(rig).json()["record_id"]
    rig.outbox()
    rig.acknowledge(
        record_id,
        "refused",
        reason_code="remote_update_disabled",
        receipt={"update": {"status": "refused", "reason_code": "remote_update_disabled"}},
    )

    (run,) = rig.phone.get("/api/runs").json()["runs"]
    assert run["undecided"] == 1 and run["pending"] == 0
    assert rig.gateway.store.retention() == {"items_purged": 0, "files_removed": 0}
    assert rig.decide(item).status_code == 200
