"""Hermetic fakes for the review gateway sync worker (RG-120): an in-memory gateway transport and a small
JSON Schema subset validator that checks every PC -> gateway payload against the checked-in contract.

The validator covers exactly the keywords ``docs/schemas/stablenew.review-gateway-sync.v1.json`` uses; it is a
dev-only stand-in until a pinned ``jsonschema`` exists (RG-110 adds one for the gateway).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import parse_qs, urlsplit

from src.app.review_gateway_client import Response

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "stablenew.review-gateway-sync.v1.json"
)
SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SECRET = "s" * 40


class SchemaViolation(AssertionError):
    pass


def _resolve(ref: str) -> dict[str, Any]:
    assert ref.startswith("#/$defs/"), ref
    return SCHEMA["$defs"][ref.removeprefix("#/$defs/")]


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: type(v) is int,
    "number": lambda v: type(v) in (int, float),
    "boolean": lambda v: type(v) is bool,
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _is_valid(value: Any, schema: Mapping[str, Any]) -> bool:
    try:
        validate(value, schema)
    except SchemaViolation:
        return False
    return True


def validate(value: Any, schema: Mapping[str, Any] | None = None, where: str = "$") -> None:
    schema = SCHEMA if schema is None else schema

    def fail(reason: str) -> None:
        raise SchemaViolation(f"{where}: {reason}")

    if "$ref" in schema:
        validate(value, _resolve(schema["$ref"]), where)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[name](value) for name in types):
            fail(f"type {types}")
    if "const" in schema and value != schema["const"]:
        fail("const")
    if "enum" in schema and value not in schema["enum"]:
        fail("enum")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            fail("minLength")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            fail("pattern")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            fail("maxLength")
        fmt = schema.get("format")
        if fmt == "uuid":
            try:
                uuid.UUID(value)
            except ValueError:
                fail("uuid")
        if fmt == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                fail("date-time")
            else:
                if parsed.tzinfo is None:
                    fail("date-time offset")
    if type(value) in (int, float):
        if "minimum" in schema and value < schema["minimum"]:
            fail("minimum")
        if "maximum" in schema and value > schema["maximum"]:
            fail("maximum")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            fail("maxItems")
        if "minItems" in schema and len(value) < schema["minItems"]:
            fail("minItems")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(
            value
        ):
            fail("uniqueItems")
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], f"{where}[{index}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                fail(f"required {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                fail(f"additional {sorted(extra)}")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            fail("maxProperties")
        for key, sub in properties.items():
            if key in value:
                validate(value[key], sub, f"{where}.{key}")
    if "oneOf" in schema:
        matches = sum(_is_valid(value, option) for option in schema["oneOf"])
        if matches != 1:
            fail(f"oneOf matched {matches}")
    for sub in schema.get("allOf", []):
        validate(value, sub, where)
    if "anyOf" in schema and not any(_is_valid(value, option) for option in schema["anyOf"]):
        fail("anyOf")
    if "if" in schema:
        branch = "then" if _is_valid(value, schema["if"]) else "else"
        if branch in schema:
            validate(value, schema[branch], where)
    if "not" in schema and _is_valid(value, schema["not"]):
        fail("not")


def validate_def(value: Any, name: str) -> None:
    validate(value, _resolve(f"#/$defs/{name}"), name)


class FakeGateway:
    """An in-memory gateway following RG-110's sync binding (shared session notes). Every JSON body the PC sends is
    validated against the schema."""

    def __init__(self, secret: str = SECRET) -> None:
        self.secret = secret
        #: What health lists; ``None`` is a gateway from before the list existed.
        self.features: list[str] | None = None
        self.media: dict[str, bytes] = {}
        self.manifests: dict[str, dict[str, Any]] = {}
        self.outbox: list[Any] = []
        self.enrolled: list[dict[str, Any]] = []
        self.acks: list[dict[str, Any]] = []
        self.offers: list[dict[str, Any]] = []
        self.revocations: list[dict[str, Any]] = []
        self.immich_page: dict[str, Any] | None = None
        self.immich_pages: dict[str, dict[str, Any]] = {}  # by the cursor asked for
        self.calls: list[tuple[str, str]] = []
        self.uploads: list[str] = []
        self.fail_next: int | None = None
        self.page_size = 500
        self.declared: set[str] = set()
        self.listed: set[Any] = set()
        self.refuse_offers = False
        self.statuses: list[dict[str, Any]] = []  # LAUNCH-UPDATE-2 pc_status payloads, in order
        self.offers_pc_status = True  # False: an older gateway without the route (404)
        self.withdrawn: list[str] = []  # PHONE-FAST library ids the PC asked to withdraw
        self.refuse_withdrawals = False
        self.catalogs: list[dict[str, Any]] = []  # RG-160 choice catalogs, in order
        self.offers_catalog = True

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: bytes | BinaryIO | None,
        timeout: float,
        limit: int,
    ) -> Response:
        assert timeout > 0 and limit > 0
        self.calls.append((method, path))
        if headers.get("Authorization") != f"Bearer {self.secret}":
            return Response(401, b"")
        if self.fail_next is not None:
            status, self.fail_next = self.fail_next, None
            return Response(status, b"")
        data = body if isinstance(body, bytes) or body is None else body.read()
        split = urlsplit(path)
        route, query = split.path, parse_qs(split.query)
        if route == "/sync/v1/health" and method == "GET":
            body_ok: dict[str, Any] = {
                "status": "ok",
                "schema_version": "stablenew.review-gateway-sync.v1",
            }
            if self.features is not None:
                body_ok["features"] = self.features
            return Response(200, json.dumps(body_ok).encode())
        if route.startswith("/sync/v1/media/"):
            digest = route.rsplit("/", 1)[1]
            assert method == "PUT" and data is not None
            assert headers["Content-Type"] == "application/octet-stream"
            assert headers["Content-Length"] == str(len(data))
            if digest not in self.declared:
                return Response(409, b'{"error":"unknown_media"}')
            if hashlib.sha256(data).hexdigest() != digest:
                return Response(422, b'{"error":"digest_mismatch"}')
            self.uploads.append(digest)
            existed = digest in self.media
            self.media[digest] = data
            return Response(200 if existed else 201, b"")
        if route == "/sync/v1/items" and method == "POST":
            manifest = json.loads(data or b"")
            validate_def(manifest, "item_manifest")
            validate(manifest)
            if manifest["item"]["sha256"] != manifest["media"]["original"]["sha256"]:
                return Response(422, b'{"error":"item_digest_mismatch"}')
            digests = {v["sha256"] for v in manifest["media"].values()}
            self.declared |= digests
            missing = sorted(d for d in digests if d not in self.media)
            self.manifests[manifest["item"]["library_id"]] = manifest
            status = "incomplete" if missing else "ready"
            return Response(200, json.dumps({"status": status, "missing": missing}).encode())
        if route == "/sync/v1/outbox" and method == "GET":
            start = int(query.get("cursor", ["0"])[0])
            size = min(int(query["limit"][0]), self.page_size)
            records = self.outbox[start : start + size]
            self.listed |= {r.get("record_id") for r in records if isinstance(r, dict)}
            page: dict[str, Any] = {
                "schema_version": "stablenew.review-gateway-sync.v1",
                "type": "outbox_page",
                "records": records,
                "next_cursor": str(start + size) if start + size < len(self.outbox) else None,
            }
            if self.enrolled:
                page["enrolled_devices"] = self.enrolled
            return Response(200, json.dumps(page).encode())
        if route == "/sync/v1/acknowledgements" and method == "POST":
            ack = json.loads(data or b"")
            validate_def(ack, "acknowledgement")
            validate(ack)
            if ack["record_id"] not in self.listed:
                return Response(404, b'{"error":"unknown_record"}')
            self.acks.append(ack)
            self.outbox = [
                r
                for r in self.outbox
                if not (isinstance(r, dict) and r.get("record_id") == ack["record_id"])
            ]
            return Response(200, b"")
        if route == "/sync/v1/pairing-offers" and method == "POST":
            offer = json.loads(data or b"")
            validate_def(offer, "pairing_offer")
            validate(offer)
            if self.refuse_offers:
                return Response(422, b'{"error":"offer_expired"}')
            self.offers.append(offer)
            return Response(200, b'{"status":"accepted"}')
        if route == "/sync/v1/device-revocations" and method == "POST":
            revocation = json.loads(data or b"")
            validate_def(revocation, "device_revocation")
            validate(revocation)
            self.revocations.append(revocation)
            self.enrolled = [d for d in self.enrolled if d["device_id"] != revocation["device_id"]]
            return Response(200, b'{"status":"revoked"}')
        if route == "/sync/v1/pc-status" and method == "PUT":
            if not self.offers_pc_status:
                return Response(404, b"")
            status = json.loads(data or b"")
            validate_def(status, "pc_status")
            validate(status)
            self.statuses.append(status)
            return Response(200, b'{"status":"stored"}')
        if route == "/sync/v1/choice-catalog" and method == "PUT":
            if not self.offers_catalog:
                return Response(404, b"")
            catalog = json.loads(data or b"")
            validate_def(catalog, "choice_catalog")
            self.catalogs.append(catalog)
            return Response(200, b'{"status":"stored"}')
        if route == "/sync/v1/withdrawals" and method == "POST":
            withdrawal = json.loads(data or b"")
            validate_def(withdrawal, "item_withdrawal")
            if self.refuse_withdrawals:
                return Response(422, b'{"error":"invalid_payload"}')
            self.withdrawn.extend(withdrawal["library_ids"])
            return Response(200, json.dumps({"withdrawn": len(withdrawal["library_ids"])}).encode())
        if route == "/sync/v1/immich-receipts" and method == "GET":
            page = self.immich_pages.get(query.get("cursor", [""])[0], self.immich_page)
            if page is None:
                return Response(404, b"")
            return Response(200, json.dumps(page).encode())
        return Response(404, b"")

    # -- phone-side helpers --------------------------------------------------------------------------------------

    def enroll(self, offer: Mapping[str, Any], device_id: str = "phone-device-01") -> str:
        self.enrolled.append(
            {
                "device_id": device_id,
                "offer_id": offer["offer_id"],
                "label": "Pixel",
                "enrolled_at": "2026-11-25T21:30:00Z",
            }
        )
        return device_id

    def action(
        self,
        library_id: str,
        sha256: str,
        action: str,
        *,
        device_id: str = "phone-device-01",
        record_id: str | None = None,
        key: str | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        """An RG-140 action request as the gateway records it (``params`` default to a prepare)."""

        record = {
            "record_id": record_id or str(uuid.uuid4()),
            "idempotency_key": key or uuid.uuid4().hex,
            "device_id": device_id,
            "created_at": "2026-11-25T21:31:00.000Z",
            "target": {"library_id": library_id, "sha256": sha256},
            "kind": "action_request",
            "action_request": {"action": action, "params": {"step": "prepare", **params}},
        }
        validate_def(record, "outbox_record")
        self.outbox.append(record)
        return record

    def update_request(
        self,
        expected_sha: str,
        *,
        device_id: str = "phone-device-01",
        record_id: str | None = None,
        key: str | None = None,
        created_at: str = "2026-11-25T21:31:00.000Z",
    ) -> dict[str, Any]:
        """A LAUNCH-UPDATE-2 ``admin_request`` as the gateway records it: no item target."""

        record = {
            "record_id": record_id or str(uuid.uuid4()),
            "idempotency_key": key or uuid.uuid4().hex,
            "device_id": device_id,
            "created_at": created_at,
            "kind": "admin_request",
            "admin_request": {"action": "update_and_restart", "expected_sha": expected_sha},
        }
        validate_def(record, "outbox_record")
        self.outbox.append(record)
        return record

    def decide(
        self,
        library_id: str,
        sha256: str,
        verdict: str,
        *,
        device_id: str = "phone-device-01",
        favorite: bool = False,
        tags: list[str] | None = None,
        record_id: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        decision: dict[str, Any] = {"verdict": verdict, "favorite": favorite}
        if tags:
            decision["tags"] = tags
        record = {
            "record_id": record_id or str(uuid.uuid4()),
            "idempotency_key": key or uuid.uuid4().hex,
            "device_id": device_id,
            "created_at": "2026-11-25T21:31:00.000Z",
            "target": {"library_id": library_id, "sha256": sha256},
            "kind": "decision",
            "decision": decision,
        }
        self.outbox.append(record)
        return record
