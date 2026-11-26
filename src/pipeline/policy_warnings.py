"""Policy warnings (N1 "warn, don't block"): typed, surface-neutral records of a policy status.

A governance, qualification or recognition status on something the operator can select (an experimental
video workflow, an unqualified checkpoint) is a warning, not a refusal (``AGENTS.md`` section 2). Every
surface (the Tk Preview and Queue summary, the inline Queue notice, the phone summary) renders the same
``PolicyWarning`` records, so nothing here imports Tk or formats for one toolkit.

When the operator selects Queue on a summary that showed warnings, the accepted warnings are frozen into the
job's provenance (``provenance.metadata["accepted_warnings"]``). The record carries no timestamp, so building the
same job twice stays deterministic; the repository already records when the job was admitted.

Real blocks (missing or changed files, an operation the backend cannot perform, process ownership, device-loss
quarantine, host or device limits) are never ``PolicyWarning`` values; they stay refusals.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

CONTRACT = "policy_warning/1"
ACCEPTED_WARNINGS_KEY = "accepted_warnings"
#: N1b: warnings a compiler attached to an NJR for Preview (``provenance.metadata["policy_warnings"]``). Queue moves
#: them to ``accepted_warnings``; they never decide whether a job runs.
PENDING_WARNINGS_KEY = "policy_warnings"
SURFACE_DESKTOP = "desktop"
SURFACE_PHONE = "phone"
KNOWN_SURFACES = frozenset({SURFACE_DESKTOP, SURFACE_PHONE})

#: An experimental Comfy video workflow (not production-promoted). Its acceptance is the job's opt-in.
CODE_VIDEO_EXPERIMENTAL = "video_experimental_workflow"
#: A checkpoint StableNew has no qualified profile for (for example a FLUX layout without a profile).
CODE_IMAGE_MODEL_UNQUALIFIED = "image_model_unqualified"
#: N1b: an SDXL-only feature on a checkpoint the registry could not classify (``src/image_backends/sdxl_target.py``).
CODE_IMAGE_MODEL_FAMILY_UNVERIFIED = "image_model_family_unverified"


@dataclass(frozen=True)
class PolicyWarning:
    """One warning: what it is about, why it is shown and what makes it work."""

    code: str
    subject: str
    title: str
    why: str
    fix: str = ""
    source_gate: str = ""

    def __post_init__(self) -> None:
        if not str(self.code).strip() or not str(self.subject).strip():
            raise ValueError("A policy warning needs a code and a subject")

    @property
    def key(self) -> tuple[str, str]:
        return (self.code, self.subject)

    def text(self) -> str:
        """Plain operator text: the title, why, then the fix. Any surface may lay these out differently."""

        parts = [self.title.strip(), self.why.strip(), self.fix.strip()]
        return " ".join(part for part in parts if part)

    def as_dict(self) -> dict[str, str]:
        return {
            "contract": CONTRACT,
            "code": self.code,
            "subject": self.subject,
            "title": self.title,
            "why": self.why,
            "fix": self.fix,
            "source_gate": self.source_gate,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PolicyWarning:
        return cls(
            code=str(value.get("code") or ""),
            subject=str(value.get("subject") or ""),
            title=str(value.get("title") or ""),
            why=str(value.get("why") or ""),
            fix=str(value.get("fix") or ""),
            source_gate=str(value.get("source_gate") or ""),
        )


def acceptance_record(warning: PolicyWarning, *, surface: str) -> dict[str, str]:
    """The durable record of one accepted warning (the warning plus the surface it was accepted on)."""

    if surface not in KNOWN_SURFACES:
        raise ValueError(f"Unknown warning surface '{surface}'")
    return {**warning.as_dict(), "surface": surface}


def accepted_warning_records(metadata: Mapping[str, Any] | None) -> tuple[dict[str, Any], ...]:
    raw = (metadata or {}).get(ACCEPTED_WARNINGS_KEY)
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(dict(item) for item in raw if isinstance(item, Mapping))


def accepted_warning_keys(metadata: Mapping[str, Any] | None) -> frozenset[tuple[str, str]]:
    return frozenset(
        (str(item.get("code") or ""), str(item.get("subject") or ""))
        for item in accepted_warning_records(metadata)
    )


def is_accepted(metadata: Mapping[str, Any] | None, code: str, subject: str) -> bool:
    return (code, subject) in accepted_warning_keys(metadata)


def merge_accepted_warnings(
    metadata: Mapping[str, Any] | None,
    warnings: Iterable[PolicyWarning],
    *,
    surface: str,
) -> dict[str, Any]:
    """A copy of ``metadata`` with ``warnings`` added to its accepted list (one record per code and subject)."""

    merged = dict(metadata or {})
    records = list(accepted_warning_records(merged))
    seen = {(str(item.get("code") or ""), str(item.get("subject") or "")) for item in records}
    for warning in warnings:
        if warning.key in seen:
            continue
        seen.add(warning.key)
        records.append(acceptance_record(warning, surface=surface))
    if records:
        merged[ACCEPTED_WARNINGS_KEY] = records
    return merged


def with_accepted_warnings(record: Any, warnings: Iterable[PolicyWarning], *, surface: str) -> Any:
    """Return ``record`` (a ``NormalizedJobRecord``) re-frozen with ``warnings`` accepted in its provenance.

    The same record is returned unchanged when there is nothing new to accept, so an ordinary job keeps its
    exact identity.
    """

    pending = [
        item for item in warnings if item.key not in accepted_warning_keys(record.extra_metadata)
    ]
    if not pending:
        return record
    metadata = merge_accepted_warnings(record.extra_metadata, pending, surface=surface)
    return _with_provenance_metadata(record, metadata)


def _with_provenance_metadata(record: Any, metadata: Mapping[str, Any]) -> Any:
    """``record`` re-frozen with new provenance metadata only; the job's identity and plan are unchanged."""

    return replace(record, provenance=replace(record.provenance, metadata=metadata))


