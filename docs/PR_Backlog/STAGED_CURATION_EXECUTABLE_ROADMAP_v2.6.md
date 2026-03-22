# Staged Curation Executable Roadmap v2.6

Status: Proposed  
Updated: 2026-03-21  
Applies to: Learning, Review, discovered-review, queue-first staged advancement

## 0. Summary

This roadmap converts the staged curation idea into a queue-first,
NJR-backed rollout that fits the current StableNew product shape.

It does **not** add a parallel curation architecture.

It instead extends the existing surfaces:

- `Learning` becomes the canonical evidence-and-advancement workspace
- `Review` remains the canonical advanced reprocess workspace
- discovered-review and history-imported runs become first-class learning inputs

## 1. Guardrails

- no second execution path
- no second outer job model
- no backend-owned curation logic
- no GUI-owned lineage truth
- no blanket treatment of non-advanced candidates as hard negatives
- no duplicate reprocess surface beside `Review`

## 2. Product Shape

The target product shape is:

- `Learning -> Designed Experiments`
- `Learning -> Discovered / Imported Review`
- `Learning -> Staged Curation`
- `Review -> canonical advanced reprocess surface`

## 3. PR Sequence

### `PR-LEARN-259A-Curation-Contracts-Lineage-and-Selection-Events`

Purpose:

- establish the canonical curation objects and manifest/history contracts

Primary outcomes:

- `CurationWorkflow`
- `CurationCandidate`
- `SelectionEvent`
- `CurationOutcome`
- manifest and history blocks for candidate lineage and advancement decisions

### `PR-LEARN-259B-Learning-Workspace-Staged-Curation-Mode`

Status:

- Completed 2026-03-21

Purpose:

- add a first-class `Staged Curation` mode inside the existing Learning tab

Primary outcomes:

- staged curation mode in [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
- candidate grid and advancement controls
- fast reason-tag capture
- no new standalone curation tab required

### `PR-LEARN-259C-Review-History-Import-and-Large-Compare-Surface`

Status:

- Completed 2026-03-21

Purpose:

- remove the current biggest evidence-collection friction

Primary outcomes:

- import prior outputs from history/discovered-review into staged curation
- larger image compare/review surface
- easier advancement from existing runs without extra generation work

### `PR-LEARN-259D-Derived-Stage-Advancement-and-Face-Triage-Routing`

Status:

- Completed 2026-03-21

Purpose:

- derive refine, face-triage, and upscale jobs from selected candidates using normal NJR-backed work

Primary outcomes:

- scout -> refine derivation
- refine -> face-triage derivation
- finalist -> upscale derivation
- optional per-candidate face triage tiers

### `PR-LEARN-259E-Learning-Evidence-Bridge-and-Reason-Tag-Analytics`

Purpose:

- turn advancement behavior into structured learning signal without collapsing it into crude thumbs-up/down

Primary outcomes:

- staged soft scoring
- separate controlled vs observational evidence tagging
- reason-tag analytics and learning export
- final ratings remain distinct from stage advancement

### `PR-LEARN-259F-Replay-Diagnostics-and-Workflow-Summaries`

Purpose:

- make staged curation inspectable, replayable, and diagnosable

Primary outcomes:

- curation workflow summaries
- lineage reconstruction
- replay-safe transition provenance
- diagnostics bundle summaries for staged workflows

## 4. Recommended Order

1. `PR-LEARN-259A-Curation-Contracts-Lineage-and-Selection-Events`
2. `PR-LEARN-259B-Learning-Workspace-Staged-Curation-Mode`
3. `PR-LEARN-259C-Review-History-Import-and-Large-Compare-Surface`
4. `PR-LEARN-259D-Derived-Stage-Advancement-and-Face-Triage-Routing`
5. `PR-LEARN-259E-Learning-Evidence-Bridge-and-Reason-Tag-Analytics`
6. `PR-LEARN-259F-Replay-Diagnostics-and-Workflow-Summaries`

## 5. Sequencing Recommendation

This tranche should begin only after the current image output-route regression is
closed, because imported/discovered-review learning quality depends on correct
output classification and stable scan roots.
