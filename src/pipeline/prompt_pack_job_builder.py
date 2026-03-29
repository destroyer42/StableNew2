"""Builder pipeline that converts PromptPack entries into NormalizedJobRecords."""

from __future__ import annotations

import copy
import itertools
import json
import logging
import random
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.config_contract_v26 import (
    canonicalize_intent_config,
    derive_backend_options,
    extract_adaptive_refinement_intent,
    extract_secondary_motion_intent,
)
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import (
    BatchSettings,
    LoRATag,
    NormalizedJobRecord,
    OutputSettings,
    PackUsageInfo,
    StageConfig,
)
from src.pipeline.prompt_pack_parser import PackRow, parse_prompt_pack_text
from src.pipeline.resolution_layer import UnifiedConfigResolver, UnifiedPromptResolver
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode
from src.training.lora_manager import LoRAManager
from src.utils.config import ConfigManager
from src.utils.embedding_prompt_utils import render_embedding_reference
from src.utils.prompt_pack_utils import get_matrix_slots_dict, load_pack_metadata

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
_DEFAULT_MATRIX_EXPANSION_LIMIT = 8


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
        packs_dir: Path | str = "packs",
        lora_manager: LoRAManager | None = None,
    ) -> None:
        self._config_manager = config_manager
        self._job_builder = job_builder
        self._prompt_resolver = prompt_resolver or UnifiedPromptResolver()
        self._config_resolver = config_resolver or UnifiedConfigResolver()
        self._packs_dir = Path(packs_dir)
        self._lora_manager = lora_manager
        self._pack_rows_cache: dict[tuple[Any, ...], list[PackRow]] = {}
        self._pack_metadata_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._pack_config_cache: dict[tuple[Any, ...], dict[str, Any] | None] = {}
        self._resolved_config_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    def build_jobs(self, entries: Iterable[PackJobEntry]) -> list[NormalizedJobRecord]:
        # Convert to list to avoid consuming iterator and to enable length check
        entries_list = list(entries)
        _logger.info(f"[PromptPackNormalizedJobBuilder] build_jobs() called with {len(entries_list)} entries")
        records: list[NormalizedJobRecord] = []
        entry_count = 0
        for entry in entries_list:
            entry_count += 1
            if not entry.pack_id:
                _logger.warning("Pack entry missing pack_id, skipping")
                continue
            
            # Expand entry by matrix combinations from pack JSON
            expanded_entries = self._expand_entry_by_matrix(entry)
            _logger.info(f"[PromptPackNormalizedJobBuilder] Entry {entry_count} ({entry.pack_id}) expanded to {len(expanded_entries)} variant(s)")
            
            # Track jobs per prompt to renumber variant indices correctly
            jobs_for_this_prompt: list[NormalizedJobRecord] = []
            
            for expanded_entry in expanded_entries:
                jobs = self._build_jobs_for_entry(expanded_entry)
                if jobs:
                    _logger.info(f"[PromptPackNormalizedJobBuilder] Expanded entry produced {len(jobs)} NJR(s)")
                    jobs_for_this_prompt.extend(jobs)
            
            # Renumber variant indices sequentially across all matrix combinations
            if jobs_for_this_prompt:
                self._renumber_variant_indices(jobs_for_this_prompt, len(expanded_entries))
                records.extend(jobs_for_this_prompt)
        
        _logger.info(f"[PromptPackNormalizedJobBuilder] Total NJRs generated: {len(records)}")
        return records

    def _renumber_variant_indices(
        self, jobs: list[NormalizedJobRecord], matrix_combinations_count: int
    ) -> None:
        """Renumber variant indices sequentially across matrix combinations.
        
        When matrix expansion creates multiple combinations, each combination produces
        jobs with variant_index starting at 0. This method renumbers them sequentially
        so that matrix combination 1 gets v01-v0N, combination 2 gets v(N+1)-v(2N), etc.
        
        Args:
            jobs: List of NJRs to renumber (modified in place)
            matrix_combinations_count: Number of matrix combinations that were expanded
        """
        if matrix_combinations_count <= 1:
            # No matrix expansion, variants are already numbered correctly
            return
        
        # Group jobs by their original variant_index to preserve batch grouping
        # Jobs are ordered: [matrix1_variant0_batch0, matrix1_variant0_batch1, ..., matrix2_variant0_batch0, ...]
        jobs_per_combination = len(jobs) // matrix_combinations_count
        
        # Renumber: each matrix combination gets sequential variant indices
        for i, job in enumerate(jobs):
            matrix_combo_index = i // jobs_per_combination
            job.variant_index = matrix_combo_index
            job.variant_total = matrix_combinations_count
            _logger.debug(f"[Variant Renumber] Job {i}: variant_index={job.variant_index}, variant_total={job.variant_total}")

    def _expand_entry_by_matrix(self, entry: PackJobEntry) -> list[PackJobEntry]:
        """Expand a single entry into multiple entries based on pack JSON matrix slots.
        
        If the pack has matrix slots defined in its JSON metadata:
        1. Load pack JSON metadata
        2. Extract matrix slots (e.g., {"job": ["wizard", "knight"], "env": ["forest", "castle"]})
        3. Generate all combinations (Cartesian product)
        4. Create one entry per combination with matrix_slot_values set
        
        If no matrix or matrix disabled, returns [entry] unchanged.
        
        Args:
            entry: Original PackJobEntry
            
        Returns:
            List of PackJobEntry, one per matrix combination
        """
        # Resolve pack path
        pack_path = self._resolve_pack_text_path(entry.pack_id)
        if not pack_path:
            _logger.debug(f"[Matrix Expansion] No pack path found for {entry.pack_id}, skipping expansion")
            return [entry]
        
        # Load pack JSON metadata
        metadata = self._load_pack_metadata_cached(pack_path)
        if not metadata:
            _logger.debug(f"[Matrix Expansion] No JSON metadata for {entry.pack_id}, skipping expansion")
            return [entry]
        
        # Extract matrix slots
        matrix_slots_dict = get_matrix_slots_dict(metadata)
        if not matrix_slots_dict:
            _logger.debug(f"[Matrix Expansion] No matrix slots in {entry.pack_id}, skipping expansion")
            return [entry]
        
        # Check matrix config for mode
        pack_data = metadata.get("pack_data", {})
        matrix_config = pack_data.get("matrix", {})
        matrix_mode = matrix_config.get("mode", "sequential")
        limit = self._resolve_matrix_expansion_limit(entry, matrix_config, matrix_slots_dict)

        slot_names = list(matrix_slots_dict.keys())
        slot_values_lists = [matrix_slots_dict[name] for name in slot_names]
        total_combinations = self._estimate_matrix_combinations(slot_values_lists)

        # Generate combinations based on mode
        if matrix_mode == "random":
            target_count = min(total_combinations, limit) if limit > 0 else min(
                total_combinations,
                _DEFAULT_MATRIX_EXPANSION_LIMIT,
            )
            combinations = self._sample_random_matrix_combinations(
                slot_values_lists,
                target_count,
                total_combinations,
            )
            _logger.info(
                "[Matrix Expansion] Generated %s random combinations for %s with slots: %s "
                "(total_possible=%s, effective_limit=%s)",
                len(combinations),
                entry.pack_id,
                slot_names,
                total_combinations,
                target_count,
            )
        else:
            effective_limit = min(total_combinations, limit) if limit > 0 else total_combinations
            combinations = list(itertools.islice(itertools.product(*slot_values_lists), effective_limit))
            if total_combinations > effective_limit:
                _logger.info(
                    "[Matrix Expansion] Limited combinations to %s (from %s total) for %s",
                    effective_limit,
                    total_combinations,
                    entry.pack_id,
                )
            _logger.info(
                "[Matrix Expansion] Generating %s sequential combinations for %s with slots: %s "
                "(total_possible=%s)",
                len(combinations),
                entry.pack_id,
                slot_names,
                total_combinations,
            )
        
        # Create one entry per combination
        expanded_entries = []
        for combo in combinations:
            # Build matrix_slot_values dict for this combination
            matrix_values = {name: value for name, value in zip(slot_names, combo)}
            
            # Create a copy of the entry with matrix_slot_values set
            expanded_entry = PackJobEntry(
                pack_id=entry.pack_id,
                pack_name=entry.pack_name,
                pack_row_index=entry.pack_row_index,
                prompt_text=entry.prompt_text,
                negative_prompt_text=entry.negative_prompt_text,
                config_snapshot=entry.config_snapshot,
                stage_flags=entry.stage_flags,
                matrix_slot_values=matrix_values,  # Set the matrix values for this combination
                randomizer_metadata=entry.randomizer_metadata,
            )
            expanded_entries.append(expanded_entry)
        
        return expanded_entries

    def _estimate_matrix_combinations(self, slot_values_lists: list[list[str]]) -> int:
        total = 1
        for values in slot_values_lists:
            total *= max(1, len(values))
        return total

    def _resolve_matrix_expansion_limit(
        self,
        entry: PackJobEntry,
        matrix_config: dict[str, Any],
        matrix_slots_dict: dict[str, list[str]],
    ) -> int:
        raw_limit = matrix_config.get("limit")
        try:
            configured_limit = max(int(raw_limit or 0), 0)
        except Exception:
            configured_limit = 0

        if configured_limit > 0:
            return configured_limit

        randomizer_limit = 0
        randomizer_meta = entry.randomizer_metadata or {}
        try:
            randomizer_limit = max(int(randomizer_meta.get("max_variants") or 0), 0)
        except Exception:
            randomizer_limit = 0
        if randomizer_limit <= 0:
            randomization_cfg = (entry.config_snapshot or {}).get("randomization", {})
            if isinstance(randomization_cfg, dict):
                try:
                    randomizer_limit = max(int(randomization_cfg.get("max_variants") or 0), 0)
                except Exception:
                    randomizer_limit = 0

        slot_values_lists = [matrix_slots_dict[name] for name in matrix_slots_dict.keys()]
        total_combinations = self._estimate_matrix_combinations(slot_values_lists)
        auto_limit = randomizer_limit if randomizer_limit > 0 else _DEFAULT_MATRIX_EXPANSION_LIMIT

        if total_combinations > auto_limit:
            _logger.warning(
                "[Matrix Expansion] Pack %s has %s possible combinations with no safe matrix.limit; "
                "auto-limiting expansion to %s. Set pack_data.matrix.limit to override.",
                entry.pack_id,
                total_combinations,
                auto_limit,
            )
        return auto_limit

    def _sample_random_matrix_combinations(
        self,
        slot_values_lists: list[list[str]],
        target_count: int,
        total_combinations: int,
    ) -> list[tuple[str, ...]]:
        if target_count <= 0 or total_combinations <= 0:
            return []
        if target_count >= total_combinations:
            return list(itertools.product(*slot_values_lists))

        sampled_indexes = random.sample(range(total_combinations), target_count)
        sampled_indexes.sort()
        return [self._decode_matrix_combination_index(index, slot_values_lists) for index in sampled_indexes]

    def _decode_matrix_combination_index(
        self,
        index: int,
        slot_values_lists: list[list[str]],
    ) -> tuple[str, ...]:
        values: list[str] = []
        remaining = index
        for slot_values in reversed(slot_values_lists):
            slot_size = max(1, len(slot_values))
            remaining, position = divmod(remaining, slot_size)
            values.append(slot_values[position])
        values.reverse()
        return tuple(values)

    def _build_jobs_for_entry(self, entry: PackJobEntry) -> list[NormalizedJobRecord]:
        pack_config = self._load_pack_config(entry.pack_id)
        
        # BUGFIX: Allow learning experiments without pack config if config_snapshot is provided
        if pack_config is None:
            # Check if this is a learning experiment with full config_snapshot
            if entry.config_snapshot and entry.pack_id.startswith("learning_"):
                # Use config_snapshot as pack_config for learning experiments
                pack_config = {}  # Empty pack_config, will use runtime_params from config_snapshot
            else:
                _logger.error("Missing config for pack '%s', skipping entry", entry.pack_id)
                return []

        runtime_params = dict(entry.config_snapshot or {})
        resolved_cache_key = (
            entry.pack_id,
            self._pack_source_fingerprint(entry.pack_id),
            self._runtime_params_cache_key(runtime_params),
        )
        cached_resolved = self._resolved_config_cache.get(resolved_cache_key)
        if cached_resolved is None:
            cached_resolved = copy.deepcopy(
                self._config_manager.resolve_config(
                    pack_overrides=pack_config, runtime_params=runtime_params
                )
            )
            self._resolved_config_cache[resolved_cache_key] = copy.deepcopy(cached_resolved)
        merged_config = copy.deepcopy(cached_resolved)
        stage_flags = self._normalize_stage_flags(
            merged_config.get("pipeline", {}), entry.stage_flags or {}
        )
        randomizer_metadata = entry.randomizer_metadata or {}

        stage_chain = self._build_stage_chain(merged_config, stage_flags)
        resolved_actors = self._resolve_entry_actors(entry, merged_config)
        record_metadata = self._build_record_metadata(merged_config, resolved_actors)
        prompt_resolution = self._resolve_prompt(entry, merged_config, resolved_actors)
        config_for_builder = self._build_config_payload(
            entry, merged_config, prompt_resolution, stage_chain, record_metadata
        )

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
        txt2img = merged_config.get("txt2img", {})
        pack_path = self._resolve_pack_text_path(entry.pack_id)

        for record in jobs:
            record.prompt_pack_id = entry.pack_id
            record.prompt_pack_name = entry.pack_name or entry.pack_id
            record.prompt_pack_row_index = entry.pack_row_index or 0
            record.prompt_pack_version = pack_config.get("version")
            record.positive_prompt = prompt_resolution.positive
            record.negative_prompt = prompt_resolution.negative
            record.positive_embeddings = [
                render_embedding_reference(name, weight)
                for name, weight in prompt_resolution.positive_embeddings
            ]
            record.negative_embeddings = [
                render_embedding_reference(name, weight)
                for name, weight in prompt_resolution.negative_embeddings
            ]
            record.lora_tags = [
                LoRATag(name=name, weight=weight) for name, weight in prompt_resolution.lora_tags
            ]
            record.matrix_slot_values = dict(entry.matrix_slot_values or {})
            record.stage_chain = copy.deepcopy(stage_chain)
            record.steps = int(txt2img.get("steps") or 0)
            record.cfg_scale = float(txt2img.get("cfg_scale") or 0.0)
            record.width = int(txt2img.get("width") or 0)
            record.height = int(txt2img.get("height") or 0)
            record.sampler_name = txt2img.get("sampler_name") or txt2img.get("sampler") or ""
            record.scheduler = txt2img.get("scheduler") or ""
            record.clip_skip = int(txt2img.get("clip_skip") or 0)
            record.base_model = txt2img.get("model") or ""
            record.vae = txt2img.get("vae") or None
            record.images_per_prompt = int(pipeline_section.get("images_per_prompt", 1))
            record.loop_type = pipeline_section.get("loop_type", "pipeline")
            record.loop_count = int(pipeline_section.get("loop_count", 1) or 1)
            record.variant_mode = pipeline_section.get("variant_mode", "standard") or "standard"
            record.randomization_enabled = bool(
                randomizer_metadata.get("enabled")
                or merged_config.get("randomization", {}).get("enabled")
            )
            record.matrix_mode = matrix_section.get("mode")
            record.matrix_prompt_mode = matrix_section.get("prompt_mode")
            record.matrix_name = matrix_section.get("name")
            record.aesthetic_enabled = bool(aesthetic_section.get("enabled"))
            record.aesthetic_weight = aesthetic_section.get("weight")
            record.aesthetic_text = aesthetic_section.get("text")
            record.aesthetic_embedding = aesthetic_section.get("embedding")
            record.extra_metadata = copy.deepcopy(record_metadata)
            intent_payload = {
                "run_mode": record.run_mode.lower(),
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
            record.intent_config = canonicalize_intent_config(intent_payload)
            record.backend_options = derive_backend_options(record.config)
            record.pack_usage = [
                PackUsageInfo(
                    pack_name=record.prompt_pack_name,
                    pack_path=str(pack_path) if pack_path else None,
                    prompt_index=record.prompt_pack_row_index,
                )
            ]
            record.randomizer_summary = {
                "enabled": randomizer_plan.enabled,
                "max_variants": randomizer_plan.max_variants,
                "seed_mode": randomizer_plan.seed_mode.value if randomizer_plan.seed_mode else None,
                "base_seed": randomizer_plan.base_seed,
            }
        return jobs

    def _resolve_prompt(
        self,
        entry: PackJobEntry,
        config: dict[str, Any],
        resolved_actors: list[dict[str, Any]] | None = None,
    ) -> Any:
        pack_rows = self._load_pack_rows(entry.pack_id)
        row_index = entry.pack_row_index or 0
        pack_row = None
        if pack_rows:
            if row_index >= len(pack_rows):
                row_index = len(pack_rows) - 1
            pack_row = pack_rows[row_index]
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
        pipeline_section = config.get("pipeline", {})
        negative_prompt = config.get("txt2img", {}).get("negative_prompt", "")
        apply_global = pipeline_section.get("apply_global_negative_txt2img", True)
        return self._prompt_resolver.resolve_from_pack(
            pack_row=pack_row,
            matrix_slot_values=matrix_values,
            actor_resolutions=resolved_actors,
            pack_negative=negative_prompt,
            global_negative=self._config_manager.get_global_negative_prompt(),
            apply_global_negative=bool(apply_global),
        )

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
        return self._lora_manager.resolve_actors(actor_items)

    def _build_record_metadata(
        self,
        merged_config: dict[str, Any],
        resolved_actors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        data = _mapping_dict(merged_config)
        metadata = copy.deepcopy(_mapping_dict(data.get("metadata")))
        plan_origin = _mapping_dict(data.get("plan_origin")) or _mapping_dict(metadata.get("plan_origin"))
        story_plan = _mapping_dict(data.get("story_plan")) or _mapping_dict(metadata.get("story_plan"))

        if resolved_actors:
            metadata["actors"] = copy.deepcopy(resolved_actors)
        if plan_origin:
            if resolved_actors and not plan_origin.get("actors"):
                plan_origin = dict(plan_origin)
                plan_origin["actors"] = copy.deepcopy(resolved_actors)
            metadata["plan_origin"] = copy.deepcopy(plan_origin)
        if story_plan:
            metadata["story_plan"] = copy.deepcopy(story_plan)
        return metadata

    def _build_config_payload(
        self,
        entry: PackJobEntry,
        merged_config: dict[str, Any],
        prompt_resolution: Any,
        stage_chain: list[StageConfig],
        record_metadata: dict[str, Any],
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
            **({"refiner_checkpoint": txt2img.get("refiner_checkpoint"),
                "refiner_switch_at": txt2img.get("refiner_switch_at")}
               if txt2img.get("use_refiner") else {}),
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
            "randomization": merged_config.get("randomization"),
            "hires_fix": merged_config.get("hires_fix"),
            "refiner": merged_config.get("refiner"),
            "adetailer": merged_config.get("adetailer"),
            "upscale": merged_config.get("upscale"),
            "animatediff": merged_config.get("animatediff"),
            "video_workflow": merged_config.get("video_workflow"),
            "aesthetic": merged_config.get("aesthetic"),
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
            str(self._resolve_pack_text_path(entry.pack_id))
            if self._resolve_pack_text_path(entry.pack_id)
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
        for stage in ("txt2img", "img2img", "adetailer", "upscale", "animatediff", "video_workflow"):
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

    def _resolve_pack_text_path(self, pack_id: str) -> Path | None:
        candidate = Path(pack_id)
        if candidate.is_absolute():
            if candidate.exists():
                return candidate
        base = Path(pack_id)
        stem = base.stem
        extensions = [".txt", ".tsv"]
        candidates = []
        if base.suffix:
            candidates.append(self._packs_dir / pack_id)
        else:
            for ext in extensions:
                candidates.append(self._packs_dir / f"{stem}{ext}")
        for path in candidates:
            if path.exists():
                return path
        return None

    @staticmethod
    def _path_fingerprint(path: Path | None) -> tuple[Any, ...]:
        if path is None:
            return ("missing",)
        try:
            stat = path.stat()
            return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        except Exception:
            return (str(path), "missing")

    def _pack_source_fingerprint(self, pack_id: str) -> tuple[Any, ...]:
        text_path = self._resolve_pack_text_path(pack_id)
        json_path = text_path.with_suffix(".json") if text_path is not None else None
        return (self._path_fingerprint(text_path), self._path_fingerprint(json_path))

    @staticmethod
    def _runtime_params_cache_key(runtime_params: dict[str, Any]) -> str:
        try:
            return json.dumps(runtime_params, sort_keys=True, default=str)
        except Exception:
            return repr(runtime_params)

    def _load_pack_metadata_cached(self, pack_path: Path) -> dict[str, Any]:
        json_path = pack_path.with_suffix(".json")
        cache_key = (self._path_fingerprint(json_path),)
        cached = self._pack_metadata_cache.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)
        metadata = load_pack_metadata(pack_path)
        self._pack_metadata_cache[cache_key] = copy.deepcopy(metadata)
        return metadata

    def _load_pack_rows(self, pack_id: str) -> list[PackRow]:
        """Load and parse pack rows from the pack file."""
        path = self._resolve_pack_text_path(pack_id)
        if not path:
            _logger.warning("Pack file not found for '%s'", pack_id)
            return []
        cache_key = (self._path_fingerprint(path),)
        cached = self._pack_rows_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            _logger.warning("Failed to read prompt pack '%s': %s", pack_id, exc)
            return []
        rows = parse_prompt_pack_text(content)
        self._pack_rows_cache[cache_key] = list(rows)
        return rows

    def _load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        config_path_getter = getattr(self._config_manager, "_pack_config_path", None)
        config_path = config_path_getter(pack_id) if callable(config_path_getter) else None
        cache_key = (pack_id, self._path_fingerprint(config_path))
        if cache_key in self._pack_config_cache:
            cached = self._pack_config_cache[cache_key]
            return copy.deepcopy(cached) if isinstance(cached, dict) else cached
        try:
            loaded = self._config_manager.load_pack_config(pack_id)
            self._pack_config_cache[cache_key] = copy.deepcopy(loaded)
            return loaded
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
