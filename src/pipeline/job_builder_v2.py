# Subsystem: Pipeline
# Role: Centralized job construction for Pipeline V2.

"""JobBuilderV2: the expansion planner for merged image configurations, and the generic (Pipeline tab) route.

``plan_expansion`` owns cardinality: config variants, randomizer variants, seed mode and batch runs, returned as one
``ExpansionItem`` per record with its configuration and indexes. ``build_jobs`` turns each item into a ``RAW`` draft
that ``njr_compiler.compile_njr`` assembles (the core runs the shared steps once per record). The PromptPack builder
consumes ``plan_expansion`` directly and builds its own ``EFFECTIVE`` drafts.

The builder is pure pipeline logic: no GUI, no AppState, no Tkinter.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any

from src.pipeline.config_variant_plan_v2 import ConfigVariant, ConfigVariantPlanV2
from src.pipeline.job_models_v2 import (
    BatchSettings,
    ImageWorkloadSpec,
    NJRProvenance,
    NormalizedJobRecord,
    OutputPlan,
    OutputSettings,
    PackUsageInfo,
    SourceDescriptor,
    SourceKind,
    StageConfig,
    StagePromptInfo,
    WorkloadKind,
)
from src.pipeline.njr_compiler import (
    CompileCheck,
    NjrDraft,
    PolicyState,
    RawImagePlan,
    compile_njr,
)
from src.randomizer import (
    RandomizationPlanV2,
    RandomizationSeedMode,
    generate_run_config_variants,
)


@dataclass(frozen=True, slots=True)
class ExpansionItem:
    """One record's place in an expansion: its configuration and indexes.

    The batch runs of one variant share the same ``config`` object; a consumer copies it (``config_mapping``).
    """

    config: Any
    seed: int | None
    variant_index: int
    variant_total: int
    batch_index: int
    batch_total: int
    config_variant: ConfigVariant
    randomizer_summary: dict[str, Any]


def config_mapping(config: Any) -> dict[str, Any]:
    """A detached mapping of one expanded configuration (a mapping, a dataclass or an object with fields)."""

    if isinstance(config, dict):
        return deepcopy(config)
    if is_dataclass(config) and not isinstance(config, type):
        return asdict(config)
    if hasattr(config, "__dict__"):
        return deepcopy(vars(config))
    raise TypeError("base_config must be a mapping or object with configuration fields")


def _config_text(config: Any, key: str) -> str:
    """Safely extract a string value from a config dict or object."""

    value = config.get(key) if isinstance(config, dict) else getattr(config, key, None)
    return "" if value is None else str(value)


def stage_prompt_info(config: Mapping[str, Any]) -> StagePromptInfo:
    """The txt2img prompt metadata of a prepared configuration: its own prompt and negative, verbatim."""

    prompt = _config_text(config, "prompt")
    negative = _config_text(config, "negative_prompt")
    return StagePromptInfo(
        original_prompt=prompt,
        final_prompt=prompt,
        original_negative_prompt=negative,
        final_negative_prompt=negative,
        global_negative_applied=False,
        global_negative_terms="",
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value not in (None, "") else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value not in (None, "") else None


def _generic_model_name(config: Mapping[str, Any]) -> str | None:
    txt2img = config.get("txt2img")
    nested = txt2img.get("model") if isinstance(txt2img, dict) else None
    return str(nested or config.get("model") or "") or None


def _generic_pack_usage(config: Mapping[str, Any]) -> tuple[PackUsageInfo, ...]:
    """Prompt pack usage metadata if the configuration names a pack."""

    pack_name = _config_text(config, "pack_name")
    if not pack_name:
        return ()
    pack_path = _config_text(config, "pack_path")
    return (PackUsageInfo(pack_name=pack_name, pack_path=pack_path or None),)


def _generic_bind(draft: NjrDraft, config: Mapping[str, Any]) -> NjrDraft:
    """The prompt text and its provenance come from the effective configuration."""

    prompt_info = stage_prompt_info(config)
    return replace(
        draft,
        workload=replace(
            draft.workload,
            positive_prompt=prompt_info.final_prompt,
            negative_prompt=prompt_info.final_negative_prompt,
        ),
        provenance=replace(
            draft.provenance,
            txt2img_prompt_info=prompt_info,
            pack_usage=_generic_pack_usage(config),
        ),
    )


def _generic_adetailer_applies(config: Mapping[str, Any]) -> bool:
    """ADetailer is compiled only when no stage list is supplied and the pipeline enables it."""

    pipeline = config.get("pipeline") or {}
    return "stages" not in config and pipeline.get("adetailer_enabled") is True


def _generic_stages(
    config: Mapping[str, Any], adetailer_mode: Mapping[str, Any]
) -> tuple[StageConfig, ...]:
    stages: tuple[StageConfig, ...] = (
        StageConfig(
            stage_type="txt2img",
            enabled=True,
            steps=_optional_int(config.get("steps")),
            cfg_scale=_optional_float(config.get("cfg_scale")),
            sampler_name=str(config.get("sampler") or "") or None,
            model=str(config.get("model") or "") or None,
        ),
    )
    if adetailer_mode:
        stages += (StageConfig("adetailer", enabled=True, extra=config["adetailer"]),)
    return stages


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

    def mint_job_id(self) -> str:
        """The next job identity from this builder's injected id function."""
        return self._id_fn()

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
        output = output_settings or OutputSettings()
        expansion = self.plan_expansion(
            base_config=base_config,
            randomization_plan=randomization_plan,
            config_variant_plan=config_variant_plan,
            batch_settings=batch_settings,
            rng_seed=rng_seed,
        )
        plan = RawImagePlan(
            stages_for=_generic_stages,
            model_name_for=_generic_model_name,
            bind=_generic_bind,
            adetailer_applies=_generic_adetailer_applies,
            mint_job_id=self._id_fn,
        )
        return [compile_njr(self._generic_draft(item, output, plan)) for item in expansion]

    def plan_expansion(
        self,
        *,
        base_config: Any,
        randomization_plan: RandomizationPlanV2 | None = None,
        config_variant_plan: ConfigVariantPlanV2 | None = None,
        batch_settings: BatchSettings | None = None,
        rng_seed: int | None = None,
    ) -> list[ExpansionItem]:
        """One ``ExpansionItem`` per record, in the order ``build_jobs`` documents.

        Config variants (dot-path overrides), then randomizer variants (or the seed mode on the non-randomized
        path), then batch runs. Nothing here compiles a configuration.
        """
        batch = batch_settings or BatchSettings()
        config_plan = config_variant_plan or ConfigVariantPlanV2.single_variant()
        items: list[ExpansionItem] = []
        for config_variant in config_plan.iter_variants():
            config_with_overrides = self._apply_config_overrides(
                base_config, config_variant.overrides
            )
            variant_configs = self._generate_variants(
                config_with_overrides, randomization_plan, rng_seed
            )
            variant_total = len(variant_configs)
            if randomization_plan is None or not randomization_plan.enabled:
                variant_configs = self._apply_seed_mode_non_randomized(
                    variant_configs, randomization_plan
                )
            for variant_index, matrix_config in enumerate(variant_configs):
                for batch_index in range(batch.batch_runs):
                    summary: dict[str, Any] = {}
                    if randomization_plan and randomization_plan.enabled:
                        summary = self._build_randomizer_summary(randomization_plan, variant_index)
                    items.append(
                        ExpansionItem(
                            config=matrix_config,
                            seed=self._extract_seed(matrix_config),
                            variant_index=variant_index,
                            variant_total=variant_total,
                            batch_index=batch_index,
                            batch_total=batch.batch_runs,
                            config_variant=config_variant,
                            randomizer_summary=summary,
                        )
                    )
        return items

    @staticmethod
    def _generic_draft(item: ExpansionItem, output: OutputSettings, plan: RawImagePlan) -> NjrDraft:
        """A ``RAW`` draft: the merged configuration and its indexes; the core prepares the rest.

        Generic records keep the ``CLI`` source label (assessment finding X1, frozen as observed) and run the
        exact-profile check after construction, as they did before the move onto the core.
        """
        return NjrDraft(
            job_id="",  # minted by the plan after the shared steps (a refused draft consumes no identity)
            workload_kind=WorkloadKind.IMAGE,
            source=SourceDescriptor(kind=SourceKind.CLI),
            workload=ImageWorkloadSpec(config=config_mapping(item.config)),
            stages=(),
            output_plan=OutputPlan(base_output_dir=output.base_output_dir),
            provenance=NJRProvenance(
                seed=item.seed,
                variant_index=item.variant_index,
                variant_total=item.variant_total,
                batch_index=item.batch_index,
                batch_total=item.batch_total,
                config_variant_label=item.config_variant.label,
                config_variant_index=item.config_variant.index,
                config_variant_overrides=item.config_variant.overrides.copy(),
                randomizer_summary=item.randomizer_summary,
            ),
            policy_state=PolicyState.RAW,
            checks=(CompileCheck.PROFILE_NJR,),
            raw_plan=plan,
        )

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


__all__ = ["ExpansionItem", "JobBuilderV2", "config_mapping", "stage_prompt_info"]
