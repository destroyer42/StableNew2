"""Pure history-replay compiler for canonical NJRs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.pipeline.animatediff_retirement import require_animatediff_not_enabled
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.pipeline.njr_compiler import NjrDerivation, derive_njr, history_lineage, mint_job_id
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


def _with_run_directives(
    record: NormalizedJobRecord, directives: Mapping[str, Mapping[str, Any]] | None
) -> NormalizedJobRecord:
    """Merge this execution's run directives into the named stage's ``extra`` and its config block."""

    for stage_name, updates in (directives or {}).items():
        stages = tuple(
            replace(stage, extra={**thaw_json(stage.extra), **updates})
            if stage.stage_type == stage_name
            else stage
            for stage in record.stage_chain
        )
        config = thaw_json(record.workload.config)
        if isinstance(config.get(stage_name), Mapping):
            config[stage_name] = {**config[stage_name], **updates}
        record = replace(record, stages=stages, workload=replace(record.workload, config=config))
    return record


@dataclass(frozen=True, slots=True)
class ReplayIntent:
    """A persisted NJR selected for a new execution.

    ``batch`` optionally places the new job in a *new* explicitly versioned batch (a selected retry).
    It is never copied from the source record. ``run_directives`` (stage name -> directive block, such as a sequence
    resume) apply to this execution only; directives inherited from the source record are always dropped first.
    """

    record: NormalizedJobRecord
    parent_artifact_id: str | None = None
    batch: Mapping[str, Any] | None = None
    run_directives: Mapping[str, Mapping[str, Any]] | None = None
    #: Re-run the whole frozen recipe with this seed instead of the recorded one (RG-140 slice 2 "more like this").
    #: Only an image recipe that ``reseed_refusals`` accepts may be reseeded.
    seed: int | None = None


_SEED_MAX = 4_294_967_295


def reseed_refusals(record: NormalizedJobRecord) -> tuple[str, ...]:
    """Why a persisted job's whole recipe cannot be re-run with a new seed (empty means it can).

    A reseed keeps every frozen value, the prompt and every stage after txt2img included, and changes only the seed, so
    unlike an edited variation it may carry a multi-stage chain, batch membership (archived as ``replay_origin``) or a
    Matrix/randomizer expansion (already frozen into the record). Reasons never contain prompt text.
    """

    from src.pipeline.job_models_v2 import WorkloadKind

    if record.workload_kind is not WorkloadKind.IMAGE:
        return ("Only still-image recipes can be re-run with new seeds.",)
    reasons: list[str] = []
    chain = record.stage_chain_labels
    if not chain or chain[0] != "txt2img":
        reasons.append("Only a recipe that starts with text-to-image can be re-run with new seeds.")
    if record.input_image_paths:
        reasons.append(
            "This recipe used a source image; a new seed would not reproduce that input."
        )
    if record.images_per_prompt != 1 or record.loop_count != 1:
        reasons.append("Multi-image or looped recipes cannot be re-run one seed at a time.")
    if record.provenance.learning_context is not None:
        reasons.append("Learning experiment arms are not re-run with new seeds.")
    return tuple(reasons)


def _with_seed(record: NormalizedJobRecord, seed: int) -> NormalizedJobRecord:
    """``record`` with ``seed`` wherever the runner reads one (provenance first, then the txt2img and top-level config)."""

    if type(seed) is not int or not 0 <= seed <= _SEED_MAX:
        raise ValueError(f"Seed must be an integer from 0 through {_SEED_MAX}.")
    refusals = reseed_refusals(record)
    if refusals:
        raise ValueError(" ".join(refusals))
    config = thaw_json(record.workload.config)
    config["seed"] = seed
    nested = config.get("txt2img")
    if isinstance(nested, dict):
        nested["seed"] = seed
    return replace(
        record,
        workload=replace(record.workload, config=config),
        provenance=replace(record.provenance, seed=seed),
    )


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
    directed = _with_run_directives(parent, intent.run_directives)
    source_metadata = dict(parent.source.metadata)
    if intent.seed is not None:
        directed = _with_seed(directed, intent.seed)
        metadata["reseed"] = {"parent_seed": parent.seed}
        source_metadata["reseed"] = True
    return derive_njr(
        directed,
        NjrDerivation(
            job_id=mint_job_id(id_fn),
            source=history_lineage(
                parent,
                parent_artifact_id=intent.parent_artifact_id,
                metadata=source_metadata,
            ),
            provenance=replace(directed.provenance, metadata=metadata),
        ),
    )


__all__ = ["ReplayIntent", "compile_replay_intent", "reseed_refusals"]
