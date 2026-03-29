# StableNew Staged Curation Pipeline Spec v2.6

Status: Proposed, repo-ready  
Applies to: StableNew2 v2.6+  
Architecture alignment: Queue-first, NJR-only, canonical artifact/history/replay/learning contracts

---

## 0. Purpose

This spec defines a **Staged Curation Pipeline** for StableNew that lets the user:

1. generate a low-cost scout batch,
2. manually or semi-automatically advance promising candidates,
3. refine only selected images,
4. selectively run face repair tiers,
5. upscale only finalists,
6. record all advancement behavior as structured learning data.

This is not a side workflow. It is a StableNew-owned orchestration layer that sits on top of the existing canonical runtime:

`Intent Surface -> Builder/Compiler -> NJR -> JobService Queue -> PipelineRunner -> Stage/Backend Execution -> Canonical Artifacts -> History/Learning/Diagnostics`

The Staged Curation Pipeline must:
- remain NJR-backed,
- remain queue-first,
- preserve replayability,
- preserve lineage between scout/refine/final outputs,
- treat user selection as structured signal rather than lost manual effort.

---

## 1. Problem Statement

Today, StableNew can generate images, apply ADetailer, and upscale, but the highest-cost post-processing often runs before the system knows whether a candidate is worth saving.

That creates four problems:

1. **Wasted compute**
   - bad candidates still consume ADetailer/upscale cycles.

2. **Poor signal quality**
   - the system knows the final rating, but not which candidates survived each curation gate.

3. **Mixed failure diagnosis**
   - it is unclear whether an image failed because of:
     - bad composition,
     - poor refinement robustness,
     - face repair damage,
     - or upscale drift.

4. **Underused user behavior**
   - the user already performs useful curation, but it is not captured as canonical learning data.

---

## 2. Design Goals

### 2.1 Primary goals
- Let the user explore cheaply, refine selectively, and finalize intentionally.
- Preserve exact lineage from scout -> refine -> face repair -> upscale.
- Capture advancement behavior as structured learning signal.
- Avoid introducing a second execution architecture.

### 2.2 Non-goals
- This is not a replacement for PromptPack.
- This is not a new outer job model.
- This is not a backend-owned feature.
- This is not an always-on autonomous optimizer.

### 2.3 Invariants
- Every stage submission is NJR-backed.
- Fresh execution is queue-only.
- Final outputs remain canonical artifacts.
- Selection behavior is stored as StableNew metadata, not side notes.
- Replay must be able to reconstruct the full curation chain.

---

## 3. High-Level User Workflow

## 3.1 Scout batch
The user launches a low-cost batch to explore:
- pose
- composition
- framing
- broad aesthetic direction

Recommended scout resolutions:
- 640x960 for cheap exploration
- 768x1152 for safer anatomy/composition scouting
- avoid very low scout resolutions when body/face integrity matters

Default scout rules:
- no ADetailer
- no face restore
- no upscale
- no expensive final polish

User action:
- mark each result:
  - Hard Reject
  - Pass / Not Advancing
  - Advance to Refine

## 3.2 Refine selected
Selected scout candidates are re-run through img2img refine.

Purpose:
- test whether promising compositions survive higher-quality generation
- improve texture/detail without wasting full compute on all candidates

User action:
- mark each refined result:
  - Reject
  - Advance to Face Triage
  - Advance directly to Finalist

## 3.3 Face triage
Only images that actually need help get ADetailer.

Per candidate options:
- Skip
- Light
- Medium
- Heavy

This may be:
- user-selected manually,
- system-recommended,
- or both.

## 3.4 Final upscale
Only finalists are upscaled.

User action:
- final rating
- optional detailed review
- optional keep/export/archive decision

---

## 4. Architecture Placement

The staged curation system belongs at the StableNew orchestration layer, not in backend code.

Canonical placement:

`Intent Surface`
-> `Curation Workflow Builder`
-> `NJR-backed Scout Jobs`
-> `Selection Events`
-> `Derived NJR-backed Refine Jobs`
-> `Selection Events`
-> `Derived NJR-backed Face Triage Jobs`
-> `Selection Events`
-> `Derived NJR-backed Final Upscale Jobs`
-> `Canonical Artifacts`
-> `History / Replay / Learning`

