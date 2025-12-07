PR-043-RANDOMIZER-ENGINE-CORE-V2-P1
1. Title

PR-043 – Randomizer Engine Core for RunConfigV2 (Logic Only, No GUI)

2. Summary

This PR creates a new, V2-only randomization engine that:

Lives in its own module (src/randomizer/randomizer_engine_v2.py), completely isolated from legacy/randomizer code.

Defines a RandomizationPlanV2 describing what to vary (models, samplers, steps, CFG, seeds, etc.) and how many variants to produce.

Exposes pure functions that take a base RunConfigV2 and a plan and return a deterministic list of run-config variants.

Includes a small, focused test suite verifying:

Determinism (same seed ⇒ same variants).

Truncation at max_variants.

Correct field overrides on each variant.

No coupling to legacy src/utils/randomizer.py.

No GUI or controller wiring happens here; that will be done later in PR-044 (Randomizer GUI integration).

3. Problem Statement

Right now:

There is a legacy/randomizer implementation (src/utils/randomizer.py + tests in tests/utils/test_randomizer_*), but:

It is not V2-aligned.

It operates tightly around the old prompt-matrix system and is considered legacy for V2.

The V2 pipeline/JobDraft path has a conceptual place for randomization (job-level variants, config permutations), but:

There is no clean, standalone engine that takes a base RunConfigV2 + a structured plan and returns variants.

Any future GUI work (Pipeline left-panel Randomizer card, job preview, queue expansion) would have to re-invent or copy logic.

We want Randomizer to be:

Headless (no Tk dependencies).

Deterministic (seeded).

Unit-testable and independent of UI details.

Without a dedicated engine, future PRs (Randomizer GUI, Job expansion, Learning) will be fragile and scatter randomization logic across GUI and controller layers.

4. Goals

Create a dedicated V2 randomization engine module

New package: src/randomizer/ with randomizer_engine_v2.py and __init__.py.

No imports from src/utils/randomizer.py or other legacy modules.

Define a RandomizationPlanV2 schema

Minimal but useful description of:

Fields to vary: model, VAE, sampler, scheduler, steps, CFG, batch size.

How to vary them: discrete value lists vs ranges.

Variant control: max_variants, seed behavior.

Example fields (final names can be adapted to existing structures):

enabled: bool

max_variants: int

seed_mode: Literal["fixed", "per_variant", "none"]

base_seed: int | None

model_choices: list[str]

vae_choices: list[str]

sampler_choices: list[str]

scheduler_choices: list[str]

cfg_scale_values: list[float]

steps_values: list[int]

batch_sizes: list[int]

Expose pure engine functions

Core API (conceptual; adapt to actual types):

def generate_run_config_variants(
    base_config: RunConfigV2,
    plan: RandomizationPlanV2,
    *,
    rng_seed: int | None = None,
) -> list[RunConfigV2]:
    ...


Behavior:

If plan.enabled is False, return [base_config] unchanged.

When enabled:

Compute an ordered set of candidate overrides from the plan.

Apply them to deep-cloned copies of base_config.

Produce at most max_variants configs.

Deterministic given rng_seed.

Add tests for correctness & determinism

New test module tests/randomizer/test_randomizer_engine_v2.py verifying:

Determinism with a fixed rng_seed.

Multiple fields being randomized simultaneously.

max_variants truncation.

Seed modes:

"fixed": preserved base seed in all variants.

"per_variant": different, deterministic seeds.

No import of src/utils/randomizer.py.

No GUI or JobQueue integration yet

This PR lays the foundation.

GUI wiring, JobDraft expansion, and Job preview changes will occur in PR-044 and later.

5. Non-goals

No modifications to Tk/GUI components (Pipeline tab, Randomizer panel, etc.).

No changes to JobQueue, JobHistory, or Learning.

No changes to legacy randomizer (src/utils/randomizer.py) or its tests.

No attempt to support the full legacy prompt-matrix randomization — we only care about config-level randomization for now.

6. Allowed Files

New V2 randomizer engine

src/randomizer/__init__.py (new, minimal package initializer)

src/randomizer/randomizer_engine_v2.py (new)

Optional type glue (minimal & careful)

src/pipeline/run_config_v2.py (or equivalent run-config module)

Only if:

A type alias or lightweight Protocol is required for RunConfigV2 to avoid circular imports.

Do not change core run-config behavior or fields in this PR.

Tests

tests/randomizer/test_randomizer_engine_v2.py (new)

7. Forbidden Files

Do not modify:

src/utils/randomizer.py

tests/utils/test_randomizer_*

Any GUI files:

src/gui/main_window_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/panels_v2/sidebar_panel_v2.py

src/gui/panels_v2/randomizer_panel_v2.py (or similar)

src/gui/preview_panel_v2.py

Job execution / queue core:

src/pipeline/executor.py / src/pipeline/executor_v2.py

