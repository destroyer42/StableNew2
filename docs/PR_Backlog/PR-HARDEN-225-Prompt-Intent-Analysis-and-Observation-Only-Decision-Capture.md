# PR-HARDEN-225 - Prompt Intent Analysis and Observation-Only Decision Capture

Status: Implemented 2026-03-20
Priority: HIGH
Effort: MEDIUM
Phase: Adaptive Refinement Observation Layer
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-HARDEN-224`, StableNew has the canonical refinement contract but still
has no decision engine. The runner cannot yet infer creative intent or emit a
stable decision bundle.

### Specific Problem

The research memo assumed the analyzer and policy layer could be introduced at
the same time as stage mutation. That is too risky. StableNew needs an
observation-only phase first so metadata and decision semantics can stabilize
before any output-changing behavior lands.

### Why This PR Exists Now

This PR adds the deterministic analyzer and decision-capture path while keeping
all stage configs unchanged.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-HARDEN-224-Adaptive-Refinement-Contracts-and-Dark-Launch-Foundation.md`

## Goals & Non-Goals

### Goals

1. Implement prompt intent analysis using existing prompt infrastructure.
2. Implement a deterministic decision-bundle assembly path with a null-detector
   fallback.
3. Wire the runner to emit refinement decision bundles in observation mode.
4. Keep stage configs, prompts, and manifests unchanged in this PR.
5. Freeze the observation bundle so later manifest, embedded-metadata,
   diagnostics, and learning surfaces can reuse it without schema forks.

### Non-Goals

1. Do not apply any ADetailer, prompt, or upscale overrides in this PR.
2. Do not add OpenCV detector support in this PR.
3. Do not add executor manifest fields in this PR.
4. Do not add learning-system changes in this PR.

## Guardrails

1. Observation mode must never mutate stage configs.
2. The analyzer must reuse existing prompt helpers instead of duplicating prompt
   parsing or introducing a second classifier stack.
3. The default detector in production remains a null detector until
   `PR-HARDEN-226`.
