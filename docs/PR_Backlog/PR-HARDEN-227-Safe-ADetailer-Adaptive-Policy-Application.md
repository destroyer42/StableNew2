# PR-HARDEN-227 - Safe ADetailer Adaptive Policy Application

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Adaptive Refinement Controlled Actuation
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-HARDEN-226`, StableNew can assess subject scale and pose and emit rich
observation bundles. It still does not change output behavior.

### Specific Problem

The biggest immediate product need is improving small or profile faces without
destabilizing the entire image stack. ADetailer is the safest first actuation
surface because its knobs are already stable, explicit, and stage-local.

### Why This PR Exists Now

This PR is the first controlled behavior change in the adaptive refinement
series, and it must remain tightly scoped to ADetailer-only overrides.

### Reference

- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Goals & Non-Goals

### Goals

1. Apply per-image adaptive overrides only to the ADetailer stage.
2. Keep prompt text and upscale behavior unchanged in this PR.
3. Record the applied override summary in a manifest-facing canonical structure.
4. Preserve explicit rollback modes: `disabled`, `observe`, `adetailer`.
5. Reuse the same canonical `adaptive_refinement` carrier shape already frozen
   in earlier PRs instead of creating a new manifest-only payload format.

### Non-Goals

1. Do not patch prompts in this PR.
2. Do not change upscale behavior in this PR.
3. Do not change learning-system behavior in this PR.
4. Do not add GUI exposure in this PR.

## Guardrails

1. The only allowed behavior mutations are ADetailer-specific config overrides.
2. Allowed override keys in v1 are limited to:
   `ad_mask_min_ratio`, `ad_confidence`,
   `ad_inpaint_only_masked_padding`, `ad_use_inpaint_width_height`,
   `ad_inpaint_width`, `ad_inpaint_height`.
3. Do not mutate NJR prompts, executor global prompt state, or non-ADetailer
   stage configs.
4. Applied overrides must be recorded from the same canonical structure used to
   decide them.
5. Manifest and embedded image metadata surfaces must consume the same
   refinement carrier shape, not parallel ad hoc summaries.

## Allowed Files

### Files to Create

- `tests/pipeline/test_executor_refinement_manifest.py`: manifest-facing
  assertions for applied overrides

### Files to Modify

- `src/refinement/refinement_policy_registry.py`: add v1 ADetailer policy
  selection rules
- `src/refinement/subject_scale_policy_service.py`: produce applied ADetailer
  override decisions
- `src/pipeline/pipeline_runner.py`: copy per-image ADetailer overrides into
  execution flow
- `src/pipeline/executor.py`: persist applied override summary into stage
  manifests
- `tests/pipeline/test_pipeline_runner.py`: per-image override assertions
- `tests/pipeline/test_executor_adetailer.py`: ADetailer payload assertions
- `tests/pipeline/test_executor_refinement_manifest.py`: new manifest
  assertions
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`: document `applied_overrides` for
  ADetailer mode
- `docs/Image_Metadata_Contract_v2.6.md`: document manifest payload additions

### Forbidden Files

- `src/learning/**`: no learning work yet
- `src/controller/**`: no GUI or controller work
- `src/video/**`: no backend or video coupling
- `tests/gui_v2/**`: no GUI work

## Implementation Plan

### Step 1: Limit the policy registry to ADetailer-safe v1 behavior

Required details:

- implement only the ADetailer-safe policy presets in this PR
- keep decisions stage-local and explicit
- reject or ignore any request to produce prompt patches here

Files:

- modify `src/refinement/refinement_policy_registry.py`
- modify `src/refinement/subject_scale_policy_service.py`

### Step 2: Apply per-image overrides in the runner

Required details:

- respect rollout mode: only `mode="adetailer"` or `mode="full"` may apply
  overrides
- copy stage config before mutation; do not mutate shared config state across
  images
- keep non-ADetailer stage configs untouched

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 3: Persist applied overrides into the manifest path

