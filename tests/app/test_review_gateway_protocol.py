"""RG-120: the PC's closed-list codec for the review gateway sync contract."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime

import pytest

from src.app import review_gateway_protocol as protocol
from src.app.review_gateway_protocol import (
    ItemRef,
    MediaVariant,
    ProtocolError,
    acknowledgement,
    code_hash,
    device_revocation,
    item_manifest,
    new_pairing_offer,
    parse_immich_receipt,
    parse_json,
    parse_outbox_page,
    parse_record,
)
from tests.helpers.review_gateway_fakes import SCHEMA, SchemaViolation, validate, validate_def

DIGEST = "a" * 64
RECORD = {
    "record_id": "0b9f1f8e-6c55-4d2a-9a43-2f0d6e8e1c11",
    "idempotency_key": "k" * 20,
    "device_id": "phone-device-01",
    "created_at": "2026-11-25T21:31:00Z",
    "target": {"library_id": "b" * 32, "sha256": DIGEST},
    "kind": "decision",
    "decision": {"verdict": "keep", "favorite": True, "tags": ["face", "needs_fix"]},
}


def _forged(**changes):
    record = copy.deepcopy(RECORD)
    for dotted, value in changes.items():
        cursor = record
        *parents, last = dotted.split("__")
        for part in parents:
            cursor = cursor[part]
        if value is KeyError:
            cursor.pop(last)
        else:
            cursor[last] = value
    return record


def test_a_well_formed_decision_parses_and_matches_the_schema():
    validate_def(RECORD, "outbox_record")
    record = parse_record(RECORD)
    assert record.target == ItemRef("b" * 32, DIGEST)
    assert record.decision is not None and record.decision.favorite is True
    assert record.decision.tags == ("face", "needs_fix")


@pytest.mark.parametrize(
    "changes",
    [
        {"path": "C:/Users/rob/output/x.png"},  # a path field is never accepted
        {"target__path": "../../x.png"},
        {"target__library_id": "../../etc/passwd"},
        {"target__library_id": "C:\\output\\x.png"},
        {"target__sha256": "A" * 64},
        {"target__sha256": "a" * 63},
        {"kind": "delete_file"},
        {"kind": "action_request"},  # kind without its body
        {"decision__verdict": "purge"},
        {"decision__favorite": 1},
        {"decision__tags": ["face", "face"]},
        {"decision__tags": ["shell"]},
        {"decision__extra": True},
        {"action_request": {"action": "fix_face"}},  # both bodies
        {"record_id": "not-a-uuid"},
        {"created_at": "2026-11-25T21:31:00"},  # no offset
        {"device_id": "x"},
        {"idempotency_key": "short"},
        {"decision": KeyError},
    ],
)
def test_forged_records_are_refused(changes):
    forged = _forged(**changes)
    with pytest.raises(ProtocolError, match="invalid_record"):
        parse_record(forged)


def test_unknown_action_is_refused_and_known_action_parses():
    request = {**_forged(kind="action_request", decision=KeyError)}
    request["action_request"] = {"action": "rm_rf", "params": {"step": "prepare"}}
    with pytest.raises(ProtocolError):
        parse_record(request)
    request["action_request"] = {"action": "fix_face", "params": {"step": "prepare"}}
    assert parse_record(request).action_request == protocol.ActionRequest("fix_face", "prepare")


PREPARED = "7d0e4b3e-2f0a-4c55-9a62-0b8a7f1c2d3e"


@pytest.mark.parametrize(
    "action_request",
    [
        {"action": "fix_face"},  # params are required (RG-140)
        {"action": "fix_face", "params": {}},
        {"action": "fix_face", "params": {"step": "prepare", "strength": 1}},
        {"action": "fix_face", "params": {"step": "run"}},
        {"action": "fix_face", "params": {"step": "prepare", "count": 2}},
        {"action": "more_like_this", "params": {"step": "prepare", "count": 0}},
        {"action": "more_like_this", "params": {"step": "prepare", "count": 9}},
        {"action": "fix_face", "params": {"step": "confirm", "prepared_record": PREPARED}},
        {"action": "fix_face", "params": {"step": "prepare", "prepared_record": PREPARED}},
        {
            "action": "more_like_this",
            "params": {
                "step": "confirm",
                "count": 2,
                "prepared_record": PREPARED,
                "summary_revision": DIGEST,
            },
        },
        {
            "action": "fix_face",
            "params": {"step": "confirm", "prepared_record": "x", "summary_revision": DIGEST},
        },
    ],
)
def test_action_params_are_typed_per_step(action_request):
    request = {
        **_forged(kind="action_request", decision=KeyError),
        "action_request": action_request,
    }
    with pytest.raises(ProtocolError):
        parse_record(request)
    with pytest.raises(SchemaViolation):
        validate_def(request, "outbox_record")


def test_a_boolean_is_not_a_seed_count():
    request = {
        **_forged(kind="action_request", decision=KeyError),
        "action_request": {"action": "more_like_this", "params": {"step": "prepare", "count": True}},
    }
    with pytest.raises(ProtocolError):
        parse_record(request)


def test_typed_action_params_parse():
    base = _forged(kind="action_request", decision=KeyError)
    more = {
        **base,
        "action_request": {"action": "more_like_this", "params": {"step": "prepare", "count": 3}},
    }
    validate_def(more, "outbox_record")
    assert parse_record(more).action_request.count == 3
    confirm = {
        **base,
        "action_request": {
            "action": "fix_both",
            "params": {"step": "confirm", "prepared_record": PREPARED, "summary_revision": DIGEST},
        },
    }
    validate_def(confirm, "outbox_record")
    parsed = parse_record(confirm).action_request
    assert (parsed.step, parsed.prepared_record, parsed.summary_revision) == (
        "confirm",
        PREPARED,
        DIGEST,
    )


def test_an_action_summary_carries_no_path_and_matches_the_schema():
    warning = protocol.SummaryWarning(
        "image_model_unqualified",
        "C:\\Users\\rob\\Forge\\models\\Stable-diffusion\\flux1-dev.safetensors",
        "flux1-dev.safetensors is not qualified.",
        "It needs a VAE.",
        "A VAE goes in C:\\Users\\rob\\Forge\\models\\VAE. Or /home/rob/forge/models/VAE/ae.safetensors works.",
    )
    summary = protocol.ActionSummary(
        "fix_face",
        DIGEST,
        "Fix face",
        ("Checkpoint \\\\nas\\share\\juggernaut.safetensors.", "txt2img/img2img and/or upscale"),
        1,
        "next",
        (warning,),
        datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
    )
    body = summary.payload()
    validate_def(body, "action_summary")
    text = json.dumps(body)
    for private in ("Users", "rob", "nas", "home", "Forge"):
        assert private not in text, private
    assert body["warnings"][0]["subject"] == "flux1-dev.safetensors"
    assert body["warnings"][0]["fix"] == "A VAE goes in VAE. Or ae.safetensors works."
    assert body["lines"] == [
        "Checkpoint juggernaut.safetensors.",
        "txt2img/img2img and/or upscale",
    ]
    ack = acknowledgement(
        RECORD["record_id"], "applied", receipt={"action_summary": body, "job_ids": ["a" * 32]}
    )
    validate_def(ack, "acknowledgement")
    with pytest.raises(ProtocolError):
        acknowledgement(
            RECORD["record_id"],
            "refused",
            reason_code="action_unavailable",
            receipt={"detail": "C:/x"},
        )


def test_duplicate_json_keys_and_oversized_bodies_are_refused():
    with pytest.raises(ProtocolError):
        parse_json(b'{"kind": "decision", "kind": "action_request"}')
    with pytest.raises(ProtocolError, match="response_too_large"):
        parse_json(b"[" + b"1," * 10 + b"1]", limit=8)


def test_outbox_envelope_is_strict_but_records_stay_raw():
    page = {
        "schema_version": protocol.SCHEMA_VERSION,
        "type": "outbox_page",
        "records": [RECORD, {"junk": True}],
        "next_cursor": None,
    }
    parsed = parse_outbox_page(page)
    assert len(parsed.records) == 2  # each record is judged (and refused) on its own
    with pytest.raises(ProtocolError):
        parse_outbox_page({**page, "extra": 1})
    with pytest.raises(ProtocolError):
        parse_outbox_page({**page, "schema_version": "stablenew.review-gateway-sync.v2"})
    with pytest.raises(ProtocolError):
        parse_outbox_page({**page, "records": [RECORD] * 501})


def test_pairing_offer_sends_only_the_salted_hash():
    offer = new_pairing_offer(label="Rob's phone", now=datetime(2026, 11, 25, 21, 0, tzinfo=UTC))
    payload = offer.payload()
    validate_def(payload, "pairing_offer")
    validate(payload)
    assert offer.code not in repr(payload)
    expected = hashlib.sha256((offer.salt + offer.code).encode("ascii")).hexdigest()
    assert payload["code_sha256"] == expected
    assert payload["scopes"] == ["review"] and payload["max_attempts"] == 5
    assert payload["expires_at"] == "2026-11-25T21:05:00.000Z"
    assert len(offer.code) == 8 and set(offer.code) <= set(protocol.PAIRING_ALPHABET)
    # The phone may type it lower-case and with the hyphen the desktop shows.
    typed = f"{offer.code[:4]}-{offer.code[4:]}".lower()
    assert code_hash(offer.salt, typed) == expected


def test_outgoing_payloads_validate_against_the_checked_in_schema():
    manifest = item_manifest(
        item=ItemRef("b" * 32, DIGEST),
        kind="image",
        run_id="20261125_213000_portraits",
        created_at=datetime(2026, 11, 25, 21, 30, tzinfo=UTC),
        media={
            "thumb_320": MediaVariant("c" * 64, 1200, "image/webp", 320, 240),
            "original": MediaVariant(DIGEST, 99_000, "image/png", 1024, 768),
        },
        display={"model": "sdxl", "prompt_excerpt": "p" * 600, "seed": 42, "job_id": None},
    )
    assert len(manifest["display"]["prompt_excerpt"]) == 512
    for payload, name in (
        (manifest, "item_manifest"),
        (
            acknowledgement(RECORD["record_id"], "applied", receipt={"archived": True}),
            "acknowledgement",
        ),
        (
            acknowledgement(RECORD["record_id"], "refused", reason_code="digest_mismatch"),
            "acknowledgement",
        ),
        (device_revocation("phone-device-01"), "device_revocation"),
    ):
        validate_def(payload, name)
        validate(payload)
    with pytest.raises(ProtocolError):
        acknowledgement(RECORD["record_id"], "refused")
    with pytest.raises(ProtocolError):
        acknowledgement(RECORD["record_id"], "applied", receipt={"path": "C:/x"})


def test_the_validator_itself_rejects_contract_violations():
    with pytest.raises(SchemaViolation):
        validate_def({**RECORD, "path": "x"}, "outbox_record")
    with pytest.raises(SchemaViolation):
        validate_def(_forged(kind="action_request"), "outbox_record")


def test_closed_lists_match_the_schema():
    defs = SCHEMA["$defs"]
    assert (
        set(defs["acknowledgement"]["properties"]["reason_code"]["enum"]) == protocol.REASON_CODES
    )
    assert set(defs["acknowledgement"]["properties"]["outcome"]["enum"]) == protocol.OUTCOMES
    assert set(defs["decision"]["properties"]["tags"]["items"]["enum"]) == protocol.TAGS
    assert set(defs["decision"]["properties"]["verdict"]["enum"]) == protocol.VERDICTS
    assert set(defs["action_name"]["enum"]) == protocol.ACTIONS
    assert protocol.SLICE_ONE_ACTIONS <= protocol.ACTIONS
    receipt = defs["acknowledgement"]["properties"]["receipt"]["properties"]
    assert set(receipt["detail"]["enum"]) == protocol.DETAILS
    positions = defs["action_summary"]["properties"]["queue_position"]["enum"]
    assert set(positions) == protocol.QUEUE_POSITIONS
    params = defs["action_request"]["properties"]["params"]["properties"]
    assert set(params["step"]["enum"]) == protocol.STEPS
    assert params["count"]["maximum"] == protocol.MAX_SEEDS
    assert set(defs["outbox_record"]["properties"]["kind"]["enum"]) == protocol.RECORD_KINDS
    assert (
        set(defs["media_variant"]["properties"]["content_type"]["enum"]) == protocol.CONTENT_TYPES
    )
    assert set(defs["pairing_offer"]["properties"]["scopes"]["items"]["enum"]) == protocol.SCOPES
    assert defs["schema_version"]["const"] == protocol.SCHEMA_VERSION
    for name, pattern in (
        ("sha256", protocol.SHA256),
        ("library_id", protocol.LIBRARY_ID),
        ("run_id", protocol.RUN_ID),
    ):
        assert defs[name]["pattern"] == f"^{pattern.pattern}$"
    assert (
        defs["outbox_record"]["properties"]["device_id"]["pattern"]
        == f"^{protocol.DEVICE_ID.pattern}$"
    )


def test_immich_receipts_are_parsed_strictly():
    receipt = {
        "schema_version": protocol.SCHEMA_VERSION,
        "type": "immich_receipt",
        "record_id": RECORD["record_id"],
        "item": {"library_id": "b" * 32, "sha256": DIGEST},
        "status": "uploaded",
        "immich_asset_id": "asset-1",
        "album": "20261125_213000_portraits",
        "favorite": True,
        "at": "2026-11-25T21:40:00Z",
    }
    validate_def(receipt, "immich_receipt")
    assert parse_immich_receipt(receipt).favorite is True
    with pytest.raises(ProtocolError):
        parse_immich_receipt({**receipt, "status": "deleted"})