4. All emitted metadata must live under a single `adaptive_refinement` block.
5. Observation mode remains dark-launch only; no GUI path or implicit enable
   behavior may be added here.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/refinement/prompt_intent_analyzer.py` | Stable prompt-intent inference layer |
| `src/refinement/subject_scale_policy_service.py` | Decision-bundle assembly with null-detector support |
| `src/refinement/detectors/__init__.py` | Detector package boundary |
| `src/refinement/detectors/base_detector.py` | Detector interface |
| `src/refinement/detectors/null_detector.py` | Default no-op detector |
| `tests/refinement/test_prompt_intent_analyzer.py` | Analyzer coverage |
| `tests/refinement/test_subject_scale_policy_service.py` | Decision-bundle coverage |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/refinement/refinement_policy_registry.py` | Implement the default v1 selection path |
| `src/pipeline/pipeline_runner.py` | Emit observation-only refinement metadata when enabled |
| `tests/pipeline/test_pipeline_runner.py` | Observation-mode runner assertions |
| `docs/REFINEMENT_POLICY_SCHEMA_v1.md` | Freeze bundle fields emitted by the runner |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/pipeline/executor.py` | No manifest or payload mutation yet |
| `src/learning/**` | No learning work yet |
| `src/controller/**` | No controller or GUI work |
| `src/video/**` | No backend coupling |

## Implementation Plan

### Step 1: Implement prompt-intent analysis on top of existing prompt utilities

Required details:

- use `src/prompting/prompt_bucket_rules.py`
- use `src/prompting/prompt_classifier.py`
- use `src/prompting/prompt_splitter.py`
- use `src/utils/embedding_prompt_utils.py`
- do not add a second tokenizer or a second prompt-bucket rules file

Files:

- create `src/refinement/prompt_intent_analyzer.py`
- create `tests/refinement/test_prompt_intent_analyzer.py`

### Step 2: Implement observation-only decision-bundle assembly

Required details:

- the service must accept an injected detector but default to `NullDetector`
- when no detector data exists, the bundle must explicitly record an assessment
  note such as `assessment_unavailable` or `no_face_detected`
- the default registry path may select policy ids, but it must return
  observation-only decisions with empty applied overrides in this PR
- the emitted bundle shape must be directly extensible into later manifest,
  embedded image metadata, diagnostics, and learning surfaces

Files:

- create `src/refinement/subject_scale_policy_service.py`
- create `src/refinement/detectors/base_detector.py`
- create `src/refinement/detectors/null_detector.py`
- modify `src/refinement/refinement_policy_registry.py`
- create `tests/refinement/test_subject_scale_policy_service.py`

### Step 3: Wire the runner for observation-only metadata capture

Required details:

- read the nested refinement intent through the contract helper added in
  `PR-HARDEN-224`
- emit metadata only when `enabled=true` and `mode="observe"`
- store all emitted data under `run_result.metadata["adaptive_refinement"]`
- do not mutate `config`, `stage.extra`, payloads, prompts, or executor inputs
- include stable fields that can later be mirrored into manifests and embedded
  image metadata without translation loss

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 4: Freeze the observation payload in docs

Required details:

- update the schema doc so later PRs extend an explicit observation payload
- distinguish clearly between `decision_bundle` and future `applied_overrides`
- make clear that this observation payload is the base canonical carrier for
  all later refinement provenance surfaces

Files:

- modify `docs/REFINEMENT_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/refinement/test_prompt_intent_analyzer.py`
- `tests/refinement/test_subject_scale_policy_service.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`

### Journey or Smoke Coverage

- one focused runner smoke path with refinement observation enabled

### Manual Verification

1. Run a simple txt2img job with `adaptive_refinement.enabled=true` and
   `mode="observe"`.
2. Confirm the run completes identically to baseline output behavior.
3. Confirm `run_result.metadata["adaptive_refinement"]` contains the prompt
   intent summary and an observation-only decision bundle.

Suggested command set:

- `pytest tests/refinement/test_prompt_intent_analyzer.py tests/refinement/test_subject_scale_policy_service.py tests/pipeline/test_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. Prompt intent analysis reuses the existing prompt subsystem.
2. Observation-only bundles appear in runner metadata when enabled.
3. The runner does not mutate stage configs or outputs in this PR.
4. The observation bundle is shaped so later surfaces can reuse it directly.

### Failure Criteria

1. The PR adds a second prompt-classification stack.
2. Observation mode changes output behavior.
3. The emitted metadata is spread across multiple unrelated keys.
4. The observation payload is so ad hoc that later PRs would need a schema
   rewrite to reuse it.

## Risk Assessment

### Low-Risk Areas

- isolated analyzer and service files

### Medium-Risk Areas With Mitigation

- runner metadata growth
  - Mitigation: keep all data under one `adaptive_refinement` key and cover the
    exact shape in tests

### High-Risk Areas With Mitigation

- accidental output mutation in the runner
  - Mitigation: explicit no-op assertions in runner tests for observation mode

### Rollback Plan

Remove runner observation logic and leave the contracts from `PR-HARDEN-224`
intact.

## Critical Appraisal and Incorporated Corrections

1. Weakness: the research memo mixed observation and actuation in one runner
   step. Incorporated correction: this PR is observation-only.
2. Weakness: the memo risked duplicating prompt infrastructure.
   Incorporated correction: this PR requires reuse of the existing prompt
   classifier, bucket rules, splitter, and embedding extractor.
3. Weakness: the memo assumed detector data would always exist.
   Incorporated correction: this PR requires a null-detector fallback and
   explicit assessment notes.
4. Weakness: the memo did not constrain how observation data would later flow
   into replay, diagnostics, manifests, and embedded metadata.
   Incorporated correction: this PR freezes a reusable canonical carrier shape
   now, before any actuation lands.

## Tech Debt Analysis

### Debt Removed

- lack of a runner-owned observation path for refinement decisions

### Debt Intentionally Deferred

- real subject assessment
  - Owner: `PR-HARDEN-226`
- applied ADetailer behavior changes
  - Owner: `PR-HARDEN-227`
- prompt patch and upscale behavior changes
  - Owner: `PR-HARDEN-228`

## Documentation Updates

- update `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- update `docs/Image_Metadata_Contract_v2.6.md` only if the runner metadata
  contract is documented there today

## Dependencies

### Internal Module Dependencies

- prompt helpers under `src/prompting/`
- `src/utils/embedding_prompt_utils.py`
- `src/pipeline/pipeline_runner.py`

### External Tools or Runtimes

- none

## Approval & Execution

Planner: GitHub Copilot / ChatGPT planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-HARDEN-225`.
2. If observation payloads are stable, execute `PR-HARDEN-226`.
