# Video and Secondary Motion Remaining Work Sequence v2.6

Status: Superseded by canonical queue alignment  
Date: 2026-03-24  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: video subsystem, secondary motion, learning, UX, metadata inspection

## 1. Purpose

This file previously described `PR-VIDEO-238` through `PR-VIDEO-243` as one
remaining rollout sequence.

That is no longer the current repo truth.

The canonical queue now lives in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/MASTER_PR_SEQUENCE_FROM_CURRENT_REPO_STATE_v2.6.md`

This document is retained only to record how the old video-sequence plan maps to
the current canonical queue.

## 2. Current Repo Truth

Completed already:

- `PR-VIDEO-236` completed the canonical secondary-motion intent contract and
  observation-only carrier foundation
- `PR-VIDEO-237` completed the shared secondary-motion engine and provenance
  contract
- `PR-VIDEO-238` completed SVD-native secondary-motion runtime integration
- `PR-VIDEO-239` completed AnimateDiff secondary-motion runtime integration
- `PR-VIDEO-240` completed workflow-video parity and replay closure
- `PR-VIDEO-241` completed learning and risk-aware secondary-motion feedback

Not separately queued anymore:

- `PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls`
- `PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish`

Those two items were not kept as standalone video PRs in the newer canonical
queue. Their intended scope was absorbed by later UX and metadata tranches after
the secondary-motion runtime sequence finished.

## 3. Absorption Mapping

### `PR-VIDEO-242-Video-UX-Exposure-and-Operator-Controls`

Original intent:

- expose video-motion behavior clearly to operators
- make video controls understandable before use
- add help text, tooltips, and safe workflow guidance

Current canonical home:

- `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`
  - absorbed the top-level cross-tab video workflow orientation work
- `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
  - absorbed the action-semantics and pre-click explanation work
- `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`
  - carries the settings-level explanation work that 242 originally implied
- `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`
  - carries the "which video path should I use and when" guidance that was part
    of the original operator-controls intent
- `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`
  - carries the broader contextual-help and wording-polish layer

Practical interpretation:

- 242 was split into a broader product-wide UX/help tranche rather than kept as
  a video-only PR
- the video surfaces now evolve under the shared UX/help queue instead of a
  separate secondary-motion-only UX branch

### `PR-VIDEO-243-Video-Metadata-and-Result-Inspection-UX-Polish`

Original intent:

- make video result state and motion behavior inspectable after execution
- surface policy, provenance, and applied-vs-observed outcomes in UI
- improve artifact inspection and compare/debug flows for video outputs

Current canonical home:

- `PR-LEARN-261-Portable-Review-Metadata-Stamping`
  - provides the artifact-portable metadata base layer
- `PR-LEARN-262-Portable-Review-Metadata-Rehydration-and-UI-Surfacing`
  - makes metadata re-usable inside StableNew surfaces
- `PR-LEARN-263-Artifact-Metadata-Inspector-and-Debug-UI`
  - absorbed the explicit metadata-inspector and inspection-debug surface work
- `PR-LEARN-264-Canonical-Metadata-Schemas-and-Contracts`
  - absorbed the schema/contract stabilization needed for trustworthy inspection
- `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`
  - carries the remaining presentation and inspectability wording polish

Practical interpretation:

- 243 was absorbed into the artifact-metadata and inspection tranche rather than
  staying a video-only result-polish PR
- the canonical path is now metadata-contract first, inspection UI second,
  wording polish after that

## 4. Old Sequence vs Canonical Sequence

Old proposed sequence:

1. `PR-VIDEO-238`
2. `PR-VIDEO-239`
3. `PR-VIDEO-240`
4. `PR-VIDEO-241`
5. `PR-VIDEO-242`
6. `PR-VIDEO-243`

Current canonical interpretation:

1. treat `PR-VIDEO-238` through `PR-VIDEO-241` as completed
2. continue with the prompt-optimizer tranche
3. continue with the current UX/help tranche
4. continue with the metadata portability and inspection tranche where needed

The key change is that 242 and 243 are no longer scheduled as dedicated video
PRs after 241. Their scope was redistributed into the shared UX and metadata
queues.

## 5. What To Follow Now

Use these files as the active source of truth instead of this document:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/MASTER_PR_SEQUENCE_FROM_CURRENT_REPO_STATE_v2.6.md`

For secondary-motion-specific historical context, use:

- `docs/CompletedPlans/SECONDARY_MOTION_EXECUTABLE_ROADMAP_v2.6.md`

## 6. Recommendation

Treat this file as a historical mapping note, not as an active execution queue.

The correct current reading is:

- the secondary-motion rollout itself is complete through `PR-VIDEO-241`
- the old `PR-VIDEO-242` intent now lives in the shared UX/help tranche
- the old `PR-VIDEO-243` intent now lives in the metadata portability and
  inspection tranche
