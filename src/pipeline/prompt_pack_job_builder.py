"""Builder pipeline that converts PromptPack entries into NormalizedJobRecords."""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from src.conditioning.controlnet import SLOT_FIELD as CONTROLNET_SLOT_FIELD
from src.conditioning.controlnet import FrozenControlNet
from src.conditioning.openpose import SLOT_FIELD as OPENPOSE_SLOT_FIELD
from src.contracts import PackJobEntry
from src.image_backends.forge_klein_lora import LoraResolver
from src.image_backends.forge_klein_profile import klein_selected
from src.image_backends.forge_zimage_profile import (
    validate_zimage_njr,
    zimage_selected,
)
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_policy import (
    FamilyLookup,
    apply_model_compile_policy,
    normalize_profile_owned_values,
)
from src.pipeline import config_contract_v26
from src.pipeline.animatediff_retirement import refuse_enabled_animatediff
from src.pipeline.compile_evidence import CompileEvidence
from src.pipeline.config_contract_v26 import (
    canonicalize_intent_config,
    derive_backend_options,
    extract_adaptive_refinement_intent,
    extract_secondary_motion_intent,
)
from src.pipeline.controlnet_compile import CompiledUnits, compile_units
from src.pipeline.global_prompt_policy import has_frozen_global_prompt_policy
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import (
    CURRENT_NJR_SCHEMA_VERSION,
    BatchSettings,
    ImageWorkloadSpec,
    LoRATag,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    OutputSettings,
    PackUsageInfo,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    WorkloadKind,
)
from src.pipeline.matrix_expansion_plan import (
    SEVERITY_WARNING,
    MatrixExpansionPlan,
    matrix_randomizer_limit_hint,
    plan_matrix_expansion,
)
from src.pipeline.openpose_compile import CompiledConditioning, OpenPoseCompiler
from src.pipeline.prompt_pack_parser import PackRow
from src.pipeline.resolution_layer import (
    PackPromptIntent,
    UnifiedConfigResolver,
    UnifiedPromptResolver,
    adapt_pack_intent,
    compose_global_positive,
)
from src.prompting.pack_lora_selection import (
    SELECTION_METADATA_KEY,
    KleinLoraAssessment,
    KleinLoraSelection,
    KleinSelectionError,
    SelectionChoice,
    applies,
    assess_target_loras,
)
from src.prompting.prompt_adaptation import (
    EFFECT_REWRITTEN,
    OP_PROFILE_VALUE_NORMALIZED,
    SCOPE_CONFIG,
    AdaptationOperation,
)
from src.promptpacks.storage import load_prompt_pack_document, prompt_pack_rows
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode
from src.training.lora_manager import LoRAManager
from src.training.style_lora_manager import StyleLoRAManager
from src.utils.config import ConfigManager
from src.utils.embedding_prompt_utils import render_embedding_reference

_logger = logging.getLogger(__name__)

_TXT2IMG_INACTIVE_HIRES_KEYS = (
    "hr_scale",
    "hr_upscaler",
    "denoising_strength",
    "hr_second_pass_steps",
    "hires_steps",
    "hr_resize_x",
    "hr_resize_y",
)
#: Version of the adaptation manifest frozen into ``NJRProvenance.metadata['prompt_adaptation']``.
PROMPT_ADAPTATION_CONTRACT = "prompt_adaptation/1"


@dataclass
class _PreparedPrompt:
    entry: PackJobEntry
    matrix_index: int
    matrix_count: int
    source_config: dict[str, Any]
    config: dict[str, Any]
    stages: list[StageConfig]
    metadata: dict[str, Any]
    style: dict[str, Any] | None
    intent: PackPromptIntent
    revision: Any = None
    selection: KleinLoraSelection | None = None
    #: Transient (never frozen as text): stored global positive terms and whether the source enabled them, for a target
    #: whose executor cannot apply them (exact Z-Image), and what the profile's own values replaced.
    global_positive: str = ""
    global_positive_enabled: bool = False
    normalizations: tuple[dict[str, Any], ...] = ()
    #: The slot's verified, frozen OpenPose conditioning (PR-IMG-CNET-210); ``None`` when the slot has none.
    conditioning: CompiledConditioning | CompiledUnits | None = None
    #: Content-free expansion evidence for this variant (``MatrixExpansionPlan.provenance``); ``None`` without a Matrix.
    matrix_expansion: dict[str, Any] | None = None


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _txt2img_hires_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("enable_hr") or config.get("hires_enabled"))


def _effective_txt2img_stage_config(config: dict[str, Any]) -> dict[str, Any]:
    effective = dict(config or {})
    if not _txt2img_hires_enabled(effective):
        for key in _TXT2IMG_INACTIVE_HIRES_KEYS:
            effective.pop(key, None)
    return effective