### 4.1 Ownership rules
StableNew owns:
- stage progression,
- candidate lineage,
- user selection events,
- learning signal,
- replay and diagnostics.

Backends execute only.

---

## 5. Core Objects

## 5.1 `CurationWorkflow`
Top-level container for one staged curation session.

Suggested file:
`src/curation/models.py`

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

CurationWorkflowStatus = Literal[
    "draft",
    "scout_running",
    "scout_complete",
    "refine_running",
    "refine_complete",
    "face_triage_running",
    "face_triage_complete",
    "upscale_running",
    "complete",
    "cancelled",
]

@dataclass(slots=True)
class CurationWorkflow:
    workflow_id: str
    title: str
    created_at: str
    status: CurationWorkflowStatus
    root_prompt_fingerprint: str
    root_config_fingerprint: str
    root_model: str
    notes: Optional[str] = None
```

## 5.2 `CurationCandidate`
Represents one image candidate at any stage.

```python
from dataclasses import dataclass
from typing import Literal, Optional

CandidateStage = Literal["scout", "refine", "face_triage", "upscale", "final"]

@dataclass(slots=True)
class CurationCandidate:
    candidate_id: str
    workflow_id: str
    stage: CandidateStage
    artifact_id: str
    job_id: str
    njr_id: str
    parent_candidate_id: Optional[str]
    root_candidate_id: str
    prompt_fingerprint: str
    config_fingerprint: str
    model_name: str
    selected: bool = False
```

## 5.3 `SelectionEvent`
Captures user advancement behavior.

```python
from dataclasses import dataclass, field
from typing import Literal

SelectionDecision = Literal[
    "rejected_hard",
    "not_advanced",
    "advanced_to_refine",
    "advanced_to_face_triage",
    "advanced_to_finalist",
    "advanced_to_upscale",
    "curated_final",
]

@dataclass(slots=True)
class SelectionEvent:
    event_id: str
    workflow_id: str
    candidate_id: str
    stage: str
    decision: SelectionDecision
    timestamp: str
    actor: str = "user"
    reason_tags: list[str] = field(default_factory=list)
    notes: str | None = None
```

## 5.4 `RefineProfile`
Describes how a scout winner should be refined.

```python
from dataclasses import dataclass
from typing import Literal, Optional

RefineStrength = Literal["light", "medium", "heavy"]

@dataclass(slots=True)
class RefineProfile:
    strength: RefineStrength
    img2img_denoise: float
    steps: int
    sampler_name: str
    scheduler: str
    override_model: Optional[str] = None
```

## 5.5 `FaceTriageProfile`
Describes user- or policy-selected ADetailer intensity.

```python
from dataclasses import dataclass
from typing import Literal

FaceTriageTier = Literal["skip", "light", "medium", "heavy"]

@dataclass(slots=True)
class FaceTriageProfile:
    tier: FaceTriageTier
    confidence: float
    denoise: float
    steps: int
    mask_padding: int
```

## 5.6 `CurationOutcome`
Final learning-facing summary.

```python
from dataclasses import dataclass, field

@dataclass(slots=True)
class CurationOutcome:
    workflow_id: str
    candidate_id: str
    final_rating: float | None
    final_reason_tags: list[str] = field(default_factory=list)
    final_review_notes: str | None = None
    kept: bool = False
    exported: bool = False
