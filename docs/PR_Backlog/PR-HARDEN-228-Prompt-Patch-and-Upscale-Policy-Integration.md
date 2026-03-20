# PR-HARDEN-228 - Prompt Patch and Upscale Policy Integration

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Adaptive Refinement Full Runtime Integration
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-HARDEN-227`, StableNew can safely apply bounded ADetailer overrides.
The remaining runtime gap is stage-scoped prompt patching and limited upscale
policy adjustments.

### Specific Problem

The research memo proposed prompt tweaks, LoRA and embedding weight changes, and
upscale policies as one bundle. That is too broad for a single rollout unless
the patch contract and merge order are tightly constrained.

### Why This PR Exists Now

This PR completes the runtime-facing part of adaptive refinement while keeping a
strict boundary around what prompt and upscale mutations are allowed in v1.

### Reference

- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Goals & Non-Goals

### Goals

1. Add a stage-scoped prompt patch contract with deterministic merge order.
2. Apply prompt patches only through StableNew-owned executor logic.
3. Apply bounded upscale policy overrides when mode allows.
4. Preserve original prompt, patch payload, and final prompt provenance.
5. Keep the prompt patch surface strictly textual and compatible with the
   canonical `adaptive_refinement` provenance carrier.

### Non-Goals

1. Do not mutate NJR base prompts directly.
2. Do not add LoRA or embedding weight overrides in v1.
3. Do not add autonomous prompt generation or AI planning.
4. Do not extend learning behavior in this PR.

## Guardrails

1. Prompt patches are stage-scoped only; base NJR prompts must remain unchanged.
2. V1 prompt patches are text-token operations only:
   `add_positive`, `remove_positive`, `add_negative`, `remove_negative`.
3. V1 upscale overrides must be limited and explicit; do not allow arbitrary
   backend payload mutation.
4. Merge order must be documented and tested exactly.
5. V1 prompt patches must not add, remove, or rewrite LoRA tags, embedding
   tokens, textual inversion names, or weighted prompt syntax.

## Allowed Files

### Files to Create

- `src/refinement/prompt_patcher.py`: deterministic patch merge helper
- `tests/refinement/test_prompt_patcher.py`: merge-order coverage

### Files to Modify

- `src/refinement/refinement_policy_registry.py`: add prompt-patch and upscale
   policy outputs
- `src/refinement/subject_scale_policy_service.py`: emit prompt-patch and
   upscale decisions
- `src/pipeline/pipeline_runner.py`: pass patch and upscale decisions into
   execution
- `src/pipeline/executor.py`: apply prompt patches before existing optimizer
   flow and persist provenance
- `tests/pipeline/test_pipeline_runner.py`: end-to-end decision propagation
   assertions
- `tests/pipeline/test_executor_prompt_optimizer.py`: merge-order and optimizer
   coexistence assertions
- `tests/api/test_sdxl_payloads.py`: payload-level assertions for bounded
   upscale mutation
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`: document patch payload and upscale
   override fields
- `docs/Image_Metadata_Contract_v2.6.md`: document prompt and patch provenance
   fields

### Forbidden Files

- `src/learning/**`: no learning changes in this PR
- `src/controller/**`: no controller or GUI work
- `src/video/**`: no backend or video coupling

## Implementation Plan

### Step 1: Create the deterministic prompt patch helper

Required details:

- implement a helper that accepts a base prompt and the v1 patch payload
- preserve token order deterministically
- remove only exact matching tokens in v1; do not invent fuzzy matching
- explicitly ignore or reject attempts to patch LoRA tags, embedding tokens, or
  weighted prompt syntax in v1

Files:

- create `src/refinement/prompt_patcher.py`
- create `tests/refinement/test_prompt_patcher.py`

### Step 2: Freeze the merge order with the executor

Required merge order:

1. start from the stage-local base prompt
2. apply adaptive refinement text-token patch
3. apply StableNew's existing global positive or negative prompt rules
4. run the existing prompt optimizer and deduper
5. persist original prompt, patch payload, and final prompt to metadata

Additional required provenance rule:

- persist all prompt-patch provenance under the same canonical
  `adaptive_refinement` carrier used by runner metadata and manifests; do not
  create a second prompt-only metadata block

Files:

- modify `src/pipeline/executor.py`
- modify `tests/pipeline/test_executor_prompt_optimizer.py`

