"""Operator attestation that an outbound firewall restriction exists for the runtime (owner decision D8).

StableNew never creates, edits or inspects firewall rules and cannot prove egress denial from code. For strict-offline
qualification the operator manages the restriction themselves and records here that they did. The record is shown as
"attested by the operator, not verified by StableNew".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.ai_assist.paths import attestation_path
from src.utils.atomic_io import atomic_write_json

ATTESTATION_SCHEMA_VERSION = 1
MAX_STATEMENT_CHARS = 400


def record_attestation(root: Path, statement: str) -> Path:
    """Store the operator's statement (for example the rule name) and the time. A blank statement is refused."""

    text = (statement or "").strip()
    if not text or len(text) > MAX_STATEMENT_CHARS:
        raise ValueError(f"statement must be 1-{MAX_STATEMENT_CHARS} characters")
    return atomic_write_json(
        attestation_path(root),
        {
            "schema_version": ATTESTATION_SCHEMA_VERSION,
            "attested_utc": datetime.now(UTC).isoformat(),
            "statement": text,
            "verified_by_stablenew": False,
        },
        indent=2,
        sort_keys=True,
    )


def read_attestation(root: Path) -> dict[str, object] | None:
    """The valid attestation record, or ``None`` (absent or malformed is the same: not attested)."""

    try:
        document = json.loads(attestation_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != ATTESTATION_SCHEMA_VERSION
        or not isinstance(document.get("statement"), str)
        or not document["statement"].strip()
    ):
        return None
    return document


__all__ = ["ATTESTATION_SCHEMA_VERSION", "read_attestation", "record_attestation"]
