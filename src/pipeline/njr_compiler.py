"""The single assembly boundary for ``NormalizedJobRecord`` (P4-2).

Source planners (CLI, PromptPack, reprocess, video, Learning, training, history) keep cardinality and source-specific
preparation and hand this module one envelope-shaped draft per record. ``compile_njr`` turns a draft into a record and
``derive_njr`` gives an existing record a new identity; outside the read path (``NormalizedJobRecord.from_dict``,
``migrate_legacy_njr``) nothing else constructs a record or assigns a new ``job_id`` once the P4-2 sequence is complete.

The core changes no behavior: a draft declares how far its values were prepared (``PolicyState``) and which
post-construction checks its route runs today (``CompileCheck``), so a route keeps its own policy order and refusal
timing. Only neutral seams are called here; model-family rules stay behind them. The core takes no service, registry
handle or configuration manager.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from operator import attrgetter
from typing import Any
from uuid import uuid4

from src.image_backends.exact_model_profile import validate_profile_njr
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_policy import apply_model_compile_policy
from src.image_backends.operation_compatibility import require_njr_operation
from src.pipeline.adetailer_profiles import compile_adetailer
from src.pipeline.config_contract_v26 import canonicalize_intent_config
from src.pipeline.exact_profile_effective_config import prepare_effective_config
from src.pipeline.job_models_v2 import (
    CURRENT_NJR_SCHEMA_VERSION,
    ImageWorkloadSpec,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    WorkloadKind,
)
from src.pipeline.njr_core_v26 import Workload, thaw_json
from src.pipeline.retired_execution import require_no_retired_execution


class PolicyState(Enum):
    """How far a draft's values were prepared before assembly."""

    RAW = "raw"  # a merged image configuration; the core applies the fresh-work steps in its fixed order
    EFFECTIVE = (
        "effective"  # the planner already ran the shared steps it runs today, in its own order
    )
    FROZEN = "frozen"  # values come from a validated frozen snapshot; never transformed, equality is verified


class CompileCheck(Enum):
    """A post-construction check a route runs today; a draft lists exactly its route's checks."""

    PROFILE_NJR = "profile_njr"  # validate_profile_njr: the pure exact-profile NJR admission check
    OPERATION = "operation"  # require_njr_operation: operation compatibility of the exact profile
    RETIRED = (
        "retired"  # require_no_retired_execution: retired execution (AnimateDiff, secondary motion)
    )


_CHECKS: Mapping[CompileCheck, Callable[[NormalizedJobRecord], None]] = {
    CompileCheck.PROFILE_NJR: validate_profile_njr,
    CompileCheck.OPERATION: require_njr_operation,
    CompileCheck.RETIRED: require_no_retired_execution,
}


@dataclass(frozen=True, slots=True)
class RawImagePlan:
    """Planner rules a ``RAW`` image draft needs after the shared steps have run on its configuration."""

    stages_for: Callable[[Mapping[str, Any]], tuple[StageConfig, ...]]
    model_name_for: Callable[[Mapping[str, Any]], str | None]


@dataclass(frozen=True, slots=True)
class FrozenExpectation:
    """The frozen values a ``FROZEN`` draft must reproduce, keyed by record attribute path (``workload.config``)."""

    values: Mapping[str, Any]
    message: str


@dataclass(frozen=True, slots=True)
class NjrDraft:
    """Envelope-shaped: the parts of one NJR before validation. Not a configuration IR.

    ``checks`` run in the declared order after construction, so a route's refusal order is unchanged. A ``RAW`` draft
    needs an image workload and ``raw_plan``; a ``FROZEN`` draft needs ``frozen``.
    """

    job_id: str
    workload_kind: WorkloadKind
    source: SourceDescriptor
    workload: Workload
    stages: tuple[StageConfig, ...]
    output_plan: OutputPlan
    provenance: NJRProvenance
    policy_state: PolicyState
    checks: tuple[CompileCheck, ...] = ()
    raw_plan: RawImagePlan | None = None
    frozen: FrozenExpectation | None = None


@dataclass(frozen=True, slots=True)
class NjrDerivation:
    """A new identity for an existing record: what changes; every omitted part is carried over unchanged.

    ``source=None`` keeps the parent's source (a re-identification); a history derivation passes ``history_lineage``.
    """

    job_id: str
    source: SourceDescriptor | None = None
    workload: Workload | None = None
    stages: tuple[StageConfig, ...] | None = None
    provenance: NJRProvenance | None = None
    checks: tuple[CompileCheck, ...] = ()


