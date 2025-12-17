# Subsystem: Test Helpers
# Role: Shared fixtures for V2.5 parity tests (PR-204E).

"""Shared test fixtures for Pipeline V2.5 parity tests.

These helpers create real domain objects (not ad-hoc dicts) to stay aligned
with ARCHITECTURE_v2.5.

References:
- ARCHITECTURE_v2.5.md: Run path and job construction flow
- KNOWN_PITFALLS_QUEUE_TESTING.md: Queue test best practices
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.pipeline.job_models_v2 import BatchSettings, NormalizedJobRecord, OutputSettings
from src.randomizer import RandomizationPlanV2, RandomizationSeedMode

# ---------------------------------------------------------------------------
# Run Mode / Source Enums (for test isolation)
# ---------------------------------------------------------------------------


class RunMode(str, Enum):
    """Run mode for pipeline jobs."""

    DIRECT = "direct"
    QUEUE = "queue"


class RunSource(str, Enum):
    """Source of run request."""

    RUN = "run"
    RUN_NOW = "run_now"
    ADD_TO_QUEUE = "add_to_queue"


# ---------------------------------------------------------------------------
# RunConfig Factory
# ---------------------------------------------------------------------------


@dataclass
class RunConfigV2:
    """Minimal run config for testing controller paths."""

    run_mode: RunMode = RunMode.QUEUE
    source: RunSource = RunSource.RUN
    prompt_pack_id: str | None = "pack-001"
    prompt_source: str = "pack"


def make_run_config_v2(
    *,
    run_mode: RunMode = RunMode.QUEUE,
    source: RunSource = RunSource.RUN,
    prompt_pack_id: str | None = "pack-001",
) -> RunConfigV2:
    """Create a RunConfigV2 for testing."""
    return RunConfigV2(
        run_mode=run_mode,
        source=source,
        prompt_pack_id=prompt_pack_id,
    )


# ---------------------------------------------------------------------------
# Randomization Plan Factories
# ---------------------------------------------------------------------------


def make_randomizer_plan_disabled() -> RandomizationPlanV2:
    """Create a disabled randomization plan."""
    return RandomizationPlanV2(enabled=False)


def make_randomizer_plan_simple_models(
    models: list[str],
    max_variants: int = 2,
    seed_mode: RandomizationSeedMode = RandomizationSeedMode.PER_VARIANT,
    base_seed: int = 12345,
) -> RandomizationPlanV2:
    """Create a randomization plan with model choices."""
    return RandomizationPlanV2(
        enabled=True,
        max_variants=max_variants,
        seed_mode=seed_mode,
        base_seed=base_seed,
        model_choices=models,
    )


def make_randomizer_plan_with_variants(
    *,
    max_variants: int = 2,
    seed_mode: RandomizationSeedMode = RandomizationSeedMode.PER_VARIANT,
    base_seed: int = 12345,
    model_choices: list[str] | None = None,
    sampler_choices: list[str] | None = None,
    cfg_scale_values: list[float] | None = None,
    steps_values: list[int] | None = None,
) -> RandomizationPlanV2:
    """Create a customizable randomization plan."""
    return RandomizationPlanV2(
        enabled=True,
        max_variants=max_variants,
        seed_mode=seed_mode,
        base_seed=base_seed,
        model_choices=model_choices or [],
        sampler_choices=sampler_choices or [],
        cfg_scale_values=cfg_scale_values or [],
        steps_values=steps_values or [],
    )


# ---------------------------------------------------------------------------
# Pipeline Config Factory
# ---------------------------------------------------------------------------


@dataclass
class MinimalPipelineConfig:
    """Minimal pipeline config for testing.

    This is a test double, not the real PipelineConfig, but has the same
    attributes needed for JobBuilder and controller tests.
    """

    model: str = "base-model"
    prompt: str = "test prompt"
    negative_prompt: str = ""
    sampler: str = "Euler"
    scheduler: str = "Normal"
    steps: int = 20
    cfg_scale: float = 7.0
    width: int = 512
    height: int = 512
    seed: int | None = None
    hires_enabled: bool = False
    refiner_enabled: bool = False
    adetailer_enabled: bool = False
    stages: list[str] = field(default_factory=lambda: ["txt2img"])


def make_minimal_pipeline_config(
    model: str = "base-model",
    steps: int = 20,
    cfg_scale: float = 7.0,
    seed: int | None = None,
    *,
    hires_enabled: bool = False,
    refiner_enabled: bool = False,
    adetailer_enabled: bool = False,
) -> MinimalPipelineConfig:
    """Create a minimal pipeline config for testing."""
    return MinimalPipelineConfig(
        model=model,
        steps=steps,
        cfg_scale=cfg_scale,
        seed=seed,
        hires_enabled=hires_enabled,
        refiner_enabled=refiner_enabled,
        adetailer_enabled=adetailer_enabled,
    )


# ---------------------------------------------------------------------------
# Batch Settings Factory
# ---------------------------------------------------------------------------


def make_batch_settings(
    batch_size: int = 1,
    batch_runs: int = 1,
) -> BatchSettings:
    """Create batch settings for testing."""
    return BatchSettings(batch_size=batch_size, batch_runs=batch_runs)


# ---------------------------------------------------------------------------
# Output Settings Factory
# ---------------------------------------------------------------------------


def make_output_settings(
    base_output_dir: str = "output",
    filename_template: str = "{seed}",
) -> OutputSettings:
    """Create output settings for testing."""
    return OutputSettings(
        base_output_dir=base_output_dir,
        filename_template=filename_template,
    )


# ---------------------------------------------------------------------------
# NormalizedJobRecord Factory
# ---------------------------------------------------------------------------


def make_normalized_job_record(
    job_id: str = "job-001",
    config: Any = None,
    seed: int | None = 12345,
    variant_index: int = 0,
    variant_total: int = 1,
    batch_index: int = 0,
    batch_total: int = 1,
    output_dir: str = "output",
    filename_template: str = "{seed}",
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    if config is None:
        config = make_minimal_pipeline_config(seed=seed)

    return NormalizedJobRecord(
        job_id=job_id,
        config=config,
        path_output_dir=output_dir,
        filename_template=filename_template,
        seed=seed,
        variant_index=variant_index,
        variant_total=variant_total,
        batch_index=batch_index,
        batch_total=batch_total,
        created_ts=1000.0,
    )


# ---------------------------------------------------------------------------
# Job ID Generator for Deterministic Tests
# ---------------------------------------------------------------------------


class SequentialIdGenerator:
    """Generates sequential job IDs for deterministic testing."""

    def __init__(self, prefix: str = "job") -> None:
        self._prefix = prefix
        self._counter = 0

    def __call__(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:03d}"

    def reset(self) -> None:
        self._counter = 0


class FixedTimeGenerator:
    """Generates fixed/sequential timestamps for deterministic testing."""

    def __init__(self, start: float = 1000.0, increment: float = 1.0) -> None:
        self._current = start
        self._increment = increment

    def __call__(self) -> float:
        result = self._current
        self._current += self._increment
        return result

    def reset(self, start: float = 1000.0) -> None:
        self._current = start


__all__ = [
    "RunMode",
    "RunSource",
    "RunConfigV2",
    "make_run_config_v2",
    "make_randomizer_plan_disabled",
    "make_randomizer_plan_simple_models",
    "make_randomizer_plan_with_variants",
    "MinimalPipelineConfig",
    "make_minimal_pipeline_config",
    "make_batch_settings",
    "make_output_settings",
    "make_normalized_job_record",
    "SequentialIdGenerator",
    "FixedTimeGenerator",
]
