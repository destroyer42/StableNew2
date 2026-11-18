"""The one rule for a frozen Learning experiment snapshot carried by reference (LEARN-SNAPSHOT-914).

A Learning job's NJR metadata and a Learning rating record both carry a ``frozen_experiment`` block. Before this
package that block embedded the whole frozen experiment (``snapshot``), once under the workload metadata and once under
the provenance metadata of every variant job, and again in every rating. New blocks carry only ``snapshot_sha256`` plus
the storage marker ``snapshot_storage == "job_repository"``; the body is stored once per experiment in the
``experiment_snapshots`` table that ``JobRepository`` owns, inserted in the same transaction as the jobs that refer to it.

``resolve_experiment_snapshot`` is the only reader:

* a legacy block (no storage marker) returns its embedded body unchanged, so stored rows read exactly as before;
* a by-reference block returns the stored body for its hash, and refuses a body whose SHA-256 differs from the hash.

The hash is the SHA-256 of the canonical snapshot JSON (``experiment_execution.freeze_snapshot``), the same digest the
block always carried. This module imports nothing from the rest of the application, so the repository and Learning can
both use it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

FROZEN_KEY = "frozen_experiment"
STORAGE_KEY = "snapshot_storage"
#: Marks a block whose body is stored once, by hash, in ``JobRepository``'s ``experiment_snapshots`` table.
STORAGE_JOB_REPOSITORY = "job_repository"


class _VerifiedFrozen(dict):  # type: ignore[type-arg]
    """A ``frozen_experiment`` block whose body ``with_resolved_snapshot`` verified (in memory only).

    Parsed JSON never produces this type, and it serializes like any dict, so the mark cannot be forged on disk and
    never breaks a reader that hashes or serializes the block.
    """


#: A lookup from snapshot SHA-256 to the stored canonical snapshot JSON (``None`` when nothing is stored).
SnapshotLookup = Callable[[str], "str | None"]


class ExperimentSnapshotError(ValueError):
    """A by-reference snapshot cannot be resolved to a verified body."""


class ExperimentSnapshotUnavailable(ExperimentSnapshotError):
    """No stored body exists for the referenced hash, or no lookup was supplied."""


class ExperimentSnapshotIntegrityError(ExperimentSnapshotError):
    """The stored body does not hash to the reference: it was altered after admission."""


def canonical_snapshot_json(snapshot: Mapping[str, Any]) -> str:
    """The canonical text ``experiment_execution.freeze_snapshot`` produces (sorted, compact, ASCII)."""

    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def snapshot_sha256(snapshot_json: str) -> str:
    return hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()


def verify_snapshot_body(digest: str, snapshot_json: str) -> None:
    """Raise ``ExperimentSnapshotIntegrityError`` unless ``snapshot_json`` hashes to ``digest``."""

    if not isinstance(snapshot_json, str) or snapshot_sha256(snapshot_json) != digest:
        raise ExperimentSnapshotIntegrityError(
            f"Stored experiment snapshot {str(digest)[:12]} does not match its SHA-256; it was altered after admission."
        )


def is_by_reference(frozen: Any) -> bool:
    return isinstance(frozen, Mapping) and frozen.get(STORAGE_KEY) == STORAGE_JOB_REPOSITORY


def snapshot_reference(metadata: Any) -> str | None:
    """The hash a by-reference ``frozen_experiment`` block points at, else ``None`` (legacy or no block)."""

    frozen = metadata.get(FROZEN_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(frozen, Mapping) or not is_by_reference(frozen):
        return None
    digest = frozen.get("snapshot_sha256")
    return str(digest) if isinstance(digest, str) and digest else None


def snapshot_references(metadata_blocks: Iterable[Any]) -> set[str]:
    return {digest for block in metadata_blocks if (digest := snapshot_reference(block))}


def by_reference(frozen: Mapping[str, Any], *, schema_version: int) -> dict[str, Any]:
    """``frozen`` without its embedded body, marked as stored by hash."""

    block = {key: value for key, value in frozen.items() if key != "snapshot"}
    if not block.get("snapshot_sha256"):
        raise ExperimentSnapshotError(
            "A by-reference experiment snapshot needs its snapshot_sha256."
        )
    block["schema_version"] = schema_version
    block[STORAGE_KEY] = STORAGE_JOB_REPOSITORY
    return block


def resolve_experiment_snapshot(
    metadata: Any, lookup: SnapshotLookup | None = None
) -> dict[str, Any] | None:
    """The frozen experiment snapshot ``metadata`` carries, or ``None`` when it carries none.

    A legacy block returns its embedded body as stored. A by-reference block returns the stored body for its hash,
    verified on every read; a missing body raises ``ExperimentSnapshotUnavailable`` and an altered one
    ``ExperimentSnapshotIntegrityError``. A by-reference block that was already resolved at a load boundary
    (``with_resolved_snapshot``) returns that verified body.
    """

    frozen = metadata.get(FROZEN_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(frozen, Mapping):
        return None
    embedded = frozen.get("snapshot")
    if not is_by_reference(frozen):
        return embedded if isinstance(embedded, dict) else None
    digest = snapshot_reference(metadata)
    if digest is None:
        raise ExperimentSnapshotUnavailable(
            "By-reference experiment snapshot has no snapshot_sha256."
        )
    if isinstance(embedded, dict):
        # Resolved and verified at a load boundary (with_resolved_snapshot) when it is the in-memory verified type,
        # which parsed JSON cannot produce; any other embedded body in a by-reference block is verified here.
        if not isinstance(frozen, _VerifiedFrozen):
            verify_snapshot_body(digest, canonical_snapshot_json(embedded))
        return embedded
    stored = lookup(digest) if lookup is not None else None
    if stored is None:
        raise ExperimentSnapshotUnavailable(
            f"Experiment snapshot {digest[:12]} is not stored in the job repository."
        )
    verify_snapshot_body(digest, stored)
    body = json.loads(stored)
    if not isinstance(body, dict):
        raise ExperimentSnapshotIntegrityError(
            f"Stored experiment snapshot {digest[:12]} is not an object."
        )
    return body


def with_resolved_snapshot(row: Mapping[str, Any], lookup: SnapshotLookup | None) -> dict[str, Any]:
    """A copy of a rating row whose by-reference ``frozen_experiment`` carries its verified body in memory.

    Legacy rows are returned as a shallow copy unchanged. Raises like ``resolve_experiment_snapshot``. The row on disk
    is never rewritten; only the in-memory copy carries the body.
    """

    copied = dict(row)
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping) or snapshot_reference(metadata) is None:
        return copied
    body = resolve_experiment_snapshot(metadata, lookup)
    frozen = _VerifiedFrozen(metadata[FROZEN_KEY])
    frozen["snapshot"] = body
    copied["metadata"] = {**metadata, FROZEN_KEY: frozen}
    return copied


def resolve_rows(
    rows: Iterable[Mapping[str, Any]], lookup: SnapshotLookup | None
) -> tuple[list[dict[str, Any]], int, int]:
    """Rating rows with by-reference snapshots resolved at the load boundary.

    Returns ``(rows, unavailable, altered)``. A row whose snapshot cannot be resolved stays in the list unresolved, so
    every reader that resolves it refuses it as evidence; ``altered`` counts bodies that failed hash verification.
    """

    cached = caching_lookup(lookup)
    resolved: list[dict[str, Any]] = []
    unavailable = altered = 0
    for row in rows:
        try:
            resolved.append(with_resolved_snapshot(row, cached))
        except ExperimentSnapshotIntegrityError:
            altered += 1
            resolved.append(dict(row))
        except ExperimentSnapshotError:
            unavailable += 1
            resolved.append(dict(row))
    return resolved, unavailable, altered


def caching_lookup(lookup: SnapshotLookup | None) -> SnapshotLookup | None:
    """``lookup`` memoized per hash; stored bodies are immutable, and every read is still verified."""

    if lookup is None:
        return None
    cache: dict[str, str | None] = {}

    def cached(digest: str) -> str | None:
        if digest not in cache:
            cache[digest] = lookup(digest)
        return cache[digest]

    return cached


__all__ = [
    "FROZEN_KEY",
    "STORAGE_JOB_REPOSITORY",
    "STORAGE_KEY",
    "ExperimentSnapshotError",
    "ExperimentSnapshotIntegrityError",
    "ExperimentSnapshotUnavailable",
    "SnapshotLookup",
    "by_reference",
    "caching_lookup",
    "canonical_snapshot_json",
    "is_by_reference",
    "resolve_experiment_snapshot",
    "resolve_rows",
    "snapshot_reference",
    "snapshot_references",
    "snapshot_sha256",
    "verify_snapshot_body",
    "with_resolved_snapshot",
]
