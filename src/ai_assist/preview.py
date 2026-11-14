"""AI Assist Preview: the operator-recorded enablement of an unqualified candidate (owner decision D13, 2026-11-13).

Preview lets production run a registered, installed, hash-verified *candidate* model on a pinned runtime build, but only
while a record written by an explicit operator action names exactly that model SHA-256 and runtime build id. The record
holds identities and timestamps, never prompt content. Since owner decision D20 it may hold several identities, one per
(model SHA-256, runtime build id) the operator confirmed; enabling one never enables another. It is not a global switch:
any identity change makes an entry not match, each entry is revocable, and a missing, malformed or mismatched record means
"not enabled" (never an admission).

``qualified`` keeps its meaning and is set only by the qualification authority (PR-AI-111). Nothing here sets it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.ai_assist.manifests import (
    ModelEntry,
    ModelRegistry,
    RuntimeBuild,
    RuntimeManifest,
    verify_installation,
)
from src.ai_assist.paths import preview_enablement_path
from src.utils.atomic_io import atomic_write_json

PREVIEW_SCHEMA_VERSION = 2
#: The single-identity record of owner decision D13; still read (as one identity), no longer written.
PREVIEW_LEGACY_SCHEMA_VERSION = 1
#: Far more than the registry holds; a bound so a damaged or hostile record cannot grow without limit.
MAX_PREVIEW_IDENTITIES = 32
TRUST_QUALIFIED = "qualified"
TRUST_PREVIEW = "preview"
#: Harness-only tier for a candidate admitted through ``ServicePolicy.allow_candidate``; never recorded in events.
TRUST_CANDIDATE = "candidate"
PREVIEW_LABEL = "AI Assist Preview: unqualified model"
PREVIEW_MEANING = (
    "AI Assist Preview runs a model that has NOT been qualified. It runs on this computer only, on the CPU, "
    "offline, and only suggests: every suggestion is advisory and nothing changes until you review it and press Accept."
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def trust_tier(entry: ModelEntry, build: RuntimeBuild) -> str:
    """``qualified`` only when both the model and the runtime build are qualified; anything else is a candidate."""

    return TRUST_QUALIFIED if entry.qualified and build.qualified else TRUST_CANDIDATE


def _parse_identity(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    model = raw.get("model_sha256")
    build = raw.get("runtime_build_id")
    stamp = raw.get("enabled_utc")
    if (
        not isinstance(model, str)
        or not _SHA256.match(model)
        or not isinstance(build, str)
        or not build
        or len(build) > 80
        or not isinstance(stamp, str)
        or not stamp
    ):
        return None
    return {"model_sha256": model, "runtime_build_id": build, "enabled_utc": stamp}


def read_preview_identities(root: Path) -> tuple[dict[str, str], ...]:
    """Every well-formed enabled identity, or ``()``. Absent, unreadable and malformed are the same: nothing is enabled.

    Schema 2 holds a list of identities (owner decision D20); the schema 1 record of D13 is one identity and is read as
    such, so enabling made before the model selector keeps working. One malformed identity is dropped, never repaired,
    and never takes a valid neighbour with it."""

    try:
        document = json.loads(preview_enablement_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(document, dict):
        return ()
    version = document.get("schema_version")
    if version == PREVIEW_LEGACY_SCHEMA_VERSION:
        legacy = _parse_identity(document)
        return (legacy,) if legacy is not None else ()
    if version != PREVIEW_SCHEMA_VERSION:
        return ()
    raw = document.get("identities")
    if not isinstance(raw, list):
        return ()
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for item in raw[:MAX_PREVIEW_IDENTITIES]:
        parsed = _parse_identity(item)
        if parsed is not None:
            seen.setdefault((parsed["model_sha256"], parsed["runtime_build_id"]), parsed)
    return tuple(seen.values())


def preview_enabled_for(root: Path, entry: ModelEntry, build: RuntimeBuild) -> bool:
    """True only when an identity in the record names exactly this model SHA-256 and this runtime build id."""

    return any(
        item["model_sha256"] == entry.sha256 and item["runtime_build_id"] == build.build_id
        for item in read_preview_identities(root)
    )


def _write_identities(root: Path, identities: tuple[dict[str, str], ...]) -> Path | None:
    path = preview_enablement_path(root)
    if not identities:
        path.unlink(missing_ok=True)
        return None
    return atomic_write_json(
        path,
        {"schema_version": PREVIEW_SCHEMA_VERSION, "identities": list(identities)},
        indent=2,
        sort_keys=True,
    )


def revoke_preview(
    root: Path, entry: ModelEntry | None = None, build: RuntimeBuild | None = None
) -> bool:
    """Revoke Preview. With ``entry`` and ``build`` only that identity is removed (the others stay enabled); without them
    the whole record is. ``True`` when nothing is left for the revoked identity (a missing record is already revoked)."""

    try:
        if entry is None or build is None:
            preview_enablement_path(root).unlink(missing_ok=True)
            return True
        kept = tuple(
            item
            for item in read_preview_identities(root)
            if (item["model_sha256"], item["runtime_build_id"]) != (entry.sha256, build.build_id)
        )
        _write_identities(root, kept)
    except OSError:
        return False
    return True


class PreviewRefused(Exception):
    """Preview cannot be enabled. ``code`` is a stable string; nothing was recorded."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def enable_preview(root: Path, runtime: RuntimeManifest, registry: ModelRegistry) -> Path:
    """Record the operator's explicit enablement for the *currently active, verified* model and runtime build.

    Refused unless the active installation verifies (identity check, candidates allowed) and is actually a candidate:
    a qualified installation needs no enablement. The identity written is the verified one, never caller input. It is
    added to the record; identities enabled earlier for other models stay as they were (owner decision D20).
    """

    verification = verify_installation(root, runtime, registry, allow_candidate=True)
    if not verification.ok or verification.entry is None or verification.build is None:
        raise PreviewRefused(verification.reason or "not_installed")
    if trust_tier(verification.entry, verification.build) == TRUST_QUALIFIED:
        raise PreviewRefused("already_qualified")
    identity = (verification.entry.sha256, verification.build.build_id)
    others = tuple(
        item
        for item in read_preview_identities(root)
        if (item["model_sha256"], item["runtime_build_id"]) != identity
    )
    fresh = {
        "model_sha256": identity[0],
        "runtime_build_id": identity[1],
        "enabled_utc": datetime.now(UTC).isoformat(),
    }
    written = _write_identities(root, (*others[-(MAX_PREVIEW_IDENTITIES - 1) :], fresh))
    assert written is not None
    return written


@dataclass(frozen=True, slots=True)
class PreviewState:
    """What the operator needs to decide on Preview. Content-free."""

    #: ``qualified``, ``preview`` (enabled), ``candidate`` (installed, not enabled) or ``""`` (nothing usable).
    trust: str
    #: Exact next prerequisite: ``pinned_build``, ``imported_model``, ``integrity``, ``enablement``, ``attestation`` or ``""``.
    missing: str
    model_name: str = ""
    build_id: str = ""
    model_sha256: str = ""

    @property
    def can_enable(self) -> bool:
        return self.trust == TRUST_CANDIDATE

    @property
    def enabled(self) -> bool:
        return self.trust == TRUST_PREVIEW


__all__ = [
    "PREVIEW_LABEL",
    "PREVIEW_MEANING",
    "PREVIEW_LEGACY_SCHEMA_VERSION",
    "PREVIEW_SCHEMA_VERSION",
    "MAX_PREVIEW_IDENTITIES",
    "TRUST_CANDIDATE",
    "TRUST_PREVIEW",
    "TRUST_QUALIFIED",
    "PreviewRefused",
    "PreviewState",
    "enable_preview",
    "preview_enabled_for",
    "read_preview_identities",
    "revoke_preview",
    "trust_tier",
]
