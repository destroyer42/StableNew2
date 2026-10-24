"""Pure compiler for "Regenerate with Changes" from a persisted history job (PR-HISTORY-610A).

A variation starts from the *frozen effective recipe* of one persisted single-image txt2img NJR. The operator may change
only the effective positive prompt, the effective negative prompt (where the frozen target profile accepts one), the seed,
the steps and the CFG scale. Every other effective value (checkpoint, VAE, sampler, scheduler, geometry, backend profile,
frozen global prompt policy, hires/refiner settings) is carried forward byte-for-byte; nothing is re-read from a live
PromptPack, re-sampled, or defaulted.

The result is an ordinary new ``NormalizedJobRecord`` on the existing path: a new job identity, ``HISTORY_REPLAY`` lineage
with a content-free ``history_variation`` block that distinguishes an edited variation from an unchanged Replay, and the
same operation-compatibility validation the compiler and queue admission use. It builds no queue, runner or preview; the
accepted ``preview_jobs`` / claim-revision contract (``preview_admission``) stays the only admission authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from src.image_backends.forge_zimage_profile import validate_zimage_njr
from src.image_backends.image_backend_types import resolve_image_backend_id
from src.image_backends.model_policy import Support
from src.image_backends.operation_compatibility import (
    OperationNotSupportedError,
    assess_njr,
    policy_for_njr,
)
from src.pipeline.history_variation_marker import (
    VARIATION_KEY,
    VARIATION_SCHEMA,
    is_history_variation,
)
from src.pipeline.job_models_v2 import (
    NJRProvenance,
    NormalizedJobRecord,
    SourceDescriptor,
    SourceKind,
    StagePromptInfo,
    WorkloadKind,
)
from src.pipeline.njr_core_v26 import thaw_json
from src.prompting.pack_lora_selection import SELECTION_METADATA_KEY
from src.queue.batch_membership import ACTIVE_BATCH_KEYS

EDITABLE_FIELDS = ("positive_prompt", "negative_prompt", "seed", "steps", "cfg_scale")

_SEED_MAX = 4_294_967_295
_SUPPORTED_SOURCE_KINDS = frozenset(
    {SourceKind.PROMPT_PACK, SourceKind.CLI, SourceKind.HISTORY_REPLAY}
)
#: Metadata that describes how the *source* prompt was authored/adapted; it is stale for an edited prompt.
_STALE_PROVENANCE_KEYS = ("prompt_adaptation", "source_prompt_intent", SELECTION_METADATA_KEY)
_STALE_WORKLOAD_KEYS = ("source_prompt_intent",)
_PACK_INTENT_KEYS = ("prompt_pack_id", "plan_origin", "story_plan", "adaptive_refinement")

_FIELD_LABELS = {
    "positive_prompt": "positive prompt",
    "negative_prompt": "negative prompt",
    "seed": "seed",
    "steps": "steps",
    "cfg_scale": "CFG",
}


class HistoryVariationRefused(ValueError):
    """The persisted job cannot be represented as an editable variation; nothing was compiled."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class VariationEdits:
    positive_prompt: str
    negative_prompt: str
    seed: int
    steps: int
    cfg_scale: float


