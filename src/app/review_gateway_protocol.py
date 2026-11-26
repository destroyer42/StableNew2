"""Closed-list codec for the review gateway sync contract (RG-120, schema ``stablenew.review-gateway-sync.v1``).

Everything the gateway sends is untrusted. Each payload is checked field by field against the closed lists in
``docs/schemas/stablenew.review-gateway-sync.v1.json``: unknown keys, unknown kinds, unknown actions, wrong types and
anything path-shaped are refused. Items are named only by library id plus SHA-256 (RG-100 invariant 3).

Pure functions and frozen records; no I/O, no logging of payload text.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "stablenew.review-gateway-sync.v1"

SHA256 = re.compile(r"[0-9a-f]{64}")
LIBRARY_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
RUN_ID = re.compile(r"[0-9]{8}_[0-9]{6}_[A-Za-z0-9._ -]{1,96}")
DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{16,128}")
CODE_SALT = re.compile(r"[0-9a-f]{32}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

RECORD_KINDS = frozenset({"decision", "action_request"})
VERDICTS = frozenset({"keep", "delete"})
TAGS = frozenset({"face", "hands", "anatomy", "artifact", "prompt_miss", "needs_fix"})
ACTIONS = frozenset(
    {
        "fix_face",
        "fix_hands",
        "more_like_this",
        "another_model",
        "aspect_ratio",
        "prompt_tweak",
        "make_video",
        "rerun_clip",
        "continue_clip",
    }
)
SCOPES = frozenset({"review", "queue"})
OUTCOMES = frozenset({"applied", "refused", "duplicate"})
CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "video/mp4", "video/webm"})
IMMICH_STATUSES = frozenset({"uploaded", "duplicate", "failed"})

DIGEST_MISMATCH = "digest_mismatch"
UNKNOWN_ITEM = "unknown_item"
REVOKED_DEVICE = "revoked_device"
NOT_GRANTED = "not_granted"
INVALID_RECORD = "invalid_record"
FAVORITE_WITH_DELETE = "favorite_with_delete"
ARCHIVE_FAILED = "archive_failed"
ADMISSION_REFUSED = "admission_refused"
REASON_CODES = frozenset(
    {
        DIGEST_MISMATCH,
        UNKNOWN_ITEM,
        REVOKED_DEVICE,
        NOT_GRANTED,
        INVALID_RECORD,
        FAVORITE_WITH_DELETE,
        ARCHIVE_FAILED,
        ADMISSION_REFUSED,
    }
)

MAX_PAGE_RECORDS = 500
MAX_ENROLLED_DEVICES = 50
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_MEDIA_BYTES = 4294967296

PAIRING_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
PAIRING_CODE_LENGTH = 8
PAIRING_TTL_SECONDS = 300
PAIRING_MAX_ATTEMPTS = 5


class ProtocolError(ValueError):
    """A payload outside the contract. ``str(error)`` is a stable, content-free reason."""


def _fail() -> ProtocolError:
    return ProtocolError(INVALID_RECORD)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload = dict(pairs)
    if len(payload) != len(pairs):
        raise ProtocolError(INVALID_RECORD)
    return payload


def parse_json(raw: bytes, *, limit: int = MAX_PAGE_BYTES) -> Any:
    """Decode a bounded JSON body; duplicate keys are a refusal, not "last one wins"."""

    if len(raw) > limit:
        raise ProtocolError("response_too_large")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ProtocolError(INVALID_RECORD) from error


def encode_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


# -- field checks ---------------------------------------------------------------------------------------------------


def _object(
    value: Any, required: set[str], optional: set[str] | frozenset[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail()
    keys = set(value)
    if not required <= keys or not keys <= required | optional:
        raise _fail()
    return value


def _text(value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _fail()
    return value


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _fail()
    return value


def _bool(value: Any) -> bool:
    if type(value) is not bool:
        raise _fail()
    return value


def _choice(value: Any, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _fail()
    return value


def parse_uuid(value: Any) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise _fail()
    return str(uuid.UUID(value))


def parse_timestamp(value: Any) -> datetime:
    """RFC 3339 date-time with an explicit offset (``Z`` or ``+hh:mm``)."""

    if not isinstance(value, str) or not 20 <= len(value) <= 40 or "T" not in value:
        raise _fail()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as error:
        raise _fail() from error
    if parsed.tzinfo is None:
        raise _fail()
    return parsed.astimezone(UTC)


def utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


# -- gateway -> PC ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemRef:
    library_id: str
    sha256: str


@dataclass(frozen=True)
class Decision:
    verdict: str
    favorite: bool
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ActionRequest:
    action: str


@dataclass(frozen=True)
class OutboxRecord:
    record_id: str
    idempotency_key: str
    device_id: str
    created_at: datetime
    target: ItemRef
    kind: str
    decision: Decision | None
    action_request: ActionRequest | None


@dataclass(frozen=True)
class EnrolledDevice:
    device_id: str
    offer_id: str
    label: str
    enrolled_at: datetime


@dataclass(frozen=True)
class OutboxPage:
    records: tuple[Any, ...]
    next_cursor: str | None
    enrolled_devices: tuple[EnrolledDevice, ...]


def _item_ref(value: Any) -> ItemRef:
    body = _object(value, {"library_id", "sha256"})
    return ItemRef(_text(body["library_id"], LIBRARY_ID), _text(body["sha256"], SHA256))


def _decision(value: Any) -> Decision:
    body = _object(value, {"verdict", "favorite"}, {"tags"})
    tags_value = body.get("tags", [])
    if not isinstance(tags_value, list) or len(tags_value) > 6:
        raise _fail()
    tags = tuple(_choice(tag, TAGS) for tag in tags_value)
    if len(set(tags)) != len(tags):
        raise _fail()
    return Decision(_choice(body["verdict"], VERDICTS), _bool(body["favorite"]), tags)


def _action_request(value: Any) -> ActionRequest:
    body = _object(value, {"action"}, {"params"})
    params = body.get("params", {})
    if (
        not isinstance(params, dict)
        or len(params) > 16
        or not all(isinstance(key, str) and len(key) <= 64 for key in params)
    ):
        raise _fail()
    return ActionRequest(_choice(body["action"], ACTIONS))


def record_id_of(value: Any) -> str | None:
    """The record id of a record that may be malformed, when it can be acknowledged at all."""

    if not isinstance(value, dict):
        return None
    try:
        return parse_uuid(value.get("record_id"))
    except ProtocolError:
        return None


def parse_record(value: Any) -> OutboxRecord:
    body = _object(
        value,
        {"record_id", "idempotency_key", "device_id", "created_at", "target", "kind"},
        {"decision", "action_request"},
    )
    kind = _choice(body["kind"], RECORD_KINDS)
    other = "action_request" if kind == "decision" else "decision"
    if kind not in body or other in body:
        raise _fail()
    return OutboxRecord(
        record_id=parse_uuid(body["record_id"]),
        idempotency_key=_text(body["idempotency_key"], IDEMPOTENCY_KEY),
        device_id=_text(body["device_id"], DEVICE_ID),
        created_at=parse_timestamp(body["created_at"]),
        target=_item_ref(body["target"]),
        kind=kind,
        decision=_decision(body["decision"]) if kind == "decision" else None,
        action_request=_action_request(body["action_request"])
        if kind == "action_request"
        else None,
    )


def _enrolled_device(value: Any) -> EnrolledDevice:
    body = _object(value, {"device_id", "offer_id", "enrolled_at"}, {"label"})
    return EnrolledDevice(
        _text(body["device_id"], DEVICE_ID),
        parse_uuid(body["offer_id"]),
        _bounded_text(body.get("label", ""), 64),
        parse_timestamp(body["enrolled_at"]),
    )


def parse_outbox_page(value: Any) -> OutboxPage:
    """Check the envelope strictly; records are returned raw so each is validated (and refused) on its own."""

    body = _object(
        value, {"schema_version", "type", "records"}, {"next_cursor", "enrolled_devices"}
    )
    if body["schema_version"] != SCHEMA_VERSION or body["type"] != "outbox_page":
        raise ProtocolError("schema_mismatch")
    records = body["records"]
    if not isinstance(records, list) or len(records) > MAX_PAGE_RECORDS:
        raise _fail()
    cursor = body.get("next_cursor")
    if cursor is not None:
        cursor = _bounded_text(cursor, 256)
    devices = body.get("enrolled_devices", [])
    if not isinstance(devices, list) or len(devices) > MAX_ENROLLED_DEVICES:
        raise _fail()
    return OutboxPage(tuple(records), cursor or None, tuple(_enrolled_device(d) for d in devices))


@dataclass(frozen=True)
class ImmichReceipt:
    record_id: str
    item: ItemRef
    status: str
    immich_asset_id: str
    album: str
    favorite: bool | None
    error_code: str
    at: datetime


def parse_immich_receipt(value: Any) -> ImmichReceipt:
    body = _object(
        value,
        {"schema_version", "type", "record_id", "item", "status", "at"},
        {"immich_asset_id", "album", "favorite", "error_code"},
    )
    if body["schema_version"] != SCHEMA_VERSION or body["type"] != "immich_receipt":
        raise _fail()
    return ImmichReceipt(
        record_id=parse_uuid(body["record_id"]),
        item=_item_ref(body["item"]),
        status=_choice(body["status"], IMMICH_STATUSES),
        immich_asset_id=_bounded_text(body.get("immich_asset_id", ""), 64),
        album=_bounded_text(body.get("album", ""), 200),
        favorite=_bool(body["favorite"]) if "favorite" in body else None,
        error_code=_bounded_text(body.get("error_code", ""), 64),
        at=parse_timestamp(body["at"]),
    )


# -- PC -> gateway ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MediaVariant:
    sha256: str
    size: int
    content_type: str
    width: int = 0
    height: int = 0

    def payload(self) -> dict[str, Any]:
        if (
            not SHA256.fullmatch(self.sha256)
            or not 1 <= self.size <= MAX_MEDIA_BYTES
            or self.content_type not in CONTENT_TYPES
        ):
            raise ProtocolError("invalid_media")
        body: dict[str, Any] = {
            "sha256": self.sha256,
            "bytes": self.size,
            "content_type": self.content_type,
        }
        if 1 <= self.width <= 16384 and 1 <= self.height <= 16384:
            body.update(width=self.width, height=self.height)
        return body


def item_manifest(
    *,
    item: ItemRef,
    kind: str,
    run_id: str,
    created_at: datetime,
    media: Mapping[str, MediaVariant],
    duration_s: float | None = None,
    display: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a manifest; refuses anything the contract does not allow rather than trimming silently."""

    _text(item.library_id, LIBRARY_ID)
    _text(item.sha256, SHA256)
    if kind not in ("image", "video") or not RUN_ID.fullmatch(run_id):
        raise ProtocolError("invalid_manifest")
    if (
        not {"thumb_320", "original"}
        <= media.keys()
        <= {
            "thumb_320",
            "preview_1080",
            "mobile_video",
            "original",
        }
    ):
        raise ProtocolError("invalid_manifest")
    if media["original"].sha256 != item.sha256:
        raise ProtocolError("invalid_manifest")
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "item_manifest",
        "item": {"library_id": item.library_id, "sha256": item.sha256},
        "kind": kind,
        "run_id": run_id,
        "created_at": utc_text(created_at),
        "media": {name: variant.payload() for name, variant in media.items()},
    }
    if duration_s is not None and 0 <= duration_s <= 3600:
        body["duration_s"] = round(float(duration_s), 3)
    shown = _display(display or {})
    if shown:
        body["display"] = shown
    return body


