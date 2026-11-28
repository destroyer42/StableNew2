"""The per-job licence attestation (owner decision 2026-11-28, VID-CAND-LTX25).

LTX-2.5's licence forbids sexually explicit content, so queueing a job that uses it needs the operator's own
confirmation of one plain sentence.  It is frozen into the job's provenance
(``provenance.metadata["licence_attestation"]``: attested, text version, time), which Replay keeps and the clip
manifest copies.  It is a record of what the operator said, not a check: nothing here or anywhere else looks at the
source, the prompt or the output, and only a missing record refuses a job.

Declared here by workflow id, outside the catalog specs, so that a published spec stays unchanged and every version of
the workflow is covered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.pipeline.policy_warnings import with_provenance_metadata
from src.video.workflow_catalog_ltx25 import LTX25_IDS

#: The NJR provenance key, the manifest key, the form field a surface fills and the phone protocol's arm field.
ATTESTATION_KEY = "licence_attestation"

LTX25_ATTESTATION_TEXT = (
    "LTX-2.5's licence forbids sexually explicit content. I confirm this source and prompt are not "
    "sexually explicit."
)
#: Change this with any change to the text: a surface that showed an older sentence must show the new one.
LTX25_ATTESTATION_VERSION = "ltx25-non-explicit-1"


@dataclass(frozen=True)
class LicenceAttestation:
    """The sentence an operator confirms, and its version."""

    version: str
    text: str


_DECLARED: Mapping[str, LicenceAttestation] = dict.fromkeys(
    LTX25_IDS, LicenceAttestation(LTX25_ATTESTATION_VERSION, LTX25_ATTESTATION_TEXT)
)


def declared_attestation(*workflow_ids: Any) -> LicenceAttestation | None:
    """The confirmation a job running these workflows needs, or ``None``."""

    return next((_DECLARED[str(item)] for item in workflow_ids if str(item) in _DECLARED), None)


def workflow_ids_of(record: Any) -> tuple[str, ...]:
    """Every video workflow an NJR runs: its own, and each sequence segment's."""

    # Imported here: the resolver imports the backend, which imports this module.
    from src.video.video_execution_resolver import effective_workflow_identity

    config = getattr(record, "config", None)
    stage = config.get("video_workflow") if isinstance(config, Mapping) else None
    if not isinstance(stage, Mapping):
        return ()
    plan = stage.get("sequence_metadata")
    segments = plan.get("segments") if isinstance(plan, Mapping) else None
    ids = [effective_workflow_identity(stage)[0]]
    ids += [item.get("workflow_id") for item in segments or () if isinstance(item, Mapping)]
    return tuple(str(item) for item in ids if item)


def attestation_record(
    attestation: LicenceAttestation, *, at: datetime | None = None
) -> dict[str, Any]:
    """The record of one confirmation, made by the surface at the moment the operator gave it."""

    return {
        "attested": True,
        "text_version": attestation.version,
        "attested_at": (at or datetime.now(UTC)).isoformat(timespec="seconds"),
    }


def recorded_attestation(metadata: Any) -> dict[str, Any] | None:
    """The complete record in a job's provenance metadata, or ``None``."""

    value = metadata.get(ATTESTATION_KEY) if isinstance(metadata, Mapping) else None
    if not (
        isinstance(value, Mapping)
        and value.get("attested") is True
        and value.get("text_version")
        and value.get("attested_at")
    ):
        return None
    return dict(value)


def with_attestation(record: Any, attestation: Any) -> Any:
    """``record`` re-frozen with the operator's confirmation in its provenance, for a job that needs one.

    Called between building a job and ``submit_njrs``.  The same record comes back when the job needs no confirmation,
    none was given, or it confirms a sentence that is no longer the current one.
    """

    declared = declared_attestation(*workflow_ids_of(record))
    given = recorded_attestation({ATTESTATION_KEY: attestation})
    if declared is None or given is None or given["text_version"] != declared.version:
        return record
    return with_provenance_metadata(record, {**record.extra_metadata, ATTESTATION_KEY: given})


def attestation_problem(record: Any) -> str:
    """Why a job cannot be queued for want of a confirmation, or an empty string.

    Any complete record satisfies it, so a Replay of a job confirmed against an earlier sentence still runs.
    """

    declared = declared_attestation(*workflow_ids_of(record))
    if declared is None or recorded_attestation(getattr(record, "extra_metadata", None)):
        return ""
    return (
        f'This job needs your confirmation before it is queued: "{declared.text}" '
        "Queue it from a screen that asks for it."
    )


__all__ = [
    "ATTESTATION_KEY",
    "LTX25_ATTESTATION_TEXT",
    "LTX25_ATTESTATION_VERSION",
    "LicenceAttestation",
    "attestation_problem",
    "attestation_record",
    "declared_attestation",
    "recorded_attestation",
    "with_attestation",
    "workflow_ids_of",
]
