# Revised Mini-Roadmap PR Order v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: stabilization, staged curation, review, metadata portability, video, UX

## 1. Purpose

This mini-roadmap consolidates the currently relevant remaining work into one
practical execution order.

It is intentionally shorter and more execution-oriented than the full backlog.
It prioritizes:

1. correctness and stability
2. user-visible workflow gaps
3. inspectability and metadata portability
4. unfinished video rollout
5. broad UX/help polish

## 2. Planning Principles

This order is designed to:

- close blockers before building on top of them
- land the highest-friction workflow fixes early
- expose effective config and prompt context before adding more abstraction
- make artifact metadata portable and inspectable before relying on it heavily
- finish video rollout only after the non-video workflow is coherent enough to
  support it
- treat UX help/guidance as important, but sequence it after core workflow truth
  is clearer

## 3. Recommended Execution Order

### Phase 0 - Stability and missing roadmap baseline

#### 0.1 Close image output-route regression

Reason:

- discovered/imported review quality depends on correct output classification and
  stable scan roots
- this was explicitly called out as a sequencing requirement in the staged-curation
  roadmap

#### 0.2 `PR-LEARN-259A-Curation-Contracts-Lineage-and-Selection-Events` is verified

Reason:

- this is the contract/foundation item for the staged-curation tranche
- more dependent work should layer on top of this verified baseline instead of
  reopening the contract PR

---

### Phase 1 - Highest-value staged-curation workflow fixes

Completed in this tranche already:

- `PR-LEARN-260A-Staged-Curation-Source-Prompt-Surface-and-Decision-Context`
- `PR-LEARN-260B-Staged-Curation-Plan-Build-vs-Enqueue-Seam`
- `PR-LEARN-260C-Learning-To-Review-Handoff-and-Review-Draft-Load`
- `PR-LEARN-260D-Review-Derived-Config-Inspector-and-Effective-Settings-Summary`

#### 1.1 `PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump`

Why fourth:

- once users can hand off into Review, they need to see the effective config that
  will actually be queued
- reduces ambiguity around inherited vs defaulted vs merged settings

#### 1.5 `PR-LEARN-260E-Source-vs-Derived-Outcome-Compare-and-Lineage-Jump`

Why fifth:

- closes the intervention loop and makes the workflow much more intelligible
- especially valuable once edit-in-Review becomes part of the main path

#### 1.6 `PR-LEARN-260F-Queue-Now-vs-Edit-in-Review-UX-Polish-and-Bulk-Selection-Rules`

Why sixth:

- polish should happen after the functional hybrid flow exists
- this locks in clarity for single-item vs bulk behavior

---

### Phase 2 - Portable review metadata and inspectability

#### 2.1 `PR-LEARN-261-Portable-Review-Metadata-Stamping`

Why first in this tranche:

- makes review/rating outcomes portable with the artifact itself
- creates the artifact-level data foundation for later rehydration and external
  interoperability

#### 2.2 `PR-LEARN-262-Portable-Review-Metadata-Rehydration-and-UI-Surfacing`

Why second:

- once metadata is written to artifacts, StableNew needs to read it back into
  Review / Learning / Staged Curation

#### 2.3 `PR-LEARN-263-Artifact-Metadata-Inspector-and-Debug-UI`

Why third:

- makes the portability work inspectable and debuggable
- reduces operator confusion around embedded vs sidecar vs internal precedence

#### 2.4 `PR-LEARN-264-Canonical-Metadata-Schemas-and-Contracts`

Why fourth:

- formalizes the contract after the intended write/read/inspect flows are fully
  defined
- stabilizes future implementation and external-tool interoperability

---

### Phase 3 - Finish the remaining video and secondary-motion rollout

#### 3.1 `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`

Why first:

- the shared secondary-motion foundation already exists
- SVD-native integration is the most direct backend rollout step

#### 3.2 `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`

#### 3.3 `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-Integration`

#### 3.4 `PR-VIDEO-241-Secondary-Motion-Learning-and-Evidence-Integration`

#### 3.5 `PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls`

#### 3.6 `PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish`

Why this tranche is after Phase 2:

- video rollout is important, but the non-video Review/Learning/metadata workflow
  is more immediately blocking and affects broader operator experience
- finishing inspectability and metadata semantics first will also improve the
  quality of the later video UX and metadata work

---

### Phase 4 - Broad UX help and in-product guidance

#### 4.1 `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`

#### 4.2 `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`

#### 4.3 `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`

#### 4.4 `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`

#### 4.5 `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`

#### 4.6 `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`

Why this tranche is last in the broad sequence:

- many help surfaces are most valuable once the underlying workflow behavior is
  stable and truthful
- however, the first three UX PRs are strong candidates to pull earlier if you
  want more operator guidance sooner

## 4. Fast-Track Recommendation

If you want the highest practical value fastest, prioritize this shorter path:

1. close output-route regression
2. `PR-VIDEO-238`
3. `PR-UX-265`
4. `PR-UX-266`
5. `PR-UX-268`

This path delivers:

- grounded staged-curation decisions
- hybrid Learning -> Review workflow
- visible effective config before queueing
- much better user guidance on major surfaces
- artifact-portable review metadata and inspectability

## 5. Full Ordered List

1. close image output-route regression
2. `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`
3. `PR-VIDEO-239-AnimateDiff-Secondary-Motion-Frame-Pipeline-Integration`
4. `PR-VIDEO-240-Workflow-Video-Secondary-Motion-Parity-Integration`
5. `PR-VIDEO-241-Secondary-Motion-Learning-and-Evidence-Integration`
6. `PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls`
7. `PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish`
8. `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`
9. `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
10. `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`
11. `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`
12. `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`
13. `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`

## 6. Recommendation

Use the full order as the master execution sequence, but treat the fast-track path
as the practical near-term roadmap.

That will fix the most painful current user problems first while still preserving a
coherent longer-term rollout for metadata, video, and broader UX guidance.