```

---

## 6. Canonical Manifests and Metadata

## 6.1 Candidate lineage block
Every stage artifact produced by this workflow should include a curation lineage block.

```json
{
  "curation": {
    "schema": "stablenew.curation.v2.6",
    "workflow_id": "cwf_123",
    "candidate_id": "cand_456",
    "stage": "refine",
    "parent_candidate_id": "cand_123",
    "root_candidate_id": "cand_001",
    "source_decision": "advanced_to_refine",
    "prompt_fingerprint": "sha256:...",
    "config_fingerprint": "sha256:...",
    "model_name": "albedobaseXL_v31Large"
  }
}
```

## 6.2 Selection event sidecar / history entry
Selections should be written into history as first-class events.

```json
{
  "schema": "stablenew.selection_event.v2.6",
  "event_id": "sel_001",
  "workflow_id": "cwf_123",
  "candidate_id": "cand_456",
  "stage": "scout",
  "decision": "advanced_to_refine",
  "reason_tags": ["good_composition", "nice_lighting"],
  "notes": "face weak but composition worth saving",
  "timestamp": "2026-03-21T18:00:00Z"
}
```

## 6.3 Final outcome block
For final curated images:

```json
{
  "curation_outcome": {
    "schema": "stablenew.curation_outcome.v2.6",
    "workflow_id": "cwf_123",
    "candidate_id": "cand_999",
    "final_rating": 4.5,
    "final_reason_tags": ["keeper", "good_face", "strong_composition"],
    "final_review_notes": "worked best with light ADetailer only",
    "kept": true,
    "exported": false
  }
}
```

---

## 7. Learning Semantics

## 7.1 Do not treat all non-selected images as hard negatives
This is critical.

A candidate that is not advanced may be:
- bad,
- decent but not preferred,
- redundant,
- not worth further compute,
- composition-good but face-bad.

So selection scoring should be staged and soft.

## 7.2 Recommended stage score mapping
Suggested default learning weights:

- `rejected_hard`: `-0.7`
- `not_advanced`: `-0.2`
- `advanced_to_refine`: `+0.3`
- `advanced_to_face_triage`: `+0.2`
- `advanced_to_finalist`: `+0.5`
- `advanced_to_upscale`: `+0.7`
- `curated_final`: `+1.0`

Final user rating should be recorded separately, not collapsed into the same scalar.

## 7.3 Learning record additions
Suggested new fields in learning-facing records:
- `curation_stage`
- `selection_decision`
- `selection_reason_tags`
- `advanced_count`
- `lineage_depth`
- `was_refined`
- `face_triage_tier`
- `was_upscaled`
- `final_rating`

---

## 8. UI Flow

## 8.1 New workspace: `Curation Workflow`
Recommended new GUI surface:
- a dedicated `Curation Workflow` tab
or
- a mode within PromptPack generation

## 8.2 Main panes
### Left pane
Workflow setup:
- prompt source
- model
- scout resolution
- scout batch size
- refine profile defaults
- face triage defaults
- upscale defaults

### Center pane
Candidate grid for current stage:
- thumbnail
- candidate ID
- stage badge
- model badge
- quick stats
- lineage link

### Right pane
Selection controls:
- Hard Reject
- Pass
- Advance to Refine
- Advance to Face Triage
- Advance to Upscale
- Mark Final

Optional notes:
- reason tags
- free text notes
- face triage tier selector

## 8.3 Stage transitions
Buttons:
- `Run Scout Batch`
- `Generate Refine Jobs for Selected`
- `Generate Face Triage Jobs for Selected`
- `Generate Final Upscale Jobs for Selected`
- `Complete Workflow`

---

## 9. NJR and Builder Integration

## 9.1 No new outer job model
The curation system must compile all stage work into normal NJR-backed jobs.

## 9.2 Builder additions
Suggested module:
`src/curation/curation_workflow_builder.py`

Responsibilities:
- create scout NJRs
- create refine NJRs from selected parent candidates
- create face triage NJRs from selected parent candidates
- create final upscale NJRs from selected parent candidates

## 9.3 Derivation rules
### Scout
- base prompt and config
- no ADetailer
- no upscale
- scout resolution

### Refine
- img2img from scout artifact
- same prompt by default
- optional prompt patch only if explicitly chosen
- refine profile determines denoise/model/etc.

### Face Triage
- selected candidate routed to ADetailer profile
- tier-based parameter set

### Upscale
- selected finalist routed to upscale settings

---

## 10. Suggested File Layout

```text
src/curation/
  __init__.py
  models.py
  curation_workflow_builder.py
  curation_service.py
  selection_service.py
  curation_manifest.py
  learning_bridge.py
  ui_projection.py

