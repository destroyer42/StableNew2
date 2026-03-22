# StableNew Staged Curation Pipeline PR Sequence v2.6

Status: Proposed  
Applies to: StableNew2  
Scope: staged scout -> refine -> face triage -> upscale workflow

---

## PR-CURATE-230 — Contracts, models, and manifest schema

### BLUF
Establish the canonical staged curation contract before adding UI or behavior.

### Add
- `src/curation/models.py`
- `src/curation/curation_manifest.py`

### Implement
- `CurationWorkflow`
- `CurationCandidate`
- `SelectionEvent`
- `CurationOutcome`
- manifest schema block `stablenew.curation.v2.6`

### Tests
- contract serialization tests
- manifest roundtrip tests

### Success criteria
- no runtime behavior changes yet
- canonical contract exists
- replay-safe lineage schema exists

---

## PR-CURATE-231 — Builder and service foundation

### BLUF
Add StableNew-owned orchestration for scout/refine/upscale derivation.

### Add
- `src/curation/curation_workflow_builder.py`
- `src/curation/curation_service.py`
- `src/curation/selection_service.py`

### Implement
- scout NJR creation
- refine NJR derivation from parent candidate
- upscale NJR derivation from finalist candidate
- selection event persistence

### Tests
- builder derivation tests
- invalid transition tests

### Success criteria
- no second outer job model
- all stage work remains NJR-backed

---

## PR-CURATE-232 — History and learning bridge

### BLUF
Turn user advancement behavior into structured learning signal.

### Add
- `src/curation/learning_bridge.py`

### Implement
- soft stage scoring
- final rating integration
- curation lineage summary export for learning

### Tests
- learning score projection tests
- non-advanced vs hard-reject distinction tests

### Success criteria
- no blunt thumbs-up/down collapse
- final ratings remain distinct from stage advancement signal

---

## PR-CURATE-233 — GUI surface MVP

### BLUF
Expose scout -> refine -> upscale staged curation in a first-class UI flow.

### Add
- `src/gui/views/curation_workflow_tab.py`

### Implement
- workflow setup form
- candidate grid
- selection buttons
- notes and reason tags
- stage transition buttons

### Tests
- headless UI wiring tests
- selection command routing tests

### Success criteria
- scout batches can be launched and curated
- refine/upscale jobs can be derived from selected candidates

---

## PR-CURATE-234 — Face triage routing

### BLUF
Add selective ADetailer routing instead of blanket face repair.

### Extend
- `src/curation/models.py`
- `src/curation/curation_workflow_builder.py`
- `src/curation/selection_service.py`
- UI tab

### Implement
- `FaceTriageProfile`
- per-candidate `skip/light/medium/heavy`
- ADetailer derivation only for selected candidates

### Tests
- face tier mapping tests
- invalid face-triage transition tests

### Success criteria
- user can route only needed candidates through ADetailer
- ADetailer is no longer assumed for all candidates

---

## PR-CURATE-235 — Replay, diagnostics, and summaries

### BLUF
Make staged curation auditable and replayable.

### Extend
- history/replay display surfaces
- diagnostics bundle generation

### Implement
- workflow summary
- candidate lineage display
- selection event summaries
- replay chain reconstruction

### Tests
- replay lineage reconstruction tests
- diagnostics serialization tests

### Success criteria
- staged curation can be inspected and replayed
- failures can be localized by stage

---

## Recommended execution order

```text
PR-CURATE-230
PR-CURATE-231
PR-CURATE-232
PR-CURATE-233
PR-CURATE-234
PR-CURATE-235
```

---

## Global guardrails

- No second execution path
- No backend-owned curation logic
- No GUI-owned lineage truth
- No treating all non-selected candidates as hard negatives
- No silent prompt/config drift between stages without recorded lineage

---

## Done definition

The staged curation pipeline is complete when:
- scout, refine, face triage, and upscale can all be driven from one workflow,
- all stage jobs are NJR-backed,
- every candidate has lineage,
- user advancement is persisted canonically,
- learning can consume stage-aware selection behavior,
- replay and diagnostics can reconstruct the full funnel.