_DISPLAY_LIMITS = {"model": 200, "prompt_excerpt": 512, "job_id": 64, "workflow": 120}


def _display(values: Mapping[str, Any]) -> dict[str, Any]:
    shown: dict[str, Any] = {}
    for key, limit in _DISPLAY_LIMITS.items():
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            shown[key] = value.strip()[:limit]
    seed = values.get("seed")
    if type(seed) is int and -(2**63) <= seed < 2**63:
        shown["seed"] = seed
    return shown


def acknowledgement(
    record_id: str,
    outcome: str,
    *,
    reason_code: str = "",
    receipt: Mapping[str, Any] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    if outcome not in OUTCOMES or (reason_code and reason_code not in REASON_CODES):
        raise ProtocolError("invalid_acknowledgement")
    if outcome == "refused" and not reason_code:
        raise ProtocolError("invalid_acknowledgement")
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "acknowledgement",
        "record_id": parse_uuid(record_id),
        "outcome": outcome,
        "acknowledged_at": utc_text(at or utc_now()),
    }
    if reason_code:
        body["reason_code"] = reason_code
    if receipt:
        allowed = {"review_evidence_id", "archived", "job_ids"}
        if not receipt.keys() <= allowed:
            raise ProtocolError("invalid_acknowledgement")
        body["receipt"] = dict(receipt)
    return body


