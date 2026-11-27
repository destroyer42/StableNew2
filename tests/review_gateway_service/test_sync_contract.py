"""The sync schema is the RG-110 / RG-120 contract: it must be valid, and every payload must be checked."""

from __future__ import annotations

import json
import uuid

import pytest
from jsonschema import Draft202012Validator
from review_gateway.contract import Contract, ContractError

from tests.review_gateway_service.conftest import SCHEMA_PATH, SCHEMA_VERSION

DIGEST = "a" * 64
ITEM = {"library_id": "lib-00000001", "sha256": DIGEST}
VARIANT = {"sha256": DIGEST, "bytes": 10, "content_type": "image/png"}
NOW = "2026-11-25T12:00:00Z"


def sample(kind: str) -> dict:
    record = {
        "record_id": str(uuid.uuid4()),
        "idempotency_key": "k" * 16,
        "device_id": "device-0001",
        "created_at": NOW,
        "target": ITEM,
        "kind": "decision",
        "decision": {"verdict": "keep", "favorite": True, "tags": ["face", "needs_fix"]},
    }
    payloads = {
        "item_manifest": {
            "item": ITEM,
            "kind": "video",
            "run_id": "20261125_101500_pack",
            "created_at": NOW,
            "duration_s": 5.5,
            "media": {"thumb_320": VARIANT, "original": VARIANT},
            "display": {"model": "m", "prompt_excerpt": "p", "seed": 1, "workflow": "w"},
        },
        "outbox_page": {
            "records": [record],
            "next_cursor": None,
            "enrolled_devices": [
                {"device_id": "device-0001", "offer_id": str(uuid.uuid4()), "enrolled_at": NOW}
            ],
        },
        "acknowledgement": {
            "record_id": record["record_id"],
            "outcome": "refused",
            "reason_code": "digest_mismatch",
            "acknowledged_at": NOW,
        },
        "immich_receipt": {
            "record_id": record["record_id"],
            "item": ITEM,
            "status": "uploaded",
            "at": NOW,
        },
        "device_revocation": {"device_id": "device-0001", "revoked_at": NOW},
        "pairing_offer": {
            "offer_id": str(uuid.uuid4()),
            "code_salt": "b" * 32,
            "code_sha256": DIGEST,
            "scopes": ["review"],
            "expires_at": NOW,
        },
        "deploy_request": {
            "request_id": str(uuid.uuid4()),
            "target_sha": "c" * 40,
            "requested_at": NOW,
        },
        "deploy_status": {
            "remote_deploy": "enabled",
            "deployed_commit": "c" * 40,
            "pending": None,
            "last": {
                "action": "deploy",
                "request_id": None,
                "target": "c" * 40,
                "old_commit": None,
                "new_commit": "c" * 40,
                "outcome": "deployed",
                "schema_changed": False,
                "finished_at": NOW,
            },
        },
        "pc_status": {
            "published_at": NOW,
            "checkout": {
                "head_sha": "1" * 40,
                "origin_main_sha": "2" * 40,
                "commits_behind": 3,
                "fetched_at": NOW,
            },
            "queue": {"state": "running", "queued": 4},
            "remote_update_enabled": True,
            "update": {"state": "idle"},
            "last_result": {
                "status": "applied",
                "source": "remote",
                "old_sha": "0" * 40,
                "new_sha": "1" * 40,
                "health": "unconfirmed",
                "finished_at": NOW,
            },
        },
    }
    return {"schema_version": SCHEMA_VERSION, "type": kind, **payloads[kind]}


KINDS = (
    "item_manifest",
    "outbox_page",
    "acknowledgement",
    "immich_receipt",
    "device_revocation",
    "pairing_offer",
    "deploy_request",
    "deploy_status",
    "pc_status",
)


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract(SCHEMA_PATH)


def test_the_schema_is_a_valid_2020_12_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema["$defs"]["schema_version"]["const"] == SCHEMA_VERSION


def test_every_top_level_payload_in_the_schema_has_a_sample() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    # The RG-170 payloads have their samples and checks in test_rating.py and test_item_withdrawal.py.
    rating = ["rating_task", "rating_submission_page", "rating_acknowledgement", "item_withdrawal"]
    assert [entry["$ref"].rsplit("/", 1)[1] for entry in schema["oneOf"]] == [*KINDS, *rating]


@pytest.mark.parametrize("kind", KINDS)
def test_a_sample_of_every_payload_is_accepted(contract: Contract, kind: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    contract.validate(kind, sample(kind))
    Draft202012Validator(schema).validate(sample(kind))  # exactly one of the oneOf branches


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_fields_and_a_foreign_version_are_refused(contract: Contract, kind: str) -> None:
    for change in ({"path": "C:/x"}, {"schema_version": "stablenew.review-gateway-sync.v2"}):
        with pytest.raises(ContractError):
            contract.validate(kind, {**sample(kind), **change})


@pytest.mark.parametrize(
    ("kind", "change"),
    [
        ("pairing_offer", {"expires_at": "tomorrow"}),
        ("pairing_offer", {"expires_at": "2026-11-25T12:00:00"}),  # no time zone
        ("pairing_offer", {"offer_id": "not-a-uuid"}),
        ("device_revocation", {"device_id": "short"}),
        ("device_revocation", {"device_id": "device-0001\n"}),  # "$" alone would accept this
        ("item_manifest", {"item": {"library_id": "C:/x/y.png", "sha256": DIGEST}}),
        ("item_manifest", {"item": {"library_id": "lib-00000001", "sha256": DIGEST + "\n"}}),
        ("item_manifest", {"run_id": "../../etc"}),
        ("acknowledgement", {"outcome": "refused", "reason_code": "because"}),
        ("deploy_request", {"target_sha": "main"}),
        ("deploy_request", {"target_sha": "c" * 40 + "\n"}),
        ("deploy_status", {"remote_deploy": "maybe"}),
    ],
)
def test_malformed_values_are_refused(contract: Contract, kind: str, change: dict) -> None:
    with pytest.raises(ContractError):
        contract.validate(kind, {**sample(kind), **change})


def test_a_refused_acknowledgement_needs_a_reason(contract: Contract) -> None:
    payload = sample("acknowledgement")
    del payload["reason_code"]

    with pytest.raises(ContractError):
        contract.validate("acknowledgement", payload)


@pytest.mark.parametrize(
    "body", [b"not json", b"[1]", b'{"a": NaN}', b'"x"', b"\xff\xfe{}", b'{"a": "\\ud800"}']
)
def test_only_a_strict_json_object_parses(contract: Contract, body: bytes) -> None:
    with pytest.raises(ContractError):
        contract.parse(body)
