"""Builder pipeline that converts PromptPack entries into NormalizedJobRecords."""

from __future__ import annotations

import copy
import itertools
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.gui.app_state_v2 import PackJobEntry
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
from src.utils.config import ConfigManager
from src.utils.prompt_pack_utils import get_matrix_slots_dict, load_pack_metadata

_logger = logging.getLogger(__name__)


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
    ) -> None:
        self._config_manager = config_manager
        self._job_builder = job_builder
        self._prompt_resolver = prompt_resolver or UnifiedPromptResolver()
        self._config_resolver = config_resolver or UnifiedConfigResolver()
        self._packs_dir = Path(packs_dir)

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
        metadata = load_pack_metadata(pack_path)
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
        limit = matrix_config.get("limit", 0)
        
        slot_names = list(matrix_slots_dict.keys())
        slot_values_lists = [matrix_slots_dict[name] for name in slot_names]
        
        # Generate combinations based on mode
        if matrix_mode == "random":
            # Random mode: generate N random combinations (each slot independently randomized)
            import random
            target_count = limit if limit > 0 else 10  # Default to 10 if no limit specified
            combinations = []
            for _ in range(target_count):
                # Pick a random value from each slot independently
                combo = tuple(random.choice(slot_values_lists[i]) for i in range(len(slot_names)))
                combinations.append(combo)
            _logger.info(f"[Matrix Expansion] Generated {len(combinations)} random combinations for {entry.pack_id} with slots: {slot_names}")
        else:
            # Sequential mode: generate all Cartesian product combinations
            combinations = list(itertools.product(*slot_values_lists))
            if limit > 0 and len(combinations) > limit:
                combinations = combinations[:limit]
                _logger.info(f"[Matrix Expansion] Limited combinations to {limit} (from {len(combinations)} total)")
            _logger.info(f"[Matrix Expansion] Generating {len(combinations)} sequential combinations for {entry.pack_id} with slots: {slot_names}")
        
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

    def _build_jobs_for_entry(self, entry: PackJobEntry) -> list[NormalizedJobRecord]:
        pack_config = self._load_pack_config(entry.pack_id)
        if pack_config is None:
            _logger.error("Missing config for pack '%s', skipping entry", entry.pack_id)
            return []

        runtime_params = dict(entry.config_snapshot or {})
        merged_config = copy.deepcopy(
            self._config_manager.resolve_config(
                pack_overrides=pack_config, runtime_params=runtime_params
            )
        )
        stage_flags = self._normalize_stage_flags(
            merged_config.get("pipeline", {}), entry.stage_flags or {}
        )
        randomizer_metadata = entry.randomizer_metadata or {}

        stage_chain = self._build_stage_chain(merged_config, stage_flags)
        prompt_resolution = self._resolve_prompt(entry, merged_config)
        config_for_builder = self._build_config_payload(
            entry, merged_config, prompt_resolution, stage_chain
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
            record.positive_embeddings = list(prompt_resolution.positive_embeddings)
            record.negative_embeddings = list(prompt_resolution.negative_embeddings)
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
            record.extra_metadata = dict(merged_config.get("metadata") or {})
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

    def _resolve_prompt(self, entry: PackJobEntry, config: dict[str, Any]) -> Any:
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
            pack_negative=negative_prompt,
            global_negative=self._config_manager.get_global_negative_prompt(),
            apply_global_negative=bool(apply_global),
        )

    def _build_config_payload(
        self,
        entry: PackJobEntry,
        merged_config: dict[str, Any],
        prompt_resolution: Any,
        stage_chain: list[StageConfig],
    ) -> dict[str, Any]:
        txt2img = merged_config.get("txt2img", {})
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
            "aesthetic": merged_config.get("aesthetic"),
        }
        payload["pack_name"] = entry.pack_name or entry.pack_id
        payload["pack_path"] = (
            str(self._resolve_pack_text_path(entry.pack_id))
            if self._resolve_pack_text_path(entry.pack_id)
            else None
        )
        payload["prompt_pack_id"] = entry.pack_id
        payload["prompt_pack_row_index"] = entry.pack_row_index or 0
        payload["matrix_slot_values"] = dict(entry.matrix_slot_values or {})
        return payload

    def _build_stage_chain(
        self, merged_config: dict[str, Any], stage_flags: dict[str, bool]
    ) -> list[StageConfig]:
        stage_sections = {
            "txt2img": merged_config.get("txt2img", {}),
            "img2img": merged_config.get("img2img", {}),
            "adetailer": merged_config.get("adetailer", {}),
            "upscale": merged_config.get("upscale", {}),
        }
        chain: list[StageConfig] = []
        for stage in ("txt2img", "img2img", "adetailer", "upscale"):
            data = stage_sections.get(stage, {}) or {}
            enabled = bool(stage_flags.get(stage, stage == "txt2img"))
            extra: dict[str, Any] = {}
            if stage == "txt2img":
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
                extra.update({
                    "prompt": data.get("adetailer_prompt"),
                    "negative_prompt": data.get("adetailer_negative_prompt"),
                    "adetailer_enabled": data.get("adetailer_enabled"),
                    "adetailer_model": data.get("adetailer_model"),
                    "adetailer_confidence": data.get("adetailer_confidence"),
                    "adetailer_mask_feather": data.get("adetailer_mask_feather"),
                    "adetailer_sampler": data.get("adetailer_sampler"),
                    "adetailer_scheduler": data.get("adetailer_scheduler"),
                    "adetailer_steps": data.get("adetailer_steps"),
                    "adetailer_denoise": data.get("adetailer_denoise"),
                    "adetailer_cfg": data.get("adetailer_cfg"),
                })
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
            stage_cfg = StageConfig(
                stage_type=stage,
                enabled=enabled,
                steps=data.get("steps"),
                cfg_scale=data.get("cfg_scale"),
                denoising_strength=data.get("denoising_strength"),
                sampler_name=data.get("sampler_name") or data.get("sampler"),
                scheduler=data.get("scheduler"),
                model=data.get("model"),
                vae=data.get("vae"),
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

    def _load_pack_rows(self, pack_id: str) -> list[PackRow]:
        """Load and parse pack rows from the pack file."""
        path = self._resolve_pack_text_path(pack_id)
        if not path:
            _logger.warning("Pack file not found for '%s'", pack_id)
            return []
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            _logger.warning("Failed to read prompt pack '%s': %s", pack_id, exc)
            return []
        return parse_prompt_pack_text(content)

    def _load_pack_config(self, pack_id: str) -> dict[str, Any] | None:
        try:
            return self._config_manager.load_pack_config(pack_id)
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
        }
        normalized = dict(defaults)
        for key, value in overrides.items():
            if key in normalized:
                normalized[key] = bool(value)
        return normalized
