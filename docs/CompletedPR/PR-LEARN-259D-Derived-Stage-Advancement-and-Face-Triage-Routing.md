# PR-LEARN-259D - Derived Stage Advancement and Face Triage Routing

Status: Completed 2026-03-21

## Summary

Compiled staged-curation advancement into normal NJR-backed reprocess jobs for
refine, face triage, and upscale without adding a parallel execution path.

## Delivered

- added [curation_workflow_builder.py](/c:/Users/rob/projects/StableNew/src/curation/curation_workflow_builder.py)
  as the canonical staged-curation derivation helper
- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with:
  - per-candidate face-triage tier persistence
  - staged decision -> derived NJR compilation
  - canonical queue submission for refine, face-triage, and upscale jobs
- extended [discovered_review_store.py](/c:/Users/rob/projects/StableNew/src/learning/discovered_review_store.py)
  so staged-curation items can persist per-candidate tier metadata
- extended [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with:
  - face-triage tier selector
  - `Generate Refine Jobs`
  - `Generate Face Jobs`
  - `Generate Upscale Jobs`

## Outcomes

- staged-curation selections now produce normal queue-backed jobs instead of
  stopping at a stored decision event
- face-triage routing is per candidate, not blanket ADetailer
- derived stage jobs are explicitly routed to the Learning output surface
- curation lineage and source decision metadata survive into derived jobs

## Guardrails Preserved

- all staged advancement remains NJR-backed
- no new outer job model was introduced
- no direct runner or bypass execution path was added
- expensive refine, face-triage, and upscale work runs only for selected
  candidates

## Verification

- `pytest tests/curation/test_curation_workflow_builder.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_learning_tab_state_persistence.py -q`
- `python -m compileall src/curation src/learning/discovered_review_store.py src/gui/controllers/learning_controller.py src/gui/views/learning_tab_frame_v2.py tests/curation/test_curation_workflow_builder.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_learning_tab_state_persistence.py`
