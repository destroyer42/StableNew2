# D-LEARN-003 - Auto-Discovered Review Experiments From Output History

**Status:** Discovery
**Version:** v2.6
**Date:** 2026-03-11
**Subsystem:** Learning / Review / Output Scanning
**Author:** StableNew Development Team

---

## 1. Executive Summary

This discovery evaluates a feature that scans the `output/` directory, automatically groups related images into reviewable comparison sets, and turns those sets into Learning-adjacent experiments with a `waiting_review` lifecycle.

The main idea is sound and valuable, but it must be implemented carefully because:

1. the output tree contains many runs with mixed manifest schemas and metadata quality
2. the current Learning model is designed for controlled experiments, not uncontrolled historical comparisons
3. naively feeding grouped-output ratings into recommendations would pollute the evidence model

### Recommended Direction

Build this as an **auto-discovered review experiment inbox** inside the Learning subsystem, not as a new queue or pipeline path.

### Core Recommendation

1. Scan manifests first, embedded image metadata second, raw image heuristics last.
2. Group candidates by **stage + normalized prompt + normalized negative prompt + input-lineage key**.
3. Require:
   - at least `3` artifacts
   - at least `1` meaningful varying configuration field
4. Persist discovered groups under a dedicated Learning workspace.
5. Reuse Learning review/rating surfaces where possible, but keep discovered-group evidence distinct from controlled Learning experiments.

### Final Conclusion

This feature should be implemented, but only through a staged PR series that:

- creates a durable discovery/grouping layer first
- integrates a review inbox second
- adds analytics ingestion only after evidence-tiering rules are explicit

---

## 2. Problem Statement

StableNew already has many historical outputs in `output/`, often with embedded or sidecar metadata sufficient to compare runs. Those outputs are largely stranded unless a user manually browses folders and remembers what should be compared.

The desired feature is:

1. scan all existing outputs
2. find comparable images automatically
3. group them into an experiment-like review unit
4. mark them `waiting_review`
5. let the user rate them in a focused review flow
6. close out the experiment when done
7. use the resulting signals to improve later learning and analysis

---

## 3. Existing Relevant Architecture

### 3.1 Strengths Already Present

The repo already has strong building blocks:

- `src/utils/image_metadata.py`
  - resolves prompt/model/VAE fields across inconsistent schemas
  - supports embedded payload extraction

- `src/learning/experiment_store.py`
  - durable Learning experiment/session persistence

- `src/gui/learning_state.py`
  - stable Learning tab session model

- `src/gui/controllers/learning_controller.py`
  - existing rating/recommendation orchestration

- `src/learning/learning_record.py`
  - durable JSONL learning record store

### 3.2 Important Architectural Boundaries

Per `docs/Learning_System_Spec_v2.6.md`:

- Learning is a post-execution subsystem
- it must not create alternate generation paths
- ratings and evidence are allowed to influence learning and recommendations
- evidence quality matters

This proposed feature fits that architecture **if treated as a post-execution discovery and review workflow**.

### 3.3 Current Weaknesses

The current system does **not** yet have:

- a scanner for historical outputs/manifests
- a durable grouping model for discovered comparisons
- a status lifecycle for discovered-review groups
- evidence-tier separation between controlled experiments and uncontrolled historical groups

---

## 4. What We Can Reliably Scan Today

### 4.1 Primary Source: Manifest JSON

Real output manifests already commonly contain:

- `stage`
- `original_prompt`
- `final_prompt`
- `original_negative_prompt`
- `final_negative_prompt`
- `config`
- `path` / `output_path`
- `all_paths`
- sometimes `model`, `vae`, `job_id`, `actual_seed`

This makes manifests the best primary scan source.

### 4.2 Secondary Source: Embedded Image Metadata

For images with v2.6 embedded metadata, `src/utils/image_metadata.py` already provides normalization helpers that can recover:

- prompt
- negative prompt
- model
- VAE
- stage history
- stage config

### 4.3 Tertiary Fallback: Raw File Heuristics

File names and folder structure should only be used as a weak fallback, not as the primary grouping logic.

---

## 5. Proposed Feature Model

### 5.1 User-Facing Concept

The feature should present a Learning-side **Discovered Review Inbox**.

Each inbox item is a **discovered review experiment**:

- a comparable group of images
- inferred from historical outputs
- awaiting user review

### 5.2 Lifecycle

Each discovered review experiment should have one of:

- `waiting_review`
- `in_review`
- `closed`
- `ignored`

### 5.3 Storage

Persist under a dedicated workspace, for example:

`data/learning/discovered_experiments/{group_id}/`

Each group should store:

- `meta.json`
- `items.json`
- `review_state.json`

### 5.4 Why Not Reuse `LearningExperiment` Directly

The current `LearningExperiment` model assumes:

- one designed experiment
- one selected stage
- one variable-under-test concept
- generated plan variants

Discovered groups are different:

- they are imported from history
- they may vary across multiple knobs
- there may be no single variable-under-test

So the better design is:

- keep discovered groups inside the Learning subsystem
- but model them as a **distinct discovered-review entity**
- optionally adapt them into shared review widgets

That is cleaner than overloading `LearningExperiment` with uncontrolled historical data.

---

## 6. Grouping Contract

### 6.1 Required Group Key

A discovered group should key on:

1. `stage`
2. normalized positive prompt
3. normalized negative prompt
4. input-lineage key for image-based stages

