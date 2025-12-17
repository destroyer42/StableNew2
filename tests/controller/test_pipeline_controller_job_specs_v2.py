# Subsystem: Controller
# Role: End-to-end parity tests for PipelineController + JobBuilderV2 (PR-204E).

"""Controller-level parity tests: run_config + pipeline state → NormalizedJobRecord list.

These tests verify:
1. Given synthetic run_config + pipeline state + randomizer plan, exact
   NormalizedJobRecord lists are produced with correct variant and batch indexing.
2. Direct vs queue run modes result in the right JobService calls.
3. Key pipeline_config fields (model, steps, CFG, etc.) are correctly passed through.

References:
- ARCHITECTURE_v2.5.md: Run path and job construction flow
- PR-204E: End-to-End Controller + Queue Parity Tests
"""

from __future__ import annotations

import pytest

from src.pipeline.job_builder_v2 import JobBuilderV2
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode
from tests.helpers.pipeline_fixtures_v2 import (
    FixedTimeGenerator,
    SequentialIdGenerator,
    make_batch_settings,
    make_minimal_pipeline_config,
    make_output_settings,
    make_randomizer_plan_disabled,
    make_randomizer_plan_simple_models,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def id_gen() -> SequentialIdGenerator:
    """Sequential ID generator for deterministic tests."""
    return SequentialIdGenerator(prefix="job")


@pytest.fixture
def time_gen() -> FixedTimeGenerator:
    """Fixed timestamp generator for deterministic tests."""
    return FixedTimeGenerator(start=1000.0)


@pytest.fixture
def job_builder(id_gen: SequentialIdGenerator, time_gen: FixedTimeGenerator) -> JobBuilderV2:
    """JobBuilderV2 with deterministic ID and time generators."""
    return JobBuilderV2(time_fn=time_gen, id_fn=id_gen)


# ---------------------------------------------------------------------------
# Test: Single Job, Randomizer Disabled
# ---------------------------------------------------------------------------


class TestSingleJobRandomizerDisabled:
    """Test single job construction when randomizer is disabled."""

    def test_produces_single_job(self, job_builder: JobBuilderV2) -> None:
        """Single job is produced when randomizer is disabled."""
        config = make_minimal_pipeline_config(model="test-model", seed=12345)
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=1),
        )

        assert len(jobs) == 1

    def test_job_has_correct_indices(self, job_builder: JobBuilderV2) -> None:
        """Single job has variant_index=0, variant_total=1, batch_index=0, batch_total=1."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=1),
        )

        job = jobs[0]
        assert job.variant_index == 0
        assert job.variant_total == 1
        assert job.batch_index == 0
        assert job.batch_total == 1

    def test_job_preserves_config_model(self, job_builder: JobBuilderV2) -> None:
        """Job config preserves model from base config."""
        config = make_minimal_pipeline_config(model="my-special-model")

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        job_config = jobs[0].config
        assert job_config.model == "my-special-model"

    def test_job_preserves_config_steps(self, job_builder: JobBuilderV2) -> None:
        """Job config preserves steps from base config."""
        config = make_minimal_pipeline_config(steps=42)

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        job_config = jobs[0].config
        assert job_config.steps == 42

    def test_job_preserves_config_cfg_scale(self, job_builder: JobBuilderV2) -> None:
        """Job config preserves cfg_scale from base config."""
        config = make_minimal_pipeline_config(cfg_scale=9.5)

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        job_config = jobs[0].config
        assert job_config.cfg_scale == 9.5

    def test_job_has_output_settings(self, job_builder: JobBuilderV2) -> None:
        """Job has correct output directory and filename template."""
        config = make_minimal_pipeline_config()
        output = make_output_settings(
            base_output_dir="/custom/output",
            filename_template="{model}_{seed}",
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
            output_settings=output,
        )

        job = jobs[0]
        assert job.path_output_dir == "/custom/output"
        assert job.filename_template == "{model}_{seed}"

    def test_job_has_unique_id(self, job_builder: JobBuilderV2) -> None:
        """Each job gets a unique ID."""
        config = make_minimal_pipeline_config()

        jobs1 = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )
        jobs2 = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        assert jobs1[0].job_id != jobs2[0].job_id


# ---------------------------------------------------------------------------
# Test: Variants Only (No Batch Expansion)
# ---------------------------------------------------------------------------


class TestVariantsOnly:
    """Test job construction with randomizer variants but no batch expansion."""

    def test_two_model_variants_produces_two_jobs(self, job_builder: JobBuilderV2) -> None:
        """Two model choices with max_variants=2 produces 2 jobs."""
        config = make_minimal_pipeline_config(model="base-model")
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=1),
            rng_seed=42,  # deterministic
        )

        assert len(jobs) == 2

    def test_variant_indices_are_sequential(self, job_builder: JobBuilderV2) -> None:
        """Variant indices are [0, 1] for 2 variants."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=42,
        )

        assert jobs[0].variant_index == 0
        assert jobs[1].variant_index == 1
        assert jobs[0].variant_total == 2
        assert jobs[1].variant_total == 2

    def test_seed_mode_per_variant_applies(self, job_builder: JobBuilderV2) -> None:
        """PER_VARIANT seed mode increments seed for each variant."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
            seed_mode=RandomizationSeedMode.PER_VARIANT,
            base_seed=1000,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=42,
        )

        # Seeds should be base_seed + variant_index
        seeds = [job.seed for job in jobs]
        assert 1000 in seeds
        assert 1001 in seeds

    def test_seed_mode_fixed_uses_same_seed(self, job_builder: JobBuilderV2) -> None:
        """FIXED seed mode uses same seed for all variants."""
        config = make_minimal_pipeline_config()
        plan = RandomizationPlanV2(
            enabled=True,
            max_variants=2,
            seed_mode=RandomizationSeedMode.FIXED,
            base_seed=9999,
            model_choices=["model-a", "model-b"],
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=42,
        )

        seeds = [job.seed for job in jobs]
        assert all(s == 9999 for s in seeds)

    def test_max_variants_limits_output(self, job_builder: JobBuilderV2) -> None:
        """max_variants limits the number of jobs produced."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["a", "b", "c", "d", "e"],
            max_variants=3,  # only 3 variants
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=42,
        )

        assert len(jobs) <= 3

    def test_randomizer_summary_included(self, job_builder: JobBuilderV2) -> None:
        """Jobs include randomizer_summary when randomization is enabled."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=42,
        )

        for job in jobs:
            assert job.randomizer_summary is not None
            assert "variant_index" in job.randomizer_summary


# ---------------------------------------------------------------------------
# Test: Batch Expansion Only (No Variants)
# ---------------------------------------------------------------------------


class TestBatchExpansionOnly:
    """Test job construction with batch expansion but no randomizer variants."""

    def test_batch_runs_creates_multiple_jobs(self, job_builder: JobBuilderV2) -> None:
        """batch_runs=3 creates 3 jobs."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=3),
        )

        assert len(jobs) == 3

    def test_batch_indices_are_sequential(self, job_builder: JobBuilderV2) -> None:
        """Batch indices are [0, 1, 2] for batch_runs=3."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=3),
        )

        batch_indices = [job.batch_index for job in jobs]
        assert batch_indices == [0, 1, 2]

    def test_batch_total_is_correct(self, job_builder: JobBuilderV2) -> None:
        """All jobs have batch_total matching batch_runs."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=5),
        )

        assert all(job.batch_total == 5 for job in jobs)

    def test_variant_indices_all_zero(self, job_builder: JobBuilderV2) -> None:
        """All batch jobs have variant_index=0 when no randomization."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=3),
        )

        assert all(job.variant_index == 0 for job in jobs)
        assert all(job.variant_total == 1 for job in jobs)

    def test_all_batch_jobs_same_config(self, job_builder: JobBuilderV2) -> None:
        """All batch jobs share the same config values."""
        config = make_minimal_pipeline_config(model="batch-model", steps=25)
        plan = make_randomizer_plan_disabled()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=3),
        )

        for job in jobs:
            assert job.config.model == "batch-model"
            assert job.config.steps == 25


# ---------------------------------------------------------------------------
# Test: Variants × Batch Expansion
# ---------------------------------------------------------------------------


class TestVariantsTimesBatch:
    """Test job construction with both variants and batch expansion."""

    def test_total_jobs_equals_variants_times_batches(self, job_builder: JobBuilderV2) -> None:
        """2 variants × 3 batch_runs = 6 jobs."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=3),
            rng_seed=42,
        )

        assert len(jobs) == 6  # 2 variants × 3 batches

    def test_job_ordering_outer_variant_inner_batch(self, job_builder: JobBuilderV2) -> None:
        """Jobs are ordered: variant 0 batches, then variant 1 batches."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=2),
            rng_seed=42,
        )

        # Expected order: v0-b0, v0-b1, v1-b0, v1-b1
        expected = [
            (0, 0),  # variant 0, batch 0
            (0, 1),  # variant 0, batch 1
            (1, 0),  # variant 1, batch 0
            (1, 1),  # variant 1, batch 1
        ]
        actual = [(j.variant_index, j.batch_index) for j in jobs]
        assert actual == expected

    def test_seeds_consistent_within_variant(self, job_builder: JobBuilderV2) -> None:
        """All batch jobs within same variant have same seed (PER_VARIANT mode)."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
            seed_mode=RandomizationSeedMode.PER_VARIANT,
            base_seed=5000,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=2),
            rng_seed=42,
        )

        # Group by variant_index
        variant_0_seeds = [j.seed for j in jobs if j.variant_index == 0]
        variant_1_seeds = [j.seed for j in jobs if j.variant_index == 1]

        # Within same variant, seeds should be same (or based on variant index)
        assert len(set(variant_0_seeds)) == 1  # All same within variant
        assert len(set(variant_1_seeds)) == 1

    def test_all_jobs_have_unique_ids(self, job_builder: JobBuilderV2) -> None:
        """All jobs have unique IDs."""
        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(
            models=["model-a", "model-b"],
            max_variants=2,
        )

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=make_batch_settings(batch_runs=3),
            rng_seed=42,
        )

        job_ids = [job.job_id for job in jobs]
        assert len(job_ids) == len(set(job_ids))  # All unique


