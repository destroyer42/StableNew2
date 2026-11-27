"""The PC-facing sync listener: secret, publish with digest verification, outbox and acknowledgements."""

from __future__ import annotations

import asyncio

import pytest
from review_gateway.contract import Contract

from tests.review_gateway_service.conftest import SCHEMA_PATH, SECRET, sha

SYNC_ROUTES = (
    ("GET", "/sync/v1/health"),
    ("POST", "/sync/v1/items"),
    ("HEAD", f"/sync/v1/media/{'a' * 64}"),
    ("PUT", f"/sync/v1/media/{'a' * 64}"),
    ("GET", "/sync/v1/outbox"),
    ("POST", "/sync/v1/acknowledgements"),
    ("POST", "/sync/v1/pairing-offers"),
    ("POST", "/sync/v1/device-revocations"),
    ("GET", "/sync/v1/immich-receipts"),
    ("POST", "/sync/v1/deploy-requests"),
    ("GET", "/sync/v1/deploy-status"),
    ("PUT", "/sync/v1/pc-status"),
    ("POST", "/sync/v1/rating-tasks"),
    ("HEAD", f"/sync/v1/rating-media/{'a' * 64}"),
    ("PUT", f"/sync/v1/rating-media/{'a' * 64}"),
    ("GET", "/sync/v1/rating-submissions"),
    ("POST", "/sync/v1/rating-acknowledgements"),
    ("POST", "/sync/v1/withdrawals"),
)


@pytest.mark.parametrize(("method", "path"), SYNC_ROUTES)
@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong-secret", f"Basic {SECRET}", SECRET, "Bearer "]
)
def test_every_sync_route_needs_the_sync_secret(rig, method, path, authorization) -> None:
    client = rig.client(rig.gateway.sync_app())
    headers = {"Authorization": authorization} if authorization else {}

    assert client.request(method, path, headers=headers).status_code == 401


@pytest.mark.parametrize(("method", "path"), SYNC_ROUTES)
def test_the_phone_app_refuses_every_sync_route(rig, method, path) -> None:
    """S2: even a caller holding the sync secret gets nothing from the phone listener."""

    rig.pair()
    rig.publish()
    response = rig.phone.request(method, path, headers=rig.auth(), json={})

    assert response.status_code == 404
    assert rig.outbox()["records"] == []


def test_the_test_covers_every_route_the_sync_app_serves(rig) -> None:
    served = {
        (method, route.path.replace("{digest}", "a" * 64))
        for route in rig.gateway.sync_app().routes
        for method in route.methods
        if not (method == "HEAD" and "GET" in route.methods)
    }

    assert served == set(SYNC_ROUTES)


def test_the_sync_app_serves_no_phone_route(rig) -> None:
    for path in ("/", "/api/runs", "/api/pair", "/static/app.js"):
        assert rig.sync.get(path).status_code == 404, path


def test_publishing_is_idempotent_and_reports_what_is_still_missing(rig) -> None:
    manifest, blobs = rig.manifest("one")

    first = rig.sync.post("/sync/v1/items", json=manifest).json()
    assert first["status"] == "incomplete"
    assert sorted(first["missing"]) == sorted(blobs)
    for digest, data in blobs.items():
        assert rig.sync.head(f"/sync/v1/media/{digest}").status_code == 404
        assert rig.sync.put(f"/sync/v1/media/{digest}", content=data).status_code == 201
        assert rig.sync.put(f"/sync/v1/media/{digest}", content=data).status_code == 200
        assert rig.sync.head(f"/sync/v1/media/{digest}").status_code == 200

    again = rig.sync.post("/sync/v1/items", json=manifest)
    assert again.json() == {"status": "ready", "missing": []}
    rig.pair()
    assert rig.phone.get("/api/runs").json()["runs"][0]["total"] == 1


def test_an_item_stays_hidden_until_all_its_media_arrived(rig) -> None:
    manifest, blobs = rig.manifest("one")
    rig.sync.post("/sync/v1/items", json=manifest)
    digests = list(blobs)
    for digest in digests[:-1]:
        rig.sync.put(f"/sync/v1/media/{digest}", content=blobs[digest])
    rig.pair()

    assert rig.phone.get("/api/runs").json()["runs"] == []
    rig.sync.put(f"/sync/v1/media/{digests[-1]}", content=blobs[digests[-1]])
    assert len(rig.phone.get("/api/runs").json()["runs"]) == 1


def test_a_body_that_does_not_hash_to_its_address_is_refused_and_not_kept(rig) -> None:
    manifest, blobs = rig.manifest("one")
    rig.sync.post("/sync/v1/items", json=manifest)
    digest, data = next(iter(blobs.items()))
    tampered = bytes([data[0] ^ 1]) + data[1:]

    response = rig.sync.put(f"/sync/v1/media/{digest}", content=tampered)

    assert response.status_code == 422
    assert response.json() == {"error": "digest_mismatch"}
    assert rig.sync.head(f"/sync/v1/media/{digest}").status_code == 404
    assert [p for p in rig.settings.media_dir.rglob("*") if p.is_file()] == []


@pytest.mark.parametrize("extra", [b"x", b""])
def test_a_body_of_the_wrong_size_is_refused(rig, extra) -> None:
    manifest, blobs = rig.manifest("one")
    rig.sync.post("/sync/v1/items", json=manifest)
    digest, data = next(iter(blobs.items()))
    body = data + extra if extra else data[:-1]

    response = rig.sync.put(f"/sync/v1/media/{digest}", content=body)

    assert response.status_code in (413, 422)
    assert rig.sync.head(f"/sync/v1/media/{digest}").status_code == 404
    assert [p for p in rig.settings.media_dir.rglob("*") if p.is_file()] == []


