"""Pure history-replay compiler for canonical NJRs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceDescriptor, SourceKind


@dataclass(frozen=True, slots=True)
class ReplayIntent:
    """A persisted NJR selected for a new execution."""

    record: NormalizedJobRecord
    parent_artifact_id: str | None = None


def compile_replay_intent(intent: ReplayIntent, *, id_fn: Any | None = None) -> NormalizedJobRecord:
    """Create a new replay identity without invoking a runner or queue."""

    parent = intent.record
    metadata = {
        **parent.extra_metadata,
        "replay": True,
        "parent_job_id": parent.job_id,
        **({"parent_artifact_id": intent.parent_artifact_id} if intent.parent_artifact_id else {}),
    }
    return replace(
        parent,
        job_id=str((id_fn or (lambda: uuid4().hex))()),
        source=SourceDescriptor(
            kind=SourceKind.HISTORY_REPLAY,
            parent_job_id=parent.job_id,
            parent_artifact_id=intent.parent_artifact_id,
            display_name=parent.source.display_name,
            metadata={
                "original_source_kind": parent.source.kind.value,
                **parent.source.metadata,
            },
        ),
        provenance=replace(parent.provenance, metadata=metadata),
    )


__all__ = ["ReplayIntent", "compile_replay_intent"]