src/pipeline/job_queue_v2.py (or equivalent)

Entry point and WebUI integration:

src/main.py

src/api/healthcheck.py

src/api/webui_process_manager.py

src/api/webui_client.py

If changes to any forbidden file become necessary, they must be handled in a separate, explicitly scoped PR (likely the GUI/queue integration PR).

8. Step-by-step Implementation
A. New module: src/randomizer/randomizer_engine_v2.py

Create src/randomizer/__init__.py:

Minimal:

# V2 randomizer package (engine-only, GUI-independent)


In randomizer_engine_v2.py, define:

RandomizationSeedMode type:

from enum import Enum

class RandomizationSeedMode(str, Enum):
    FIXED = "fixed"
    PER_VARIANT = "per_variant"
    NONE = "none"


RandomizationPlanV2 dataclass:

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class RandomizationPlanV2:
    enabled: bool = False
    max_variants: int = 1

    seed_mode: RandomizationSeedMode = RandomizationSeedMode.NONE
    base_seed: Optional[int] = None

    model_choices: List[str] = field(default_factory=list)
    vae_choices: List[str] = field(default_factory=list)
    sampler_choices: List[str] = field(default_factory=list)
    scheduler_choices: List[str] = field(default_factory=list)

    cfg_scale_values: List[float] = field(default_factory=list)
    steps_values: List[int] = field(default_factory=list)
    batch_sizes: List[int] = field(default_factory=list)


A small helper struct for overrides (internal use):

@dataclass(frozen=True)
class _VariantOverride:
    model: Optional[str] = None
    vae: Optional[str] = None
    sampler: Optional[str] = None
    scheduler: Optional[str] = None
    cfg_scale: Optional[float] = None
    steps: Optional[int] = None
    batch_size: Optional[int] = None


Implement override generation:

Create an internal function:

from typing import Iterable
import itertools
import random

def _iter_candidate_overrides(plan: RandomizationPlanV2, rng: random.Random) -> Iterable[_VariantOverride]:
    # 1. Turn each list into at least [None] so that missing dims fall back to base_config.
    # 2. Build a Cartesian product across configured fields.
    # 3. Optionally shuffle order with rng for variation.
    ...


Behavior details:

If all choice lists are empty → yield a single _VariantOverride() (i.e., no overrides).

Otherwise:

Build finite combinations from non-empty lists.

For empty dimensions, use [None] so no override is applied.

Optionally shuffle the combination list using rng.shuffle so we don't always iterate in the same grid order, but we stay deterministic.

Implement core engine: generate_run_config_variants

from copy import deepcopy

def generate_run_config_variants(
    base_config,
    plan: RandomizationPlanV2,
    *,
    rng_seed: int | None = None,
) -> list:
    """
    base_config: expected to behave like RunConfigV2 (duck-typed).
    Returns a list of deep-copied configs with randomized overrides.
    """
    if not plan.enabled:
        return [deepcopy(base_config)]

    rng = random.Random(rng_seed)

    # Compute overrides, shuffle deterministically, truncate to max_variants
    overrides_iter = list(_iter_candidate_overrides(plan, rng))
    if plan.max_variants and plan.max_variants > 0:
        overrides_iter = overrides_iter[: plan.max_variants]

    variants: list = []
    for idx, override in enumerate(overrides_iter):
        cfg = deepcopy(base_config)

        # apply overrides onto cfg (assume cfg has fields like .model, .vae, etc.)
        # NOTE: do not import RunConfigV2 directly; rely on duck-typing.
        if override.model is not None:
            cfg.txt2img.model = override.model
        if override.vae is not None:
            cfg.txt2img.vae = override.vae
        if override.sampler is not None:
            cfg.txt2img.sampler = override.sampler
        if override.scheduler is not None:
            cfg.txt2img.scheduler = override.scheduler
        if override.cfg_scale is not None:
            cfg.txt2img.cfg_scale = override.cfg_scale
        if override.steps is not None:
            cfg.txt2img.steps = override.steps
        if override.batch_size is not None:
            cfg.txt2img.batch_size = override.batch_size

        # Seed handling
        if plan.seed_mode == RandomizationSeedMode.FIXED and plan.base_seed is not None:
            cfg.txt2img.seed = plan.base_seed
        elif plan.seed_mode == RandomizationSeedMode.PER_VARIANT and plan.base_seed is not None:
            cfg.txt2img.seed = plan.base_seed + idx

        variants.append(cfg)

    if not variants:
        # Fallback: at least base config
        variants.append(deepcopy(base_config))

    return variants


Important:

Do not import RunConfigV2 directly in this module to avoid circular dependencies.

Use duck-typing expectations (tests will create simple fake configs if needed).

The exact attribute paths (cfg.txt2img.*) can be adjusted in Codex implementation based on real run-config structure; the PR intent is clear: apply overrides to the primary stage config (txt2img) for now.