def mint_job_id(id_fn: Callable[[], Any] | None = None) -> str:
    """The new job identity: ``id_fn()`` when injected, otherwise a random hex id."""

    return str((id_fn or (lambda: uuid4().hex))())


_INHERIT: Any = object()


def history_lineage(
    parent: NormalizedJobRecord,
    *,
    parent_artifact_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    display_name: str | None = _INHERIT,
) -> SourceDescriptor:
    """The ``HISTORY_REPLAY`` source of a record derived from ``parent``.

    ``original_source_kind`` comes first; ``metadata`` is merged after it, so a value the caller passes for the same key
    wins. The display name is the parent's unless one is given (``None`` clears it).
    """

    return SourceDescriptor(
        kind=SourceKind.HISTORY_REPLAY,
        parent_job_id=parent.job_id,
        parent_artifact_id=parent_artifact_id,
        display_name=parent.source.display_name if display_name is _INHERIT else display_name,
        metadata={"original_source_kind": parent.source.kind.value, **(metadata or {})},
    )


def _prepare_raw(draft: NjrDraft) -> NjrDraft:
    """Steps 1-5 for a ``RAW`` image draft: effective config, model policy, ADetailer, backend options, intent.

    The workload's ``config`` is the merged configuration; backend options come from its ``backend_options`` block.
    """

    workload = draft.workload
    if not isinstance(workload, ImageWorkloadSpec) or draft.workload_kind is not WorkloadKind.IMAGE:
        raise ValueError("a RAW draft must carry an image workload")
    if draft.raw_plan is None:
        raise ValueError("a RAW draft needs a raw_plan")
    effective = prepare_effective_config(deepcopy(thaw_json(workload.config)))
    config = apply_model_compile_policy(effective.config)
    config, adetailer_mode = compile_adetailer(config, workload.positive_prompt)
    metadata = dict(thaw_json(draft.provenance.metadata))
    evidence = effective.evidence()
    if evidence:
        metadata["effective_configuration"] = evidence
    if adetailer_mode:
        metadata["adetailer_mode"] = adetailer_mode
    backend_options = normalize_image_backend_options(
        config.get("backend_options"), model_name=draft.raw_plan.model_name_for(config)
    )
    return replace(
        draft,
        workload=replace(
            workload,
            config=config,
            backend_options=backend_options,
            intent_config=canonicalize_intent_config(thaw_json(workload.intent_config)),
        ),
        stages=draft.raw_plan.stages_for(config),
        provenance=replace(draft.provenance, metadata=metadata),
    )


def _verify_frozen(record: NormalizedJobRecord, expectation: FrozenExpectation | None) -> None:
    if expectation is None:
        raise ValueError("a FROZEN draft needs its frozen expectation")
    for path, expected in expectation.values.items():
        if attrgetter(path)(record) != expected:
            raise ValueError(expectation.message)


def _run_checks(record: NormalizedJobRecord, checks: tuple[CompileCheck, ...]) -> None:
    for check in checks:
        _CHECKS[check](record)


def compile_njr(draft: NjrDraft) -> NormalizedJobRecord:
    """Assemble exactly one record from ``draft``, then run its declared checks."""

    if draft.policy_state is PolicyState.RAW:
        draft = _prepare_raw(draft)
    record = NormalizedJobRecord(
        schema_version=CURRENT_NJR_SCHEMA_VERSION,
        job_id=draft.job_id,
        workload_kind=draft.workload_kind,
        source=draft.source,
        workload=draft.workload,
        stages=tuple(draft.stages),
        output_plan=draft.output_plan,
        provenance=draft.provenance,
    )
    if draft.policy_state is PolicyState.FROZEN:
        _verify_frozen(record, draft.frozen)
    _run_checks(record, draft.checks)
    return record


def derive_njr(parent: NormalizedJobRecord, change: NjrDerivation) -> NormalizedJobRecord:
    """A new record with a new identity from ``parent``, then the derivation's declared checks."""

    parts: dict[str, Any] = {
        name: value
        for name, value in (
            ("source", change.source),
            ("workload", change.workload),
            ("stages", change.stages),
            ("provenance", change.provenance),
        )
        if value is not None
    }
    record = replace(parent, job_id=change.job_id, **parts)
    _run_checks(record, change.checks)
    return record


__all__ = [
    "CompileCheck",
    "FrozenExpectation",
    "NjrDerivation",
    "NjrDraft",
    "PolicyState",
    "RawImagePlan",
    "compile_njr",
    "derive_njr",
    "history_lineage",
    "mint_job_id",
]