def pending_warnings(record: Any) -> tuple[PolicyWarning, ...]:
    """The warnings a compiler attached to ``record`` for Preview (N1b), as ``PolicyWarning`` values."""

    raw = (getattr(record, "extra_metadata", None) or {}).get(PENDING_WARNINGS_KEY)
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(PolicyWarning.from_dict(item) for item in raw if isinstance(item, Mapping))


def with_pending_warnings(record: Any, warnings: Iterable[PolicyWarning]) -> Any:
    """``record`` re-frozen with ``warnings`` attached for Preview (N1b); unchanged when there are none."""

    items = list(warnings)
    if not items:
        return record
    metadata = dict(record.extra_metadata or {})
    records = [
        dict(item) for item in metadata.get(PENDING_WARNINGS_KEY) or () if isinstance(item, Mapping)
    ]
    seen = {(str(item.get("code") or ""), str(item.get("subject") or "")) for item in records}
    records.extend(item.as_dict() for item in items if item.key not in seen)
    metadata[PENDING_WARNINGS_KEY] = records
    return _with_provenance_metadata(record, metadata)


def unaccepted(
    metadata: Mapping[str, Any] | None, warnings: Iterable[PolicyWarning]
) -> tuple[PolicyWarning, ...]:
    keys = accepted_warning_keys(metadata)
    return tuple(item for item in warnings if item.key not in keys)


__all__ = [
    "ACCEPTED_WARNINGS_KEY",
    "CODE_IMAGE_MODEL_FAMILY_UNVERIFIED",
    "CODE_IMAGE_MODEL_UNQUALIFIED",
    "CODE_VIDEO_EXPERIMENTAL",
    "CONTRACT",
    "KNOWN_SURFACES",
    "PENDING_WARNINGS_KEY",
    "PolicyWarning",
    "SURFACE_DESKTOP",
    "SURFACE_PHONE",
    "acceptance_record",
    "accepted_warning_keys",
    "accepted_warning_records",
    "is_accepted",
    "merge_accepted_warnings",
    "pending_warnings",
    "unaccepted",
    "with_accepted_warnings",
    "with_pending_warnings",
]
