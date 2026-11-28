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
#: PHONE-FAST: the phone's review sections (the schema's ``item_source``).
ITEM_SOURCES = ("pipeline", "learning", "reprocess", "video", "testing", "other")

SHA256 = re.compile(r"[0-9a-f]{64}")
LIBRARY_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
RUN_ID = re.compile(r"[0-9]{8}_[0-9]{6}_[A-Za-z0-9._ -]{1,96}")
DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_-]{16,128}")
CODE_SALT = re.compile(r"[0-9a-f]{32}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")

RECORD_KINDS = frozenset({"decision", "action_request", "admin_request"})
VERDICTS = frozenset({"keep", "delete"})
TAGS = frozenset({"face", "hands", "anatomy", "artifact", "prompt_miss", "needs_fix"})
ACTIONS = frozenset(
    {
        "fix_face",
        "fix_hands",
        "fix_both",
        "more_like_this",
        "another_model",
        "aspect_ratio",
        "prompt_tweak",
        "make_video",
        "rerun_clip",
        "continue_clip",
    }
)
#: ``admin`` (LAUNCH-UPDATE-2, D2) is only ever put in an offer the desktop creates for remote update.
SCOPES = frozenset({"review", "queue", "admin"})
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
SUMMARY_CHANGED = "summary_changed"
ACTION_UNAVAILABLE = "action_unavailable"
PREPARE_REQUIRED = "prepare_required"
#: LAUNCH-UPDATE reason codes, acknowledged to an admin phone (``src/app/live_update.py`` and the updater script),
#: plus ``request_expired`` and ``update_unavailable`` from the remote hand-off (``src/app/live_update_remote.py``).
UPDATE_REASONS = frozenset(
    {
        "invalid_request",
        "remote_update_disabled",
        "update_unavailable",
        "update_in_progress",
        "rate_limited",
        "request_expired",
        "wrong_branch",
        "wrong_upstream",
        "origin_mismatch",
        "dirty_checkout",
        "fetch_failed",
        "git_failed",
        "target_moved",
        "already_current",
        "not_fast_forward",
        "not_github_signed",
        "github_unavailable",
        "environment_drift",
        "queue_unavailable",
        "busy_timeout",
        "updater_failed",
        "updater_lost",
        "old_app_did_not_exit",
        "checkout_changed",
        "merge_failed",
        "rolled_back",
        "rollback_failed",
    }
)
ADMIN_ACTIONS = frozenset({"update_and_restart"})
UPDATE_STATUSES = frozenset({"applied", "refused", "already_current"})
UPDATE_HEALTH = frozenset({"confirmed", "unconfirmed", "exited"})
UPDATE_SOURCES = frozenset({"desktop", "remote"})
QUEUE_STATES = frozenset({"idle", "running", "paused", "unknown"})
UPDATE_STATES = frozenset({"idle", "in_progress"})
UPDATE_PHASES = frozenset({"checking", "waiting_for_job", "restarting"})
MAX_STATUS_COUNT = 1_000_000
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
        SUMMARY_CHANGED,
        ACTION_UNAVAILABLE,
        PREPARE_REQUIRED,
    }
    | UPDATE_REASONS
)