src/gui/views/
  curation_workflow_tab.py

tests/curation/
  test_curation_workflow_builder.py
  test_selection_events.py
  test_candidate_lineage.py
  test_learning_bridge.py
  test_manifest_projection.py
```

---

## 11. Service Responsibilities

## 11.1 `CurationService`
Suggested file:
`src/curation/curation_service.py`

Responsibilities:
- create workflows
- launch scout batches
- derive next-stage jobs from selections
- resolve workflow status

## 11.2 `SelectionService`
Suggested file:
`src/curation/selection_service.py`

Responsibilities:
- persist selection events
- compute stage advancement sets
- guard against invalid transitions
- produce stage summaries

## 11.3 `LearningBridge`
Suggested file:
`src/curation/learning_bridge.py`

Responsibilities:
- translate selection events and final ratings into learning-friendly records
- avoid over-penalizing non-advanced candidates
- aggregate lineage-aware signals

---

## 12. Default Profiles

## 12.1 Scout defaults
- resolution: `640x960` or `768x1152`
- no ADetailer
- no face restore
- no upscale
- moderate step count
- deterministic seed handling if desired

## 12.2 Refine defaults
### Light
- img2img denoise: `0.18–0.28`

### Medium
- img2img denoise: `0.30–0.42`

### Heavy
- img2img denoise: `0.45+`

## 12.3 Face triage defaults
### Skip
- no ADetailer

### Light
- conservative denoise
- preserve structure

### Medium
- standard repair

### Heavy
- salvage mode only

## 12.4 Upscale defaults
- only for finalists
- conservative denoise
- no automatic face restore by default

---

## 13. Replay and Diagnostics

Replay must be able to:
- locate the root scout candidate,
- reconstruct all parent/child transitions,
- show which stage each candidate entered,
- show why it was advanced or rejected,
- reconstruct final outcome and notes.

Diagnostics bundles should include:
- workflow summary
- stage candidate counts
- selection decision distribution
- lineage chain
- config/model changes across passes

---

## 14. Failure Handling

## 14.1 Stage job failure
If a refine/face/upscale job fails:
- candidate lineage remains intact,
- failure is recorded as candidate status,
- workflow continues,
- user may retry that candidate only.

## 14.2 Invalid transition prevention
Examples:
- cannot upscale a candidate that was never marked finalist
- cannot face-triage a candidate not produced by scout or refine
- cannot finalize without a produced artifact

---

## 15. Test Strategy

## 15.1 Unit tests
- workflow creation
- candidate lineage creation
- selection event persistence
- advancement set computation
- learning score projection
- manifest serialization

## 15.2 Integration tests
- scout batch -> refine derivation
- refine -> face triage derivation
- face triage -> upscale derivation
- replay of staged workflow lineage

## 15.3 Architecture guard tests
- `src/curation/**` must not create a second runner path
- no backend-owned curation logic
- no GUI-owned candidate lineage logic

---

## 16. Rollout Plan

## Phase 1 — MVP
- `CurationWorkflow`
- `CurationCandidate`
- `SelectionEvent`
- scout -> refine -> upscale
- final ratings
- lineage in manifests

## Phase 2 — Face triage
- face triage tiers
- user-facing ADetailer routing
- learning bridge additions

## Phase 3 — Recommendation layer
- suggest refine/face/upscale paths
- recommend ADetailer tier
- summarize which settings survive the funnel best

---

## 17. Done Definition

This feature is done when:
- the user can launch scout batches and selectively advance results,
- all advanced stages remain NJR-backed and queue-first,
- every candidate has lineage,
- selection events are persisted canonically,
- final ratings and detailed reviews attach to curated finalists,
- learning can distinguish:
  - hard rejects,
  - non-advanced candidates,
  - advanced candidates,
  - finalists,
  - curated finals.

---

## 18. Strategic Outcome

This feature turns StableNew from:
- one-pass generation with manual hidden curation

into:
- structured staged generation with replayable, learnable, user-driven selection intelligence.

That improves:
- compute efficiency,
- training signal quality,
- user control,
- and long-term recommendation quality.