### Step 3: Add bounded upscale policy application

Required details:

- only permit an explicit v1 allowlist of upscale policy fields
- do not allow arbitrary backend payload injection
- tie upscale policy application to `mode="full"`

Files:

- modify `src/refinement/refinement_policy_registry.py`
- modify `src/refinement/subject_scale_policy_service.py`
- modify `src/pipeline/pipeline_runner.py`
- modify `tests/api/test_sdxl_payloads.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 4: Extend the schema and metadata docs

Files:

- modify `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- modify `docs/Image_Metadata_Contract_v2.6.md`

## Testing Plan

### Unit Tests

- `tests/refinement/test_prompt_patcher.py`

### Integration Tests

- `tests/pipeline/test_executor_prompt_optimizer.py`
- `tests/api/test_sdxl_payloads.py`
- `tests/pipeline/test_pipeline_runner.py`

### Journey or Smoke Coverage

- one txt2img -> adetailer -> upscale smoke path with `mode="full"`

### Manual Verification

1. Compare a baseline run, an `adetailer` run, and a `full` run for the same
   input.
2. Confirm base NJR prompts remain unchanged.
3. Confirm the manifest records original prompt, patch payload, and final prompt
   after optimizer processing.

Suggested command set:

- `pytest tests/refinement/test_prompt_patcher.py tests/pipeline/test_executor_prompt_optimizer.py tests/api/test_sdxl_payloads.py tests/pipeline/test_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. Prompt patching follows one documented merge order.
2. NJR base prompts remain unchanged.
3. Upscale policy changes are bounded and explicit.
4. Replay provenance captures original prompt, patch payload, and final prompt.
5. Prompt patching cannot mutate LoRA tags, embedding tokens, or weighted
   syntax in v1.

### Failure Criteria

1. The PR adds LoRA or embedding weight override behavior in v1.
2. The merge order is undocumented or differs from tests.
3. Arbitrary backend payload mutation becomes possible through prompt or upscale
   policy fields.
4. The implementation can silently alter LoRA tags, embeddings, or weighted
   prompt syntax under the banner of text-token patching.

## Risk Assessment

### Low-Risk Areas

- isolated prompt patch helper logic

### Medium-Risk Areas With Mitigation

- prompt-optimizer integration
  - Mitigation: merge-order tests against existing executor prompt-optimizer
    behavior

### High-Risk Areas With Mitigation

- unintended composition drift from prompt or upscale changes
  - Mitigation: restrict v1 to text-token patches and a bounded upscale allowlist

### Rollback Plan

Revert to `mode="adetailer"` behavior only and remove prompt/upscale actuation.

## Critical Appraisal and Incorporated Corrections

1. Weakness: the research memo included LoRA and embedding weight overrides too
   early. Incorporated correction: v1 prompt patches are text-token only.
2. Weakness: the memo described prompt patches without a concrete merge order.
   Incorporated correction: this PR freezes and tests the merge order.
3. Weakness: the memo risked broad upscale mutation. Incorporated correction:
   this PR requires an explicit allowlist for upscale fields.
4. Weakness: the memo still left room for accidental mutation of special prompt
   syntaxes after weight overrides were removed.
   Incorporated correction: this PR explicitly forbids patching LoRA tags,
   embedding tokens, and weighted syntax in v1.

## Tech Debt Analysis

### Debt Removed

- missing stage-scoped prompt and upscale policy path for full adaptive mode

### Debt Intentionally Deferred

- learning-based evaluation and recommendation stratification
  - Owner: `PR-HARDEN-229`
- GUI exposure of the new runtime controls
  - Owner: future GUI follow-on after this series

## Documentation Updates

- update `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- update `docs/Image_Metadata_Contract_v2.6.md`
- update `docs/StableNew_Coding_and_Testing_v2.6.md` only if new merge-order
  rules need to be codified there

## Dependencies

### Internal Module Dependencies

- `src/pipeline/executor.py`
- current prompt optimizer path
- `src/pipeline/pipeline_runner.py`

### External Tools or Runtimes

- optional OpenCV assessment path from `PR-HARDEN-226`

## Approval & Execution

Planner: GitHub Copilot / ChatGPT planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-HARDEN-228`.
2. After runtime metadata and replay provenance are stable, execute
   `PR-HARDEN-229`.
