# D-VIDEO-003 - AnimateDiff Research Scaffold and Investigation Framework

> For the current Phase 1 runtime-planning baseline, see
> [`docs/D-VIDEO-004-AnimateDiff-Current-State-Discovery.md`](./D-VIDEO-004-AnimateDiff-Current-State-Discovery.md).
> This scaffold remains active for broader future research beyond the narrower
> contract-gated runtime foundation described in D-VIDEO-004.

**Status:** Research Scaffold
**Version:** v2.6
**Date:** 2026-03-11
**Subsystem:** Pipeline / Video / Extension Integration
**Author:** StableNew Development Team

---

## 1. Purpose

This document is not an implementation plan. It is a structured investigation framework for future AnimateDiff work so that later research can proceed systematically and produce architecture-ready conclusions.

Use this document when the team is ready to move beyond the Movie Clips MVP and investigate true motion generation.

---

## 2. What Must Be Answered Before Implementation

The current repo does not yet know, with enough certainty, the answers to these questions:

1. Is AnimateDiff best modeled as:
   - a `txt2img/img2img` generation modifier
   - a new stage type
   - a hybrid frame-generation plus video-assembly chain

2. What is the exact A1111 extension API contract in the versions users are likely to run?

3. What artifacts are canonical outputs of an animation run:
   - frames only
   - video only
   - both frames and video

4. How should History, Preview, Review, and Learning represent a clip-oriented run?

5. What is the queue/runtime behavior for cancellation, partial failure, and resume when the output is multi-frame?

6. What are the resource and performance implications for:
   - SD 1.5
   - SDXL
   - different motion module sizes

---

## 3. Required Research Tracks

### Track A: WebUI / Extension Contract

Investigate:

1. exact request payload structure for AnimateDiff via A1111 API
2. returned response format
3. where motion-module names come from
4. whether extension state is available via API
5. how errors are surfaced

Deliverables:

- concrete payload examples
- extension version matrix
- required settings and optional settings
- failure-mode matrix

Primary sources to inspect later:

- A1111 extension documentation
- extension source code
- API behavior from a live test environment

### Track B: Artifact Semantics

Investigate:

1. how output frames are named
2. whether frame ordering is deterministic
3. whether videos should be treated as primary artifacts or derived artifacts
4. whether manifests must store:
   - frame paths
   - clip path
   - motion module
   - interpolation settings
   - loop settings

Deliverables:

- proposed animation manifest schema
- proposed output directory layout
- primary/secondary artifact rules

### Track C: Stage Model Impact

Investigate:

1. exact changes needed in:
   - `src/pipeline/stage_models.py`
   - `src/pipeline/stage_sequencer.py`
   - `src/pipeline/run_plan.py`
   - `src/pipeline/pipeline_runner.py`
   - `src/pipeline/job_builder_v2.py`
2. whether a new stage type breaks current assumptions that every stage yields images
3. whether stage ordering should allow:
   - `txt2img -> animatediff`
   - `img2img -> animatediff`
   - `txt2img -> upscale -> animatediff`

Deliverables:

- exact architecture delta report
- no-go list of assumptions that must be removed first
- recommendation on modifier vs stage

### Track D: UI/UX Model

Investigate:

1. whether AnimateDiff belongs:
   - in Pipeline tab as a new stage card
   - in a dedicated motion tab
   - in both
2. how motion parameters should be grouped
3. how frame and clip previews should appear
4. how users select source image for image-based animation flows

Deliverables:

- UI wireframe proposal
- control taxonomy
- preview/history interaction proposal

### Track E: History / Review / Learning Impact

Investigate:

1. how History should display clip runs
2. whether Review can review clips or only frame outputs
3. whether Learning should:
   - ignore clip runs
   - allow clip-level ratings
   - allow frame-level ratings
4. what metadata schema is required for future learning from motion settings

Deliverables:

- subsystem impact matrix
- recommendation on what is in scope for first AnimateDiff release

### Track F: Operational Constraints

Investigate:

1. VRAM requirements by model family
2. extension installation and detection
3. missing motion-module handling
4. timeout and progress semantics
5. cancellation behavior
6. disk usage and cleanup policy

Deliverables:

- environment prerequisites checklist
- runtime risk matrix
- ops guidance for failure handling

---

## 4. Research Method

### Step 1: Source Audit

Collect and summarize:

- extension docs
- extension source
- actual live API traces

### Step 2: Controlled Experiments

Run a minimal matrix:

1. txt2img AnimateDiff
2. img2img AnimateDiff
3. SD 1.5 vs SDXL
4. short vs longer clip lengths

Record:

- payloads
- response structure
- runtime
- memory use
- output artifacts

### Step 3: Architecture Fit Review

Map experimental findings back onto StableNew v2.6 invariants:

- NJR-only execution
- stage-chain ownership
- History/Review/Learning ownership boundaries

### Step 4: Implementation Strategy Selection

Choose one of:

1. modifier model
2. new stage model
3. hybrid frame-generation plus video stage

Reject the other two with explicit reasons.

---

## 5. Expected Deliverables From Future Research

When this investigation is later executed thoroughly, it should produce:

1. a new discovery report superseding `D-VIDEO-001`
2. exact payload/response contract documentation
3. a recommended architecture decision
4. a full PR series for implementation
5. test strategy updates

---

## 6. Known Current Conclusions

These conclusions are already strong enough to treat as working assumptions:

1. AnimateDiff should **not** be folded into the Movie Clips MVP.
2. The current runner/sequencer/stage model is too image-centric to casually absorb a clip stage.
3. A real animation feature should likely be treated as a distinct capability, not just “video export.”
4. The largest unresolved question is whether AnimateDiff is best represented as a new stage type or as a generation modifier.

---

## 7. Recommended Future Entry Sequence

When this is resumed later, the recommended order is:

1. execute the WebUI/extension contract investigation
2. execute the artifact-semantics investigation
3. perform architecture-fit review
4. choose one representation model
5. only then draft PRs

Do not start implementation before those steps are complete.
