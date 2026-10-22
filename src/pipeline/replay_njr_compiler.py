"""Pure history-replay compiler for canonical NJRs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from src.pipeline.animatediff_retirement import require_animatediff_not_enabled
from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceDescriptor, SourceKind
from src.pipeline.njr_core_v26 import thaw_json
from src.pipeline.secondary_motion_retirement import require_secondary_motion_not_enabled
from src.queue.batch_membership import (
    REPLAY_ORIGIN_KEY,
    VERSIONED_DESCRIPTOR_KEY,
    build_replay_origin,
    split_active_membership,
)

#: Directives that belong to one execution of a video sequence (resume from a checkpoint, compare with an original
#: run). A replay recomputes the whole frozen plan, so it never inherits them (PR-VID-SEQ-330-CORE).
_RUN_DIRECTIVE_KEYS = ("sequence_resume", "sequence_replay_of")


def _without_run_directives(record: NormalizedJobRecord) -> NormalizedJobRecord:
    if not any(
        key in thaw_json(stage.extra) for stage in record.stage_chain for key in _RUN_DIRECTIVE_KEYS
    ):
        return record
    stages = tuple(
        replace(
            stage,
            extra={k: v for k, v in thaw_json(stage.extra).items() if k not in _RUN_DIRECTIVE_KEYS},
        )
        for stage in record.stage_chain
    )
    config = thaw_json(record.workload.config)
    for stage in record.stage_chain:
        block = config.get(stage.stage_type)
        if isinstance(block, Mapping):
            config[stage.stage_type] = {
                k: v for k, v in block.items() if k not in _RUN_DIRECTIVE_KEYS
            }
    return replace(record, stages=stages, workload=replace(record.workload, config=config))


@dataclass(frozen=True, slots=True)
class ReplayIntent:
    """A persisted NJR selected for a new execution.

    ``batch`` optionally places the new job in a *new* explicitly versioned batch (a selected retry).
    It is never copied from the source record.
    """

    record: NormalizedJobRecord
    parent_artifact_id: str | None = None
    batch: Mapping[str, Any] | None = None


def compile_replay_intent(intent: ReplayIntent, *, id_fn: Any | None = None) -> NormalizedJobRecord:
    """Create a new replay identity without invoking a runner or queue.

    A replay is a new submission, not another original member of the batch its parent belonged to: the
    parent's active batch keys are not inherited. They are preserved verbatim, and inert, under
    ``replay_origin`` so the historical batch stays discoverable.
    """

    parent = _without_run_directives(intent.record)
    # Retired AnimateDiff execution: an enabled stage is never replayed (a disabled placeholder replays unchanged).
    require_animatediff_not_enabled(parent)
    # Retired secondary motion: a parent that enabled it is not replayed either (D8).
    require_secondary_motion_not_enabled(parent)
    inherited, archived = split_active_membership(parent.extra_metadata)
    metadata = {
        **inherited,
        "replay": True,
        "parent_job_id": parent.job_id,
        **({"parent_artifact_id": intent.parent_artifact_id} if intent.parent_artifact_id else {}),
    }
    if archived:
        metadata[REPLAY_ORIGIN_KEY] = build_replay_origin(parent.job_id, archived)
    if intent.batch is not None:
        metadata[VERSIONED_DESCRIPTOR_KEY] = dict(intent.batch)
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
