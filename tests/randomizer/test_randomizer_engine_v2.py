from __future__ import annotations

from dataclasses import dataclass

from src.randomizer import (
    RandomizationPlanV2,
    RandomizationSeedMode,
    generate_run_config_variants,
)


@dataclass
class FakeConfig:
    model: str = "base_model"
    vae: str = "base_vae"
    sampler: str = "base_sampler"
    scheduler: str = "base_scheduler"
    cfg_scale: float = 7.0
    steps: int = 20
    batch_size: int = 1
    seed: int = 0


def test_disabled_plan_returns_base():
    config = FakeConfig()
    plan = RandomizationPlanV2(enabled=False)
    variants = generate_run_config_variants(config, plan)
    assert len(variants) == 1
    assert variants[0] is not config
    assert variants[0].model == "base_model"


def test_single_field_choices():
    config = FakeConfig()
    plan = RandomizationPlanV2(
        enabled=True,
        model_choices=["m1", "m2", "m3"],
        max_variants=3,
    )
    variants = generate_run_config_variants(config, plan, rng_seed=1)
    assert len(variants) == 3
    assert {v.model for v in variants} == {"m1", "m2", "m3"}
    assert all(v.sampler == "base_sampler" for v in variants)


def test_multi_field_truncation_and_determinism():
    config = FakeConfig()
    plan = RandomizationPlanV2(
        enabled=True,
        model_choices=["m1", "m2"],
        cfg_scale_values=[4.5, 7.0],
        steps_values=[10, 30],
        max_variants=3,
    )
    first = generate_run_config_variants(config, plan, rng_seed=42)
    second = generate_run_config_variants(config, plan, rng_seed=42)
    assert len(first) == 3
    assert first == second
    for variant in first:
        assert variant.model in plan.model_choices
        assert variant.cfg_scale in plan.cfg_scale_values
        assert variant.steps in plan.steps_values


def test_seed_modes_fixed_and_per_variant():
    config = FakeConfig()
    plan_fixed = RandomizationPlanV2(
        enabled=True,
        seed_mode=RandomizationSeedMode.FIXED,
        base_seed=123,
        model_choices=["m"],
        max_variants=2,
    )
    variants = generate_run_config_variants(config, plan_fixed, rng_seed=0)
    assert all(v.seed == 123 for v in variants)

    plan_variant = RandomizationPlanV2(
        enabled=True,
        seed_mode=RandomizationSeedMode.PER_VARIANT,
        base_seed=10,
        model_choices=["m1", "m2"],
        sampler_choices=["s1"],
        steps_values=[10, 20],
        max_variants=3,
    )
    variants = generate_run_config_variants(config, plan_variant, rng_seed=0)
    assert [v.seed for v in variants] == [10, 11, 12]
