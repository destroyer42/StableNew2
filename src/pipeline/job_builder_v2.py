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
    NormalizedJobRecord,
    OutputSettings,
    PackUsageInfo,
    StagePromptInfo,
)
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
            batch_settings: Settings for batch expansion.
                If None, defaults to batch_size=1, batch_runs=1.
            output_settings: Settings for output directory and filename.
                If None, defaults to "output" and "{seed}".
            rng_seed: Optional seed for randomizer RNG (for determinism).

        Returns:
            List of NormalizedJobRecord instances in deterministic order:
            - Outer: variant_index ascending (0 to variant_total-1)
            - Inner: batch_index ascending (0 to batch_runs-1)

        Total jobs = len(variants) * batch_runs
        """
        # Apply defaults
        batch = batch_settings or BatchSettings()
        output = output_settings or OutputSettings()

        # Step 1: Generate variants via randomizer
        variant_configs = self._generate_variants(
            base_config, randomization_plan, rng_seed
        )
        variant_total = len(variant_configs)

        # Step 2: Apply seed mode for non-randomized path
        # (Randomizer engine already applies seed mode when plan.enabled is True)
        if randomization_plan is None or not randomization_plan.enabled:
            variant_configs = self._apply_seed_mode_non_randomized(
                variant_configs, randomization_plan
            )

        # Step 3: Expand by batch_runs and build job records
        jobs: list[NormalizedJobRecord] = []

        for variant_index, config_variant in enumerate(variant_configs):
            for batch_index in range(batch.batch_runs):
                # Extract seed from config
                seed = self._extract_seed(config_variant)

                # Build randomizer summary if applicable
                randomizer_summary = None
                if randomization_plan and randomization_plan.enabled:
                    randomizer_summary = self._build_randomizer_summary(
                        randomization_plan, variant_index
                    )

                job = NormalizedJobRecord(
                    job_id=self._id_fn(),
                    config=config_variant,
                    path_output_dir=output.base_output_dir,
                    filename_template=output.filename_template,
                    seed=seed,
                    variant_index=variant_index,
                    variant_total=variant_total,
                    batch_index=batch_index,
                    batch_total=batch.batch_runs,
                    created_ts=self._time_fn(),
                    randomizer_summary=randomizer_summary,
                    txt2img_prompt_info=self._build_stage_prompt_info(config_variant),
                    pack_usage=self._build_pack_usage(config_variant),
                )
                jobs.append(job)

        return jobs

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
