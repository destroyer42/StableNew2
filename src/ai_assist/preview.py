"""AI Assist Preview: the operator-recorded enablement of an unqualified candidate (owner decision D13, 2026-11-13).

Preview lets production run a registered, installed, hash-verified *candidate* model on a pinned runtime build, but only
while a record written by an explicit operator action names exactly that model SHA-256 and runtime build id. The record
holds identities and a timestamp, never prompt content. It is not a global switch: any identity change makes the record
not match, it is revocable, and a missing, malformed or mismatched record means "not enabled" (never an admission).

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

PREVIEW_SCHEMA_VERSION = 1
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


def read_preview_enablement(root: Path) -> dict[str, str] | None:
    """The well-formed enablement record, or ``None``. Absent, unreadable and malformed are the same: not enabled."""

    try:
        document = json.loads(preview_enablement_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or document.get("schema_version") != PREVIEW_SCHEMA_VERSION:
        return None
    model = document.get("model_sha256")
    build = document.get("runtime_build_id")
    stamp = document.get("enabled_utc")
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


def preview_enabled_for(root: Path, entry: ModelEntry, build: RuntimeBuild) -> bool:
    """True only when the record names exactly this model SHA-256 and this runtime build id."""

    record = read_preview_enablement(root)
    return (
        record is not None
        and record["model_sha256"] == entry.sha256
        and record["runtime_build_id"] == build.build_id
    )


def revoke_preview(root: Path) -> bool:
    """Remove the enablement record. ``True`` when nothing is left (a missing record is already revoked)."""

    try:
        preview_enablement_path(root).unlink(missing_ok=True)
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
    a qualified installation needs no enablement. The identities written are the verified ones, never caller input.
    """

    verification = verify_installation(root, runtime, registry, allow_candidate=True)
    if not verification.ok or verification.entry is None or verification.build is None:
        raise PreviewRefused(verification.reason or "not_installed")
    if trust_tier(verification.entry, verification.build) == TRUST_QUALIFIED:
        raise PreviewRefused("already_qualified")
    return atomic_write_json(
        preview_enablement_path(root),
        {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "model_sha256": verification.entry.sha256,
            "runtime_build_id": verification.build.build_id,
            "enabled_utc": datetime.now(UTC).isoformat(),
        },
        indent=2,
        sort_keys=True,
    )


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
    "PREVIEW_SCHEMA_VERSION",
    "TRUST_CANDIDATE",
    "TRUST_PREVIEW",
    "TRUST_QUALIFIED",
    "PreviewRefused",
    "PreviewState",
    "enable_preview",
    "preview_enabled_for",
    "read_preview_enablement",
    "revoke_preview",
    "trust_tier",
]
