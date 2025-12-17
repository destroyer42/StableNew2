# Subsystem: Pipeline
# Role: Tests for payload normalization invariants.

"""Tests for payload normalization invariants.

These tests verify that the job construction pipeline maintains
key invariants regardless of the config object type used.

Invariants:
1. All output jobs have unique job_id strings
2. Output directory and filename template are preserved
3. Seed handling follows seed_mode semantics
4. Config objects are deep-copied (immutability)
5. Variant and batch indices are correctly assigned
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import BatchSettings, OutputSettings
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode

# ---------------------------------------------------------------------------
# Test Config Types
# ---------------------------------------------------------------------------


@dataclass
class DataclassConfig:
    """Standard dataclass config."""

    model: str = "model_dc"
    sampler: str = "euler"
    seed: int = 1000


class PlainClassConfig:
    """Plain class (non-dataclass) config."""

    def __init__(self) -> None:
        self.model = "model_plain"
        self.sampler = "ddim"
        self.seed = 2000


@dataclass
class NestedConfig:
    """Config with nested objects."""

    model: str = "model_nested"
    sampler: str = "dpm"
    seed: int = 3000
    nested: dict[str, Any] = field(default_factory=lambda: {"a": 1, "b": [1, 2, 3]})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def builder() -> JobBuilderV2:
    """Create a JobBuilderV2 instance."""
    return JobBuilderV2()


@pytest.fixture
def output_settings() -> OutputSettings:
    """Create output settings."""
    return OutputSettings(base_output_dir="/output/norm_test", filename_template="{job_id}_{seed}")


# ---------------------------------------------------------------------------
# Invariant: Unique Job IDs
# ---------------------------------------------------------------------------


class TestUniqueJobIds:
    """Verify all output jobs have unique IDs."""

    def test_single_job_has_id(self, builder: JobBuilderV2) -> None:
        """Single job has a non-empty ID."""
        jobs = builder.build_jobs(base_config=DataclassConfig())
        assert len(jobs) == 1
        assert jobs[0].job_id
        assert isinstance(jobs[0].job_id, str)

    def test_multiple_jobs_unique_ids(self, builder: JobBuilderV2) -> None:
        """Multiple jobs have unique IDs."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3"],
            max_variants=3,
        )
        batch = BatchSettings(batch_size=1, batch_runs=2)

        jobs = builder.build_jobs(
            base_config=DataclassConfig(), randomization_plan=plan, batch_settings=batch
        )
        ids = [j.job_id for j in jobs]
        assert len(ids) == len(set(ids)), "All job IDs must be unique"

    def test_repeated_calls_unique_ids(self, builder: JobBuilderV2) -> None:
        """Repeated calls produce unique IDs."""
        jobs1 = builder.build_jobs(base_config=DataclassConfig())
        jobs2 = builder.build_jobs(base_config=DataclassConfig())
        all_ids = [j.job_id for j in jobs1 + jobs2]
        assert len(all_ids) == len(set(all_ids)), "IDs unique across calls"


# ---------------------------------------------------------------------------
# Invariant: Output Settings Preserved
# ---------------------------------------------------------------------------


class TestOutputSettingsPreserved:
    """Verify output settings are correctly applied."""

    def test_output_dir_applied(
        self, builder: JobBuilderV2, output_settings: OutputSettings
    ) -> None:
        """Output directory is set on jobs."""
        jobs = builder.build_jobs(base_config=DataclassConfig(), output_settings=output_settings)
        assert all(j.path_output_dir == "/output/norm_test" for j in jobs)

    def test_filename_template_applied(
        self, builder: JobBuilderV2, output_settings: OutputSettings
    ) -> None:
        """Filename template is set on jobs."""
        jobs = builder.build_jobs(base_config=DataclassConfig(), output_settings=output_settings)
        assert all(j.filename_template == "{job_id}_{seed}" for j in jobs)

    def test_default_settings_when_none(self, builder: JobBuilderV2) -> None:
        """Default settings used when not provided."""
        jobs = builder.build_jobs(base_config=DataclassConfig())
        # Implementation defaults: output_dir="output", filename_template="{seed}"
        assert jobs[0].path_output_dir == "output"
        assert jobs[0].filename_template == "{seed}"


