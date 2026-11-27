"""D5 / S1 / S11: single-use pairing codes, hashed device tokens, scopes and revocation."""

from __future__ import annotations

import sqlite3

import pytest
from review_gateway.contract import Contract
from review_gateway.errors import GatewayError

from tests.review_gateway_service.conftest import SCHEMA_PATH, SCHEMA_VERSION, sha


def database(rig) -> bytes:
    with sqlite3.connect(rig.settings.data_dir / "gateway.sqlite3") as connection:
        return "\n".join(connection.iterdump()).encode()


def offer(rig, **options) -> dict:
    payload = rig.offer(**options)
    assert rig.sync.post("/sync/v1/pairing-offers", json=payload).status_code == 200
    return payload


def enter(phone, code: str, **fields):
    return phone.post("/api/pair", json={"code": code, **fields})


def revocation(rig, device_id: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "device_revocation",
        "device_id": device_id,
        "revoked_at": rig.clock.stamp(),
    }


def test_pairing_sets_a_locked_down_cookie_and_enrolls_the_device(rig) -> None:
    sent = offer(rig)

    response = enter(rig.phone, "K7QF2M9D")

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=lax", "path=/", "max-age="):
        assert attribute in cookie
    assert rig.phone.get("/api/session").json()["device_id"] == response.json()["device_id"]
    page = rig.outbox()
    Contract(SCHEMA_PATH).validate("outbox_page", page)
    [device] = page["enrolled_devices"]
    assert device["device_id"] == response.json()["device_id"]
    assert device["offer_id"] == sent["offer_id"]
    assert device["label"] == "Pixel"


def test_the_code_is_accepted_however_the_owner_types_it(rig) -> None:
    offer(rig)

    assert enter(rig.phone, " k7qf-2m9d ").status_code == 200


def test_the_device_token_is_stored_only_as_a_hash(rig) -> None:
    offer(rig)
    enter(rig.phone, "K7QF2M9D")
    token = rig.phone.cookies["rg_session"]

    dump = database(rig)

    assert token.encode() not in dump
    assert sha(token.encode()).encode() in dump


def test_a_code_works_once(rig) -> None:
    offer(rig)
    assert enter(rig.phone, "K7QF2M9D").status_code == 200

    second = enter(rig.new_phone(), "K7QF2M9D")

    assert second.status_code == 403
    assert second.json() == {"error": "invalid_code"}
    assert "set-cookie" not in second.headers


def test_a_code_expires_after_five_minutes_even_if_the_offer_asks_for_longer(rig) -> None:
    offer(rig, expires_in=3600)
    rig.clock.advance(minutes=5, seconds=1)

    assert enter(rig.phone, "K7QF2M9D").status_code == 403


def test_an_already_expired_offer_is_refused(rig) -> None:
    response = rig.sync.post("/sync/v1/pairing-offers", json=rig.offer(expires_in=-1))

    assert response.status_code == 422
    assert response.json() == {"error": "offer_expired"}


def test_wrong_codes_use_up_the_offer(rig) -> None:
    offer(rig, max_attempts=3)
    for _ in range(3):
        assert enter(rig.phone, "WRONG234").status_code == 403

    assert enter(rig.phone, "K7QF2M9D").status_code == 403


def test_an_offer_without_a_cap_allows_five_attempts(rig) -> None:
    offer(rig)
    for _ in range(4):
        enter(rig.phone, "WRONG234")
    assert enter(rig.phone, "K7QF2M9D").status_code == 200

    offer(rig, code="SECOND22")
    for _ in range(5):
        enter(rig.new_phone(), "WRONG234")
    assert enter(rig.new_phone(), "SECOND22").status_code == 403


def test_guessing_is_rate_limited_across_offers(rig) -> None:
    phone = rig.new_phone()
    statuses = [enter(phone, "WRONG234").status_code for _ in range(21)]

    assert statuses[:20] == [403] * 20
    assert statuses[20] == 429
    rig.clock.advance(minutes=10, seconds=1)
    assert enter(phone, "WRONG234").status_code == 403


