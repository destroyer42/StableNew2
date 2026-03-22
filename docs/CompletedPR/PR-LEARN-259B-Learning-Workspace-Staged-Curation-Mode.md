# PR-LEARN-259B - Learning Workspace Staged Curation Mode

Status: Completed 2026-03-21

## Summary

Added a first-class `Staged Curation` mode inside the existing Learning
workspace so users can review discovered candidates, preview them at a useful
size, and record advancement decisions inline.

## Delivered

- extended [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with a third Learning mode: `Staged Curation`
- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with staged-curation projection and decision-recording APIs
- extended [discovered_review_store.py](/c:/Users/rob/projects/StableNew/src/learning/discovered_review_store.py)
  to persist canonical selection events per discovered group
- extended [learning_state.py](/c:/Users/rob/projects/StableNew/src/gui/learning_state.py)
  with staged-curation selection state

## Outcomes

- staged curation is reachable from the existing Learning notebook
- users can open active discovered-review groups and review candidates without
  switching to a separate outer workflow
- the mode provides:
  - candidate grid
  - large preview surface
  - quick advancement / hold / reject decisions
  - reason-tag capture
  - notes capture
- selection decisions are now persisted as canonical
  `stablenew.selection_event.v2.6` records under the discovered-review store

## Guardrails Preserved

- `Review` remains the canonical advanced reprocess workspace
- no standalone competing curation tab was introduced
- no new execution path was added in this PR

## Verification

- `pytest tests/learning_v2/test_discovered_review_store.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_learning_tab_state_persistence.py -q`
- `python -m compileall src/gui/learning_state.py src/learning/discovered_review_store.py src/gui/controllers/learning_controller.py src/gui/views/learning_tab_frame_v2.py tests/learning_v2/test_discovered_review_store.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_learning_tab_state_persistence.py`
