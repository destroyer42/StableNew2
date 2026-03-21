# PR-HARDEN-224 - Adaptive Refinement Contracts and Dark-Launch Foundation

Status: Implemented 2026-03-20
Priority: HIGH
Effort: MEDIUM
Phase: Adaptive Refinement Foundation
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

StableNew already has the runner, NJR, prompt infrastructure, and learning
infrastructure needed for adaptive refinement, but there is no canonical
refinement contract yet.

Current gaps:

- no `src/refinement/` boundary
- no canonical `intent_config["adaptive_refinement"]` key
- no versioned refinement schema doc
- no import guard preventing the refinement layer from drifting into GUI or
  video/backend ownership

### Specific Problem

The research memo correctly identified a runner-owned refinement feature, but it
did not first establish a canonical opt-in contract. Without that first step,
later PRs would be forced to invent ad hoc toggles, parallel metadata, or a new
execution DTO.

### Why This PR Exists Now

This PR is the safe starting point for the entire adaptive refinement series.
It creates the contract and dark-launch scaffolding without changing runtime
behavior.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Goals & Non-Goals

### Goals

1. Add a StableNew-owned `src/refinement/` package for adaptive refinement
   contracts.
2. Define one canonical nested `intent_config["adaptive_refinement"]` payload.
3. Preserve the refinement intent through builder and NJR snapshot paths without
   changing queue or runner semantics.
4. Add architecture guard tests that keep the refinement layer free of GUI and
   backend/video imports.
5. Add a versioned schema document for the v1 refinement contract.
6. Freeze one canonical `adaptive_refinement` carrier shape for later reuse
   across runner metadata, manifests, embedded image metadata, diagnostics, and
   learning context.

### Non-Goals

1. Do not add runner decision logic in this PR.
2. Do not apply any stage overrides in this PR.
3. Do not add OpenCV or detector behavior in this PR.
4. Do not add learning-record or recommendation changes in this PR.
5. Do not add GUI controls in this PR.

## Guardrails

1. NJR remains the only outer execution contract.
2. `adaptive_refinement` must live under `intent_config`; do not add a sibling
   top-level NJR field for it.
3. Queue semantics, runner semantics, and stage execution must remain unchanged.
4. The refinement layer must not import `tkinter`, `src.gui`, `src.gui_v2`,
   `src.video`, or backend-specific workflow code.
5. The contract must support explicit rollout modes:
   `disabled`, `observe`, `adetailer`, `full`.
