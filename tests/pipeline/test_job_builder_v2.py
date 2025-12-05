# Subsystem: Pipeline
# Role: Tests for JobBuilderV2 job construction logic.

"""Tests for JobBuilderV2: Centralized job construction.

These tests verify:
1. Single job - no randomization, no batch
2. Randomizer enabled - multiple variants
3. Batch expansion - batch_runs creates multiple jobs
4. Seed mode - FIXED, PER_VARIANT, NONE
5. Combined randomizer + batch expansion
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import BatchSettings, OutputSettings
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeConfig:
    """Minimal config for testing."""
    model: str = "base_model"
    vae: str = "base_vae"
    sampler: str = "Euler a"
    scheduler: str = "normal"
    cfg_scale: float = 7.0
    steps: int = 20
    batch_size: int = 1
    seed: int = 12345
    prompt: str = "test prompt"
    negative_prompt: str = ""


@pytest.fixture
def base_config() -> FakeConfig:
    """Create a base config for testing."""
    return FakeConfig()


@pytest.fixture
def builder() -> JobBuilderV2:
    """Create a builder with deterministic time/id for testing."""
    counter = [0]
    timestamp = [1000.0]

    def fake_id() -> str:
        counter[0] += 1
        return f"job-{counter[0]:04d}"

    def fake_time() -> float:
        timestamp[0] += 1.0
        return timestamp[0]

    return JobBuilderV2(time_fn=fake_time, id_fn=fake_id)


# ---------------------------------------------------------------------------
# Test 1: Single job, no randomization, no batch
# ---------------------------------------------------------------------------


class TestSingleJobNoRandomization:
    """Test building a single job with no randomization or batch expansion."""

    def test_single_job_basic(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Single job with default settings."""
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
            batch_settings=BatchSettings(batch_size=1, batch_runs=1),
            output_settings=OutputSettings("/tmp/out", "{seed}"),
        )

        assert len(jobs) == 1
        job = jobs[0]

        # Verify NormalizedJobRecord fields
        assert job.job_id == "job-0001"
        assert job.variant_total == 1
        assert job.variant_index == 0
        assert job.batch_total == 1
        assert job.batch_index == 0
        assert job.path_output_dir == "/tmp/out"
        assert job.filename_template == "{seed}"
        assert job.seed == 12345  # From base_config
        assert job.created_ts == 1001.0

    def test_single_job_preserves_config(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Config is preserved (deep copied) in job."""
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
        )

        assert len(jobs) == 1
        job = jobs[0]

        # Config should have same values but be a copy
        assert job.config is not base_config
        assert job.config.model == "base_model"
        assert job.config.steps == 20
        assert job.config.cfg_scale == 7.0
        assert job.config.seed == 12345

    def test_single_job_does_not_mutate_base(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Building jobs should not mutate the base config."""
        original_seed = base_config.seed
        original_model = base_config.model

        builder.build_jobs(
            base_config=base_config,
            randomization_plan=RandomizationPlanV2(
                enabled=False,
                seed_mode=RandomizationSeedMode.FIXED,
                base_seed=999,
            ),
        )

        # Original config unchanged
        assert base_config.seed == original_seed
        assert base_config.model == original_model

    def test_single_job_with_default_settings(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """None settings use defaults."""
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
            batch_settings=None,
            output_settings=None,
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert job.path_output_dir == "output"  # Default
        assert job.filename_template == "{seed}"  # Default
        assert job.batch_total == 1
        assert job.variant_total == 1


# ---------------------------------------------------------------------------
# Test 2: Randomizer enabled, multiple variants
# ---------------------------------------------------------------------------


class TestRandomizerVariants:
    """Test variant generation via randomizer engine."""

    def test_randomizer_creates_variants(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Randomizer with model choices creates multiple variants."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["model_a", "model_b", "model_c"],
            max_variants=3,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            batch_settings=BatchSettings(batch_size=1, batch_runs=1),
            rng_seed=42,  # For determinism
        )

        assert len(jobs) == 3
        assert jobs[0].variant_total == 3
        assert jobs[1].variant_total == 3
        assert jobs[2].variant_total == 3

        # Variant indices should be 0, 1, 2
        assert [j.variant_index for j in jobs] == [0, 1, 2]

        # All batch indices should be 0 (no batch expansion)
        assert all(j.batch_index == 0 for j in jobs)
        assert all(j.batch_total == 1 for j in jobs)

        # Models should be from choices (randomized)
        models = {j.config.model for j in jobs}
        assert models == {"model_a", "model_b", "model_c"}

    def test_randomizer_deterministic_with_seed(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Same rng_seed produces same results."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3"],
            sampler_choices=["s1", "s2"],
            max_variants=4,
        )

        jobs1 = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=123,
        )

        # Reset builder for fresh IDs
        builder2 = JobBuilderV2(
            time_fn=lambda: 1000.0,
            id_fn=lambda: "id",
        )

        jobs2 = builder2.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=123,
        )

        # Configs should match (ignoring job IDs)
        assert len(jobs1) == len(jobs2)
        for j1, j2 in zip(jobs1, jobs2, strict=True):
            assert j1.config.model == j2.config.model
            assert j1.config.sampler == j2.config.sampler

    def test_randomizer_max_variants_limits_output(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """max_variants limits the number of jobs."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3", "m4", "m5"],
            max_variants=2,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=1,
        )

        assert len(jobs) == 2
        assert all(j.variant_total == 2 for j in jobs)

    def test_randomizer_includes_summary(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Jobs include randomizer_summary when randomization is enabled."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2"],
            seed_mode=RandomizationSeedMode.PER_VARIANT,
            base_seed=100,
            max_variants=2,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=1,
        )

        assert len(jobs) == 2
        for i, job in enumerate(jobs):
            assert job.randomizer_summary is not None
            assert job.randomizer_summary["variant_index"] == i
            assert job.randomizer_summary["seed_mode"] == "per_variant"
            assert job.randomizer_summary["base_seed"] == 100
            assert job.randomizer_summary["model_choices"] == 2


# ---------------------------------------------------------------------------
# Test 3: Batch expansion
# ---------------------------------------------------------------------------


class TestBatchExpansion:
    """Test batch_runs expansion into multiple jobs."""

    def test_batch_runs_creates_multiple_jobs(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """batch_runs=4 creates 4 jobs from single variant."""
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
            batch_settings=BatchSettings(batch_size=1, batch_runs=4),
        )

        assert len(jobs) == 4

        # All jobs should have same variant info
        assert all(j.variant_total == 1 for j in jobs)
        assert all(j.variant_index == 0 for j in jobs)

        # Batch indices should be 0, 1, 2, 3
        assert [j.batch_index for j in jobs] == [0, 1, 2, 3]
        assert all(j.batch_total == 4 for j in jobs)

        # All configs should be equivalent (same content)
        for job in jobs:
            assert job.config.model == "base_model"
            assert job.config.seed == 12345

    def test_batch_runs_with_variants(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Variants × batch_runs produces correct total jobs."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2"],
            max_variants=2,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            batch_settings=BatchSettings(batch_size=1, batch_runs=3),
            rng_seed=1,
        )

        # Total = 2 variants × 3 batch_runs = 6 jobs
        assert len(jobs) == 6

        # Check ordering: outer loop is variants, inner is batches
        # variant 0: batch 0, 1, 2
        # variant 1: batch 0, 1, 2
        expected_indices = [
            (0, 0), (0, 1), (0, 2),
            (1, 0), (1, 1), (1, 2),
        ]
        actual_indices = [(j.variant_index, j.batch_index) for j in jobs]
        assert actual_indices == expected_indices

        # All should have variant_total=2, batch_total=3
        assert all(j.variant_total == 2 for j in jobs)
        assert all(j.batch_total == 3 for j in jobs)

    def test_batch_size_passed_through(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """batch_size in config is preserved (not used for job expansion)."""
        base_config.batch_size = 4

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
            batch_settings=BatchSettings(batch_size=4, batch_runs=2),
        )

        # 2 jobs from batch_runs
        assert len(jobs) == 2

        # batch_size in config should be preserved
        for job in jobs:
            assert job.config.batch_size == 4


# ---------------------------------------------------------------------------
# Test 4: Seed mode behavior
# ---------------------------------------------------------------------------


class TestSeedMode:
    """Test seed mode application."""

    def test_seed_mode_fixed_non_randomized(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """FIXED seed mode sets all jobs to base_seed."""
        plan = RandomizationPlanV2(
            enabled=False,
            seed_mode=RandomizationSeedMode.FIXED,
            base_seed=999,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            batch_settings=BatchSettings(batch_runs=3),
        )

        assert len(jobs) == 3
        # All jobs should have seed=999
        assert all(j.seed == 999 for j in jobs)

    def test_seed_mode_per_variant_non_randomized(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """PER_VARIANT seed mode increments seed (even without randomization)."""
        plan = RandomizationPlanV2(
            enabled=False,
            seed_mode=RandomizationSeedMode.PER_VARIANT,
            base_seed=100,
        )

        # With batch_runs, each batch job is a "variant" for seed purposes
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            batch_settings=BatchSettings(batch_runs=1),
        )

        # Single variant with base_seed
        assert len(jobs) == 1
        assert jobs[0].seed == 100

    def test_seed_mode_none_preserves_original(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """NONE seed mode leaves original seed unchanged."""
        base_config.seed = 54321

        plan = RandomizationPlanV2(
            enabled=False,
            seed_mode=RandomizationSeedMode.NONE,
            base_seed=999,  # Should be ignored
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
        )

        assert len(jobs) == 1
        assert jobs[0].seed == 54321  # Original preserved

    def test_seed_mode_with_randomizer_fixed(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Randomizer with FIXED seed mode sets all variants to base_seed."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3"],
            max_variants=3,
            seed_mode=RandomizationSeedMode.FIXED,
            base_seed=123,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=1,
        )

        assert len(jobs) == 3
        # All variants should have seed=123
        assert all(j.seed == 123 for j in jobs)

    def test_seed_mode_with_randomizer_per_variant(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Randomizer with PER_VARIANT seed mode increments per variant."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3"],
            max_variants=3,
            seed_mode=RandomizationSeedMode.PER_VARIANT,
            base_seed=10,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=1,
        )

        assert len(jobs) == 3
        # Seeds should be 10, 11, 12
        assert [j.seed for j in jobs] == [10, 11, 12]


# ---------------------------------------------------------------------------
# Test 5: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_model_choices_uses_base(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Empty model_choices with enabled=True still produces job."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=[],  # Empty
            max_variants=1,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            rng_seed=1,
        )

        # Should still produce at least one job
        assert len(jobs) >= 1
        # Model should be preserved from base
        assert jobs[0].config.model == "base_model"

    def test_disabled_plan_with_settings(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Disabled plan ignores choices and produces single variant."""
        plan = RandomizationPlanV2(
            enabled=False,
            model_choices=["m1", "m2", "m3"],  # Should be ignored
            max_variants=10,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
        )

        assert len(jobs) == 1
        assert jobs[0].config.model == "base_model"  # Unchanged

    def test_dict_config_support(self, builder: JobBuilderV2) -> None:
        """Builder works with dict configs."""
        dict_config = {
            "model": "dict_model",
            "seed": 999,
            "steps": 25,
        }

        jobs = builder.build_jobs(
            base_config=dict_config,
            randomization_plan=None,
        )

        assert len(jobs) == 1
        assert jobs[0].config["model"] == "dict_model"
        assert jobs[0].seed == 999

    def test_unique_job_ids(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """All jobs get unique IDs."""
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
            batch_settings=BatchSettings(batch_runs=5),
        )

        job_ids = [j.job_id for j in jobs]
        assert len(job_ids) == len(set(job_ids))  # All unique

    def test_timestamps_are_sequential(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """Jobs get sequential timestamps."""
        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=None,
            batch_settings=BatchSettings(batch_runs=3),
        )

        timestamps = [j.created_ts for j in jobs]
        assert timestamps == sorted(timestamps)  # Ascending order

    def test_display_summary(
        self, builder: JobBuilderV2, base_config: FakeConfig
    ) -> None:
        """NormalizedJobRecord.get_display_summary() works."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["test_model"],
            max_variants=1,
        )

        jobs = builder.build_jobs(
            base_config=base_config,
            randomization_plan=plan,
            batch_settings=BatchSettings(batch_runs=2),
            rng_seed=1,
        )

        assert len(jobs) == 2

        # Check display summary format
        summary = jobs[0].get_display_summary()
        assert "test_model" in summary or "base_model" in summary
        assert "seed=" in summary

        # With batch > 1, should show batch info
        summary = jobs[1].get_display_summary()
        assert "[b2/2]" in summary
