from __future__ import annotations

import itertools
import random
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional


class RandomizationSeedMode(str, Enum):
    FIXED = "fixed"
    PER_VARIANT = "per_variant"
    NONE = "none"


@dataclass
class RandomizationPlanV2:
    enabled: bool = False
    max_variants: int = 0
    seed_mode: RandomizationSeedMode = RandomizationSeedMode.NONE
    base_seed: Optional[int] = None
    model_choices: List[str] = field(default_factory=list)
    vae_choices: List[str] = field(default_factory=list)
    sampler_choices: List[str] = field(default_factory=list)
    scheduler_choices: List[str] = field(default_factory=list)
    cfg_scale_values: List[float] = field(default_factory=list)
    steps_values: List[int] = field(default_factory=list)
    batch_sizes: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class _VariantOverride:
    model: Optional[str] = None
    vae: Optional[str] = None
    sampler: Optional[str] = None
    scheduler: Optional[str] = None
    cfg_scale: Optional[float] = None
    steps: Optional[int] = None
    batch_size: Optional[int] = None


def _ensure_list(values: Iterable) -> list:
    entries = [v for v in values if v is not None and str(v).strip()]
    return entries or [None]


def _iter_candidate_overrides(plan: RandomizationPlanV2, rng: random.Random) -> list[_VariantOverride]:
    if not plan.enabled:
        return []
    model_vals = _ensure_list(plan.model_choices)
    vae_vals = _ensure_list(plan.vae_choices)
    sampler_vals = _ensure_list(plan.sampler_choices)
    scheduler_vals = _ensure_list(plan.scheduler_choices)
    cfg_vals = _ensure_list(plan.cfg_scale_values)
    steps_vals = _ensure_list(plan.steps_values)
    batch_vals = _ensure_list(plan.batch_sizes)

    combos = []
    for combo in itertools.product(
        model_vals,
        vae_vals,
        sampler_vals,
        scheduler_vals,
        cfg_vals,
        steps_vals,
        batch_vals,
    ):
        overrides = _VariantOverride(
            model=combo[0],
            vae=combo[1],
            sampler=combo[2],
            scheduler=combo[3],
            cfg_scale=combo[4],
            steps=combo[5],
            batch_size=combo[6],
        )
        combos.append(overrides)
    rng.shuffle(combos)
    return combos


def _apply_override(base: object, override: _VariantOverride) -> None:
    rows = [
        ("model", override.model),
        ("vae", override.vae),
        ("sampler", override.sampler),
        ("scheduler", override.scheduler),
        ("cfg_scale", override.cfg_scale),
        ("steps", override.steps),
        ("batch_size", override.batch_size),
    ]
    for attr, value in rows:
        if value is None:
            continue
        if hasattr(base, attr):
            setattr(base, attr, value)


def _apply_seed(base: object, plan: RandomizationPlanV2, idx: int) -> None:
    if plan.base_seed is None:
        return
    if not hasattr(base, "seed"):
        return
    if plan.seed_mode == RandomizationSeedMode.FIXED:
        setattr(base, "seed", plan.base_seed)
    elif plan.seed_mode == RandomizationSeedMode.PER_VARIANT:
        setattr(base, "seed", plan.base_seed + idx)


def generate_run_config_variants(base_config: object, plan: RandomizationPlanV2, *, rng_seed: Optional[int] = None) -> list[object]:
    if not plan.enabled:
        return [deepcopy(base_config)]

    rng = random.Random(rng_seed)
    combinations = _iter_candidate_overrides(plan, rng)
    if not combinations:
        combinations = [ _VariantOverride() ]
    if plan.max_variants > 0:
        combinations = combinations[: plan.max_variants]

    variants: list[object] = []
    for idx, override in enumerate(combinations):
        config = deepcopy(base_config)
        _apply_override(config, override)
        _apply_seed(config, plan, idx)
        variants.append(config)

    if not variants:
        variants.append(deepcopy(base_config))
    return variants