6. The feature remains dark-launched; this PR must not create any implicit
   enable path or GUI-facing surface.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/refinement/__init__.py` | Package boundary |
| `src/refinement/refinement_policy_models.py` | Versioned contract models and enums |
| `src/refinement/refinement_policy_registry.py` | Registry interface and default no-op registry |
| `tests/refinement/test_refinement_policy_models.py` | Contract round-trip coverage |
| `tests/refinement/test_refinement_layer_imports.py` | AST import guard coverage |
| `tests/pipeline/test_cli_njr_builder.py` | CLI builder coverage for refinement intent |
| `docs/REFINEMENT_POLICY_SCHEMA_v1.md` | Active schema document for adaptive refinement |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/pipeline/config_contract_v26.py` | Add canonical `adaptive_refinement` intent key and extractor helpers |
| `src/pipeline/job_builder_v2.py` | Preserve the nested refinement intent in builder-produced NJRs |
| `src/pipeline/prompt_pack_job_builder.py` | Preserve the nested refinement intent in prompt-pack builder flows |
| `src/pipeline/cli_njr_builder.py` | Preserve the nested refinement intent for CLI-produced NJRs |
| `src/pipeline/job_requests_v2.py` | Add typed carrier only if required by current builder flow |
| `tests/pipeline/test_config_contract_v26.py` | Canonicalization assertions |
| `tests/pipeline/test_job_builder_v2.py` | Snapshot persistence assertions |
| `tests/pipeline/test_prompt_pack_job_builder.py` | Prompt-pack builder persistence assertions |
| `docs/DOCS_INDEX_v2.6.md` | Reference the schema doc once created |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/pipeline/pipeline_runner.py` | No behavior change in this PR |
| `src/pipeline/executor.py` | No stage execution changes in this PR |
| `src/controller/**` | No controller or GUI entrypoint work in this PR |
| `src/video/**` | No backend/video coupling |
| `tests/gui_v2/**` | No GUI work |

## Implementation Plan

### Step 1: Define the canonical refinement contract

Create the v1 contract models under `src/refinement/`.

Required details:

- define `AdaptiveRefinementIntent` with at least:
  `schema`, `enabled`, `mode`, `profile_id`, `detector_preference`,
  `record_decisions`, `algorithm_version`
- define a minimal `RefinementDecisionBundle` contract for later PRs, but keep
  it behavior-neutral in this PR
- define strict mode literals: `disabled`, `observe`, `adetailer`, `full`
- define the top-level canonical `adaptive_refinement` carrier shape so later
  PRs extend that carrier instead of inventing adjacent metadata blocks

Files:

- create `src/refinement/refinement_policy_models.py`
- create `src/refinement/refinement_policy_registry.py`
- create `tests/refinement/test_refinement_policy_models.py`

### Step 2: Add one canonical intent-config entry point

Extend config canonicalization so `adaptive_refinement` survives normalization.

Required details:

- add `adaptive_refinement` to `_INTENT_TOP_LEVEL_KEYS`
- add a focused helper such as `extract_adaptive_refinement_intent(...)`
- preserve nested payloads as deep copies; do not flatten nested fields into
  top-level execution config

Files:

- modify `src/pipeline/config_contract_v26.py`
- modify `tests/pipeline/test_config_contract_v26.py`

### Step 3: Preserve the contract through builder paths

Make current NJR builders preserve the nested contract.

Required details:

- keep the data inside `intent_config`
- do not add a second outer job DTO or a dedicated sibling NJR field
- if `job_requests_v2.py` needs a typed field to carry the nested payload,
  add only that carrier field and nothing runner-facing

Files:

- modify `src/pipeline/job_builder_v2.py`
- modify `src/pipeline/prompt_pack_job_builder.py`
- modify `src/pipeline/cli_njr_builder.py`
- modify `src/pipeline/job_requests_v2.py` only if required
- modify builder tests listed above

### Step 4: Add architecture guard coverage

Prevent the new subsystem from accreting forbidden imports.

Required details:

- implement the guard test using the same AST-walk pattern used by
  `tests/utils/test_no_gui_imports_in_utils.py`
- block `tkinter`, `ttk`, `src.gui`, `src.gui_v2`, `src.video`, and any
  backend-specific imports from the refinement package

Files:

- create `tests/refinement/test_refinement_layer_imports.py`

### Step 5: Document the stable schema

Create the v1 schema doc now so later PRs extend a known contract instead of
re-describing the payload in code comments.

Files:

- create `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- modify `docs/DOCS_INDEX_v2.6.md`
- document dark-launch status explicitly: default disabled, no GUI exposure,
  no runtime auto-enable path

## Testing Plan

### Unit Tests

- `tests/refinement/test_refinement_policy_models.py`
- `tests/refinement/test_refinement_layer_imports.py`
- `tests/pipeline/test_config_contract_v26.py`
- `tests/pipeline/test_job_builder_v2.py`
- `tests/pipeline/test_prompt_pack_job_builder.py`
- `tests/pipeline/test_cli_njr_builder.py`

### Integration Tests

- builder-to-NJR snapshot round trips for pack, prompt-pack, and CLI paths

### Journey or Smoke Coverage

- none in this PR; behavior must remain unchanged

### Manual Verification

1. Build an NJR through the main builder path with `adaptive_refinement`
   present in the input.
2. Confirm the nested payload survives canonicalization and snapshotting.
3. Confirm queue and runner behavior are unchanged because the runner does not
   yet read the contract.

Suggested command set:

- `pytest tests/refinement/test_refinement_policy_models.py tests/refinement/test_refinement_layer_imports.py tests/pipeline/test_config_contract_v26.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_prompt_pack_job_builder.py tests/pipeline/test_cli_njr_builder.py -q`

## Verification Criteria

### Success Criteria

1. `adaptive_refinement` survives canonicalization and builder serialization.
2. No new job model, queue path, or runner path is introduced.
3. The refinement package is covered by import-boundary tests.
4. The schema doc exists and matches the code contract.
5. The schema doc establishes one canonical carrier shape for later runtime,
   manifest, embedded-metadata, diagnostics, and learning integration.

### Failure Criteria

1. A sibling top-level NJR field is added for refinement intent.
2. The runner or executor changes behavior in this PR.
3. The refinement package imports GUI or video/backend code.
4. The schema doc and code contract diverge.
5. The contract leaves later PRs needing multiple competing provenance blocks
   instead of one canonical `adaptive_refinement` carrier.

## Risk Assessment

### Low-Risk Areas

- new contract-only files
- schema documentation

### Medium-Risk Areas With Mitigation

- builder-path persistence
  - Mitigation: cover pack, prompt-pack, and CLI builders separately

### High-Risk Areas With Mitigation

- config-contract drift causing a shadow config surface
  - Mitigation: keep exactly one nested key under `intent_config` and add a
    dedicated extractor helper instead of duplicating fields elsewhere

### Rollback Plan

Remove the new refinement package and schema key while leaving builder behavior
and queue/runtime semantics otherwise untouched.

## Critical Appraisal and Incorporated Corrections

1. Weakness: the research memo jumped from theory to runner behavior too early.
   Incorporated correction: this PR is strictly contract- and builder-only.
2. Weakness: the memo did not define a canonical opt-in surface.
   Incorporated correction: this PR requires a single nested
   `intent_config["adaptive_refinement"]` payload.
3. Weakness: the memo proposed a new subsystem without enforcement boundaries.
   Incorporated correction: this PR adds AST import-guard coverage immediately.
4. Weakness: the memo did not reserve one canonical provenance carrier early.
   Incorporated correction: this PR freezes one `adaptive_refinement` shape for
   all later surfaces to reuse.

## Tech Debt Analysis

### Debt Removed

- missing canonical contract for adaptive refinement
- missing package boundary for refinement-specific logic

### Debt Intentionally Deferred

- runner observation logic
  - Owner: `PR-HARDEN-225`
- real subject assessment and OpenCV integration
  - Owner: `PR-HARDEN-226`
- any stage override application
  - Owner: `PR-HARDEN-227`
- any GUI exposure or non-dark-launch enablement
  - Owner: future GUI planning after `PR-HARDEN-229`

## Documentation Updates

- create `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- update `docs/DOCS_INDEX_v2.6.md`
- update `docs/StableNew Roadmap v2.6.md` only if roadmap status wording must
  reflect the active series start

## Dependencies

### Internal Module Dependencies

- `src/pipeline/config_contract_v26.py`
- current NJR builder paths

### External Tools or Runtimes

- none

## Approval & Execution

Planner: GitHub Copilot / ChatGPT planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-HARDEN-224`.
2. After the contract is stable, execute `PR-HARDEN-225` for observation-only
   decision capture.
