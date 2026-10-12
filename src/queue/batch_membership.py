# Subsystem: Queue
# Role: Pure, read-only normalization of persisted batch membership (PR-BATCH-OPS-201).

"""Resolve which logical batch, if any, a persisted job belongs to.

A batch is *not* a persisted entity. It is a logical grouping recovered from the immutable
``NormalizedJobRecord.provenance.metadata`` that each admitting workflow froze into its jobs:

* Review (PR-REVIEW-BATCH-200): ``review_batch = {batch_id, source_count, group_by_model}`` plus the
  associated top-level ``batch_id``. It carries no kind or per-job index, and one job may cover several
  sources when an explicit ``batch_size > 1`` was requested, so job counts and source counts differ.
* Versioned descriptor (PR-VID-BATCH-200, ``selected_retry``): ``batch = {schema: "stablenew.batch.v1",
  batch_kind, batch_id, source_index (zero-based), source_count}``.

The logical identity is always the composite ``(kind, batch_id)``. Nothing here looks at pack names,
timestamps, queue positions, output directories, prompts or GUI labels, and nothing is written: this module
performs no I/O and never mutates a record. A record without a valid, unambiguous identity is an ordinary
job; a record whose identifiers contradict each other is reported ``AMBIGUOUS`` and is never merged into
any batch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

BATCH_SCHEMA = "stablenew.batch.v1"
REPLAY_ORIGIN_SCHEMA = "stablenew.replay-origin.v1"
REVIEW_DESCRIPTOR_KEY = "review_batch"
VERSIONED_DESCRIPTOR_KEY = "batch"
TOP_LEVEL_BATCH_ID_KEY = "batch_id"
REPLAY_ORIGIN_KEY = "replay_origin"

#: The only metadata keys that make a job an *active* member of a batch.
ACTIVE_BATCH_KEYS = (VERSIONED_DESCRIPTOR_KEY, REVIEW_DESCRIPTOR_KEY, TOP_LEVEL_BATCH_ID_KEY)


class BatchKind(str, Enum):
    REVIEW = "review"
    VIDEO_WORKFLOW = "video_workflow"
    SELECTED_RETRY = "selected_retry"


_VERSIONED_KINDS = {BatchKind.VIDEO_WORKFLOW.value, BatchKind.SELECTED_RETRY.value}
KIND_LABELS = {
    BatchKind.REVIEW: "Review",
    BatchKind.VIDEO_WORKFLOW: "Video Workflow",
    BatchKind.SELECTED_RETRY: "Retry",
}


class MembershipState(str, Enum):
    #: A valid, unambiguous batch identity was found.
    MEMBER = "member"
    #: No (valid) batch identity: an ordinary job, never a synthetic batch.
    UNGROUPED = "ungrouped"
    #: Identifiers contradict each other; the job is excluded from every batch.
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class BatchKey:
    """Composite logical identity: batch kind plus batch ID (an ID alone is never enough)."""

    kind: BatchKind
    batch_id: str

    @property
    def short_id(self) -> str:
        return short_batch_id(self.batch_id)

    @property
    def label(self) -> str:
        return f"{KIND_LABELS[self.kind]} {self.short_id}"

    def to_token(self) -> str:
        return f"{self.kind.value}:{self.batch_id}"

    @classmethod
    def from_token(cls, token: str) -> BatchKey | None:
        kind_text, separator, batch_id = str(token or "").partition(":")
        if not separator or not batch_id:
            return None
        try:
            return cls(BatchKind(kind_text), batch_id)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class BatchMembership:
    key: BatchKey
    #: Zero-based position among the batch's sources; ``None`` for Review, whose descriptor has none.
    source_index: int | None
    #: Sources the admitting workflow declared. Not a job count.
    declared_source_count: int | None
    #: Which persisted shape supplied the identity (``review_batch`` or ``batch.v1``).
    shape: str


@dataclass(frozen=True, slots=True)
class MembershipResolution:
    state: MembershipState
    membership: BatchMembership | None = None
    reasons: tuple[str, ...] = ()

    @property
    def is_member(self) -> bool:
        return self.state is MembershipState.MEMBER


@dataclass(frozen=True, slots=True)
class ReplayOrigin:
    """Historical (inactive) batch the replayed job's parent belonged to."""

    parent_job_id: str | None
    kind: BatchKind | None
    batch_id: str | None

    @property
    def key(self) -> BatchKey | None:
        if self.kind is None or not self.batch_id:
            return None
        return BatchKey(self.kind, self.batch_id)


