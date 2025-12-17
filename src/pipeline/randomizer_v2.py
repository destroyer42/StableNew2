from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.gui.models.prompt_metadata import PromptMetadata
from src.pipeline.variant_planner import build_variant_plan
from src.randomizer import (
    RandomizationPlanV2,
    RandomizationSeedMode,
    generate_run_config_variants,
)


def build_prompt_variants(
    prompt_text: str, metadata: PromptMetadata | None, mode: str, max_variants: int
) -> list[str]:
    """
    Very lightweight variant builder.

    - When mode == "off": returns the base prompt only.
    - Otherwise, generates up to max_variants prompts by simple suffixing,
      using matrix_count as a hint when available.
    """
    base = prompt_text or ""
    if mode == "off":
        return [base]

    count_hint = metadata.matrix_count if metadata else 0
    variant_count = min(max(max_variants, 1), 20)
    if count_hint > 0:
        variant_count = min(variant_count, count_hint)

    variants: list[str] = []
    for i in range(variant_count):
        suffix = f" [variant {i + 1}]" if variant_count > 1 else ""
        variants.append(f"{base}{suffix}")
    return variants or [base]


def build_randomization_plan_from_config(
    config: dict[str, Any],
    *,
    mode: str,
    max_variants: int,
    base_seed: int | None = None,
) -> RandomizationPlanV2:
    """
    Build a RandomizationPlanV2 from pipeline config and randomizer knobs.

    Uses variant_planner to extract model/hypernetwork combinations and
    maps them into the engine's choice lists.

    Args:
        config: Pipeline configuration dict
        mode: Randomizer mode ("off", "fanout", etc.)
        max_variants: Maximum number of variants to generate
        base_seed: Optional seed for deterministic randomization

    Returns:
        RandomizationPlanV2 ready for generate_run_config_variants
    """
    # Disabled mode
    if mode == "off":
        return RandomizationPlanV2(enabled=False, max_variants=1)

    # Build variant plan from existing matrix/hypernetwork config
    variant_plan = build_variant_plan(config)

    # Extract model choices from variant plan
    model_choices: list[str] = []
    if variant_plan.active and variant_plan.variants:
        seen_models: set[str] = set()
        for spec in variant_plan.variants:
            if spec.model and spec.model not in seen_models:
                model_choices.append(spec.model)
                seen_models.add(spec.model)

    # Determine seed mode
    seed_mode = RandomizationSeedMode.NONE
    if base_seed is not None:
        seed_mode = RandomizationSeedMode.PER_VARIANT

    # Clamp max_variants to sane bounds
    clamped_max = max(1, min(max_variants, 512))

    return RandomizationPlanV2(
        enabled=True,
        max_variants=clamped_max,
        seed_mode=seed_mode,
        base_seed=base_seed,
        model_choices=model_choices,
        # Other choice lists can be populated from config if needed
        sampler_choices=[],
        scheduler_choices=[],
        cfg_scale_values=[],
        steps_values=[],
        batch_sizes=[],
    )


def expand_config_with_randomizer(
    base_config: dict[str, Any],
    *,
    mode: str,
    max_variants: int,
    base_seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Expand a base config into multiple variants using RandomizerEngineV2.

    This is the main entry point for pipeline/controller integration.

    Args:
        base_config: Base pipeline configuration dict
        mode: Randomizer mode ("off" disables expansion)
        max_variants: Maximum variants to generate
        base_seed: Optional seed for deterministic output

    Returns:
        List of config dicts (deep copies). Always returns at least one.
    """
    plan = build_randomization_plan_from_config(
        base_config,
        mode=mode,
        max_variants=max_variants,
        base_seed=base_seed,
    )

    # generate_run_config_variants works with any object via duck-typing
    # For dict configs, we wrap in a simple object
    class _ConfigWrapper:
        def __init__(self, d: dict[str, Any]) -> None:
            self._data = d
            # Expose top-level keys as attributes for the engine
            for k, v in d.items():
                if isinstance(k, str) and k.isidentifier():
                    setattr(self, k, v)

        def to_dict(self) -> dict[str, Any]:
            return deepcopy(self._data)

    wrapped = _ConfigWrapper(base_config)
    variants = generate_run_config_variants(wrapped, plan, rng_seed=base_seed)

    # Convert back to dicts
    result: list[dict[str, Any]] = []
    for v in variants:
        if hasattr(v, "to_dict"):
            result.append(v.to_dict())
        elif hasattr(v, "_data"):
            result.append(deepcopy(v._data))
        elif isinstance(v, dict):
            result.append(deepcopy(v))
        else:
            # Fallback: reconstruct from attributes
            result.append(deepcopy(base_config))

    return result if result else [deepcopy(base_config)]


def get_variant_count(
    mode: str,
    max_variants: int,
    config: dict[str, Any] | None = None,
) -> int:
    """
    Get the number of variants that would be generated.

    Useful for summary/preview without actually expanding configs.
    """
    if mode == "off":
        return 1

    plan = build_randomization_plan_from_config(
        config or {},
        mode=mode,
        max_variants=max_variants,
    )

    if not plan.enabled:
        return 1

    # Count Cartesian product size, capped by max_variants
    # For now, if no choices defined, just return max_variants
    return min(max(1, plan.max_variants), 512)
