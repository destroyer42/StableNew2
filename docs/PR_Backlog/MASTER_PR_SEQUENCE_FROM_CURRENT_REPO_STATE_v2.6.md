# Master PR Sequence From Current Repo State v2.6

Status: Proposed  
Date: 2026-03-24  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: all currently planned / unfinished work referenced in `docs/` and `docs/PR_Backlog/`

## 1. Purpose

This document consolidates the currently relevant unfinished or planned work into
one prioritized master PR sequence.

It is based on the current repo truth in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/`
- follow-on staged-curation, metadata, video, and UX planning docs added on this branch

This is not a dump of every idea. It is the recommended execution order from the
current repo state.

## 2. Prioritization Logic

The sequence below is ordered by these principles:

1. close blockers and correctness issues before stacking new behavior on top
2. prioritize the highest-friction user workflow gaps next
3. make prompt/config/runtime behavior inspectable before expanding automation
4. finish secondary-motion backend rollout after core image/review workflow truth
   is clearer
5. land prompt-optimizer work only after the current video tranche, matching the
   canonical roadmap
6. treat broad UX/help consistency as a real tranche, but sequence it so the help
   reflects real product behavior rather than speculative future behavior
7. defer lower-leverage structural cleanup until after the highest-value product
   and runtime issues are under better control

## 3. Master Sequence

### Phase 0 - Immediate blockers and repo-truth prerequisites

#### 0.1 Close the active image output-route regression

Why here:

- the canonical roadmap explicitly calls this out as a prerequisite for good
  discovered/imported review quality
- staged-curation imports and output classification depend on it

#### 0.2 Staged-curation contract baseline (`PR-LEARN-259A`) is verified

Why here:

- this is the contract/foundation item for the staged-curation tranche
- dependent work should proceed from this verified baseline rather than reopen
  the contract PR itself

---

### Phase 1 - Highest-value image/review workflow fixes

Completed in this tranche already:

- `PR-LEARN-260A-Staged-Curation-Source-Prompt-Surface-and-Decision-Context`
- `PR-LEARN-260B-Staged-Curation-Plan-Build-vs-Enqueue-Seam`
- `PR-LEARN-260C-Learning-To-Review-Handoff-and-Review-Draft-Load`
- `PR-LEARN-260D-Review-Derived-Config-Inspector-and-Effective-Settings-Summary`

#### 1.1 `PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump`

Why now:

- once users can hand off to Review, they need to see exactly what prompt/config
  will be queued
- reduces confusion around inherited vs baseline vs preset values

#### 1.5 `PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump`

Why now:

- closes the intervention loop and makes the workflow intelligible
- gives concrete evidence of what changed because of operator intervention

#### 1.6 `PR-LEARN-260F-Queue-Now-vs-Edit-in-Review-UX-Polish-and-Bulk-Selection-Rules`

Why now:

- locks in the hybrid flow after the functional pieces exist
- clarifies single-item deliberate work vs bulk throughput work

---

### Phase 2 - Artifact-level review portability and inspectability

#### 2.1 `PR-LEARN-261-Portable-Review-Metadata-Stamping`

Why now:

- makes review/rating outcomes portable with the artifact itself
- creates the base layer for external-tool interoperability and re-import quality

#### 2.2 `PR-LEARN-262-Portable-Review-Metadata-Rehydration-and-UI-Surfacing`

Why now:

- makes the portable metadata usable inside StableNew again
- enables prior-review context in Review / Learning / Staged Curation

#### 2.3 `PR-LEARN-263-Artifact-Metadata-Inspector-and-Debug-UI`

Why now:

- makes the metadata work inspectable and trustworthy
- gives operators direct visibility into embedded vs sidecar vs internal review data

#### 2.4 `PR-LEARN-264-Canonical-Metadata-Schemas-and-Contracts`

Why now:

- stabilizes the write/read/inspect semantics after they are clearly defined
- reduces future schema drift and ambiguity for external consumers

---

### Phase 3 - Finish the remaining secondary-motion video rollout

Completed in this tranche already:

- `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`
- `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`
- `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-and-Replay-Closure`

#### 3.1 `PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback`

Why next in video:

- the shared secondary-motion foundation is already complete through `236`/`237`
- all three current video backends now have runtime closure, so learning and
  recommendation feedback is the next secondary-motion rollout step

---

### Phase 4 - Prompt optimizer / smart prompting tranche

This phase is intentionally placed **after** the current secondary-motion video
sequence because the canonical roadmap explicitly queues the prompt-optimizer
tranche after `PR-VIDEO-237` through `PR-VIDEO-241`.

#### 4.1 `PR-PROMPT-241A-Format-Only-Safety-and-Dedupe-Hardening`

Why first:

- makes the existing optimizer path safe and non-semantic by default
- hardens the base before orchestration/policy work

#### 4.2 `PR-PROMPT-241B-Orchestrator-and-Intent-Bundle-Recommend-Only`

Why second:

- introduces the StableNew-owned orchestrator and typed prompt-intent bundle
- records structured recommendations without mutating behavior yet

#### 4.3 `PR-PROMPT-241C-Stage-Policy-Engine-and-Auto-Safe-Fill-Missing`

Why third:

- adds bounded stage policy behavior only for missing or `AUTO` config values
- preserves explicit user choices

#### 4.4 `PR-PROMPT-241D-Manifest-Schema-v3-and-Replay-Contract`

Why fourth:

- turns optimizer output into replay-grade manifest evidence
- creates the strongest observable proof that smart prompting is working

#### 4.5 `PR-PROMPT-241E-Learning-Hooks-and-Tuning-Scaffolding`

Why fifth:

- only after safe recommend/policy/replay behavior exists should the optimizer
  become learning-aware

---

### Phase 5 - Immediate UX/help/value-add sweep

This tranche should begin after the most important workflow truths above are in
place, so the help surfaces describe real behavior.

#### 5.1 `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`

Why first:

- the highest-value embedded guidance item
- gives users a built-in readme for each major surface

#### 5.2 `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`

Why second:

- clarifies what buttons actually do before the user clicks them
- especially important for queue/edit/import/reprocess actions

#### 5.3 `PR-UX-271-GUI-Layout-Resilience-and-LoRA-Control-Usability`

Why third:

- this is a real usability blocker, not cosmetic polish
- fixes shrinking controls, crowded rows, and broken LoRA interactions

#### 5.4 `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`

#### 5.5 `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`

#### 5.6 `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`

#### 5.7 `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`

Why this order:

- explain the surface first
- explain the actions second
- fix severe layout/resizing pain third
- deepen setting/config/pathway guidance after that

---

### Phase 6 - Whole-GUI consistency sweep

This is broader than individual UX help PRs and should be handled as a structured
sweep.

#### 6.1 `PR-UX-272-GUI-Audit-and-Consistency-Inventory`
#### 6.2 `PR-UX-273-Shared-Dark-Mode-Tokens-and-Widget-Theme-Discipline`
#### 6.3 `PR-UX-274-Shared-Layout-Minimums-and-Resize-Discipline`
#### 6.4 `PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep`
#### 6.5 `PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep`
#### 6.6 `PR-UX-277-Review-Learning-and-Video-Panel-Consistency-Sweep`
#### 6.7 `PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep`
#### 6.8 `PR-UX-279-GUI-Consistency-Regression-Checks-and-Maintenance-Checklist`

Why this tranche is later:

- this is large and cross-cutting
- it is best done after the nearer-term workflow and UX-help truths are established
- however, if visual inconsistency is hurting current work badly, `272` to `274`
  can be pulled forward earlier

---

### Phase 7 - Structural and architectural cleanup queue

Once the highest-value product/runtime/UX items are better controlled, resume the
post-`PR-VIDEO-241` structural queue called out by the canonical roadmap.

Recommended front of this tranche:

#### 7.1 `PR-ARCH-242-Controller-GUI-Boundary-Core-Controller-Reset`
#### 7.2 `PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation`
#### 7.3 `PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement`
#### 7.4 `PR-CI-245-CI-Truth-Sync-and-Smoke-Suite-Contract`
#### 7.5 `PR-ARCH-246-Architecture-Enforcement-Expansion-and-Import-Guards`
#### 7.6 `PR-CTRL-247-PipelineController-Service-Extraction-and-Facade-Reduction`
#### 7.7 `PR-PORTS-248-Backend-Port-Boundaries-for-Image-and-Video-Runtimes`
#### 7.8 `PR-REPLAY-250-Replay-Fidelity-Contract-and-Versioned-Validation`
#### 7.9 `PR-APP-251-Shared-Application-Bootstrap-and-Kernel-Composition`
#### 7.10 `PR-HARDEN-252-Optional-Dependency-Capabilities-and-Startup-Probes`
#### 7.11 `PR-CI-253-Mypy-Smoke-Gate-and-Whitelist-Expansion`
#### 7.12 `PR-CONTRACT-254-Intent-Artifact-Versioning-and-Hash-Closure`
#### 7.13 `PR-VIDEO-255-Workflow-Registry-Governance-and-Pinning-Closure`

Why here:

- these are important, but they are lower immediate product leverage than the
  currently unfinished workflow, portability, and UX items above

## 4. Fast-Track Subsequence

If the goal is the best real-world improvement with the fewest PRs first,
execute this shorter path:

1. close image output-route regression
1. `PR-VIDEO-241`
1. `PR-UX-265`
1. `PR-UX-266`
1. `PR-UX-271`
1. `PR-UX-268`
1. `PR-PROMPT-241A`
1. `PR-PROMPT-241B`
1. `PR-PROMPT-241D`

Why this fast-track works:

- fixes the most painful staged-curation/review gap first
- makes prompt/config behavior visible before more automation lands
- improves user comprehension early
- gives artifact-level review portability and inspection
- continues secondary-motion learning closure after backend parity completion
- gets recommend-only smart-prompting evidence and replay-grade manifest proof moving

## 5. Master Ordered List

1. close image output-route regression
1. `PR-VIDEO-241-Learning-and-Risk-Aware-Secondary-Motion-Feedback`
1. `PR-PROMPT-241A-Format-Only-Safety-and-Dedupe-Hardening`
1. `PR-PROMPT-241B-Orchestrator-and-Intent-Bundle-Recommend-Only`
1. `PR-PROMPT-241C-Stage-Policy-Engine-and-Auto-Safe-Fill-Missing`
1. `PR-PROMPT-241D-Manifest-Schema-v3-and-Replay-Contract`
1. `PR-PROMPT-241E-Learning-Hooks-and-Tuning-Scaffolding`
1. `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`
1. `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
1. `PR-UX-271-GUI-Layout-Resilience-and-LoRA-Control-Usability`
1. `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`
1. `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`
1. `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`
1. `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`
1. `PR-UX-272-GUI-Audit-and-Consistency-Inventory`
1. `PR-UX-273-Shared-Dark-Mode-Tokens-and-Widget-Theme-Discipline`
1. `PR-UX-274-Shared-Layout-Minimums-and-Resize-Discipline`
1. `PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep`
1. `PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep`
1. `PR-UX-277-Review-Learning-and-Video-Panel-Consistency-Sweep`
1. `PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep`
1. `PR-UX-279-GUI-Consistency-Regression-Checks-and-Maintenance-Checklist`
1. `PR-ARCH-242-Controller-GUI-Boundary-Core-Controller-Reset`
1. `PR-ARCH-243-Archive-Import-Fencing-and-Reference-Relocation`
1. `PR-HYGIENE-244-Tracked-Runtime-State-Purge-and-Hygiene-Enforcement`
1. `PR-CI-245-CI-Truth-Sync-and-Smoke-Suite-Contract`
1. `PR-ARCH-246-Architecture-Enforcement-Expansion-and-Import-Guards`
1. `PR-CTRL-247-PipelineController-Service-Extraction-and-Facade-Reduction`
1. `PR-PORTS-248-Backend-Port-Boundaries-for-Image-and-Video-Runtimes`
1. `PR-REPLAY-250-Replay-Fidelity-Contract-and-Versioned-Validation`
1. `PR-APP-251-Shared-Application-Bootstrap-and-Kernel-Composition`
1. `PR-HARDEN-252-Optional-Dependency-Capabilities-and-Startup-Probes`
1. `PR-CI-253-Mypy-Smoke-Gate-and-Whitelist-Expansion`
1. `PR-CONTRACT-254-Intent-Artifact-Versioning-and-Hash-Closure`
1. `PR-VIDEO-255-Workflow-Registry-Governance-and-Pinning-Closure`

## 6. Recommendation

Use this as the master planning sequence from the current repo state.

For actual near-term execution, follow the fast-track subsequence first. That
path gives the biggest operator-facing improvement soonest while preserving the
canonical roadmap order where it matters most, especially for the video and
prompt-optimizer tranches.