def device_revocation(device_id: str, *, at: datetime | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "device_revocation",
        "device_id": _text(device_id, DEVICE_ID),
        "revoked_at": utc_text(at or utc_now()),
    }


# -- pairing ----------------------------------------------------------------------------------------------------------


def new_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))


def canonical_code(code: str) -> str:
    value = code.replace("-", "").replace(" ", "").upper()
    if len(value) != PAIRING_CODE_LENGTH or any(char not in PAIRING_ALPHABET for char in value):
        raise ProtocolError("invalid_code")
    return value


def display_code(code: str) -> str:
    value = canonical_code(code)
    return f"{value[:4]}-{value[4:]}"


def code_hash(salt: str, code: str) -> str:
    """``sha256(code_salt || code)``: the 32-hex salt text followed by the canonical code, as ASCII."""

    _text(salt, CODE_SALT)
    return hashlib.sha256((salt + canonical_code(code)).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class PairingOffer:
    offer_id: str
    code: str
    salt: str
    scopes: tuple[str, ...]
    label: str
    expires_at: datetime

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "type": "pairing_offer",
            "offer_id": self.offer_id,
            "code_salt": self.salt,
            "code_sha256": code_hash(self.salt, self.code),
            "scopes": list(self.scopes),
            "expires_at": utc_text(self.expires_at),
            "max_attempts": PAIRING_MAX_ATTEMPTS,
        }
        if self.label:
            body["device_label"] = self.label[:64]
        return body


def new_pairing_offer(
    *, label: str = "", scopes: Sequence[str] = ("review",), now: datetime | None = None
) -> PairingOffer:
    if not scopes or not set(scopes) <= SCOPES or len(set(scopes)) != len(scopes):
        raise ProtocolError("invalid_scope")
    moment = now or utc_now()
    return PairingOffer(
        offer_id=str(uuid.uuid4()),
        code=new_pairing_code(),
        salt=secrets.token_hex(16),
        scopes=tuple(scopes),
        label=_bounded_text(label.strip(), 64) if label else "",
        expires_at=datetime.fromtimestamp(moment.timestamp() + PAIRING_TTL_SECONDS, UTC),
    )
