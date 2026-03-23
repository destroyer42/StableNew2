# PR-LEARN-260F - Queue Now vs Edit in Review UX Polish and Bulk Selection Rules

Status: Completed 2026-03-23

## Summary

Finalized the hybrid staged-curation operator flow by making `Queue Now` the
explicit bulk-throughput path and `Edit in Review` the explicit selected-item
deliberate-edit path.

## Delivered

- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with an explicit selected-candidate filter for staged-curation Review
  handoffs so Review opens only the chosen candidate while queue submissions
  remain bulk stage actions
- extended [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with:
  - explicit bulk labels: `Queue Refine Now`, `Queue Face Now`, `Queue Upscale Now`
  - single-candidate Review gating for `Edit ... in Review`
  - dynamic guidance showing bulk marked counts vs selected-candidate Review
    behavior
  - tooltips clarifying the throughput vs deliberate-edit split
- extended [review_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with a staged-curation handoff hint that makes Review’s role as the deliberate
  single-candidate edit workspace explicit
- added focused coverage in:
  - [test_discovered_review_inbox.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_discovered_review_inbox.py)
  - [test_learning_tab_state_persistence.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_learning_tab_state_persistence.py)
  - [test_reprocess_panel_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_reprocess_panel_v2.py)

## Outcomes

- `Queue Now` is now clearly the bulk path driven by all candidates currently
  marked for a derived stage
- `Edit in Review` is now clearly the deliberate single-candidate path driven by
  the selected candidate only
- operators can see, before acting, whether they are about to open one item in
  Review or enqueue all marked items for a target stage

## Guardrails Preserved

- no second execution path was introduced
- Review remains the canonical advanced manual-edit workspace
- bulk queueing still converges on the same NJR-backed staged-curation path
- selection logic remains in controller/learning seams rather than being
  duplicated as ad hoc GUI-owned orchestration

## Verification

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_learning_tab_state_persistence.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_reprocess_panel_v2.py -q`