class PromptPackNormalizedJobBuilder:
    """Orchestrates prompt pack → job construction pipeline."""

    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        job_builder: JobBuilderV2,
        prompt_resolver: UnifiedPromptResolver | None = None,
        config_resolver: UnifiedConfigResolver | None = None,
        packs_dir: Path | str | None = None,
        lora_manager: LoRAManager | None = None,
        style_lora_manager: StyleLoRAManager | None = None,
        model_family_lookup: FamilyLookup | None = None,
        lora_resolver: LoraResolver | None = None,
        lora_selection_policy: bool = False,
        selection_review: Any = None,
        openpose_compiler: OpenPoseCompiler | None = None,
    ) -> None:
        self._openpose_compiler = openpose_compiler
        self._config_manager = config_manager
        self._job_builder = job_builder
        self._prompt_resolver = prompt_resolver or UnifiedPromptResolver()
        self._config_resolver = config_resolver or UnifiedConfigResolver()
        self._packs_dir = Path(packs_dir) if packs_dir is not None else config_manager.packs_dir
        self._lora_manager = lora_manager
        self._style_lora_manager = style_lora_manager
        self._model_family_lookup = model_family_lookup
        self._lora_resolver = lora_resolver
        self._lora_selection_policy = lora_selection_policy
        self._selection_review = selection_review
        self._pack_rows_cache: dict[tuple[Any, ...], list[PackRow]] = {}
        self._pack_metadata_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._pack_config_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self._resolved_config_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def build_jobs(self, entries: Iterable[PackJobEntry]) -> list[NormalizedJobRecord]:
        # Convert to list to avoid consuming iterator and to enable length check
        entries_list = copy.deepcopy(list(entries))
        review = self._selection_review
        if hasattr(review, "begin"):
            review = review.begin(entries_list)
        _logger.info(
            f"[PromptPackNormalizedJobBuilder] build_jobs() called with {len(entries_list)} entries"
        )
        records: list[NormalizedJobRecord] = []
        prepared: list[_PreparedPrompt] = []
        entry_count = 0
        # One bounded, read-only evidence context for the whole build: every Matrix variant and LoRA reuses it.
        evidence = CompileEvidence(
            family_lookup=self._model_family_lookup, lora_resolver=self._lora_resolver
        )
        for entry in entries_list:
            entry_count += 1
            if not entry.pack_id:
                _logger.warning("Pack entry missing pack_id, skipping")
                continue

            # Expand entry by matrix combinations from pack JSON
            expanded_entries, matrix_plan, matrix_indexes = self._expand_entry_with_plan(entry)
            _logger.info(
                f"[PromptPackNormalizedJobBuilder] Entry {entry_count} ({entry.pack_id}) expanded to {len(expanded_entries)} variant(s)"
            )

            for matrix_variant_index, expanded_entry in enumerate(expanded_entries):
                prompt = self._prepare_entry(
                    expanded_entry,
                    matrix_variant_index=matrix_variant_index,
                    matrix_variant_count=len(expanded_entries),
                    evidence=evidence,
                )
                if prompt is not None:
                    if matrix_plan is not None and matrix_plan.expands:
                        prompt.matrix_expansion = matrix_plan.provenance(
                            matrix_variant_index, matrix_indexes[matrix_variant_index]
                        )
                    prepared.append(prompt)

        self._freeze_conditioning(prepared, evidence)

        assessments: list[KleinLoraAssessment] = []
        targets: list[_PreparedPrompt] = []
        if self._lora_selection_policy:
            for prompt in prepared:
                policy = evidence.policy_for(self._selected_model_name(prompt.source_config))
                if applies(policy):
                    if hasattr(review, "validate"):
                        review.validate()
                    if prompt.intent.loras:
                        if not assessments and hasattr(review, "notify"):
                            review.notify("Preparing exact PromptPack LoRA evidence in the background...")
                        evidence.prepare_lora_selection(cancelled=getattr(review, "cancelled", None))
                    assessments.append(assess_target_loras(
                        policy, prompt.intent.loras, evidence.lora_evidence,
                        label=f"{prompt.entry.pack_name or prompt.entry.pack_id} / row {prompt.entry.pack_row_index or 0} / variant {prompt.matrix_index + 1}",
                    ))
                    targets.append(prompt)
        choices = [SelectionChoice("auto") for _ in assessments]
        if any(item.requires_choice for item in assessments):
            if review is None:
                raise KleinSelectionError("Multiple verified Klein LoRAs require batch operator selection before admission")
            choices = review(assessments)
            if choices is None:
                raise KleinSelectionError("Klein LoRA selection cancelled; no jobs admitted")
        if len(choices) != len(assessments):
            raise KleinSelectionError("Incomplete batch Klein LoRA decisions; no jobs admitted")
        for prompt, assessment, choice in zip(targets, assessments, choices, strict=True):
            prompt.selection = assessment.choose(choice)
        if assessments and hasattr(review, "validate"):
            review.validate()
        # All evidence and operator decisions are complete before the first NJR exists.
        for prompt in prepared:
            records.extend(self._build_jobs_for_entry(prompt.entry, evidence=evidence, prepared=prompt))

        if assessments and hasattr(review, "validate"):
            review.validate()

        _logger.info(f"[PromptPackNormalizedJobBuilder] Total NJRs generated: {len(records)}")
        return records

    def _expand_entry_by_matrix(self, entry: PackJobEntry) -> list[PackJobEntry]:
        """Expand one entry into one entry per selected Matrix combination (see ``matrix_expansion_plan``).

        A disabled Matrix, or one with no dimension that has both a name and values, returns ``[entry]``.
        """
        return self._expand_entry_with_plan(entry)[0]

    def _expand_entry_with_plan(
        self, entry: PackJobEntry
    ) -> tuple[list[PackJobEntry], MatrixExpansionPlan | None, tuple[int, ...]]:
        """Expanded entries plus the plan and the Cartesian position behind each one."""
        pack_path = self._resolve_pack_json_path(entry.pack_id)
        if not pack_path:
            _logger.debug(f"[Matrix Expansion] No pack path found for {entry.pack_id}, skipping expansion")
            return [entry], None, ()
        metadata = self._load_pack_metadata_cached(pack_path)
        if not metadata:
            _logger.debug(f"[Matrix Expansion] No JSON metadata for {entry.pack_id}, skipping expansion")
            return [entry], None, ()
        pack_data = metadata.get("pack_data", {})
        plan = plan_matrix_expansion(
            pack_data.get("matrix", {}) if isinstance(pack_data, Mapping) else {},
            randomizer_limit=matrix_randomizer_limit_hint(
                entry.randomizer_metadata, entry.config_snapshot
            ),
        )
        for issue in plan.issues:
            if issue.severity == SEVERITY_WARNING:
                _logger.warning("[Matrix Expansion] %s: %s", entry.pack_id, issue.message)
        if not plan.expands:
            _logger.debug(f"[Matrix Expansion] No matrix slots in {entry.pack_id}, skipping expansion")
            return [entry], plan, ()

        indexes = plan.selected_indexes()
        if plan.truncated:
            _logger.info(
                "[Matrix Expansion] %s: %s of %s combinations selected (limit %s from %s)",
                entry.pack_id, plan.selected_count, plan.theoretical_count,
                plan.effective_limit, plan.limit_source,
            )
        names = plan.dimension_names()
        expanded_entries = [
            PackJobEntry(
                pack_id=entry.pack_id,
                pack_name=entry.pack_name,
                pack_row_index=entry.pack_row_index,
                prompt_text=entry.prompt_text,
                negative_prompt_text=entry.negative_prompt_text,
                config_snapshot=entry.config_snapshot,
                stage_flags=entry.stage_flags,
                matrix_slot_values=dict(zip(names, plan.combination_at(index), strict=True)),
                randomizer_metadata=entry.randomizer_metadata,
            )
            for index in indexes
        ]
        return expanded_entries, plan, indexes

    def _prepare_entry(
        self,
        entry: PackJobEntry,
        *,
        matrix_variant_index: int = 0,
        matrix_variant_count: int = 1,
        evidence: CompileEvidence | None = None,
    ) -> _PreparedPrompt | None:
        evidence = evidence or CompileEvidence(
            family_lookup=self._model_family_lookup, lora_resolver=self._lora_resolver
        )
        pack_config = self._load_pack_config(entry.pack_id)

        # BUGFIX: Allow learning experiments without pack config if config_snapshot is provided
        if pack_config is None:
            # Check if this is a learning experiment with full config_snapshot
            if entry.config_snapshot and entry.pack_id.startswith("learning_"):
                # Use config_snapshot as pack_config for learning experiments
                pack_config = {}  # Empty pack_config, will use runtime_params from config_snapshot
            else:
                _logger.error("Missing config for pack '%s', skipping entry", entry.pack_id)
                return None

        runtime_params = dict(entry.config_snapshot or {})
        resolved_cache_key = (
            entry.pack_id,
            self._pack_source_fingerprint(entry.pack_id),
            self._runtime_params_cache_key(runtime_params),
            self._application_defaults_key(),
        )
        cached_resolved = self._resolved_config_cache.get(resolved_cache_key)
        if cached_resolved is None:
            cached_resolved = copy.deepcopy(
                self._config_manager.resolve_config(
                    pack_overrides=pack_config, runtime_params=runtime_params
                )
            )
            self._resolved_config_cache[resolved_cache_key] = copy.deepcopy(cached_resolved)
        # Source intent (what the operator configured) stays separate from the effective executable config: the model
        # compile policy normalizes values (negative, global terms, optimizer) that the adaptation manifest must still see.
        source_config = copy.deepcopy(cached_resolved)
        executable_config = copy.deepcopy(cached_resolved)
        global_positive, global_positive_enabled = "", False
        normalizations: list[dict[str, Any]] = []
        if zimage_selected(source_config):
            # The exact profile's executor cannot apply global positive terms, so the compiler composes them (below),
            # and inherited values the profile owns (sampling, CLIP skip, optimizer, global terms) are replaced by the
            # profile's own in the *executable* configuration only. The source configuration, the saved PromptPack and
            # the structured intent keep the operator's values for adaptation evidence.
            global_positive, global_positive_enabled = self._source_global_positive(source_config)
            normalize_profile_owned_values(executable_config, normalizations)
            for section in (executable_config, executable_config.get("txt2img", {})):
                # Positive execution text is rendered from structured intent later.
                section.pop("prompt", None)
            executable_config.setdefault("pipeline", {})
        merged_config = apply_model_compile_policy(executable_config)
        stage_flags = self._normalize_stage_flags(
            merged_config.get("pipeline", {}), entry.stage_flags or {}
        )

        stage_chain = self._build_stage_chain(merged_config, stage_flags)
        resolved_actors = self._resolve_entry_actors(entry, merged_config)
        resolved_style_lora = self._resolve_style_lora(merged_config)
        record_metadata = self._build_record_metadata(
            merged_config,
            resolved_actors,
            resolved_style_lora,
        )
        intent = self._resolve_source_intent(
            entry,
            source_config,
            merged_config,
            resolved_actors,
            resolved_style_lora,
        )
        return _PreparedPrompt(entry, matrix_variant_index, matrix_variant_count, source_config,
                               merged_config, stage_chain, record_metadata, resolved_style_lora, intent, pack_config.get("version"),
                               global_positive=global_positive, global_positive_enabled=global_positive_enabled,
                               normalizations=tuple(normalizations))

    def _source_global_positive(self, source_config: dict[str, Any]) -> tuple[str, bool]:
        """The stored global positive terms and enablement exactly as the executor would have read them."""

        pipeline = _mapping_dict(source_config.get("pipeline"))
        frozen = has_frozen_global_prompt_policy(source_config)
        text = (
            str(source_config.get("global_positive_prompt") or "")
            if frozen
            else str(self._config_manager.get_global_positive_prompt() or "")
        )
        return text.strip(), bool(pipeline.get("apply_global_positive_txt2img", not frozen))

    def _build_jobs_for_entry(
        self, entry: PackJobEntry, *, matrix_variant_index: int = 0, matrix_variant_count: int = 1,
        evidence: CompileEvidence | None = None, prepared: _PreparedPrompt | None = None,
    ) -> list[NormalizedJobRecord]:
        evidence = evidence or CompileEvidence(family_lookup=self._model_family_lookup, lora_resolver=self._lora_resolver)
        prepared = prepared or self._prepare_entry(entry, matrix_variant_index=matrix_variant_index,
                                                  matrix_variant_count=matrix_variant_count, evidence=evidence)
        if prepared is None:
            return []
        merged_config, record_metadata, resolved_style_lora = prepared.config, prepared.metadata, prepared.style
        stage_chain = prepared.stages
        matrix_variant_index, matrix_variant_count = prepared.matrix_index, prepared.matrix_count
        randomizer_metadata = entry.randomizer_metadata or {}
        pack_config = {"version": prepared.revision}
        adapted = adapt_pack_intent(
            prepared.intent, evidence.policy_for(self._selected_model_name(prepared.source_config)),
            lora_resolver=evidence.lora_evidence, optimizer_enabled=self._optimizer_enabled(prepared.source_config),
            lora_selection=prepared.selection,
            global_positive=prepared.global_positive, apply_global_positive=prepared.global_positive_enabled,
        )
        prompt_resolution, adaptation_plan = self._prompt_resolver.render_intent(adapted.intent), adapted.plan
        if adapted.global_positive:
            prompt_resolution = compose_global_positive(prompt_resolution, adapted.global_positive)
        if prepared.normalizations:
            adaptation_plan = replace(adaptation_plan, changed=True, operations=(
                *adaptation_plan.operations,
                *(AdaptationOperation(OP_PROFILE_VALUE_NORMALIZED, SCOPE_CONFIG, EFFECT_REWRITTEN, change)
                  for change in prepared.normalizations),
            ))
        if prepared.selection is not None:
            # Source actor/style metadata is evidence, never effective LoRA participation.
            record_metadata = copy.deepcopy(record_metadata)
            record_metadata[SELECTION_METADATA_KEY] = prepared.selection.to_dict()
            from src.pipeline.resolution_layer import pack_prompt_intent_to_dict
            record_metadata["source_prompt_intent"] = pack_prompt_intent_to_dict(prepared.intent)
            if "actors" in record_metadata:
                record_metadata["source_actors"] = record_metadata.pop("actors")
            if resolved_style_lora and not any(lora.kind == "style" for lora in adapted.intent.loras):
                resolved_style_lora = {**resolved_style_lora, "applied": False}
                record_metadata["style_lora"] = resolved_style_lora
        # Frozen, content-free adaptation evidence; the effective prompt/embeddings/LoRAs it describes are already in the NJR.
        provenance_metadata = copy.deepcopy(record_metadata)
        provenance_metadata["prompt_adaptation"] = {
            "contract": PROMPT_ADAPTATION_CONTRACT,
            **adaptation_plan.to_diagnostics(),
        }
        if prepared.matrix_expansion is not None:
            provenance_metadata["matrix_expansion"] = copy.deepcopy(prepared.matrix_expansion)
        config_for_builder = self._build_config_payload(
            entry,
            merged_config,
            prompt_resolution,
            stage_chain,
            record_metadata,
            resolved_style_lora,
        )
        if prepared.conditioning is not None:
            # Structured conditioning is frozen next to the other execution settings (never prompt text, never bytes).
            field = CONTROLNET_SLOT_FIELD if isinstance(prepared.conditioning.frozen, FrozenControlNet) else OPENPOSE_SLOT_FIELD
            config_for_builder[field] = prepared.conditioning.frozen.to_config()
            provenance_metadata["conditioning"] = {
                field: {
                    **prepared.conditioning.frozen.evidence(),
                    "target": dict(prepared.conditioning.target),
                }
            }

        randomizer_plan = self._build_randomizer_plan(entry, merged_config)
        batch_settings = self._build_batch_settings(merged_config)

        # Output settings: just specify directory, filenames are handled by runner
        pipeline_section = merged_config.get("pipeline", {})
        base_output_dir = pipeline_section.get("output_dir", "output")
        output_settings = OutputSettings(base_output_dir=base_output_dir)

        jobs = self._job_builder.build_jobs(
            base_config=config_for_builder,
            randomization_plan=randomizer_plan,
            batch_settings=batch_settings,
            output_settings=output_settings,
        )

        pipeline_section = merged_config.get("pipeline", {})
        aesthetic_section = merged_config.get("aesthetic", {})
        matrix_section = merged_config.get("randomization", {}).get("matrix", {})
        pack_path = self._resolve_pack_json_path(entry.pack_id)

        finalized_jobs: list[NormalizedJobRecord] = []
        for record in jobs:
            # JobBuilderV2 numbers variants within one matrix expansion. Matrix
            # expansion happens before final NJR construction, so combine the
            # immutable provenance values without mutating the NJR.
            inner_variant_total = max(1, int(record.variant_total))
            final_variant_total = max(1, matrix_variant_count) * inner_variant_total
            final_variant_index = (
                max(0, matrix_variant_index) * inner_variant_total + record.variant_index
            )
            positive_embeddings = tuple(
                render_embedding_reference(name, weight)
                for name, weight in prompt_resolution.positive_embeddings
            )
            negative_embeddings = tuple(
                render_embedding_reference(name, weight)
                for name, weight in prompt_resolution.negative_embeddings
            )
            lora_tags = tuple(
                LoRATag(name=name, weight=weight) for name, weight in prompt_resolution.lora_tags
            )
            intent_payload = {
                "run_mode": "queue",
                "source": str(entry.learning_metadata.get("submission_source"))
                if isinstance(entry.learning_metadata, dict)
                and entry.learning_metadata.get("submission_source")
                else "add_to_queue",
                "prompt_source": "pack",
                "prompt_pack_id": entry.pack_id,
                "adaptive_refinement": extract_adaptive_refinement_intent(
                    entry.config_snapshot or merged_config
                ),
                "secondary_motion": extract_secondary_motion_intent(
                    entry.config_snapshot or merged_config
                ),
            }
            plan_origin = _mapping_dict(record_metadata.get("plan_origin"))
            story_plan = _mapping_dict(record_metadata.get("story_plan"))
            if plan_origin:
                intent_payload["plan_origin"] = copy.deepcopy(plan_origin)
            if story_plan:
                intent_payload["story_plan"] = copy.deepcopy(story_plan)
            finalized_jobs.append(
                NormalizedJobRecord(
                    schema_version=CURRENT_NJR_SCHEMA_VERSION,
                    job_id=record.job_id,
                    workload_kind=WorkloadKind.IMAGE,
                    source=SourceDescriptor(
                        kind=SourceKind.PROMPT_PACK,
                        id=entry.pack_id,
                        revision=pack_config.get("version"),
                        display_name=entry.pack_name or entry.pack_id,
                        row_index=entry.pack_row_index or 0,
                    ),
                    workload=ImageWorkloadSpec(
                        positive_prompt=prompt_resolution.positive,
                        negative_prompt=prompt_resolution.negative,
                        config=record.config,
                        images_per_prompt=int(pipeline_section.get("images_per_prompt", 1)),
                        loop_type=pipeline_section.get("loop_type", "pipeline"),
                        loop_count=int(pipeline_section.get("loop_count", 1) or 1),
                        variant_mode=(
                            pipeline_section.get("variant_mode", "standard") or "standard"
                        ),
                        intent_config=canonicalize_intent_config(intent_payload),
                        backend_options=normalize_image_backend_options(
                            derive_backend_options(record.config),
                            model_name=str(_mapping_dict(record.config).get("model") or "") or None,
                        ),
                        metadata=copy.deepcopy(record_metadata),
                    ),
                    stages=tuple(copy.deepcopy(stage_chain)),
                    output_plan=OutputPlan(
                        base_output_dir=base_output_dir,
                        filename_template="{seed}",
                    ),
                    provenance=NJRProvenance(
                        seed=record.seed,
                        variant_index=final_variant_index,
                        variant_total=final_variant_total,
                        batch_index=record.batch_index,
                        batch_total=record.batch_total,
                        randomizer_summary={
                            "enabled": bool(
                                randomizer_metadata.get("enabled")
                                or merged_config.get("randomization", {}).get("enabled")
                            ),
                            "max_variants": randomizer_plan.max_variants,
                            "seed_mode": (
                                randomizer_plan.seed_mode.value
                                if randomizer_plan.seed_mode
                                else None
                            ),
                            "base_seed": randomizer_plan.base_seed,
                        },
                        matrix_slot_values=dict(entry.matrix_slot_values or {}),
                        matrix_mode=(prepared.matrix_expansion or {}).get("mode") or matrix_section.get("mode"),
                        matrix_prompt_mode=matrix_section.get("prompt_mode"),
                        matrix_name=matrix_section.get("name"),
                        config_variant_label=record.config_variant_label,
                        config_variant_index=record.config_variant_index,
                        config_variant_overrides=record.config_variant_overrides,
                        positive_embeddings=positive_embeddings,
                        negative_embeddings=negative_embeddings,
                        lora_tags=lora_tags,
                        pack_usage=(
                            PackUsageInfo(
                                pack_name=entry.pack_name or entry.pack_id,
                                pack_path=str(pack_path) if pack_path else None,
                                prompt_index=entry.pack_row_index or 0,
                            ),
                        ),
                        txt2img_prompt_info=record.txt2img_prompt_info,
                        aesthetic_enabled=bool(aesthetic_section.get("enabled")),
                        aesthetic_weight=aesthetic_section.get("weight"),
                        aesthetic_text=aesthetic_section.get("text"),
                        aesthetic_embedding=aesthetic_section.get("embedding"),
                        metadata=copy.deepcopy(provenance_metadata),
                    ),
                )
            )
        for job in finalized_jobs:
            validate_zimage_njr(job)
        return finalized_jobs

    def _resolve_source_intent(
        self,
        entry: PackJobEntry,
        source_config: dict[str, Any],
        config: dict[str, Any],
        resolved_actors: list[dict[str, Any]] | None,
        resolved_style_lora: dict[str, Any] | None,
    ) -> PackPromptIntent:
        """Freeze structured authored intent before target adaptation and operator review.

        ``config`` is the effective (model-compile-policy) config; it receives the legacy global-prompt flag exactly as before.
        """

        pack_row = self._selected_pack_row(entry)
        if pack_row is None:
            pack_row = PackRow(
                embeddings=(),
                quality_line=entry.prompt_text or "",
                subject_template=entry.prompt_text or "",
                lora_tags=(),
                negative_embeddings=(),
                negative_phrases=(entry.negative_prompt_text or "",),
            )
        matrix_values = entry.matrix_slot_values or {}
        pipeline_section = source_config.get("pipeline", {})
        negative_prompt = source_config.get("txt2img", {}).get("negative_prompt", "")
        apply_global = pipeline_section.get("apply_global_negative_txt2img", True)
        global_negative = (
            str(source_config.get("global_negative_prompt") or "")
            if has_frozen_global_prompt_policy(source_config)
            else self._config_manager.get_global_negative_prompt()
        )
        if not has_frozen_global_prompt_policy(config):
            config["global_prompt_policy_source"] = "legacy_runtime_fallback"
        intent = self._prompt_resolver.resolve_intent(
            pack_row=pack_row,
            matrix_slot_values=matrix_values,
            actor_resolutions=resolved_actors,
            style_lora=resolved_style_lora,
            pack_negative=negative_prompt,
            global_negative=global_negative,
            apply_global_negative=bool(apply_global),
        )
        return intent

    def _selected_pack_row(self, entry: PackJobEntry) -> PackRow | None:
        """The structured row this entry compiles (the persisted row index, clamped to the last row), if any."""

        pack_rows = self._load_pack_rows(entry.pack_id)
        if not pack_rows:
            return None
        row_index = entry.pack_row_index or 0
        if row_index >= len(pack_rows):
            row_index = len(pack_rows) - 1
        return pack_rows[row_index]

    def _freeze_conditioning(self, prepared: list[_PreparedPrompt], evidence: CompileEvidence) -> None:
        """Verify and freeze every slot's OpenPose conditioning before any NJR exists (one defect aborts the build)."""

        build = None
        for prompt in prepared:
            row = self._selected_pack_row(prompt.entry)
            raw = getattr(row, "conditioning", None) if row is not None else None
            multi = getattr(row, "controlnet_units", None) if row is not None else None
            if raw is not None and multi is not None:
                raise ValueError("Use either legacy OpenPose or ordered ControlNet units for a slot, not both.")
            if raw is None and multi is None:
                continue
            if build is None:
                if self._openpose_compiler is None:
                    self._openpose_compiler = OpenPoseCompiler()
                # A session per build: library images read here are never reused by a later build.
                build = self._openpose_compiler.begin()
            model_name = self._selected_model_name(prompt.source_config)
            backend_id = normalize_image_backend_options(
                derive_backend_options(prompt.config), model_name=model_name
            )["image"]["backend_id"]
            label = (
                f"PromptPack '{prompt.entry.pack_name or prompt.entry.pack_id}' row "
                f"{(prompt.entry.pack_row_index or 0) + 1}"
                + (f" / variant {prompt.matrix_index + 1}" if prompt.matrix_count > 1 else "")
            )
            if multi is not None:
                prompt.conditioning = compile_units(
                    build, multi,
                    stage_names=tuple(stage.stage_type for stage in prompt.stages if stage.enabled),
                    label=label, model_name=model_name, backend_id=str(backend_id), policy_for=evidence.policy_for,
                )
                continue
            prompt.conditioning = build.compile_slot(
                raw,
                label=label,
                model_name=model_name,
                backend_id=str(backend_id),
                policy_for=evidence.policy_for,
            )

    @staticmethod
    def _selected_model_name(source_config: dict[str, Any]) -> str | None:
        """The checkpoint the work targets: the qualified Klein selection if any, else the txt2img model."""

        txt2img = _mapping_dict(source_config.get("txt2img"))
        if zimage_selected(source_config):
            for container in (txt2img, source_config):
                for key in ("model", "model_name", "sd_model_checkpoint", "base_model"):
                    value = str(container.get(key) or "").strip()
                    if value and zimage_selected({"txt2img": {"model": value}}):
                        return value
        if klein_selected(source_config):
            for container in (txt2img, source_config):
                for key in ("model", "model_name", "sd_model_checkpoint", "base_model"):
                    value = str(container.get(key) or "").strip()
                    if value and klein_selected({"txt2img": {"model": value}}):
                        return value
        return str(txt2img.get("model") or source_config.get("model") or "").strip() or None

    @staticmethod
    def _optimizer_enabled(source_config: dict[str, Any]) -> bool:
        txt2img = _mapping_dict(source_config.get("txt2img"))
        return bool(
            _mapping_dict(source_config.get("prompt_optimizer")).get("enabled")
            or _mapping_dict(txt2img.get("prompt_optimizer")).get("enabled")
        )

    def _resolve_style_lora(self, merged_config: dict[str, Any]) -> dict[str, Any] | None:
        raw_style_lora = merged_config.get("style_lora")
        if not isinstance(raw_style_lora, Mapping):
            return None
        try:
            normalized = config_contract_v26.validate_style_lora_execution_config(
                {"style_lora": raw_style_lora}
            )
            style_payload = _mapping_dict(normalized.get("style_lora"))
        except ValueError as exc:
            return {
                "style_id": str(
                    raw_style_lora.get("style_id") or raw_style_lora.get("name") or ""
                ).strip(),
                "applied": False,
                "available": False,
                "warning": str(exc),
            }
        if not style_payload or not bool(style_payload.get("enabled", True)):
            return None
        if self._style_lora_manager is None:
            self._style_lora_manager = StyleLoRAManager()
        base_model = (
            str(
                _mapping_dict(merged_config.get("txt2img")).get("model")
                or merged_config.get("model")
                or ""
            ).strip()
            or None
        )
        resolved = self._style_lora_manager.resolve_selection(style_payload, base_model=base_model)
        if resolved is None:
            return None
        resolved_payload = resolved.to_dict()
        if not resolved_payload.get("applied") and resolved_payload.get("warning"):
            _logger.warning("[PromptPackNormalizedJobBuilder] %s", resolved_payload["warning"])
        return resolved_payload

    @staticmethod
    def _extract_actor_groups(payload: Any) -> list[Any]:
        data = _mapping_dict(payload)
        if not data:
            return []
        metadata = _mapping_dict(data.get("metadata"))
        groups: list[Any] = []
        for story_plan in (data.get("story_plan"), metadata.get("story_plan")):
            story_plan_payload = _mapping_dict(story_plan)
            if story_plan_payload.get("actors"):
                groups.append(story_plan_payload.get("actors"))
        for plan_origin in (data.get("plan_origin"), metadata.get("plan_origin")):
            plan_origin_payload = _mapping_dict(plan_origin)
            if plan_origin_payload.get("actors"):
                groups.append(plan_origin_payload.get("actors"))
        for actors in (data.get("actors"), metadata.get("actors")):
            if actors:
                groups.append(actors)
        return groups

    def _resolve_entry_actors(
        self,
        entry: PackJobEntry,
        merged_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        actor_items: list[Any] = []
        for payload in (entry.config_snapshot, merged_config):
            for group in self._extract_actor_groups(payload):
                actor_items.extend(list(group or []))
        if not actor_items:
            return []
        if self._lora_manager is None:
            self._lora_manager = LoRAManager()
        return cast(list[dict[str, Any]], list(self._lora_manager.resolve_actors(actor_items)))

    def _build_record_metadata(
        self,
        merged_config: dict[str, Any],
        resolved_actors: list[dict[str, Any]],
        resolved_style_lora: dict[str, Any] | None,
    ) -> dict[str, Any]:
        data = _mapping_dict(merged_config)
        metadata = copy.deepcopy(_mapping_dict(data.get("metadata")))
        plan_origin = _mapping_dict(data.get("plan_origin")) or _mapping_dict(
            metadata.get("plan_origin")
        )
        story_plan = _mapping_dict(data.get("story_plan")) or _mapping_dict(
            metadata.get("story_plan")
        )

        if resolved_actors:
            metadata["actors"] = copy.deepcopy(resolved_actors)
        if plan_origin:
            if resolved_actors and not plan_origin.get("actors"):
                plan_origin = dict(plan_origin)
                plan_origin["actors"] = copy.deepcopy(resolved_actors)
            metadata["plan_origin"] = copy.deepcopy(plan_origin)
        if story_plan:
            metadata["story_plan"] = copy.deepcopy(story_plan)
        if resolved_style_lora:
            metadata["style_lora"] = copy.deepcopy(resolved_style_lora)
        return metadata

    def _build_config_payload(
        self,
        entry: PackJobEntry,
        merged_config: dict[str, Any],
        prompt_resolution: Any,
        stage_chain: list[StageConfig],
        record_metadata: dict[str, Any],
        resolved_style_lora: dict[str, Any] | None,
    ) -> dict[str, Any]:
        txt2img = _effective_txt2img_stage_config(merged_config.get("txt2img", {}))
        pipeline_section = merged_config.get("pipeline", {})
        payload: dict[str, Any] = {
            "prompt": prompt_resolution.positive,
            "negative_prompt": prompt_resolution.negative,
            "model": txt2img.get("model"),
            "sampler": txt2img.get("sampler_name") or txt2img.get("sampler"),
            "scheduler": txt2img.get("scheduler"),
            "steps": txt2img.get("steps"),
            "cfg_scale": txt2img.get("cfg_scale"),
            "width": txt2img.get("width"),
            "height": txt2img.get("height"),
            "seed": txt2img.get("seed"),
            "clip_skip": txt2img.get("clip_skip"),
            "vae": txt2img.get("vae"),
            # Add hires fix settings from txt2img section
            "enable_hr": txt2img.get("enable_hr"),
            "hr_scale": txt2img.get("hr_scale"),
            "hr_upscaler": txt2img.get("hr_upscaler"),
            "hr_second_pass_steps": txt2img.get("hr_second_pass_steps"),
            "denoising_strength": txt2img.get("denoising_strength"),
            "hr_resize_x": txt2img.get("hr_resize_x"),
            "hr_resize_y": txt2img.get("hr_resize_y"),
            "hires_use_base_model": txt2img.get("hires_use_base_model"),
            "hr_checkpoint_name": txt2img.get("hr_checkpoint_name"),
            # Add refiner settings only if use_refiner is True
            "use_refiner": txt2img.get("use_refiner", False),
            **(
                {
                    "refiner_checkpoint": txt2img.get("refiner_checkpoint"),
                    "refiner_switch_at": txt2img.get("refiner_switch_at"),
                }
                if txt2img.get("use_refiner")
                else {}
            ),
            # Add other txt2img settings
            "subseed": txt2img.get("subseed"),
            "subseed_strength": txt2img.get("subseed_strength"),
            "seed_resize_from_h": txt2img.get("seed_resize_from_h"),
            "seed_resize_from_w": txt2img.get("seed_resize_from_w"),
            "restore_faces": txt2img.get("restore_faces"),
            "tiling": txt2img.get("tiling"),
            "do_not_save_samples": txt2img.get("do_not_save_samples"),
            "do_not_save_grid": txt2img.get("do_not_save_grid"),
            # Stage and section references
            "stages": [stage.stage_type for stage in stage_chain if stage.enabled],
            "pipeline": pipeline_section,
            "global_positive_prompt": merged_config.get("global_positive_prompt", ""),
            "global_negative_prompt": merged_config.get("global_negative_prompt", ""),
            "global_prompt_policy_source": merged_config.get("global_prompt_policy_source"),
            "randomization": merged_config.get("randomization"),
            "hires_fix": merged_config.get("hires_fix"),
            "refiner": merged_config.get("refiner"),
            "adetailer": merged_config.get("adetailer"),
            "upscale": merged_config.get("upscale"),
            "animatediff": merged_config.get("animatediff"),
            "video_workflow": merged_config.get("video_workflow"),
            "aesthetic": merged_config.get("aesthetic"),
            "style_lora": copy.deepcopy(resolved_style_lora)
            if resolved_style_lora
            else merged_config.get("style_lora"),
            "metadata": copy.deepcopy(record_metadata),
        }
        actors = record_metadata.get("actors") or []
        if actors:
            payload["actors"] = copy.deepcopy(actors)
        plan_origin = _mapping_dict(record_metadata.get("plan_origin"))
        if plan_origin:
            payload["plan_origin"] = copy.deepcopy(plan_origin)
        story_plan = _mapping_dict(record_metadata.get("story_plan"))
        if story_plan:
            payload["story_plan"] = copy.deepcopy(story_plan)
        payload["pack_name"] = entry.pack_name or entry.pack_id
        payload["pack_path"] = (
            str(self._resolve_pack_json_path(entry.pack_id))
            if self._resolve_pack_json_path(entry.pack_id)
            else None
        )
        payload["prompt_pack_id"] = entry.pack_id
        payload["prompt_pack_row_index"] = entry.pack_row_index or 0
        payload["matrix_slot_values"] = dict(entry.matrix_slot_values or {})
        if not _txt2img_hires_enabled(merged_config.get("txt2img", {})):
            for key in _TXT2IMG_INACTIVE_HIRES_KEYS:
                payload.pop(key, None)
        return payload

    def _build_stage_chain(
        self, merged_config: dict[str, Any], stage_flags: dict[str, bool]
    ) -> list[StageConfig]:
        stage_sections = {
            "txt2img": merged_config.get("txt2img", {}),
            "img2img": merged_config.get("img2img", {}),
            "adetailer": merged_config.get("adetailer", {}),
            "upscale": merged_config.get("upscale", {}),
            "animatediff": merged_config.get("animatediff", {}),
            "video_workflow": merged_config.get("video_workflow", {}),
        }
        chain: list[StageConfig] = []
        for stage in (
            "txt2img",
            "img2img",
            "adetailer",
            "upscale",
            "animatediff",
            "video_workflow",
        ):
            data = stage_sections.get(stage, {}) or {}
            enabled = bool(stage_flags.get(stage, stage == "txt2img"))
            extra: dict[str, Any] = {}
            if stage == "txt2img":
                data = _effective_txt2img_stage_config(data)
                extra.update(
                    {
                        "clip_skip": data.get("clip_skip"),
                        "hr_upscaler": data.get("hr_upscaler"),
                        "refiner_model": merged_config.get("refiner", {}).get("model_name"),
                        "refiner_switch_at": data.get("refiner_switch_at"),
                        "hires_steps": data.get("hires_steps"),
                    }
                )
            if stage in {"img2img", "adetailer"}:
                extra["denoising_strength"] = data.get("denoising_strength") or data.get(
                    "adetailer_denoise"
                )
            if stage == "adetailer":
                extra.update(
                    {
                        key: value
                        for key, value in data.items()
                        if key not in {"model", "vae"} and value not in (None, "", [])
                    }
                )
                extra.update(
                    {
                        "prompt": data.get("adetailer_prompt"),
                        "negative_prompt": data.get("adetailer_negative_prompt"),
                    }
                )
            if stage == "upscale":
                extra.update(
                    {
                        "upscaler": data.get("upscaler"),
                        "upscale_mode": data.get("upscale_mode"),
                        "upscaling_resize": data.get("upscaling_resize"),  # Keep original key name
                        "gfpgan_visibility": data.get("gfpgan_visibility"),
                        "codeformer_visibility": data.get("codeformer_visibility"),
                        "codeformer_weight": data.get("codeformer_weight"),
                    }
                )
            if stage == "animatediff":
                # Inert placeholder settings only: they keep the persisted stage entry byte-compatible.
                extra.update(
                    {
                        "motion_module": data.get("motion_module"),
                        "fps": data.get("fps"),
                        "video_length": data.get("video_length"),
                        "loop_number": data.get("loop_number"),
                        "closed_loop": data.get("closed_loop"),
                        "batch_size": data.get("batch_size"),
                        "stride": data.get("stride"),
                        "overlap": data.get("overlap"),
                        "format": data.get("format"),
                    }
                )
            if stage == "video_workflow":
                extra.update(
                    {
                        "workflow_id": data.get("workflow_id"),
                        "workflow_version": data.get("workflow_version"),
                        "backend_id": data.get("backend_id"),
                        "end_anchor_path": data.get("end_anchor_path"),
                        "mid_anchor_paths": data.get("mid_anchor_paths"),
                        "motion_profile": data.get("motion_profile"),
                    }
                )
            # BUGFIX: ADetailer stage should NOT have model/VAE fields set from config
            # The 'model' in adetailer config refers to detector models (face_yolov8n.pt, mediapipe_face_full, etc.)
            # which are NOT checkpoint models and should not trigger model switching
            if stage == "adetailer":
                stage_model = None
                stage_vae = None
                stage_scheduler = None
            else:
                stage_model = data.get("model")
                stage_vae = data.get("vae")
                stage_scheduler = data.get("scheduler")

            stage_cfg = StageConfig(
                stage_type=stage,
                enabled=enabled,
                steps=data.get("steps"),
                cfg_scale=data.get("cfg_scale"),
                denoising_strength=data.get("denoising_strength"),
                sampler_name=data.get("sampler_name") or data.get("sampler"),
                scheduler=stage_scheduler,
                model=stage_model,
                vae=stage_vae,
                extra={k: v for k, v in extra.items() if v not in (None, "", [])},
            )
            chain.append(stage_cfg)
        # Retired AnimateDiff execution: refuse an enabled stage before any NJR exists. The disabled placeholder
        # every pack carries stays in the chain unchanged.
        refuse_enabled_animatediff(chain)
        return chain

    def _build_batch_settings(self, merged_config: dict[str, Any]) -> BatchSettings:
        pipeline_section = merged_config.get("pipeline", {})
        batch_size = int(pipeline_section.get("images_per_prompt", 1) or 1)
        batch_runs = int(pipeline_section.get("loop_count", 1) or 1)
        return BatchSettings(batch_size=batch_size, batch_runs=batch_runs)

    def _build_randomizer_plan(
        self, entry: PackJobEntry, merged_config: dict[str, Any]
    ) -> RandomizationPlanV2:
        """Build a randomization plan from entry metadata and config."""
        # Check if randomization is enabled in the config
        randomization_enabled = merged_config.get("randomization_enabled", False)
        if not randomization_enabled:
            return RandomizationPlanV2(enabled=False, max_variants=1)

        # Extract randomization parameters from config
        max_variants = merged_config.get("max_variants", 1)
        base_seed = merged_config.get("seed")

        # Determine seed mode
        seed_mode = RandomizationSeedMode.NONE
        if base_seed is not None:
            seed_mode = RandomizationSeedMode.PER_VARIANT

        return RandomizationPlanV2(
            enabled=True,
            max_variants=max_variants,
            seed_mode=seed_mode,
            base_seed=base_seed,
            model_choices=[],
            sampler_choices=[],
            scheduler_choices=[],
        )

    def _resolve_pack_json_path(self, pack_id: str) -> Path | None:
        candidate = Path(pack_id)
        if candidate.is_absolute():
            json_candidate = (
                candidate if candidate.suffix.lower() == ".json" else candidate.with_suffix(".json")
            )
            return json_candidate if json_candidate.exists() else None
        stem = candidate.stem
        path = self._packs_dir / f"{stem}.json"
        return path if path.exists() else None

    @staticmethod
    def _path_fingerprint(path: Path | None) -> tuple[Any, ...]:
        if path is None:
            return ("missing",)
        try:
            stat = path.stat()
            return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        except Exception:
            return (str(path), "missing")

    def _application_defaults_key(self) -> tuple[Any, ...]:
        """Changes when the saved application defaults change, so a cached resolution never outlives them."""
        key = getattr(self._config_manager, "application_defaults_key", None)
        return tuple(key()) if callable(key) else ()

    def _pack_source_fingerprint(self, pack_id: str) -> tuple[Any, ...]:
        json_path = self._resolve_pack_json_path(pack_id)
        return (self._path_fingerprint(json_path),)

    @staticmethod
    def _runtime_params_cache_key(runtime_params: dict[str, Any]) -> str:
        try:
            return json.dumps(runtime_params, sort_keys=True, default=str)
        except Exception:
            return repr(runtime_params)

    def _load_pack_metadata_cached(self, pack_path: Path) -> dict[str, Any]:
        cache_key = (self._path_fingerprint(pack_path),)
        cached = self._pack_metadata_cache.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)
        try:
            metadata = load_prompt_pack_document(pack_path)
        except Exception as exc:
            _logger.warning("Failed to load native PromptPack '%s': %s", pack_path, exc)
            metadata = {}
        self._pack_metadata_cache[cache_key] = copy.deepcopy(metadata)
        return metadata

    def _load_pack_rows(self, pack_id: str) -> list[PackRow]:
        """Load structured prompt rows from the native JSON document."""
        path = self._resolve_pack_json_path(pack_id)
        if not path:
            _logger.warning("Pack file not found for '%s'", pack_id)
            return []
        cache_key = (self._path_fingerprint(path),)
        cached = self._pack_rows_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            document = load_prompt_pack_document(path)
        except Exception as exc:
            _logger.warning("Failed to read prompt pack '%s': %s", pack_id, exc)
            return []
        rows = prompt_pack_rows(document)
        self._pack_rows_cache[cache_key] = list(rows)
        return rows

    def _load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        config_path = self._resolve_pack_json_path(pack_id)
        cache_key = (pack_id, self._path_fingerprint(config_path))
        if cache_key in self._pack_config_cache:
            cached = self._pack_config_cache[cache_key]
            return copy.deepcopy(cached) if isinstance(cached, dict) else cached
        try:
            if config_path is not None:
                loaded = load_prompt_pack_document(config_path).get("preset_data", {})
            else:
                loaded = self._config_manager.load_pack_config(pack_id)
            self._pack_config_cache[cache_key] = copy.deepcopy(loaded)
            return cast(dict[str, Any] | None, loaded)
        except Exception as exc:
            _logger.error("Failed to load pack config for '%s': %s", pack_id, exc)
            return None

    def _normalize_stage_flags(
        self, pipeline_section: dict[str, Any], overrides: dict[str, bool]
    ) -> dict[str, bool]:
        # Get img2img value without default - calculate before dictionary construction
        img2img_val = pipeline_section.get("img2img_enabled")
        img2img_enabled = bool(img2img_val) if img2img_val is not None else False

        defaults = {
            "txt2img": bool(pipeline_section.get("txt2img_enabled", True)),
            "img2img": img2img_enabled,
            "adetailer": bool(pipeline_section.get("adetailer_enabled", False)),
            "upscale": bool(pipeline_section.get("upscale_enabled", False)),
            "animatediff": bool(pipeline_section.get("animatediff_enabled", False)),
            "video_workflow": bool(pipeline_section.get("video_workflow_enabled", False)),
        }
        normalized = dict(defaults)
        for key, value in overrides.items():
            if key in normalized:
                normalized[key] = bool(value)
        return normalized