@dataclass(frozen=True)
class HistoryVariationDraft:
    """One unsent variation: the immutable persisted source, its baseline and the operator's current edits."""

    source: NormalizedJobRecord
    baseline: VariationEdits
    edits: VariationEdits
    negative_editable: bool = True
    recorded_seed: int | None = None
    parent_artifact_id: str | None = None

    @classmethod
    def from_source(
        cls,
        source: NormalizedJobRecord,
        *,
        recorded_seed: int | None = None,
        parent_artifact_id: str | None = None,
    ) -> HistoryVariationDraft:
        reasons = variation_refusals(source)
        if reasons:
            raise HistoryVariationRefused(reasons)
        baseline = VariationEdits(
            positive_prompt=str(source.positive_prompt or ""),
            negative_prompt=str(source.negative_prompt or ""),
            seed=int(source.seed if source.seed is not None else -1),
            steps=int(source.steps),
            cfg_scale=float(source.cfg_scale),
        )
        return cls(
            source=source,
            baseline=baseline,
            edits=baseline,
            negative_editable=negative_prompt_editable(source),
            recorded_seed=recorded_seed,
            parent_artifact_id=parent_artifact_id,
        )

    @property
    def source_job_id(self) -> str:
        return self.source.job_id

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in EDITABLE_FIELDS
            if getattr(self.edits, name) != getattr(self.baseline, name)
        )

    def with_edits(self, **changes: Any) -> HistoryVariationDraft:
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"not an editable variation field: {sorted(unknown)}")
        return replace(self, edits=replace(self.edits, **changes))


def negative_prompt_editable(source: NormalizedJobRecord) -> bool:
    """Whether the frozen target profile accepts a negative prompt (an exact profile that forbids one does not)."""

    return policy_for_njr(source).feature("negative_prompt").support is not Support.UNSUPPORTED


def variation_refusals(source: NormalizedJobRecord) -> tuple[str, ...]:
    """Every reason the persisted job is outside the v1 variation envelope (empty means supported)."""

    reasons: list[str] = []
    if source.workload_kind is not WorkloadKind.IMAGE:
        return (
            f"Only still-image jobs can be varied (this is a {source.workload_kind.value} job).",
        )
    if source.source.kind not in _SUPPORTED_SOURCE_KINDS:
        reasons.append(
            f"A {source.source.kind.value.replace('_', ' ')} job is not a text-to-image recipe."
        )
    if source.stage_chain_labels != ["txt2img"]:
        reasons.append(
            "Only a single text-to-image stage can be varied "
            f"(this job enabled: {', '.join(source.stage_chain_labels) or 'nothing'})."
        )
    if source.input_image_paths:
        reasons.append("This job used a source image; Regenerate would not reproduce that input.")
    if source.images_per_prompt != 1 or source.loop_count != 1 or source.loop_type != "pipeline":
        reasons.append("Multi-image or looped jobs cannot be varied.")
    provenance = source.provenance
    if provenance.variant_total != 1 or provenance.batch_total != 1:
        reasons.append("This job is one member of a variant or batch run.")
    if (
        provenance.randomizer_summary.get("enabled")
        or provenance.matrix_slot_values
        or provenance.matrix_name
        or provenance.metadata.get("matrix_expansion")
        or (source.config.get("randomization") or {}).get("enabled")
    ):
        reasons.append(
            "Randomized or Matrix-expanded recipes cannot be represented without re-expanding them."
        )
    if provenance.config_variant_index != 0 or provenance.config_variant_overrides:
        reasons.append("This job is one arm of a configuration sweep.")
    if provenance.learning_context is not None:
        reasons.append("Learning experiment arms are not editable variations.")
    if any(
        key in source.extra_metadata for key in ACTIVE_BATCH_KEYS
    ):  # valid, malformed or ambiguous
        reasons.append("This job belongs to a grouped batch.")
    refinement = source.config.get("adaptive_refinement")
    if isinstance(refinement, Mapping) and (
        refinement.get("enabled") or refinement.get("prompt_patch")
    ):
        reasons.append("Adaptive prompt refinement would rewrite the edited prompt at run time.")
    if not str(source.positive_prompt or "").strip():
        reasons.append("The recorded recipe has no positive prompt.")
    return tuple(reasons)