Optionally expose a top-level symbol in __init__.py:

from .randomizer_engine_v2 import (
    RandomizationPlanV2,
    RandomizationSeedMode,
    generate_run_config_variants,
)

__all__ = [
    "RandomizationPlanV2",
    "RandomizationSeedMode",
    "generate_run_config_variants",
]

B. Tests: tests/randomizer/test_randomizer_engine_v2.py

Implement tests focusing on engine behavior:

Test 1 – Disabled plan returns base unchanged:

Build a simple fake config object (e.g., small dataclass with .txt2img.model, etc.).

Plan: enabled=False.

Call generate_run_config_variants.

Assert:

Length = 1.

Fields match the original.

Test 2 – Single-field list:

Base model "model_base".

Plan with model_choices=["m1", "m2", "m3"], max_variants=3, enabled=True.

Assert:

Exactly 3 variants.

Each variant’s model in {"m1","m2","m3"}.

Other fields (e.g., steps, cfg_scale) unchanged.

Test 3 – Multi-field with truncation:

Base config with default values.

Plan:

model_choices=["m1", "m2"]

cfg_scale_values=[4.5, 7.0]

steps_values=[20, 30]

max_variants=3

With rng_seed=123, call the engine.

Assert:

Exactly 3 variants.

Each combination appears to be a plausible mix from the choices.

A second call with the same base config + plan + rng_seed=123 yields identical values in the same order.

Test 4 – Seed modes:

Plan: seed_mode=FIXED, base_seed=42, enabled=True, max_variants=3, with some simple choices.

Assert all variants get .txt2img.seed == 42.

Plan: seed_mode=PER_VARIANT, base_seed=100, max_variants=3.

Assert seeds are [100, 101, 102].

Test 5 – Legacy isolation:

Try to import src/utils/randomizer and ensure:

randomizer_engine_v2 does not import it.

A simple regex or static check might be overkill; simpler is:

Ensure tests only import from src/randomizer, and there are no runtime errors.

The spec-level requirement is: no direct import from src/utils/randomizer in the new module.

9. Required Tests (Failing first)

Before implementation:

tests/randomizer/test_randomizer_engine_v2.py does not exist or fails.

After implementation:

The new tests must pass:

python -m pytest tests/randomizer/test_randomizer_engine_v2.py -q


Existing randomizer tests must remain unchanged and still pass:

python -m pytest tests/utils/test_randomizer_*.py -q


(They exercise legacy logic; they are allowed to stay as-is but should not depend on the new engine.)

10. Acceptance Criteria

PR-043 is complete when:

New module exists:

src/randomizer/randomizer_engine_v2.py defines:

RandomizationPlanV2

RandomizationSeedMode

generate_run_config_variants(...)

Engine behavior:

With enabled=False, engine returns one deep-copied base config.

With simple lists, engine yields distinct variants using those lists.

With multiple lists and max_variants, engine yields ≤ max_variants variants.

With seed_mode set, seeds follow the rules described above.

Calls with same base config + plan + rng_seed yield identical sequences.

Isolation:

New engine does not import or depend on src/utils/randomizer.py.

Existing legacy randomizer tests still pass.

No GUI changes:

No GUI files modified.

App behavior from user perspective is unchanged (Randomizer UI still behaves as before; this engine is not yet wired).

No forbidden files changed:

main.py, executor, healthcheck, WebUI process manager, and GUI V2 core remain untouched.

11. Rollback Plan

If PR-043 causes any issues:

Revert:

src/randomizer/__init__.py

src/randomizer/randomizer_engine_v2.py

tests/randomizer/test_randomizer_engine_v2.py

Re-run tests to confirm:

python -m pytest -q


Confirm that existing GUI, pipeline, and legacy randomizer behavior is restored to the pre-PR state.

12. Codex Execution Constraints

Do not import RunConfigV2 or GUI modules in randomizer_engine_v2.py; it must remain headless and generic.

Do not modify:

src/utils/randomizer.py

Any GUI V2 or main entrypoint files

Any executor / pipeline runner core

Prefer dataclasses and simple types; no new dependencies.

Maintain typing (use from __future__ import annotations if needed).

13. Smoke Test Checklist

After Codex implements PR-043:

Run new tests:

python -m pytest tests/randomizer/test_randomizer_engine_v2.py -q


Run existing randomizer tests:

python -m pytest tests/utils/test_randomizer_*.py -q


Sanity-check imports:

Start Python REPL:

from src.randomizer import RandomizationPlanV2, RandomizationSeedMode, generate_run_config_variants


Confirm import works and no legacy modules are pulled in unexpectedly.

Launch the app:

python -m src.main


Confirm GUI boots and behaves the same as before (no new Randomizer behavior yet).

If everything passes, PR-043 gives us a clean, testable randomization core that PR-044 can hook into the Pipeline tab and Job queue.