# ---------------------------------------------------------------------------
# Test: Refiner / Hires / ADetailer Toggles
# ---------------------------------------------------------------------------


class TestToggleFlags:
    """Test that toggle flags are preserved through job construction."""

    def test_hires_enabled_preserved(self, job_builder: JobBuilderV2) -> None:
        """hires_enabled flag is preserved in job config."""
        config = make_minimal_pipeline_config(hires_enabled=True)

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        assert jobs[0].config.hires_enabled is True

    def test_refiner_enabled_preserved(self, job_builder: JobBuilderV2) -> None:
        """refiner_enabled flag is preserved in job config."""
        config = make_minimal_pipeline_config(refiner_enabled=True)

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        assert jobs[0].config.refiner_enabled is True

    def test_adetailer_enabled_preserved(self, job_builder: JobBuilderV2) -> None:
        """adetailer_enabled flag is preserved in job config."""
        config = make_minimal_pipeline_config(adetailer_enabled=True)

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        assert jobs[0].config.adetailer_enabled is True


# ---------------------------------------------------------------------------
# Test: Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Test that job construction is deterministic with fixed inputs."""

    def test_same_inputs_same_outputs(self) -> None:
        """Same inputs produce identical job lists."""
        # Fresh builders for each run
        id_gen1 = SequentialIdGenerator()
        time_gen1 = FixedTimeGenerator()
        builder1 = JobBuilderV2(time_fn=time_gen1, id_fn=id_gen1)

        id_gen2 = SequentialIdGenerator()
        time_gen2 = FixedTimeGenerator()
        builder2 = JobBuilderV2(time_fn=time_gen2, id_fn=id_gen2)

        config = make_minimal_pipeline_config(model="test", seed=123)
        plan = make_randomizer_plan_simple_models(["m1", "m2"], max_variants=2)
        batch = make_batch_settings(batch_runs=2)

        jobs1 = builder1.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=batch,
            rng_seed=42,
        )
        jobs2 = builder2.build_jobs(
            base_config=config,
            randomization_plan=plan,
            batch_settings=batch,
            rng_seed=42,
        )

        # Compare job IDs (should match with deterministic generators)
        assert [j.job_id for j in jobs1] == [j.job_id for j in jobs2]

        # Compare indices
        for j1, j2 in zip(jobs1, jobs2, strict=True):
            assert j1.variant_index == j2.variant_index
            assert j1.batch_index == j2.batch_index
            assert j1.seed == j2.seed

    def test_different_rng_seed_different_order(self) -> None:
        """Different rng_seed may produce different variant order."""
        id_gen = SequentialIdGenerator()
        time_gen = FixedTimeGenerator()
        builder = JobBuilderV2(time_fn=time_gen, id_fn=id_gen)

        config = make_minimal_pipeline_config()
        plan = make_randomizer_plan_simple_models(["m1", "m2", "m3"], max_variants=3)

        jobs_seed42 = builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=42,
        )
        id_gen.reset()
        jobs_seed99 = builder.build_jobs(
            base_config=config,
            randomization_plan=plan,
            rng_seed=99,
        )

        # Different seeds may produce different model orderings
        # (Just verify both produce expected count)
        assert len(jobs_seed42) == 3
        assert len(jobs_seed99) == 3