def validate_edits(draft: HistoryVariationDraft) -> tuple[str, ...]:
    edits, errors = draft.edits, []
    if not edits.positive_prompt.strip():
        errors.append("The positive prompt cannot be empty.")
    if not draft.negative_editable and edits.negative_prompt != draft.baseline.negative_prompt:
        errors.append("The frozen target profile does not accept a negative prompt.")
    if type(edits.seed) is not int or not -1 <= edits.seed <= _SEED_MAX:
        errors.append(f"Seed must be an integer from -1 through {_SEED_MAX}.")
    if type(edits.steps) is not int or not 1 <= edits.steps <= 150:
        errors.append("Steps must be an integer from 1 through 150.")
    if not isinstance(edits.cfg_scale, (int, float)) or isinstance(edits.cfg_scale, bool):
        errors.append("CFG must be a number.")
    elif not 0 <= float(edits.cfg_scale) <= 30:
        errors.append("CFG must be from 0 through 30.")
    return tuple(errors)


def summarize_variation_changes(draft: HistoryVariationDraft) -> tuple[str, ...]:
    """A small deterministic, content-free change list (prompt text is never repeated)."""

    lines: list[str] = []
    for name in draft.changed_fields:
        before, after = getattr(draft.baseline, name), getattr(draft.edits, name)
        if name.endswith("_prompt"):
            delta = len(after) - len(before)
            lines.append(f"{_FIELD_LABELS[name]} edited ({delta:+d} characters)")
        else:
            lines.append(
                f"{_FIELD_LABELS[name]}: {before:g} -> {after:g}"
                if name == "cfg_scale"
                else f"{_FIELD_LABELS[name]}: {before} -> {after}"
            )
    return tuple(lines)


def inherited_settings_summary(source: NormalizedJobRecord) -> tuple[tuple[str, str], ...]:
    """Read-only effective values the variation carries forward unchanged."""

    config = source.config
    raw_pipeline = config.get("pipeline")
    pipeline: Mapping[str, Any] = raw_pipeline if isinstance(raw_pipeline, Mapping) else {}
    optimizer = config.get("prompt_optimizer")
    rows = [
        ("Checkpoint", source.base_model or "-"),
        ("VAE", source.vae or "model default"),
        ("Sampler / scheduler", f"{source.sampler_name or '-'} / {source.scheduler or '-'}"),
        ("Size", f"{source.width}x{source.height}" if source.width and source.height else "-"),
        ("Backend", resolve_image_backend_id(source.backend_options) or "-"),
        (
            "Global prompt terms",
            "applied at run time from the job's frozen policy"
            if (
                pipeline.get("apply_global_positive_txt2img")
                or pipeline.get("apply_global_negative_txt2img")
            )
            else "not applied",
        ),
        (
            "Prompt optimizer",
            "enabled (frozen)"
            if isinstance(optimizer, Mapping) and optimizer.get("enabled")
            else "off",
        ),
    ]
    return tuple((label, str(value)) for label, value in rows)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _set_existing_or(config: dict[str, Any], key: str, value: Any, *, force: bool = False) -> None:
    if key in config or force:
        config[key] = value
    nested = config.get("txt2img")
    if isinstance(nested, dict) and key in nested:
        nested[key] = value


def _reconciled_tags(source: NormalizedJobRecord, positive: str, negative: str) -> dict[str, Any]:
    """Keep only the LoRA/embedding records the edited text still contains (no stale effective-prompt claims)."""

    provenance = source.provenance
    return {
        "positive_embeddings": tuple(e for e in provenance.positive_embeddings if e in positive),
        "negative_embeddings": tuple(e for e in provenance.negative_embeddings if e in negative),
        "lora_tags": tuple(t for t in provenance.lora_tags if f"<lora:{t.name}:" in positive),
    }


