"""PR-044: Test pipeline controller integration with RandomizerEngineV2."""

from __future__ import annotations

import pytest
from copy import deepcopy

from src.pipeline.randomizer_v2 import (
    build_randomization_plan_from_config,
    expand_config_with_randomizer,
    get_variant_count,
)
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode


class TestBuildRandomizationPlan:
    """Test build_randomization_plan_from_config helper."""

    def test_mode_off_returns_disabled_plan(self) -> None:
        config = {"txt2img": {"model": "test_model"}}
        plan = build_randomization_plan_from_config(config, mode="off", max_variants=5)
        
        assert plan.enabled is False
        assert plan.max_variants == 1

    def test_mode_fanout_returns_enabled_plan(self) -> None:
        config = {"txt2img": {"model": "test_model"}}
        plan = build_randomization_plan_from_config(config, mode="fanout", max_variants=5)
        
        assert plan.enabled is True
        assert plan.max_variants == 5

    def test_max_variants_clamped_to_bounds(self) -> None:
        config = {}
        
        # Test lower bound
        plan_low = build_randomization_plan_from_config(config, mode="fanout", max_variants=0)
        assert plan_low.max_variants >= 1
        
        # Test upper bound
        plan_high = build_randomization_plan_from_config(config, mode="fanout", max_variants=10000)
        assert plan_high.max_variants <= 512

    def test_base_seed_sets_per_variant_mode(self) -> None:
        config = {}
        plan = build_randomization_plan_from_config(
            config, mode="fanout", max_variants=3, base_seed=12345
        )
        
        assert plan.seed_mode == RandomizationSeedMode.PER_VARIANT
        assert plan.base_seed == 12345

    def test_no_seed_uses_none_mode(self) -> None:
        config = {}
        plan = build_randomization_plan_from_config(
            config, mode="fanout", max_variants=3, base_seed=None
        )
        
        assert plan.seed_mode == RandomizationSeedMode.NONE
        assert plan.base_seed is None


class TestExpandConfigWithRandomizer:
    """Test expand_config_with_randomizer main entry point."""

    def test_mode_off_returns_single_deepcopy(self) -> None:
        base = {"txt2img": {"prompt": "test", "steps": 20}}
        results = expand_config_with_randomizer(base, mode="off", max_variants=10)
        
        assert len(results) == 1
        assert results[0] == base
        # Verify it's a deep copy, not the same object
        assert results[0] is not base
        results[0]["txt2img"]["steps"] = 999
        assert base["txt2img"]["steps"] == 20

    def test_mode_fanout_returns_multiple_variants(self) -> None:
        base = {"txt2img": {"prompt": "test", "model": "base_model"}}
        results = expand_config_with_randomizer(base, mode="fanout", max_variants=3)
        
        # Should return at least 1 variant
        assert len(results) >= 1
        # All should be deep copies
        for r in results:
            assert r is not base

    def test_determinism_with_seed(self) -> None:
        base = {"txt2img": {"prompt": "test"}}
        
        results1 = expand_config_with_randomizer(
            base, mode="fanout", max_variants=5, base_seed=42
        )
        results2 = expand_config_with_randomizer(
            base, mode="fanout", max_variants=5, base_seed=42
        )
        
        assert len(results1) == len(results2)
        for r1, r2 in zip(results1, results2):
            assert r1 == r2

    def test_always_returns_at_least_one(self) -> None:
        base = {}
        results = expand_config_with_randomizer(base, mode="fanout", max_variants=0)
        
        assert len(results) >= 1


class TestGetVariantCount:
    """Test get_variant_count preview helper."""

    def test_mode_off_returns_one(self) -> None:
        count = get_variant_count(mode="off", max_variants=100)
        assert count == 1

    def test_mode_fanout_respects_max_variants(self) -> None:
        count = get_variant_count(mode="fanout", max_variants=5)
        assert count == 5

    def test_count_clamped_to_bounds(self) -> None:
        count_low = get_variant_count(mode="fanout", max_variants=0)
        assert count_low >= 1
        
        count_high = get_variant_count(mode="fanout", max_variants=10000)
        assert count_high <= 512