# ---------------------------------------------------------------------------
# Invariant: Seed Mode Semantics
# ---------------------------------------------------------------------------


class TestSeedModeSemantics:
    """Verify seed handling follows mode semantics."""

    def test_fixed_seed_all_same(self, builder: JobBuilderV2) -> None:
        """FIXED mode: all jobs get same seed."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2"],
            seed_mode=RandomizationSeedMode.FIXED,
            max_variants=2,
        )
        jobs = builder.build_jobs(
            base_config=DataclassConfig(), randomization_plan=plan, rng_seed=42
        )
        seeds = {j.seed for j in jobs}
        assert len(seeds) == 1, "FIXED mode should produce same seed for all"

    def test_per_variant_different_seeds(self, builder: JobBuilderV2) -> None:
        """PER_VARIANT mode: each variant gets unique seed."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3"],
            seed_mode=RandomizationSeedMode.PER_VARIANT,
            base_seed=100,
            max_variants=3,
        )
        jobs = builder.build_jobs(
            base_config=DataclassConfig(), randomization_plan=plan, rng_seed=42
        )
        seeds = [j.seed for j in jobs]
        assert len(seeds) == len(set(seeds)), "PER_VARIANT should produce unique seeds"

    def test_none_mode_preserves_original(self, builder: JobBuilderV2) -> None:
        """NONE mode: preserve original config seed."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1"],
            seed_mode=RandomizationSeedMode.NONE,
            max_variants=1,
        )
        jobs = builder.build_jobs(base_config=DataclassConfig(), randomization_plan=plan)
        # Should preserve the original seed from DataclassConfig (1000)
        assert jobs[0].seed == 1000


# ---------------------------------------------------------------------------
# Invariant: Immutability (Deep Copy)
# ---------------------------------------------------------------------------


class TestImmutability:
    """Verify config objects are deep-copied."""

    def test_dataclass_not_mutated(self, builder: JobBuilderV2) -> None:
        """Original dataclass config not mutated."""
        original = DataclassConfig()
        original_model = original.model

        plan = RandomizationPlanV2(enabled=True, model_choices=["changed"])
        builder.build_jobs(base_config=original, randomization_plan=plan)

        assert original.model == original_model

    def test_plain_class_not_mutated(self, builder: JobBuilderV2) -> None:
        """Original plain class config not mutated."""
        original = PlainClassConfig()
        original_model = original.model

        plan = RandomizationPlanV2(enabled=True, model_choices=["changed"])
        builder.build_jobs(base_config=original, randomization_plan=plan)

        assert original.model == original_model

    def test_nested_config_deep_copied(self, builder: JobBuilderV2) -> None:
        """Nested objects are deep-copied."""
        original = NestedConfig()
        original_nested_a = original.nested["a"]

        jobs = builder.build_jobs(base_config=original)
        # Modify the job's config nested value
        jobs[0].config.nested["a"] = 999

        assert original.nested["a"] == original_nested_a, (
            "Nested mutation should not affect original"
        )


# ---------------------------------------------------------------------------
# Invariant: Variant/Batch Indices
# ---------------------------------------------------------------------------


class TestIndices:
    """Verify variant and batch indices are correctly assigned."""

    def test_single_job_indices(self, builder: JobBuilderV2) -> None:
        """Single job has variant_index=0, batch_index=0."""
        jobs = builder.build_jobs(base_config=DataclassConfig())
        assert jobs[0].variant_index == 0
        assert jobs[0].batch_index == 0
        assert jobs[0].variant_total == 1
        assert jobs[0].batch_total == 1

    def test_variant_indices_sequential(self, builder: JobBuilderV2) -> None:
        """Variant indices are 0-based sequential."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2", "m3"],
            max_variants=3,
        )
        jobs = builder.build_jobs(base_config=DataclassConfig(), randomization_plan=plan)
        variant_indices = [j.variant_index for j in jobs]
        assert variant_indices == [0, 1, 2]
        assert all(j.variant_total == 3 for j in jobs)

    def test_batch_indices_sequential(self, builder: JobBuilderV2) -> None:
        """Batch indices are 0-based sequential."""
        batch = BatchSettings(batch_size=1, batch_runs=4)
        jobs = builder.build_jobs(base_config=DataclassConfig(), batch_settings=batch)
        batch_indices = [j.batch_index for j in jobs]
        assert batch_indices == [0, 1, 2, 3]
        assert all(j.batch_total == 4 for j in jobs)

    def test_combined_indices(self, builder: JobBuilderV2) -> None:
        """Combined variant + batch produces correct indices."""
        plan = RandomizationPlanV2(
            enabled=True,
            model_choices=["m1", "m2"],
            max_variants=2,
        )
        batch = BatchSettings(batch_size=1, batch_runs=3)

        jobs = builder.build_jobs(
            base_config=DataclassConfig(), randomization_plan=plan, batch_settings=batch
        )

        # Should have 2 variants * 3 batch_runs = 6 jobs
        assert len(jobs) == 6

        # Each variant should have 3 batch entries (batch_runs=3)
        for vi in [0, 1]:
            variant_jobs = [j for j in jobs if j.variant_index == vi]
            assert len(variant_jobs) == 3
            batch_indices = sorted(j.batch_index for j in variant_jobs)
            assert batch_indices == [0, 1, 2]