def compile_history_variation(
    draft: HistoryVariationDraft, *, id_fn: Callable[[], str] | None = None
) -> NormalizedJobRecord:
    """Compile ``draft`` into one new immutable NJR; raises before producing anything that cannot be admitted."""

    source, edits = draft.source, draft.edits
    reasons = variation_refusals(source)
    if reasons:
        raise HistoryVariationRefused(reasons)
    errors = validate_edits(draft)
    if errors:
        raise ValueError(" ".join(errors))

    config = thaw_json(source.workload.config)
    _set_existing_or(config, "prompt", edits.positive_prompt)
    _set_existing_or(config, "negative_prompt", edits.negative_prompt)
    _set_existing_or(config, "seed", edits.seed, force=True)
    _set_existing_or(config, "steps", edits.steps, force=True)
    _set_existing_or(config, "cfg_scale", float(edits.cfg_scale), force=True)

    stages = tuple(
        replace(stage, steps=edits.steps, cfg_scale=float(edits.cfg_scale))
        if stage.enabled and stage.stage_type == "txt2img"
        else stage
        for stage in source.stages
    )
    intent = thaw_json(source.workload.intent_config)
    for key in _PACK_INTENT_KEYS:
        intent.pop(key, None)
    intent["prompt_source"] = VARIATION_KEY
    workload_metadata = {
        k: v
        for k, v in thaw_json(source.workload.metadata).items()
        if k not in _STALE_WORKLOAD_KEYS
    }
    workload = replace(
        source.workload,
        positive_prompt=edits.positive_prompt,
        negative_prompt=edits.negative_prompt,
        config=config,
        intent_config=intent,
        metadata=workload_metadata,
    )

    changes = {
        name: {"from": getattr(draft.baseline, name), "to": getattr(edits, name)}
        for name in draft.changed_fields
        if not name.endswith("_prompt")
    }
    variation_block = {
        "schema": VARIATION_SCHEMA,
        "parent_job_id": source.job_id,
        "edited_fields": list(draft.changed_fields),
        "scalar_changes": changes,
        "baseline_prompt_digest": _digest(draft.baseline.positive_prompt),
        "edited_prompt_digest": _digest(edits.positive_prompt),
        "baseline_seed_was_random": draft.baseline.seed == -1,
        "origin": {
            "source_kind": source.source.kind.value,
            "prompt_pack_id": source.source.id
            if source.source.kind is SourceKind.PROMPT_PACK
            else None,
            "prompt_pack_name": source.source.display_name,
        },
    }
    provenance_metadata = {
        k: v for k, v in source.extra_metadata.items() if k not in _STALE_PROVENANCE_KEYS
    }
    provenance_metadata.update(parent_job_id=source.job_id, **{VARIATION_KEY: True})
    prompt_info = StagePromptInfo(
        original_prompt=edits.positive_prompt,
        final_prompt=edits.positive_prompt,
        original_negative_prompt=edits.negative_prompt,
        final_negative_prompt=edits.negative_prompt,
        global_negative_applied=False,
        global_negative_terms=None,
    )
    provenance: NJRProvenance = replace(
        source.provenance,
        seed=edits.seed,
        txt2img_prompt_info=prompt_info,
        metadata=provenance_metadata,
        **_reconciled_tags(source, edits.positive_prompt, edits.negative_prompt),
    )
    job = replace(
        source,
        job_id=str((id_fn or (lambda: uuid4().hex))()),
        source=SourceDescriptor(
            kind=SourceKind.HISTORY_REPLAY,
            parent_job_id=source.job_id,
            parent_artifact_id=draft.parent_artifact_id,
            display_name=source.source.display_name,
            metadata={
                "original_source_kind": source.source.kind.value,
                VARIATION_KEY: variation_block,
            },
        ),
        stages=stages,
        workload=workload,
        provenance=provenance,
    )
    # Re-run the current operation policy and the exact-profile admission check on the *edited* record.
    assessment = assess_njr(job)
    if not assessment.ready:
        raise OperationNotSupportedError(assessment)
    validate_zimage_njr(job)
    return job


__all__ = [
    "EDITABLE_FIELDS",
    "VARIATION_KEY",
    "HistoryVariationDraft",
    "HistoryVariationRefused",
    "VariationEdits",
    "compile_history_variation",
    "inherited_settings_summary",
    "is_history_variation",
    "negative_prompt_editable",
    "summarize_variation_changes",
    "validate_edits",
    "variation_refusals",
]