Input-lineage key rules:

- `txt2img`: empty / none
- `img2img`, `upscale`, `adetailer`: derived from source image path or source lineage metadata if available

### 6.2 Minimum Candidate Threshold

A group becomes reviewable only if:

- it contains at least `3` distinct artifacts

### 6.3 Meaningful Variation Requirement

A group should only be elevated if it has at least one varying non-trivial configuration field.

Candidate meaningful fields:

- model
- VAE
- sampler
- scheduler
- steps
- cfg_scale
- denoising_strength
- upscale factor
- LoRA tags / weights
- width / height

Fields that should **not** alone make a group eligible:

- output file name
- timestamp
- job id
- seed only

If only seed varies, the group should either:

- be ignored by default, or
- be classified separately as a `seed_spread` group with lower priority

### 6.4 Dedupe Rule

Artifacts must be deduplicated by canonical output path, with manifest path and payload hash available for safety.

---

## 7. UI / Workflow Proposal

### 7.1 Best Home

This belongs in the **Learning tab**, not as a separate new tab.

Reason:

- it is fundamentally a learning/review workflow
- it should share rating persistence and later analytics handling
- it should not dilute the Review tab’s current purpose

### 7.2 Proposed Learning Tab Sections

Add a high-level mode or panel split:

1. `Designed Experiments`
2. `Discovered Review Inbox`

### 7.3 Inbox Item Summary

Each discovered experiment card/list row should show:

- stage
- prompt preview
- item count
- inferred varying knobs
- created/discovered timestamp
- status

### 7.4 Review Surface

The review screen should show:

- all candidate images in the group
- per-image metadata summary
- inferred comparison knobs per item
- rating / notes / sub-scores
- close / ignore actions

It can reuse much of the current Learning review panel, but it will need a dedicated group-item table rather than the existing designed-experiment plan table semantics.

---

## 8. Analytics and Recommendation Implications

### 8.1 Important Risk

Discovered groups are **not controlled experiments**.

If their ratings are fed directly into recommendation logic as `learning_experiment_rating`, the recommendation engine will over-trust noisy evidence.

### 8.2 Required Evidence Separation

Add a distinct record kind, for example:

- `output_discovery_review`

This record kind should:

- be captured and stored
- be visible in analytics
- not be treated as equal to controlled experiment data by default

### 8.3 Recommended First-Step Policy

Phase 1:

- discovered-group ratings contribute to analytics and future research views
- recommendation engine does **not** directly use them for automatic recommendations

Phase 2:

- optionally use them as lower-weight supplemental evidence once evidence-tier logic is expanded

---

## 9. Runtime Scanning Strategy

### 9.1 Do Not Fully Re-Scan Synchronously on Every Launch

The output tree may be large. A synchronous full scan on startup will make the app feel slow and fragile.

### 9.2 Recommended Strategy

Use:

1. startup asynchronous scan
2. manual `Rescan Outputs` action
3. incremental scan index

### 9.3 Incremental Scan Index

Persist a scan index under Learning data, for example:

`data/learning/discovered_experiments/scan_index.json`

Track:

- manifest path
- image path
- mtime
- size
- last processed hash

This allows:

- skipping unchanged artifacts
- rescanning only new or modified outputs

---

## 10. Surfaced Issues and Proposed Solutions

### Issue 1: Manifest Schema Variability

Problem:

- manifests are not fully uniform across older runs

Solution:

- centralize a scan normalizer that uses:
  1. manifest fields first
  2. embedded metadata second
  3. path heuristics last

Do not spread manifest parsing across UI/controller code.

### Issue 2: False Grouping on Same Prompt Alone

Problem:

- same prompt text may exist across unrelated image-based reprocess chains

Solution:

- include `input_lineage_key` in the grouping contract for image-based stages

### Issue 3: Recommendation Pollution

Problem:

- uncontrolled historical groups are weaker evidence than designed sweeps

Solution:

- use a dedicated `record_kind`
- keep them out of automated recommendations initially

### Issue 4: Startup Performance

Problem:

- output scanning can get expensive over time

Solution:

- manifests first
- async startup scan
- incremental scan index

### Issue 5: UI Mismatch With Current Learning Plan Table

Problem:

- the current Learning plan table assumes designed variants, not arbitrary discovered images

Solution:

- add a dedicated discovered-group table/list instead of overloading the existing plan table

---

## 11. Recommended Implementation Strategy

### Strategy

Implement in five phases:

1. discovered-group data model and store
2. output scanner and grouping engine
3. Learning inbox UI and review flow
4. rating persistence and evidence-tiering
5. journeys, docs, and cleanup

### Why This Order

Because the biggest risks are:

- bad grouping
- bad persistence
- bad evidence semantics

Those must be solved before polishing UI or recommendations.

---

## 12. Final Conclusions

### Should This Be Built?

Yes.

### Is It Valuable?

Yes. It unlocks historical outputs as usable review/training evidence and makes prior generation effort less disposable.

### What Is the Correct Shape?

An **auto-discovered review inbox inside Learning**, backed by:

- manifest-first scanning
- durable discovered-group storage
- explicit review status
- evidence-tier separation from controlled experiments

### What Should Be Avoided?

1. do not overload designed Learning experiments with uncontrolled history
2. do not treat discovered-group ratings as first-class recommendation evidence on day one
3. do not block app startup with full synchronous scans