#: RG-140 slice 1; the other actions stay reserved and are refused as ``invalid_record``.
SLICE_ONE_ACTIONS = frozenset({"fix_face", "fix_hands", "fix_both", "more_like_this"})
#: RG-140 slice 2. ``rerun_clip`` and ``continue_clip`` (N8) stay reserved: they will call V1's shared functions.
SLICE_TWO_ACTIONS = frozenset({"another_model", "aspect_ratio", "prompt_tweak", "make_video"})
PHONE_ACTIONS = SLICE_ONE_ACTIONS | SLICE_TWO_ACTIONS
#: Actions whose prepare names one of the PC's options (``params.choice``); without one the PC lists them.
CHOICE_ACTIONS = frozenset({"another_model", "aspect_ratio"})
#: Actions whose prepare carries one line of the owner's words (``params.text``): required for ``prompt_tweak``.
TEXT_ACTIONS = frozenset({"prompt_tweak", "make_video"})
CHOICE_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_PLAIN_LINE = re.compile(r"[^\x00-\x1f\x7f]+")
MAX_TEXT = 200
MAX_CHOICES = 100
#: ``queue`` (RG-160) is the one step of a request made while the PC was away: compiled and admitted on arrival.
STEPS = frozenset({"prepare", "confirm", "queue"})
#: An answer that is not final yet: the record is neither recorded nor acknowledged and is asked again later.
IN_PROGRESS = "in_progress"
MAX_SEEDS = 8
#: Why an action could not be prepared or admitted (``receipt.detail``): closed codes, never compiler text.
DETAILS = frozenset(
    {
        "not_an_image",
        "source_changed",
        "provenance_unverified",
        "recipe_not_variable",
        "model_unavailable",
        "model_family_refused",
        "adetailer_unavailable",
        "detector_unavailable",
        "operation_unsupported",
        "choice_unavailable",
        "no_change",
        "prompt_required",
        "size_unsupported",
        "video_unavailable",
        "app_busy",
        "app_shutting_down",
        "compile_failed",
    }
)
QUEUE_POSITIONS = frozenset({"next", "last"})
MAX_SUMMARY_LINES = 8
MAX_SUMMARY_WARNINGS = 8
MAX_SUMMARY_JOBS = 64

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
    """A phone action (RG-140): ``prepare`` asks for a summary, ``confirm`` admits what that summary showed.

    ``queue`` (RG-160) was made while the PC was away and is admitted on arrival.
    """

    action: str
    step: str = "prepare"
    count: int | None = None
    prepared_record: str = ""
    summary_revision: str = ""
    #: Slice 2, on prepare or queue only: an option id the PC listed (``CHOICE_ACTIONS``), and the owner's words
    #: (``TEXT_ACTIONS``). Untrusted: the text is one bounded line of plain text, used only as prompt text.
    choice: str = ""
    text: str = ""


@dataclass(frozen=True)
class ActionInput:
    """What a slice-2 prepare chose: an option id and the owner's words. A confirm reuses the prepare's own."""

    choice: str = ""
    text: str = ""


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
class AdminRecord:
    """An ``admin_request`` (LAUNCH-UPDATE-2): no item target, only the ``origin/main`` commit the phone showed."""

    record_id: str
    idempotency_key: str
    device_id: str
    created_at: datetime
    action: str
    expected_sha: str
    kind: str = "admin_request"


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
    body = _object(value, {"action", "params"})
    action = _choice(body["action"], ACTIONS)
    params = _object(
        body["params"],
        {"step"},
        {"count", "prepared_record", "summary_revision", "choice", "text"},
    )
    step = _choice(params["step"], STEPS)
    asks = step != "confirm"  # a confirm only names its prepare
    choice = params.get("choice")
    text = params.get("text")
    if (choice is not None and (action not in CHOICE_ACTIONS or not asks)) or (
        text is not None and (action not in TEXT_ACTIONS or not asks)
    ):
        raise _fail()
    if action == "prompt_tweak" and asks and text is None:
        raise _fail()
    if step == "queue" and action in CHOICE_ACTIONS and choice is None:
        raise _fail()  # nothing could list the options: the PC was away when it was made
    if text is not None and not (
        isinstance(text, str) and len(text) <= MAX_TEXT and _PLAIN_LINE.fullmatch(text)
    ):
        raise _fail()
    count = params.get("count")
    if count is not None and (
        action != "more_like_this"
        or not asks
        or type(count) is not int
        or not 1 <= count <= MAX_SEEDS
    ):
        raise _fail()
    if step == "confirm":
        if not {"prepared_record", "summary_revision"} <= params.keys():
            raise _fail()
        return ActionRequest(
            action,
            step,
            None,
            parse_uuid(params["prepared_record"]),
            _text(params["summary_revision"], SHA256),
        )
    if {"prepared_record", "summary_revision"} & params.keys():
        raise _fail()
    return ActionRequest(
        action,
        step,
        count,
        choice=_text(choice, CHOICE_ID) if choice is not None else "",
        text=text or "",
    )


def record_id_of(value: Any) -> str | None:
    """The record id of a record that may be malformed, when it can be acknowledged at all."""

    if not isinstance(value, dict):
        return None
    try:
        return parse_uuid(value.get("record_id"))
    except ProtocolError:
        return None


