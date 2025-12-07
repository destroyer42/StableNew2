#CANONICAL
# Randomizer_Spec_v2.5.md

---

# Executive Summary (8–10 lines)

The StableNew v2.5 Randomizer System provides deterministic, testable configuration-level variation for pipeline runs.  
It operates strictly through the RandomizationPlanV2 → RandomizerEngineV2 → JobBuilderV2 → NormalizedJobRecord path, with zero direct GUI or pipeline coupling.  
All randomization effects occur before job execution and result in a fixed, predictable list of jobs.  
The Randomizer is responsible for generating variant configs (model choices, CFG, steps, batch sizes, seed behavior) and integrating seamlessly with batch expansion and ConfigMergerV2.  
The GUI randomizer card builds the plan, the controller invokes the engine, and the preview panel displays variant summaries.  
This document defines the schema, engine rules, GUI interfaces, controller responsibilities, and required tests for the entire system.  

---

# PR-Relevant Facts (Quick Reference)

- Randomization **only** occurs during job construction, never at runtime.  
- RandomizerEngineV2 is **pure**, **deterministic**, and GUI-independent.  
- RandomizationPlanV2 defines all allowed knobs: lists, ranges (future), and seed modes.  
- Randomizer integrates before batch expansion, so batch × variants is multiplicative.  
- GUI controls must update AppState.JobDraft.randomization_plan.  
- PreviewPanelV2 must show variant counts + field summaries.  
- JobBuilderV2 must produce one NormalizedJobRecord per variant × batch.  
- No legacy randomizer code may be referenced or imported.  

---

============================================================
# 0. TLDR / BLUF — How Randomization Works
============================================================

GUI Randomizer Card
↓ builds
RandomizationPlanV2
↓ passed into
RandomizerEngineV2.generate_run_config_variants
↓ produces
N variant RunConfigV2 objects
↓ expanded with batch settings by
JobBuilderV2
↓ results in
NormalizedJobRecord list (variant × batch)
↓ shown in preview and submitted to queue

yaml
Copy code

### Key BLUF Points

- Deterministic: same plan + seed → same variants.  
- Isolated: no GUI, no controller, no runner imports in engine.  
- Multiplicative: variants × batches = total jobs.  
- Controller is the adapter; JobBuilderV2 is the integrator.  
- GUI only edits plan; does not calculate variants.  
- Pipeline never “randomizes” during execution.  

---

============================================================
# 1. Purpose of This Specification
============================================================

This document defines the **complete randomization subsystem** in StableNew v2.5:

1. Data structures (RandomizationPlanV2, seed modes, override fields).  
2. Randomizer engine behavior and invariants.  
3. GUI Randomizer card requirements.  
4. Controller integration logic.  
5. JobBuilderV2 expansion semantics.  
6. Preview & queue presentation rules.  
7. Required tests and validations.  
8. API stability guarantees for future systems (Learning, Cluster).

This spec replaces all legacy V1 “prompt matrix” randomizer logic.

---

============================================================
# 2. RandomizationPlanV2 (Schema)
============================================================

### 2.1 Dataclass Definition

The canonical schema is:

