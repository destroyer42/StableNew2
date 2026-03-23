# PR-LEARN-260E - Source vs Derived Outcome Compare and Lineage Jump

Status: Completed 2026-03-23

## Summary

Closed the staged-curation lineage loop by preserving source metadata through
Review-originated submits, reconstructing newest derived descendants from
history, and exposing source-vs-derived compare jumps in Learning and Review.

## Delivered

- extended [curation_manifest.py](/c:/Users/rob/projects/StableNew/src/curation/curation_manifest.py)
  with serializable staged-curation source metadata and Review lineage block
  builders for Review-originated derived jobs
- extended [workflow_summary.py](/c:/Users/rob/projects/StableNew/src/curation/workflow_summary.py)
  with replay-descriptor fallback logic for Review reprocess metadata and a
  `find_latest_derived_descendant(...)` helper backed by existing history
  snapshots/results
- extended [review_workflow_adapter.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/review_workflow_adapter.py)
  so staged-curation Review handoffs carry per-image serialized source metadata
- extended [app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py)
  so Review reprocess submits can accept per-image source metadata, preserve it
  on source items, and stamp top-level curation lineage blocks on derived NJRs
- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  so staged replay summaries can surface the newest derived descendant and the
  controller can resolve the latest descendant for a candidate on demand
- extended [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with a `Compare Latest Derived` jump and replay summary details for latest
  derived stage/output
- extended [review_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with a `Compare Latest Derived` action, side-by-side source-vs-derived viewer
  rendering, and Review-submit handoff of staged-curation source metadata
- added focused coverage in:
  - [test_workflow_summary.py](/c:/Users/rob/projects/StableNew/tests/curation/test_workflow_summary.py)
  - [test_app_controller_reprocess_review_tab.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_controller_reprocess_review_tab.py)
  - [test_reprocess_panel_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_reprocess_panel_v2.py)

## Outcomes

- direct `Queue Now` and Review-mediated derived jobs now preserve enough shared
  staged-curation lineage to be rediscovered later as descendants
- operators can jump from a staged-curation candidate to the newest derived
  output and inspect source and derived images together in Review
- staged replay summaries now expose the latest derived stage/output context
  without introducing a parallel lineage registry

## Guardrails Preserved

- no new execution path was introduced
- Review remains the canonical advanced manual-edit workspace
- lineage reconstruction uses existing NJR snapshots and job history rather than
  a second persistence system
- Review-originated reprocess jobs still go through the existing queue-backed
  NJR reprocess path

## Verification

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/curation/test_workflow_summary.py tests/controller/test_app_controller_reprocess_review_tab.py tests/gui_v2/test_reprocess_panel_v2.py -q`