"""Operator attestation that an outbound firewall restriction exists for the runtime (owner decisions D8 and D19).

StableNew never creates, edits or inspects firewall rules and cannot prove egress denial from code. For strict-offline
operation the operator manages the restriction themselves and records here that they did. The record is shown as
"attested by the operator, not verified by StableNew".

A firewall rule is bound to one program, so an attestation covers only the pinned runtime builds and executable names it
lists (D19, AI-202). An attestation for ``llama-cli.exe`` says nothing about ``llama-completion.exe``, and one for one build
says nothing about another. The service refuses with ``EGRESS_NOT_ATTESTED`` unless the active build id and its pinned
executable name are both covered. A legacy record that only holds free text covers nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from src.ai_assist.paths import attestation_path
from src.utils.atomic_io import atomic_write_json

#: Version 1 was a free-text statement only. Version 2 adds ``covers``.
ATTESTATION_SCHEMA_VERSION = 2
LEGACY_ATTESTATION_SCHEMA_VERSION = 1
MAX_STATEMENT_CHARS = 400
MAX_COVERS = 16
_SAFE_BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SAFE_EXECUTABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.exe$", re.IGNORECASE)

#: ``(build_id, executable file name)``
Cover = tuple[str, str]


def _clean_covers(covers: Iterable[Cover]) -> list[Cover]:
    cleaned: list[Cover] = []
    for build_id, executable in covers:
        if not _SAFE_BUILD_ID.match(build_id or "") or not _SAFE_EXECUTABLE.match(executable or ""):
            raise ValueError(
                "a covered build needs a build id and a plain executable file name (.exe)"
            )
        pair = (build_id, executable)
        if pair not in cleaned:
            cleaned.append(pair)
    if not 1 <= len(cleaned) <= MAX_COVERS:
        raise ValueError(f"an attestation must cover 1-{MAX_COVERS} runtime builds")
    return cleaned


def record_attestation(root: Path, statement: str, covers: Iterable[Cover] | None = None) -> Path:
    """Store the operator's statement, the time and the ``(build id, executable)`` pairs it covers.

    A blank statement is refused. Without ``covers`` the legacy (version 1) record is written; it counts as not attested for
    the application (the frozen qualification harness still records it that way)."""

    text = (statement or "").strip()
    if not text or len(text) > MAX_STATEMENT_CHARS:
        raise ValueError(f"statement must be 1-{MAX_STATEMENT_CHARS} characters")
    payload: dict[str, object] = {
        "schema_version": LEGACY_ATTESTATION_SCHEMA_VERSION,
        "attested_utc": datetime.now(UTC).isoformat(),
        "statement": text,
        "verified_by_stablenew": False,
    }
    if covers is not None:
        payload["schema_version"] = ATTESTATION_SCHEMA_VERSION
        payload["covers"] = [
            {"build_id": build_id, "executable": executable}
            for build_id, executable in _clean_covers(covers)
        ]
    return atomic_write_json(attestation_path(root), payload, indent=2, sort_keys=True)


def read_attestation(root: Path) -> dict[str, object] | None:
    """The valid attestation record of either version, or ``None`` (absent or malformed is the same: not attested).

    Use :func:`attestation_covers` to decide whether a given runtime is attested."""

    try:
        document = json.loads(attestation_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(document, dict)
        or document.get("schema_version")
        not in (LEGACY_ATTESTATION_SCHEMA_VERSION, ATTESTATION_SCHEMA_VERSION)
        or not isinstance(document.get("statement"), str)
        or not document["statement"].strip()
    ):
        return None
    return document


def read_covers(root: Path) -> tuple[Cover, ...]:
    """The ``(build id, executable)`` pairs the current record covers; empty for no record, a legacy record or bad data."""

    document = read_attestation(root)
    if document is None or document.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        return ()
    raw = document.get("covers")
    if not isinstance(raw, list):
        return ()
    pairs: list[Cover] = []
    for item in raw:
        if not isinstance(item, dict):
            return ()
        build_id, executable = item.get("build_id"), item.get("executable")
        if not isinstance(build_id, str) or not isinstance(executable, str):
            return ()
        pairs.append((build_id, executable))
    return tuple(pairs)


def attestation_covers(root: Path, build_id: str, executable: str) -> bool:
    """True only when the record names exactly this build id and this executable file name."""

    wanted = Path(executable).name.lower()
    return any(
        covered_build == build_id and covered_exe.lower() == wanted
        for covered_build, covered_exe in read_covers(root)
    )


__all__ = [
    "ATTESTATION_SCHEMA_VERSION",
    "LEGACY_ATTESTATION_SCHEMA_VERSION",
    "Cover",
    "attestation_covers",
    "read_attestation",
    "read_covers",
    "record_attestation",
]
