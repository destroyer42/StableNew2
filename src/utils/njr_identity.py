"""The one identity of a stored NJR snapshot.

The SQLite repository fingerprints every job (``jobs.njr_fingerprint``) and the image/manifest provenance records the
NJR hash of the run that produced them.  Those must be the *same* number or embedded provenance cannot be matched to its
row.  Both sides build the snapshot envelope and hash it through this module, so there is exactly one rule:

* the envelope is ``{"schema_version", "job_id", "normalized_job"}`` (``snapshot_envelope``);
* it is serialized as canonical JSON: sorted keys, compact separators, ASCII-escaped (``snapshot_json``);
* the identity is the SHA-256 of those UTF-8 bytes (``snapshot_fingerprint``).

Artifacts written before this module existed carry a hash of the bare record serialized without ASCII escaping; they are
not rewritten.  This module imports nothing from the rest of the application.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SNAPSHOT_SCHEMA_VERSION = "2.6"


def snapshot_envelope(job_id: str, normalized_job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "job_id": job_id,
        "normalized_job": dict(normalized_job),
    }


def snapshot_json(envelope: Mapping[str, Any]) -> str:
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint_of_serialized(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def snapshot_fingerprint(envelope: Mapping[str, Any]) -> str:
    return fingerprint_of_serialized(snapshot_json(envelope))


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "fingerprint_of_serialized",
    "snapshot_envelope",
    "snapshot_fingerprint",
    "snapshot_json",
]