Required details:

- executor manifest payload must include the applied override summary under a
  canonical `adaptive_refinement` block
- record both the selected `policy_id` and the exact overrides that were applied
- if no overrides were applied, do not emit fake override fields
- preserve the same structure for embedded image metadata mirroring; do not
  invent a second simplified image-only refinement schema

Files:

- modify `src/pipeline/executor.py`
- modify `tests/pipeline/test_executor_adetailer.py`
- create `tests/pipeline/test_executor_refinement_manifest.py`

### Step 4: Document the applied-override contract

Files:

- modify `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- modify `docs/Image_Metadata_Contract_v2.6.md`

## Testing Plan

### Unit Tests

- focused refinement-registry and service tests already in place from earlier PRs

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_executor_adetailer.py`
- `tests/pipeline/test_executor_refinement_manifest.py`

### Journey or Smoke Coverage

- one full txt2img -> adetailer smoke path with `mode="adetailer"`

### Manual Verification

1. Run a known small-face or profile-face case with `mode="observe"` and record
   the baseline bundle.
2. Re-run with `mode="adetailer"` and verify only ADetailer config changes.
3. Confirm manifest metadata records the exact applied override summary.

Suggested command set:

- `pytest tests/pipeline/test_pipeline_runner.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py -q`

## Verification Criteria

### Success Criteria

1. ADetailer-only adaptive overrides are applied when explicitly enabled.
2. Non-ADetailer stages and prompts remain unchanged.
3. Applied overrides are preserved in a manifest-facing canonical structure.
4. Embedded image metadata can mirror the same refinement structure without
   translation loss.

### Failure Criteria

1. The PR mutates prompt text or upscale settings.
2. Shared config state leaks across images.
3. Manifest provenance records differ from the actual applied override set.
4. Manifest and embedded image metadata carry divergent refinement summaries.

## Risk Assessment

### Low-Risk Areas

- stage-local policy selection

### Medium-Risk Areas With Mitigation

- per-image config copying inside the runner
  - Mitigation: explicit tests for no cross-image leakage

### High-Risk Areas With Mitigation

- executor manifest drift from applied behavior
  - Mitigation: derive manifest payload directly from the same override summary
    object used by the runner

### Rollback Plan

Return the runner to observation-only mode and remove ADetailer override
application while leaving the assessment and metadata path intact.

## Critical Appraisal and Incorporated Corrections

1. Weakness: the research memo bundled prompt mutation with ADetailer actuation.
   Incorporated correction: this PR is ADetailer-only.
2. Weakness: the memo lacked an explicit rollout kill-switch.
   Incorporated correction: this PR requires explicit mode gating.
3. Weakness: the memo separated decision and manifest concerns loosely.
   Incorporated correction: this PR requires one canonical applied-override
   summary used by both runner and manifest code.
4. Weakness: the memo did not force embedded image metadata to stay aligned with
   manifest provenance.
   Incorporated correction: this PR explicitly requires one reusable carrier for
   both surfaces.

## Tech Debt Analysis

### Debt Removed

- absence of a safe first adaptive actuation surface

### Debt Intentionally Deferred

- prompt patching and upscale policy integration
  - Owner: `PR-HARDEN-228`
- learning-based evaluation of the new behavior
  - Owner: `PR-HARDEN-229`

## Documentation Updates

- update `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- update `docs/Image_Metadata_Contract_v2.6.md`
- update `docs/StableNew_Coding_and_Testing_v2.6.md` only if new manifest test
  expectations need to be called out

## Dependencies

### Internal Module Dependencies

- `src/refinement/refinement_policy_registry.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`

### External Tools or Runtimes

- optional OpenCV assessment path from `PR-HARDEN-226`

## Approval & Execution

Planner: GitHub Copilot / ChatGPT planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-HARDEN-227`.
2. If ADetailer-only rollout is stable, execute `PR-HARDEN-228`.