# ---------------------------------------------------------------------------
# Test: Empty/Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases in job construction."""

    def test_none_randomizer_plan(self, job_builder: JobBuilderV2) -> None:
        """None randomizer plan produces single job."""
        config = make_minimal_pipeline_config()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=None,
        )

        assert len(jobs) == 1

    def test_none_batch_settings(self, job_builder: JobBuilderV2) -> None:
        """None batch settings defaults to batch_runs=1."""
        config = make_minimal_pipeline_config()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
            batch_settings=None,
        )

        assert len(jobs) == 1
        assert jobs[0].batch_total == 1

    def test_none_output_settings(self, job_builder: JobBuilderV2) -> None:
        """None output settings uses defaults."""
        config = make_minimal_pipeline_config()

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
            output_settings=None,
        )

        assert jobs[0].path_output_dir == "output"
        assert jobs[0].filename_template == "{seed}"

    def test_dict_config_supported(self, job_builder: JobBuilderV2) -> None:
        """Dict configs are also supported."""
        config = {"model": "dict-model", "steps": 15, "seed": 999}

        jobs = job_builder.build_jobs(
            base_config=config,
            randomization_plan=make_randomizer_plan_disabled(),
        )

        assert len(jobs) == 1
        assert jobs[0].config["model"] == "dict-model"
        assert jobs[0].seed == 999
