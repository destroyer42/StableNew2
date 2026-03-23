# PR-LEARN-260C - Learning To Review Handoff and Review Draft Load

Status: Completed 2026-03-23

## Summary

Added a build-only Learning to Review handoff on top of the staged-curation
advancement-plan seam so operators can move selected candidates into the
canonical Review workspace before queueing derived jobs.

## Delivered

- extended [review_workflow_adapter.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/review_workflow_adapter.py)
  with:
  - typed `ReviewWorkspaceHandoff`
  - staged-curation target-stage to Review-toggle mapping
  - pure handoff construction from the `CurationAdvancementPlan` seam
- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with `build_staged_curation_review_handoff(...)` so Learning can build a
  Review draft without enqueueing
- extended [review_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with `load_staged_curation_handoff(...)` to preload:
  - selected source images
  - source prompt and negative prompt
  - target-stage Review toggles
  - empty prompt-edit deltas ready for deliberate editing
- extended [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with:
  - `Edit Refine in Review`
  - `Edit Face in Review`
  - `Edit Upscale in Review`
  - auto-focus to the Review tab after successful handoff
- added focused coverage in:
  - [test_discovered_review_inbox.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_discovered_review_inbox.py)
  - [test_reprocess_panel_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_reprocess_panel_v2.py)
  - [test_learning_tab_state_persistence.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_learning_tab_state_persistence.py)

## Outcomes

- staged-curation now supports the intended deliberate flow:
  Learning decides -> Review edits -> queue executes
- the Review workspace remains the single advanced manual-edit surface
- handoff uses the same staged-curation source-selection contract as direct
  queueing, avoiding duplicate selection derivation logic
- `Queue Now` remains available for the fast bulk-throughput path

## Guardrails Preserved

- handoff does not enqueue automatically
- no second execution path was introduced
- Review remains queue-backed through the existing reprocess submission path
- staged-curation provenance stays attached to the build seam rather than being
  recomputed from ad hoc GUI state

## Verification

- `python -m pytest tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_learning_tab_state_persistence.py -q`
