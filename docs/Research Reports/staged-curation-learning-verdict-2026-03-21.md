# Staged Curation Learning Proposal Verdict

Status: Accepted with restructuring  
Date: 2026-03-21  
Scope: Learning, Review, discovered-review, staged advancement, learning signal quality

## 1. Verdict

The core idea is correct and high-value:

- StableNew is currently leaving major learning signal on the table
- the user is already doing valuable curation work
- that curation is not yet captured as first-class canonical evidence
- the current learning UX still creates too much friction to collect enough ratings and advancement data

The proposal should be adopted, but not as a parallel workflow with a new
standalone architecture.

The right implementation is:

- keep the canonical queue-first NJR execution path
- keep `Review` as the canonical advanced reprocess workspace
- extend `Learning` into the canonical evidence-and-advancement workspace
- add a first-class `Staged Curation` mode inside the existing Learning surface
- let staged curation consume both:
  - intentionally designed experiments
  - previously generated/discovered/history-imported outputs

## 2. What The Proposal Gets Right

- It turns existing user behavior into useful learning signal immediately.
- It reduces wasted compute by advancing only good candidates into expensive stages.
- It captures stage-aware survival and rejection behavior instead of relying only on final star ratings.
- It better matches actual user workflow:
  - scout
  - compare
  - advance
  - refine
  - selectively repair
  - upscale finalists
- It creates much better replay and failure diagnosis by making stage lineage explicit.

## 3. What Should Change

### 3.1 Do not add a separate competing workspace

The repo already has the right product seams:

- [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
- [review_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
- [discovered_review_store.py](/c:/Users/rob/projects/StableNew/src/learning/discovered_review_store.py)

So the curation idea should be absorbed into those surfaces, not built beside them.

### 3.2 Separate evidence classes

StableNew should explicitly distinguish:

- controlled evidence
  - deliberate designed experiments
  - one variable or bounded config changes
- observational evidence
  - normal production runs
  - discovered-review imports
  - staged advancement behavior

Controlled evidence should remain the stronger recommendation source for causal
suggestions, but observational curation should still be captured heavily.

### 3.3 Large-image review is mandatory

The proposal correctly identifies that current review friction is one of the
biggest reasons learning underperforms.

The staged curation rollout should include:

- larger preview/compare surfaces
- faster advance/reject controls
- reason tags
- easy import from history/discovered outputs

Without that, StableNew will keep collecting too little evidence.

## 4. What Should Not Be Done

- Do not create a second outer job model.
- Do not create a backend-owned curation subsystem.
- Do not create GUI-owned lineage truth.
- Do not treat all non-advanced images as hard negatives.
- Do not force every workflow through all stages.
- Do not build the feature around folder scanning only.
- Do not duplicate `Review` with another reprocess workspace.

## 5. Recommended Product Shape

### 5.1 Learning Tab

`Learning` should become the canonical evidence-and-curation workspace with
three coordinated modes:

- `Designed Experiments`
- `Discovered / Imported Review`
- `Staged Curation`

### 5.2 Review Tab

`Review` remains the canonical advanced reprocess workspace:

- prompt changes
- stage toggles
- deliberate reprocess jobs
- manual advanced inspection

### 5.3 Handoff model

The clean handoff is:

- `Learning` decides what evidence exists and what should advance
- `Review` remains the low-level manual intervention surface when deeper edits are needed

## 6. Strategic Outcome

If implemented this way, StableNew gets both:

- intentional learning from designed experiments
- high-volume immediate learning from real user behavior on existing outputs

That is better than the current learning tab alone, and better than a separate
curation tab that would fragment the product.

## 7. Recommendation

Accept the proposal, but convert it into a Learning/Review integration tranche.

Immediate sequencing recommendation:

1. close the current output-route regression for image runs still landing under `output/animatediff`
2. then begin the staged curation tranche with the contract/lineage foundation PR

The executable rollout for that tranche is tracked in:

- [STAGED_CURATION_EXECUTABLE_ROADMAP_v2.6.md](/c:/Users/rob/projects/StableNew/docs/PR_Backlog/STAGED_CURATION_EXECUTABLE_ROADMAP_v2.6.md)