```python
@dataclass
class RandomizationPlanV2:
    enabled: bool = False
    max_variants: int = 1

    seed_mode: RandomizationSeedMode = RandomizationSeedMode.NONE
    base_seed: Optional[int] = None

    # Discrete choices (lists)
    model_choices: List[str] = field(default_factory=list)
    vae_choices: List[str] = field(default_factory=list)
    sampler_choices: List[str] = field(default_factory=list)
    scheduler_choices: List[str] = field(default_factory=list)

    cfg_scale_values: List[float] = field(default_factory=list)
    steps_values: List[int] = field(default_factory=list)
    batch_sizes: List[int] = field(default_factory=list)
2.2 Seed Modes
python
Copy code
class RandomizationSeedMode(str, Enum):
    NONE = "none"          # preserve original config seed
    FIXED = "fixed"        # all variants share the same seed
    PER_VARIANT = "per_variant"  # seed = base_seed + variant_index
2.3 Required Invariants
If enabled = False → exactly 1 variant (deepcopy of base config).

If all choice lists are empty → 1 variant.

Variants are ordered deterministically based on RNG seed.

max_variants truncates but never increases variant count.

============================================================

3. RandomizerEngineV2 (Core Behavior)
============================================================

3.1 Engine API
python
Copy code
def generate_run_config_variants(
    base_config: RunConfigV2,
    plan: RandomizationPlanV2,
    *,
    rng_seed: Optional[int] = None,
) -> list[RunConfigV2]
3.2 Engine Responsibilities
Must be pure and side-effect free.

Must deep-copy the base config before modifying.

Must operate only on config-level fields (txt2img stage initially).

Must NOT import GUI, controllers, queue, or runners.

Must NOT mutate the plan.

Must not rely on global RNG.

3.3 Algorithm
If plan.disabled → return [deepcopy(base_config)].

Build candidate override combinations:

Each non-empty field contributes values.

Empty fields contribute [None] (meaning no override).

Produce Cartesian product of all override axes.

Shuffle deterministically with rng_seed.

Truncate to max_variants.

Apply overrides to deep-copied configs.

Apply seed modes.

Return list.

3.4 Engine Guarantees
Deterministic output given same seed + same plan.

No reliance on legacy randomizer modules.

No dependence on any GUI state.

============================================================

4. GUI Randomizer Card Requirements
============================================================

The GUI contributes only the randomization plan.

4.1 Required Controls
Enable randomization checkbox

Max variants spinbox

Seed mode dropdown

Base seed entry

Multi-select or entry for:

models

vae

sampler

scheduler

CFG values

steps values

batch sizes

4.2 Required Behavior
On any control change → rebuild plan → call controller callback.

Panel must implement:

load_from_plan(plan)

build_plan()

Plan persists in AppState.JobDraft.

No calculation of variants inside GUI.

Dark mode compliance required (theme_v2 tokens).

4.3 Forbidden Behavior
Must not run RandomizerEngine directly.

Must not modify pipeline configs.

Must not talk to JobService.

Must not guess or simulate variant counts.

============================================================

5. Controller Integration
============================================================

5.1 Responsibilities
Controllers must:

Read randomization_plan from JobDraft.

Pass plan into RandomizerEngineV2 via JobBuilderV2.

Estimate variant count (multiplying batch × variant).

Update PreviewPanel with normalized job summaries.

Submit all jobs (variant × batch) to JobService.

5.2 Integration Pattern
The controller must follow this pattern:

python
Copy code
merged_config = merger.merge_pipeline(...)
jobs = job_builder.build_jobs(
    merged_config,
    randomization_plan,
    batch_settings,
    output_settings,
)
job_service.submit_jobs(jobs, run_mode)
5.3 Forbidden Actions
Controllers must not enumerate variants themselves.

Controllers must not modify RandomizerEngineV2 output.

Controllers must not override seeds manually.

============================================================

6. JobBuilderV2 Expansion Semantics
============================================================

6.1 Ordering
Apply ConfigMergerV2 to produce a single merged pipeline config.

Apply RandomizerEngineV2 to generate variant configs.

Apply batch expansion:

ini
Copy code
total_jobs = variants × batches
Wrap each expansion in a NormalizedJobRecord:

seed

batch index

variant index

config snapshot

output settings

6.2 Required Guarantees
All variant ordering preserved.

Batch expansion is stable and consistent.

Seed mode logic is preserved inside each NormalizedJobRecord.

Job count equals variant_count × batch_count.

No two variants share the same identity unless seed mode is FIXED.

============================================================

7. Preview and Queue Display Semantics
============================================================

7.1 PreviewPanelV2 Requirements
Must display:

Randomizer ON/OFF state

Max variants

For each configured axis:

Count of model choices

Range of CFG/steps values

Seed mode summary

Total job count (variant × batch)

7.2 QueuePanel Requirements
Each NormalizedJobRecord must appear as a separate item.

Metadata must reflect:

Variant index

Batch index

Model name

Seed

For multi-variant jobs:

Show variant order

Preserve ordering identical to JobBuilderV2 output

============================================================

8. Stability Guarantees / Backward Compatibility
============================================================

8.1 Stability Guarantees
RandomizationPlanV2 schema must remain stable for v2.5 lifecycle.

Randomizer engine signature must remain constant.

Controller contracts (plan → builder → job list) must be stable.

Variants must be reproducible across sessions.

8.2 Backward Compatibility
Legacy randomizer code remains archived and untouched.

No mixing V1 matrix-style prompting with v2.5 randomization.

Future extensions (e.g., ranges, weighted choices) must preserve deterministic core.

============================================================

9. Testing Requirements (Canonical)
============================================================

9.1 Engine Tests (Unit)
Must test:

Disabled plan → 1 variant.

Single axis choice lists.

Multi-axis Cartesian product.

Determinism via seed.

max_variants truncation.

Seed mode behavior (NONE, FIXED, PER_VARIANT).

9.2 Controller Tests (Integration)
Must confirm:

RandomizationPlan read correctly from JobDraft.

Engine invoked through JobBuilderV2, not directly.

Correct number of jobs submitted to JobService.

Preview panel receives correct normalized jobs.

9.3 GUI Tests (Behavior)
build_plan() correctness

load_from_plan() round-trip

Plan update events fire controller callbacks

9.4 JobBuilder Tests
Batch expansion correctness

Variant × batch ordering

Seed uniqueness under PER_VARIANT

FIXED seed consistency

============================================================

10. Future Extensions (v2.6+)
============================================================

Planned features:
Weighted choice lists

Multidimensional ranges

Randomization of stage enable/disable flags

Randomization of refiner/hires fix parameters

Randomizer presets

Learning-based variant scoring

Cluster-scale randomization distribution (Phase 3)

All future extensions must maintain:

determinism

purity

backward compatibility

predictable variant construction

============================================================

11. Deprecated Behaviors (Archived)
============================================================
#ARCHIVED
(For reference only — DO NOT IMPLEMENT)

Deprecated:

Prompt-matrix randomization from V1.

Mixed randomization with prompt token substitution.

Inline randomization in JobService or Runner.

GUI-based direct variant generation.

Hidden seeds or non-deterministic randomness.

End of Randomizer_Spec_v2.5.md