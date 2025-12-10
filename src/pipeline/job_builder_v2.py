# Subsystem: Pipeline
# Role: Centralized job construction for Pipeline V2.

"""JobBuilderV2: Build normalized job records from merged configs.

This module provides centralized job construction that:
- Accepts already-merged base configs (from ConfigMergerV2)
- Applies randomization via the Randomizer engine
- Applies seed mode semantics
- Expands batch_runs into separate jobs
- Produces NormalizedJobRecord instances

The builder is pure pipeline logic: no GUI, no AppState, no Tkinter.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from src.pipeline.job_models_v2 import (
    BatchSettings,
    JobStatusV2,
    NormalizedJobRecord,
    OutputSettings,
    PackUsageInfo,
    StageConfig,
    StagePromptInfo,
)
from src.pipeline.job_requests_v2 import PipelineRunRequest
from src.pipeline.config_variant_plan_v2 import ConfigVariantPlanV2
from src.randomizer import (
    RandomizationPlanV2,
    RandomizationSeedMode,
    generate_run_config_variants,
)


class JobBuilderV2:
    """Centralized job construction for Pipeline V2.

    Expects already-merged base_config (PromptPack + stage overrides via ConfigMergerV2),
    then applies randomization, seed mode, and batch expansion to produce
    NormalizedJobRecord instances.

    The builder is deterministic when provided with consistent inputs and
    injectable time/id functions for testing.
    """

    def __init__(
        self,
        time_fn: Callable[[], float] | None = None,
        id_fn: Callable[[], str] | None = None,
    ) -> None:
        """Initialize JobBuilderV2.

        Args:
            time_fn: Function to get current timestamp. Defaults to time.time.
            id_fn: Function to generate job IDs. Defaults to uuid4().hex.
        """
        self._time_fn = time_fn or time.time
        self._id_fn = id_fn or (lambda: uuid.uuid4().hex)

    def build_jobs(
        self,
        *,
        base_config: Any,
        randomization_plan: RandomizationPlanV2 | None = None,
        config_variant_plan: ConfigVariantPlanV2 | None = None,
        batch_settings: BatchSettings | None = None,
        output_settings: OutputSettings | None = None,
        rng_seed: int | None = None,
    ) -> list[NormalizedJobRecord]:
        """Build normalized job records from a merged config.

        Args:
            base_config: Already-merged pipeline config (from ConfigMergerV2).
                Can be a dataclass, dict, or any object with model/seed attrs.
            randomization_plan: Optional plan for variant generation.
                If None or disabled, produces a single variant.
            config_variant_plan: Optional plan for config sweeps (PR-CORE-E).
                If None or disabled, uses single base config.
            batch_settings: Settings for batch expansion.
                If None, defaults to batch_size=1, batch_runs=1.
            output_settings: Settings for output directory and filename.
                If None, defaults to "output" and "{seed}".
            rng_seed: Optional seed for randomizer RNG (for determinism).

        Returns:
            List of NormalizedJobRecord instances in deterministic order:
            - Outer: config_variant_index ascending (0 to config_variants-1)
            - Middle: variant_index ascending (0 to variant_total-1)
            - Inner: batch_index ascending (0 to batch_runs-1)

        Total jobs = len(config_variants) * len(matrix_variants) * batch_runs
        """
        # Apply defaults
        batch = batch_settings or BatchSettings()
        output = output_settings or OutputSettings()
        config_plan = config_variant_plan or ConfigVariantPlanV2.single_variant()

        # Step 1: Iterate over config variants (PR-CORE-E)
        jobs: list[NormalizedJobRecord] = []

        for config_variant in config_plan.iter_variants():
            # Apply config variant overrides to base_config
            config_with_overrides = self._apply_config_overrides(
                base_config, config_variant.overrides
            )

            # Step 2: Generate matrix variants via randomizer
            variant_configs = self._generate_variants(
                config_with_overrides, randomization_plan, rng_seed
            )
            variant_total = len(variant_configs)

            # Step 3: Apply seed mode for non-randomized path
            if randomization_plan is None or not randomization_plan.enabled:
                variant_configs = self._apply_seed_mode_non_randomized(
                    variant_configs, randomization_plan
                )

            # Step 4: Expand by batch_runs and build job records
            for variant_index, matrix_config in enumerate(variant_configs):
                for batch_index in range(batch.batch_runs):
                    # Extract seed from config
                    seed = self._extract_seed(matrix_config)

                    # Build randomizer summary if applicable
                    randomizer_summary = None
                    if randomization_plan and randomization_plan.enabled:
                        randomizer_summary = self._build_randomizer_summary(
                            randomization_plan, variant_index
                        )

                    job = NormalizedJobRecord(
                        job_id=self._id_fn(),
                        config=matrix_config,
                        path_output_dir=output.base_output_dir,
                        filename_template=output.filename_template,
                        seed=seed,
                        variant_index=variant_index,
                        variant_total=variant_total,
                        batch_index=batch_index,
                        batch_total=batch.batch_runs,
                        config_variant_label=config_variant.label,
                        config_variant_index=config_variant.index,
                        config_variant_overrides=config_variant.overrides.copy(),
                        created_ts=self._time_fn(),
                        randomizer_summary=randomizer_summary,
                        txt2img_prompt_info=self._build_stage_prompt_info(matrix_config),
                        pack_usage=self._build_pack_usage(matrix_config),
                    )
                    jobs.append(job)

        return jobs

    def build_from_run_request(self, run_request: PipelineRunRequest) -> list[NormalizedJobRecord]:
        """Build normalized jobs directly from a PipelineRunRequest."""
        entries = list(run_request.pack_entries or [])
        if not entries:
            return []
        jobs: list[NormalizedJobRecord] = []
        output_dir = run_request.explicit_output_dir or "output"
        filename_template = "{seed}"
        for index, entry in enumerate(entries[: run_request.max_njr_count]):
            config = entry.config_snapshot or {}
            txt2img_config = config.get("txt2img", {})
            seed = self._extract_config_value(config, "seed") or txt2img_config.get("seed")
            seed_val = int(seed) if seed is not None else None
            stage = StageConfig(
                stage_type="txt2img",
                enabled=True,
                steps=int(txt2img_config.get("steps") or config.get("steps") or 20),
                cfg_scale=float(txt2img_config.get("cfg_scale") or config.get("cfg_scale") or 7.5),
                sampler_name=txt2img_config.get("sampler_name") or config.get("sampler") or "DPM++ 2M",
                scheduler=txt2img_config.get("scheduler") or config.get("scheduler") or "ddim",
                model=txt2img_config.get("model") or config.get("model") or "unknown",
                vae=txt2img_config.get("vae"),
                extra={},
            )
            record = NormalizedJobRecord(
                job_id=self._id_fn(),
                config=config,
                path_output_dir=output_dir,
                filename_template=filename_template,
                seed=seed_val,
                variant_index=0,
                variant_total=1,
                batch_index=0,
                batch_total=1,
                created_ts=self._time_fn(),
                randomizer_summary=entry.randomizer_metadata,
                txt2img_prompt_info=StagePromptInfo(
                    original_prompt=entry.prompt_text or "",
                    final_prompt=entry.prompt_text or "",
                    original_negative_prompt=entry.negative_prompt_text or "",
                    final_negative_prompt=entry.negative_prompt_text or "",
                    global_negative_applied=False,
                ),
                pack_usage=self._build_pack_usage(config),
                prompt_pack_id=run_request.prompt_pack_id,
                prompt_pack_name=entry.pack_name or "",
                prompt_pack_row_index=entry.pack_row_index or 0,
                positive_prompt=entry.prompt_text or "",
                negative_prompt=entry.negative_prompt_text or "",
                positive_embeddings=list(entry.matrix_slot_values.keys()),
                negative_embeddings=[],
                lora_tags=[],
                matrix_slot_values=dict(entry.matrix_slot_values),
                steps=stage.steps or 0,
                cfg_scale=stage.cfg_scale or 0.0,
                width=int(txt2img_config.get("width") or config.get("width") or 1024),
                height=int(txt2img_config.get("height") or config.get("height") or 1024),
                sampler_name=stage.sampler_name or "",
                scheduler=stage.scheduler or "",
                clip_skip=int(config.get("clip_skip", 0) or 0),
                base_model=stage.model or "",
                vae=stage.vae,
                stage_chain=[stage],
                loop_type=config.get("pipeline", {}).get("loop_type", "pipeline"),
                loop_count=int(config.get("pipeline", {}).get("loop_count", 1)),
                images_per_prompt=int(config.get("pipeline", {}).get("images_per_prompt", 1)),
                variant_mode=str(config.get("pipeline", {}).get("variant_mode", "standard")),
                run_mode=run_request.run_mode.name,
                queue_source=run_request.source.name,
                randomization_enabled=bool(config.get("randomization", {}).get("enabled")),
                matrix_name=str(config.get("randomization", {}).get("matrix_name", "")),
                matrix_mode=str(config.get("randomization", {}).get("mode", "")),
                matrix_prompt_mode=str(config.get("randomization", {}).get("prompt_mode", "")),
                config_variant_label="base",
                config_variant_index=0,
                config_variant_overrides={},
                aesthetic_enabled=bool(config.get("aesthetic", {}).get("enabled")),
                aesthetic_weight=config.get("aesthetic", {}).get("weight"),
                aesthetic_text=config.get("aesthetic", {}).get("text"),
                aesthetic_embedding=config.get("aesthetic", {}).get("embedding"),
                extra_metadata={
                    "tags": list(run_request.tags),
                    "selected_row_ids": list(run_request.selected_row_ids),
                    "requested_job_label": run_request.requested_job_label,
                },
                status=JobStatusV2.QUEUED,
            )
            jobs.append(record)
        return jobs

    def _apply_config_overrides(
        self,
        base_config: Any,
        overrides: dict[str, Any],
    ) -> Any:
        """Apply config variant overrides to base config (PR-CORE-E).

        Supports dot-notation paths (e.g., "txt2img.cfg_scale" -> config["txt2img"]["cfg_scale"]).

        Args:
            base_config: Base merged config (dict or object).
            overrides: Dict of dot-path keys to values.

        Returns:
            Deep copy of base_config with overrides applied.
        """
        if not overrides:
            return deepcopy(base_config)

        # Deep copy to avoid mutating base
        config_copy = deepcopy(base_config)

        for path, value in overrides.items():
            # Split dot-notation path
            parts = path.split(".")

            # Navigate to parent container
            current = config_copy
            for part in parts[:-1]:
                if isinstance(current, dict):
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                else:
                    # Object attribute navigation
                    if not hasattr(current, part):
                        # Can't set on frozen dataclass, skip
                        break
                    current = getattr(current, part)

            # Set final value
            final_key = parts[-1]
            if isinstance(current, dict):
                current[final_key] = value
            elif hasattr(current, final_key):
                try:
                    setattr(current, final_key, value)
                except (AttributeError, TypeError):
                    # Frozen or read-only, skip
                    pass

        return config_copy

    def _generate_variants(
        self,
        base_config: Any,
        plan: RandomizationPlanV2 | None,
        rng_seed: int | None,
    ) -> list[Any]:
        """Generate config variants via randomizer engine.

        If plan is None or disabled, returns a single deep copy of base_config.
        """
        if plan is None or not plan.enabled:
            # No randomization - single variant
            return [deepcopy(base_config)]

        # Use randomizer engine
        return generate_run_config_variants(base_config, plan, rng_seed=rng_seed)

    def _apply_seed_mode_non_randomized(
        self,
        configs: list[Any],
        plan: RandomizationPlanV2 | None,
    ) -> list[Any]:
        """Apply seed mode for non-randomized path.

        When randomization is disabled but seed_mode is specified:
        - FIXED: Set all configs to base_seed
        - PER_VARIANT: Increment seed per config
        - NONE: Leave seeds unchanged
        """
        if plan is None or plan.base_seed is None:
            return configs

        # Apply seed mode to each config
        for idx, config in enumerate(configs):
            if plan.seed_mode == RandomizationSeedMode.FIXED:
                self._set_seed(config, plan.base_seed)
            elif plan.seed_mode == RandomizationSeedMode.PER_VARIANT:
                self._set_seed(config, plan.base_seed + idx)
            # NONE: leave seed unchanged

        return configs

    def _extract_seed(self, config: Any) -> int | None:
        """Extract seed value from config (dict or object)."""
        if isinstance(config, dict):
            return config.get("seed")
        return getattr(config, "seed", None)

    def _set_seed(self, config: Any, seed: int) -> None:
        """Set seed value on config (dict or object)."""
        if isinstance(config, dict):
            config["seed"] = seed
        elif hasattr(config, "seed"):
            # Only set if attribute exists (avoid adding to frozen dataclasses)
            try:
                config.seed = seed
            except (AttributeError, TypeError):
                # Frozen dataclass or read-only - can't set
                pass

    def _build_randomizer_summary(
        self,
        plan: RandomizationPlanV2,
        variant_index: int,
    ) -> dict[str, Any]:
        """Build a summary dict of randomization applied."""
        summary: dict[str, Any] = {
            "variant_index": variant_index,
            "seed_mode": plan.seed_mode.value if plan.seed_mode else None,
            "base_seed": plan.base_seed,
            "max_variants": plan.max_variants,
        }

        # Add which fields had choices
        if plan.model_choices:
            summary["model_choices"] = len(plan.model_choices)
        if plan.sampler_choices:
            summary["sampler_choices"] = len(plan.sampler_choices)
        if plan.cfg_scale_values:
            summary["cfg_scale_values"] = len(plan.cfg_scale_values)
        if plan.steps_values:
            summary["steps_values"] = len(plan.steps_values)

        return summary

    def _build_stage_prompt_info(self, config: Any) -> StagePromptInfo:
        """Capture prompt metadata for the txt2img stage."""
        prompt = self._extract_config_value(config, "prompt")
        negative = self._extract_config_value(config, "negative_prompt")
        return StagePromptInfo(
            original_prompt=prompt,
            final_prompt=prompt,
            original_negative_prompt=negative,
            final_negative_prompt=negative,
            global_negative_applied=False,
            global_negative_terms="",
        )

    def _build_pack_usage(self, config: Any) -> list[PackUsageInfo]:
        """Record prompt pack usage metadata if present."""
        pack_name = self._extract_config_value(config, "pack_name")
        if not pack_name:
            return []
        pack_path = self._extract_config_value(config, "pack_path")
        usage = PackUsageInfo(pack_name=pack_name)
        if pack_path:
            usage.pack_path = pack_path
        return [usage]

    @staticmethod
    def _extract_config_value(config: Any, key: str) -> str:
        """Safely extract string value from config dict or object."""
        if isinstance(config, dict):
            value = config.get(key)
        else:
            value = getattr(config, key, None)
        if value is None:
            return ""
        return str(value)


__all__ = ["JobBuilderV2"]