def test_media_no_manifest_declares_is_refused(rig) -> None:
    data = b"unannounced"

    response = rig.sync.put(f"/sync/v1/media/{sha(data)}", content=data)

    assert response.status_code == 409
    assert response.json() == {"error": "unknown_media"}


@pytest.mark.parametrize("name", ["..%2F..%2Fsecret", "A" * 64, "a" * 63, f"{'a' * 64}%0A"])
def test_a_media_address_is_only_ever_a_sha256(rig, name) -> None:
    assert rig.sync.put(f"/sync/v1/media/{name}", content=b"x").status_code == 404


def test_the_item_digest_must_be_the_original_the_phone_will_see(rig) -> None:
    manifest, _ = rig.manifest("one")
    manifest["item"]["sha256"] = "b" * 64

    response = rig.sync.post("/sync/v1/items", json=manifest)

    assert response.status_code == 422
    assert response.json() == {"error": "item_digest_mismatch"}


def test_a_manifest_that_breaks_the_schema_is_refused(rig) -> None:
    manifest, _ = rig.manifest("one")
    manifest["media"]["original"]["path"] = "C:/output/a.png"

    response = rig.sync.post("/sync/v1/items", json=manifest)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_payload"}


def test_an_oversized_json_body_is_refused(rig) -> None:
    response = rig.sync.post("/sync/v1/items", content=b"{" + b" " * 70_000 + b"}")

    assert response.status_code == 413


def test_the_outbox_lists_pending_records_in_order_with_a_cursor(rig) -> None:
    items = [rig.publish(f"item{index}") for index in range(5)]
    rig.pair()
    sent = [rig.decide(item).json()["record_id"] for item in items]
    contract = Contract(SCHEMA_PATH)

    first = rig.outbox("?limit=2")
    contract.validate("outbox_page", first)
    second = rig.outbox(f"?limit=2&cursor={first['next_cursor']}")
    third = rig.outbox(f"?limit=2&cursor={second['next_cursor']}")

    listed = [r["record_id"] for page in (first, second, third) for r in page["records"]]
    assert listed == sent
    assert third["next_cursor"] is None
    assert [r["record_id"] for r in rig.outbox()["records"]] == sent  # listed is not acknowledged


@pytest.mark.parametrize("query", ["?cursor=abc", "?limit=0", "?limit=501", "?limit=x"])
def test_a_bad_cursor_or_limit_is_refused(rig, query) -> None:
    assert rig.sync.get(f"/sync/v1/outbox{query}").status_code == 400


def test_an_acknowledged_record_leaves_the_outbox_and_the_first_outcome_stands(rig) -> None:
    item = rig.publish()
    rig.pair()
    record_id = rig.decide(item).json()["record_id"]
    rig.outbox()

    assert rig.acknowledge(record_id).json() == {"status": "recorded"}
    repeat = rig.acknowledge(record_id, "refused", reason_code="digest_mismatch")

    assert repeat.json() == {"status": "already_acknowledged"}
    assert rig.outbox()["records"] == []
    state = rig.phone.get("/api/runs/20261125_101500_pack").json()["items"][0]["state"]
    assert state == "applied"


def test_an_acknowledgement_for_a_record_the_gateway_never_had_is_refused(rig) -> None:
    response = rig.acknowledge("3f1c2f9e-6f0a-4a52-9f3a-0d3a1a2b3c4d")

    assert response.status_code == 404
    assert response.json() == {"error": "unknown_record"}


def test_health_names_the_contract_version_and_its_features(rig) -> None:
    # A PC sends the optional manifest "batch" only to a gateway that lists "item_batch": an older gateway's schema
    # would refuse the whole manifest.
    assert rig.sync.get("/sync/v1/health").json() == {
        "status": "ok",
        "schema_version": "stablenew.review-gateway-sync.v1",
        "features": ["item_batch", "item_withdraw", "rating_tasks"],
    }


def put_in_chunks(
    app, digest: str, chunks: list[bytes], headers: dict[str, str]
) -> tuple[int, int]:
    """Drive the ASGI app directly: ``(status, body chunks it had read when it started to answer)``."""

    pending = list(chunks)
    answered: list[tuple[int, int]] = []

    async def receive():
        body = pending.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(pending)}

    async def send(message):
        if message["type"] == "http.response.start":
            answered.append((message["status"], len(chunks) - len(pending)))

    scope = {
        "type": "http",
        "method": "PUT",
        "path": f"/sync/v1/media/{digest}",
        "raw_path": b"",
        "root_path": "",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(app(scope, receive, send))
    return answered[0]


@pytest.mark.parametrize(("case", "status"), [("stored", 200), ("unknown", 409), ("too_long", 413)])
def test_an_upload_is_read_to_the_end_before_it_is_answered(rig, case, status) -> None:
    """A client such as urllib only reads the answer after sending everything; answering early aborts it."""

    manifest, blobs = rig.manifest("one")
    rig.sync.post("/sync/v1/items", json=manifest)
    digest, data = next(iter(blobs.items()))
    if case == "stored":
        rig.sync.put(f"/sync/v1/media/{digest}", content=data)
    chunk = b"x" * (2 * 1024 * 1024) if case == "too_long" else data
    address = "0" * 64 if case == "unknown" else digest

    result = put_in_chunks(rig.gateway.sync_app(), address, [chunk] * 4, rig.auth())

    assert result == (status, 4)