# ---------------------------------------------------------------------------
# Config Type Compatibility
# ---------------------------------------------------------------------------


class TestConfigTypeCompatibility:
    """Verify different config types work correctly."""

    def test_dataclass_config(self, builder: JobBuilderV2) -> None:
        """Dataclass config works."""
        jobs = builder.build_jobs(base_config=DataclassConfig())
        assert len(jobs) == 1
        assert jobs[0].config.model == "model_dc"

    def test_plain_class_config(self, builder: JobBuilderV2) -> None:
        """Plain class config works."""
        jobs = builder.build_jobs(base_config=PlainClassConfig())
        assert len(jobs) == 1
        assert jobs[0].config.model == "model_plain"

    def test_dict_config(self, builder: JobBuilderV2) -> None:
        """Dict config works."""
        config = {"model": "model_dict", "sampler": "lms", "seed": 5000}
        jobs = builder.build_jobs(base_config=config)
        assert len(jobs) == 1
        assert jobs[0].config["model"] == "model_dict"

    def test_nested_config(self, builder: JobBuilderV2) -> None:
        """Nested config works."""
        jobs = builder.build_jobs(base_config=NestedConfig())
        assert len(jobs) == 1
        assert jobs[0].config.nested["a"] == 1


# ---------------------------------------------------------------------------
# Timestamp Invariants
# ---------------------------------------------------------------------------


class TestTimestamps:
    """Verify timestamp invariants."""

    def test_timestamps_positive(self, builder: JobBuilderV2) -> None:
        """All timestamps are positive."""
        plan = RandomizationPlanV2(enabled=True, model_choices=["m1", "m2"])
        jobs = builder.build_jobs(base_config=DataclassConfig(), randomization_plan=plan)
        assert all(j.created_ts > 0 for j in jobs)

    def test_timestamps_non_decreasing(self, builder: JobBuilderV2) -> None:
        """Timestamps are non-decreasing."""
        plan = RandomizationPlanV2(enabled=True, model_choices=["m1", "m2", "m3"])
        batch = BatchSettings(batch_size=1, batch_runs=2)
        jobs = builder.build_jobs(
            base_config=DataclassConfig(), randomization_plan=plan, batch_settings=batch
        )

        timestamps = [j.created_ts for j in jobs]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], "Timestamps should be non-decreasing"
