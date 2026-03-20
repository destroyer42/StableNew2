# Randomizer Spec v2.6

Status: Canonical subsystem reference
Updated: 2026-03-19

## 0. Purpose

This document defines the active randomizer subsystem in StableNew v2.6.

The randomizer subsystem covers two related but distinct behaviors:

- config-level variant randomization used during NJR construction
- prompt-level matrix, wildcard, and prompt S/R randomization used before
  pipeline execution

Both happen before fresh execution. Neither is allowed to randomize anything at
runner time.

## 1. Scope and Architecture

The canonical runtime remains:

`Intent Surface -> Builder/Compiler -> NJR -> Queue -> Runner`

Randomization belongs strictly in the builder/compiler layer.

The randomizer subsystem must never:

- execute at runner time
- modify queued jobs after submission
- depend on GUI widgets or controller state directly
- introduce a second execution path

## 2. Active Code Ownership

### 2.1 Config-level randomization

Primary modules:

- `src/randomizer/randomizer_engine_v2.py`
- `src/randomizer/__init__.py`
- `src/pipeline/randomizer_v2.py`

This layer produces deterministic config variants from `RandomizationPlanV2`
before NJR construction.

### 2.2 Prompt and matrix randomization

Primary modules:

- `src/utils/randomizer.py`
- `src/utils/prompt_pack_utils.py`

This layer expands:

- matrix slots
- wildcard tokens
- prompt S/R rules

before the final prompt text is frozen into NJR-backed work.

### 2.3 GUI participation

GUI surfaces may collect randomizer settings and display summaries, but they do
not own variant calculation.

Relevant GUI and adapter layers:

- `src/gui/randomizer_panel_v2.py`
- `src/gui/panels_v2/randomizer_panel_v2.py`
- `src/gui_v2/adapters/randomizer_adapter_v2.py`

## 3. Canonical Invariants

1. Randomization occurs before queue submission.
2. Identical inputs plus identical seeds produce identical outputs.
3. Randomizer logic remains GUI-independent at the execution layer.
4. Prompt randomization and config randomization may both contribute to job
   multiplicity, but the final job list must still be deterministic.
5. Queue and runner consume only the already-randomized NJR-backed work.

## 4. Config-Level Randomization Contract

### 4.1 Plan model

The canonical config-randomization plan is `RandomizationPlanV2` with:

- `enabled`
- `max_variants`
- `seed_mode`
- `base_seed`
- discrete choice lists for:
  - model
  - vae
  - sampler
  - scheduler
  - cfg_scale
  - steps
  - batch_size

### 4.2 Seed modes

Supported seed behavior:

- `none`
- `fixed`
- `per_variant`

### 4.3 Engine guarantees

`generate_run_config_variants(...)` must:

- deep-copy the base config
- enumerate candidate overrides deterministically
- apply seeded shuffling only through the provided RNG seed
- cap results to `max_variants` when configured
- return at least one config variant

## 5. Prompt-Level Randomization Contract

### 5.1 Supported behaviors

The prompt randomizer may apply:

- matrix slot substitution
- matrix fanout / rotate / sequential / random modes
- wildcard token expansion
- prompt search/replace rules

### 5.2 Matrix slot compatibility

Matrix slot names must support canonical aliasing and normalization. The active
runtime must handle practical slot-name variants such as:

- hyphenated names
- underscored names
- compact normalized aliases

### 5.3 Prompt finalization

All unresolved prompt-randomizer tokens must be removed or rejected before
fresh execution proceeds.

## 6. Builder Integration

Randomizer integration must remain inside canonical build-time expansion.

The builder path is responsible for:

- reading randomizer settings from normalized draft or metadata
- expanding prompt and config variants
- preserving provenance such as matrix slot values and randomizer summary
- freezing final prompt/config results into NJR-backed work

## 7. Queue and History Behavior

After queue submission:

- the queue stores the randomized NJR-backed work only
- history stores randomized provenance and summaries
- replay uses the persisted NJR-backed snapshot, not a fresh rerun of randomizer logic

## 8. GUI and Preview Rules

GUI randomizer panels may:

- collect plan settings
- show estimated variant counts and risk bands
- show preview-friendly summaries

GUI randomizer panels may not:

- directly execute the randomizer engine as runtime authority
- mutate queue entries
- construct alternate execution payloads

## 9. Testing Expectations

The randomizer subsystem should be covered by:

- deterministic config-randomizer tests
- prompt matrix/wildcard sanitization tests
- preview/pipeline parity tests
- controller integration tests for builder wiring

Representative active tests include:

- `tests/controller/test_pipeline_randomizer_integration_v2.py`
- `tests/utils/test_randomizer_sanitization.py`
- `tests/utils/test_prompt_randomizer.py`
- `tests/utils/test_randomizer_parity.py`

## 10. Forbidden Patterns

The following are defects:

- GUI-only randomizer calculations becoming the source of truth
- runner-time randomization
- unresolved matrix or wildcard tokens reaching execution
- queue entries that require re-randomization at run time
- reintroduction of legacy randomizer code as an execution dependency

## 11. Relationship to PromptPack

PromptPack remains the primary image authoring surface.

Randomizer behavior is one expansion layer that may be applied during
PromptPack-driven job construction. It does not change the broader v2.6 rule
that other intent surfaces may also exist as long as they converge to NJR.