def short_batch_id(batch_id: str) -> str:
    return str(batch_id or "")[:8]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _count(value: Any, *, minimum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _resolve_review(descriptor: Mapping[str, Any], top_level: str | None) -> MembershipResolution:
    batch_id = _text(descriptor.get("batch_id"))
    if batch_id is None:
        return MembershipResolution(MembershipState.UNGROUPED, reasons=("review_batch_without_id",))
    if top_level is not None and top_level != batch_id:
        return MembershipResolution(
            MembershipState.AMBIGUOUS, reasons=("review_batch_id_conflicts_with_batch_id",)
        )
    return MembershipResolution(
        MembershipState.MEMBER,
        BatchMembership(
            key=BatchKey(BatchKind.REVIEW, batch_id),
            source_index=None,
            declared_source_count=_count(descriptor.get("source_count"), minimum=1),
            shape=REVIEW_DESCRIPTOR_KEY,
        ),
    )


def _resolve_versioned(descriptor: Mapping[str, Any], top_level: str | None) -> MembershipResolution:
    kind_text = _text(descriptor.get("batch_kind"))
    batch_id = _text(descriptor.get("batch_id"))
    if descriptor.get("schema") != BATCH_SCHEMA:
        return MembershipResolution(MembershipState.UNGROUPED, reasons=("unsupported_batch_schema",))
    if kind_text not in _VERSIONED_KINDS or batch_id is None:
        return MembershipResolution(MembershipState.UNGROUPED, reasons=("invalid_batch_descriptor",))
    index = _count(descriptor.get("source_index"), minimum=0)
    count = _count(descriptor.get("source_count"), minimum=1)
    if index is None or count is None or index >= count:
        return MembershipResolution(MembershipState.UNGROUPED, reasons=("invalid_batch_counts",))
    if top_level is not None and top_level != batch_id:
        return MembershipResolution(
            MembershipState.AMBIGUOUS, reasons=("batch_id_conflicts_with_descriptor",)
        )
    return MembershipResolution(
        MembershipState.MEMBER,
        BatchMembership(
            key=BatchKey(BatchKind(kind_text), batch_id),
            source_index=index,
            declared_source_count=count,
            shape=BATCH_SCHEMA,
        ),
    )


def resolve_batch_membership(metadata: Mapping[str, Any] | None) -> MembershipResolution:
    """Normalize one job's ``provenance.metadata`` into a membership verdict (pure)."""

    data = _mapping(metadata)
    review = data.get(REVIEW_DESCRIPTOR_KEY)
    versioned = data.get(VERSIONED_DESCRIPTOR_KEY)
    top_level = _text(data.get(TOP_LEVEL_BATCH_ID_KEY))
    if isinstance(review, Mapping) and isinstance(versioned, Mapping):
        # Two different descriptors on one record: never guess which one is the real identity.
        return MembershipResolution(MembershipState.AMBIGUOUS, reasons=("multiple_batch_descriptors",))
    if isinstance(review, Mapping):
        return _resolve_review(review, top_level)
    if isinstance(versioned, Mapping):
        return _resolve_versioned(versioned, top_level)
    return MembershipResolution(MembershipState.UNGROUPED, reasons=("no_batch_descriptor",))


def replay_origin_of(metadata: Mapping[str, Any] | None) -> ReplayOrigin | None:
    """The historical batch a replay descended from, read from ``replay_origin`` only."""

    origin = _mapping(_mapping(metadata).get(REPLAY_ORIGIN_KEY))
    if not origin:
        return None
    parent = _text(origin.get("parent_job_id"))
    # The archived descriptors are parsed with the same rules as live ones; a replay origin never grants
    # active membership, it only records where the parent came from.
    archived: dict[str, Any] = {
        key: origin[key] for key in ACTIVE_BATCH_KEYS if key in origin
    }
    resolution = resolve_batch_membership(archived)
    if not resolution.is_member or resolution.membership is None:
        return ReplayOrigin(parent, None, None)
    key = resolution.membership.key
    return ReplayOrigin(parent, key.kind, key.batch_id)


def split_active_membership(
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(metadata without active batch keys, archived active batch keys)``."""

    kept: dict[str, Any] = {}
    archived: dict[str, Any] = {}
    for key, value in _mapping(metadata).items():
        (archived if key in ACTIVE_BATCH_KEYS else kept)[key] = value
    return kept, archived


def build_replay_origin(parent_job_id: str, archived: Mapping[str, Any]) -> dict[str, Any]:
    """The immutable ``replay_origin`` block: the parent's former batch keys, verbatim, never active."""

    origin: dict[str, Any] = {"schema": REPLAY_ORIGIN_SCHEMA, "parent_job_id": parent_job_id}
    origin.update({key: archived[key] for key in ACTIVE_BATCH_KEYS if key in archived})
    return origin


def build_selected_retry_descriptor(
    batch_id: str, *, source_index: int, source_count: int
) -> dict[str, Any]:
    """The ``stablenew.batch.v1`` descriptor for one job of a new selected-retry batch."""

    return {
        "schema": BATCH_SCHEMA,
        "batch_id": batch_id,
        "batch_kind": BatchKind.SELECTED_RETRY.value,
        "source_index": source_index,
        "source_count": source_count,
    }


__all__ = [
    "ACTIVE_BATCH_KEYS",
    "BATCH_SCHEMA",
    "KIND_LABELS",
    "REPLAY_ORIGIN_KEY",
    "REPLAY_ORIGIN_SCHEMA",
    "BatchKey",
    "BatchKind",
    "BatchMembership",
    "MembershipResolution",
    "MembershipState",
    "ReplayOrigin",
    "build_replay_origin",
    "build_selected_retry_descriptor",
    "replay_origin_of",
    "resolve_batch_membership",
    "short_batch_id",
    "split_active_membership",
]