def test_reposting_an_offer_is_harmless_but_changing_it_is_a_conflict(rig) -> None:
    sent = offer(rig, max_attempts=1)
    enter(rig.phone, "WRONG234")

    assert rig.sync.post("/sync/v1/pairing-offers", json=sent).status_code == 200
    assert enter(rig.phone, "K7QF2M9D").status_code == 403  # re-posting did not reset attempts
    changed = rig.sync.post("/sync/v1/pairing-offers", json={**sent, "code_salt": "c" * 32})
    assert changed.status_code == 409
    assert changed.json() == {"error": "offer_conflict"}


@pytest.mark.parametrize("body", [{}, {"code": ""}, {"code": 12345678}, {"code": "x" * 200}])
def test_a_malformed_pairing_request_is_refused(rig, body) -> None:
    assert rig.phone.post("/api/pair", json=body).status_code == 400


def test_a_revocation_from_the_desktop_refuses_the_next_request(rig) -> None:
    item = rig.publish()
    device_id = rig.pair()
    assert rig.phone.get("/api/runs").status_code == 200

    response = rig.sync.post("/sync/v1/device-revocations", json=revocation(rig, device_id))

    assert response.json() == {"status": "revoked"}
    assert rig.phone.get("/api/runs").status_code == 401
    assert rig.decide(item).status_code == 401
    assert rig.phone.get(f"/media/{item['library_id']}/{item['sha256']}/thumb").status_code == 401
    assert rig.outbox()["enrolled_devices"] == []


def test_a_local_revocation_refuses_the_next_request(rig) -> None:
    """S11: the gateway can revoke while the PC is off."""

    device_id = rig.pair()

    assert rig.gateway.store.revoke_device(device_id) is True

    assert rig.phone.get("/api/session").status_code == 401


def test_revoking_an_unknown_device_is_reported(rig) -> None:
    response = rig.sync.post("/sync/v1/device-revocations", json=revocation(rig, "nobody-here"))

    assert response.json() == {"status": "unknown_device"}


def test_every_phone_data_route_needs_an_enrolled_session(rig) -> None:
    item = rig.publish()
    media = f"/media/{item['library_id']}/{item['sha256']}"
    for method, path in (
        ("GET", "/api/session"),
        ("GET", "/api/runs"),
        ("GET", "/api/runs/20261125_101500_pack"),
        ("POST", "/api/decisions"),
        ("POST", "/api/actions"),
        ("GET", f"{media}/thumb"),
        ("GET", f"{media}/preview"),
        ("GET", f"{media}/original"),
    ):
        assert rig.phone.request(method, path, json={}).status_code == 401, path
        forged = {"Cookie": "rg_session=forged-token"}
        assert rig.phone.request(method, path, json={}, headers=forged).status_code == 401, path


def test_a_device_without_the_review_scope_cannot_see_or_decide(rig) -> None:
    item = rig.publish()
    rig.pair(scopes=("queue",))

    assert rig.phone.get("/api/runs").status_code == 403
    assert rig.decide(item).status_code == 403
    assert rig.phone.get(f"/media/{item['library_id']}/{item['sha256']}/thumb").status_code == 403


def test_a_review_only_grant_cannot_create_an_action_request(rig) -> None:
    """D6: queueing is a separate grant (RG-140); the decision route never takes an action either."""

    item = rig.publish()
    rig.pair()
    request = {**item, "action": "fix_face", "idempotency_key": "k" * 20}

    for path in ("/api/actions", "/api/decisions"):
        response = rig.phone.post(path, json={**request, "kind": "action_request"})
        assert response.status_code == 403, path
        assert response.json() == {"error": "not_granted"}
    assert rig.outbox()["records"] == []


def test_a_decision_still_in_flight_when_the_device_is_revoked_is_not_recorded(rig) -> None:
    """The device is checked again inside the write, after the request body has arrived."""

    item = rig.publish()
    device_id = rig.pair()
    rig.gateway.store.revoke_device(device_id)

    with pytest.raises(GatewayError) as refused:
        rig.gateway.store.decide(
            device_id, item, {"verdict": "delete", "favorite": False, "tags": []}, "k" * 20
        )

    assert refused.value.status == 401
    assert rig.outbox()["records"] == []