def _admin_record(value: Any) -> AdminRecord:
    body = _object(
        value, {"record_id", "idempotency_key", "device_id", "created_at", "kind", "admin_request"}
    )
    request = _object(body["admin_request"], {"action", "expected_sha"})
    return AdminRecord(
        record_id=parse_uuid(body["record_id"]),
        idempotency_key=_text(body["idempotency_key"], IDEMPOTENCY_KEY),
        device_id=_text(body["device_id"], DEVICE_ID),
        created_at=parse_timestamp(body["created_at"]),
        action=_choice(request["action"], ADMIN_ACTIONS),
        expected_sha=_text(request["expected_sha"], GIT_SHA),
    )


def parse_record(value: Any) -> OutboxRecord | AdminRecord:
    if isinstance(value, dict) and value.get("kind") == "admin_request":
        return _admin_record(value)
    body = _object(
        value,
        {"record_id", "idempotency_key", "device_id", "created_at", "target", "kind"},
        {"decision", "action_request"},
    )
    kind = _choice(body["kind"], RECORD_KINDS - {"admin_request"})
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
    batch: Mapping[str, Any] | None = None,
    parent: ItemRef | None = None,
    source: str = "",
    made_from: ItemRef | None = None,
    made_from_missing: bool = False,
    info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a manifest; refuses anything the contract does not allow rather than trimming silently.

    ``batch`` (the job's N5 batch: ``batch_id``, ``name`` and optionally ``cell`` with ``pack`` and ``model``) is
    display and grouping text: it is bounded and scrubbed like ``display``, and left out when it has no valid id or
    no name, so an unreadable batch never holds an item back.
    """

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
    if source:
        body["source"] = _source(source)
    if duration_s is not None and 0 <= duration_s <= 3600:
        body["duration_s"] = round(float(duration_s), 3)
    shown = _display(display or {})
    if shown:
        body["display"] = shown
    grouped = _batch(batch or {})
    if grouped:
        body["batch"] = grouped
    described = _info(info or {})
    if described:
        body["info"] = described
    if parent is not None:
        _text(parent.library_id, LIBRARY_ID)
        _text(parent.sha256, SHA256)
        body["parent"] = {"library_id": parent.library_id, "sha256": parent.sha256}
    elif made_from is not None:
        _text(made_from.library_id, LIBRARY_ID)
        _text(made_from.sha256, SHA256)
        body["input"] = {"library_id": made_from.library_id, "sha256": made_from.sha256}
    elif made_from_missing:
        body["input_missing"] = True
    return body


def _batch(values: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        batch_id = parse_uuid(str(values.get("batch_id") or "").lower())
    except ProtocolError:
        return None
    name = scrub_text(values.get("name"), 120) if isinstance(values.get("name"), str) else ""
    if not name:
        return None
    body: dict[str, Any] = {"batch_id": batch_id, "name": name}
    cell = values.get("cell")
    if isinstance(cell, Mapping):
        shown = {
            key: scrub_text(cell[key], limit)  # a checkpoint path is reduced to its file name
            for key, limit in (("pack", 120), ("model", 200))
            if isinstance(cell.get(key), str) and cell[key].strip()
        }
        if shown:
            body["cell"] = shown
    return body


#: NAME-INFO: the closed list of ``info`` text fields and their bounds (the schema's ``item_info``).
_INFO_LIMITS = {"stage_path": 200, "model": 40, "model_name": 200, "pack": 120, "batch": 120}


def _info(values: Mapping[str, Any]) -> dict[str, Any]:
    """What "More info" shows: bounded text with paths reduced to their last part; anything else is left out."""

    shown: dict[str, Any] = {}
    for key, limit in _INFO_LIMITS.items():
        value = values.get(key)
        if isinstance(value, str) and (text := scrub_text(value, limit)):
            shown[key] = text
    for key in ("prompt_number", "variant"):
        number = values.get(key)
        if type(number) is int and 1 <= number <= 9999:
            shown[key] = number
    seed = values.get("seed")
    if isinstance(seed, str) and re.fullmatch(r"[0-9]{1,19}", seed):
        shown["seed"] = seed
    made = values.get("made_at")
    if isinstance(made, str):
        try:
            shown["made_at"] = utc_text(parse_timestamp(made))
        except ProtocolError:
            pass
    return shown


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
        allowed = {
            "review_evidence_id",
            "choices",  # RG-140 slice 2
            "archived",
            "job_ids",
            "action_summary",
            "detail",
            "update",
        }
        if not receipt.keys() <= allowed or receipt.get("detail", "") not in DETAILS | {""}:
            raise ProtocolError("invalid_acknowledgement")
        body["receipt"] = dict(receipt)
    return body


# -- RG-140 action summaries (PC -> gateway, inside a receipt) -------------------------------------------------------

#: An absolute Windows or POSIX path, a UNC path, or any run of text with a backslash: shown by its last part only.
_PATHLIKE = re.compile(
    r"(?:(?<![\w])[A-Za-z]:[\\/]|\\\\|(?<![^\s(\"'])/(?=[^\s/]+/))[^\s,;\"'()]*"
    r"|[^\s,;\"'()]*\\[^\s,;\"'()]*"
)


def _last_part(match: re.Match[str]) -> str:
    raw = match.group(0)
    text = raw.rstrip("\\/.")
    period = "." if raw.endswith(".") else ""
    tail = re.split(r"[\\/]", text)[-1] if text else ""
    return (tail.removesuffix(":") or "a folder on the PC") + period


def scrub_text(value: Any, limit: int) -> str:
    """Display text with every path reduced to its last part (RG-100 invariant 3), bounded to ``limit``."""

    text = " ".join(str(value or "").split())
    text = _PATHLIKE.sub(_last_part, text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_WARNING_CODE = re.compile(r"[a-z0-9_]{1,64}")


@dataclass(frozen=True)
class SummaryWarning:
    code: str
    subject: str
    title: str
    why: str = ""
    fix: str = ""

    def payload(self) -> dict[str, str]:
        code = self.code if _WARNING_CODE.fullmatch(self.code) else "policy_warning"
        body = {
            "code": code,
            "subject": scrub_text(self.subject, 200) or "-",
            "title": scrub_text(self.title, 300) or code,
        }
        for key, limit in (("why", 800), ("fix", 800)):
            text = scrub_text(getattr(self, key), limit)
            if text:
                body[key] = text
        return body


@dataclass(frozen=True)
class ActionSummary:
    """The one screen the phone shows before Queue (S12). ``revision`` fingerprints what it shows and what runs."""

    action: str
    revision: str
    title: str
    lines: tuple[str, ...]
    job_count: int
    queue_position: str
    warnings: tuple[SummaryWarning, ...]
    expires_at: datetime

    def payload(self) -> dict[str, Any]:
        if (
            self.action not in ACTIONS
            or not SHA256.fullmatch(self.revision)
            or not 1 <= self.job_count <= MAX_SUMMARY_JOBS
            or self.queue_position not in QUEUE_POSITIONS
        ):
            raise ProtocolError("invalid_summary")
        return {
            "action": self.action,
            "revision": self.revision,
            "title": scrub_text(self.title, 120) or self.action,
            "lines": [scrub_text(line, 200) for line in self.lines[:MAX_SUMMARY_LINES]],
            "job_count": self.job_count,
            "queue_position": self.queue_position,
            "warnings": [item.payload() for item in self.warnings[:MAX_SUMMARY_WARNINGS]],
            "expires_at": utc_text(self.expires_at),
        }


@dataclass(frozen=True)
class ActionChoices:
    """What the phone may pick for a ``CHOICE_ACTIONS`` action (RG-140 slice 2): ``(id, label, current)`` items.

    Labels are PC-written (a checkpoint's file name, an aspect ratio's name) and reduced like every summary text; ids
    are the PC's own (``CHOICE_ID``). At most ``MAX_CHOICES`` are listed.
    """

    action: str
    items: tuple[tuple[str, str, bool], ...]
    selected: str = ""

    def payload(self) -> dict[str, Any]:
        if self.action not in CHOICE_ACTIONS or not self.items:
            raise ProtocolError("invalid_choices")
        listed = []
        for choice_id, label, current in self.items[:MAX_CHOICES]:
            if not CHOICE_ID.fullmatch(choice_id):
                raise ProtocolError("invalid_choices")
            entry: dict[str, Any] = {"id": choice_id, "label": scrub_text(label, 120) or choice_id}
            if current:
                entry["current"] = True
            listed.append(entry)
        body: dict[str, Any] = {"action": self.action, "items": listed}
        if self.selected and CHOICE_ID.fullmatch(self.selected):
            body["selected"] = self.selected
        return body


def item_withdrawal(library_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "item_withdrawal",
        "library_ids": [_text(library_id, LIBRARY_ID) for library_id in library_ids],
    }


def item_sources(items: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """``(library_id, source)`` of items published before manifests carried a source."""

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "item_sources",
        "items": [
            {"library_id": _text(library_id, LIBRARY_ID), "source": _source(source)}
            for library_id, source in items
        ],
    }


def _source(value: str) -> str:
    if value not in ITEM_SOURCES:
        raise ProtocolError("invalid_source")
    return value


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


# -- LAUNCH-UPDATE-2: the PC's status and update receipts (PC -> gateway) ---------------------------------------------


def update_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """A live update receipt (``last_result.json``) reduced to commit ids and closed codes for the phone.

    Git and launcher text (``detail``), paths and anything unknown are dropped; a reason outside the closed list is
    refused rather than passed on.
    """

    status = receipt.get("status")
    if status not in UPDATE_STATUSES:
        raise ProtocolError("invalid_receipt")
    body: dict[str, Any] = {"status": status}
    reason = receipt.get("reason") or ""
    if status == "already_current":
        reason = reason or "already_current"
    if reason:
        body["reason_code"] = _choice(reason, UPDATE_REASONS)
    elif status == "refused":
        raise ProtocolError("invalid_receipt")
    if receipt.get("source") in UPDATE_SOURCES:
        body["source"] = receipt["source"]
    for name in ("old_sha", "new_sha", "target_sha"):
        value = receipt.get(name)
        if isinstance(value, str) and GIT_SHA.fullmatch(value):
            body[name] = value
    health = str(receipt.get("health") or "")
    health = "exited" if health.startswith("exited") else health
    if health in UPDATE_HEALTH:
        body["health"] = health
    finished = receipt.get("finished_at")
    if isinstance(finished, str):
        try:
            body["finished_at"] = utc_text(parse_timestamp(finished))
        except ProtocolError:
            pass
    return body


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_STATUS_COUNT:
        raise ProtocolError("invalid_status")
    return value


def pc_status(
    *,
    head_sha: str = "",
    origin_main_sha: str = "",
    commits_behind: int | None = None,
    fetched_at: datetime | None = None,
    queue_state: str,
    queued: int,
    remote_update_enabled: bool,
    update_state: str = "idle",
    update_phase: str = "",
    update_record_id: str = "",
    last_result: Mapping[str, Any] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """The PC's checkout and queue state (D3): commit ids and counts only."""

    if (
        queue_state not in QUEUE_STATES
        or update_state not in UPDATE_STATES
        or (update_phase and update_phase not in UPDATE_PHASES)
        or type(remote_update_enabled) is not bool
    ):
        raise ProtocolError("invalid_status")
    checkout: dict[str, Any] = {}
    if head_sha:
        checkout["head_sha"] = _text(head_sha, GIT_SHA)
    if origin_main_sha:
        checkout["origin_main_sha"] = _text(origin_main_sha, GIT_SHA)
    if commits_behind is not None:
        checkout["commits_behind"] = _count(commits_behind)
    if fetched_at is not None:
        checkout["fetched_at"] = utc_text(fetched_at)
    update: dict[str, Any] = {"state": update_state}
    if update_phase:
        update["phase"] = update_phase
    if update_record_id:
        update["record_id"] = parse_uuid(update_record_id)
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": "pc_status",
        "published_at": utc_text(at or utc_now()),
        "checkout": checkout,
        "queue": {"state": queue_state, "queued": _count(queued)},
        "remote_update_enabled": remote_update_enabled,
        "update": update,
    }
    if last_result:
        try:
            body["last_result"] = update_receipt(last_result)
        except ProtocolError:
            pass  # an unreadable receipt is not shown rather than blocking the status
    return body
