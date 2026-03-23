# PR-LEARN-262 - Portable Review Metadata Rehydration and UI Surfacing

Status: Completed 2026-03-23

## Summary

Added a canonical read path for portable review metadata and surfaced that
rehydrated review context in Review and staged curation without replacing the
internal learning-record system of record.

## Delivered

- extended [src/review/review_metadata_service.py](c:/Users/rob/projects/StableNew/src/review/review_metadata_service.py)
  with:
  - normalized `PortableReviewSummary`
  - portable review summary normalization helpers
  - embedded/sidecar portable review summary read support
- extended [src/gui/controllers/learning_controller.py](c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with:
  - internal review summary normalization for `review_tab` feedback records
  - `get_prior_review_summary(...)` with precedence:
    - internal learning record
    - embedded portable review metadata
    - sidecar portable review metadata
  - discovered/manual import enrichment so imported items can carry normalized
    portable review context in `extra_fields`
- extended [src/gui/views/review_tab_frame_v2.py](c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with a read-only `Prior Review Summary` surface for the selected artifact
- extended [src/gui/views/learning_tab_frame_v2.py](c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  with a compact read-only `Prior Review` summary block in the staged-curation
  selection workspace
- added focused coverage in:
  - [tests/review/test_review_metadata_service.py](c:/Users/rob/projects/StableNew/tests/review/test_review_metadata_service.py)
  - [tests/controller/test_learning_controller_review_feedback.py](c:/Users/rob/projects/StableNew/tests/controller/test_learning_controller_review_feedback.py)
  - [tests/gui_v2/test_reprocess_panel_v2.py](c:/Users/rob/projects/StableNew/tests/gui_v2/test_reprocess_panel_v2.py)
  - [tests/gui_v2/test_learning_tab_state_persistence.py](c:/Users/rob/projects/StableNew/tests/gui_v2/test_learning_tab_state_persistence.py)

## Outcomes

- Review can now surface prior review state even when it comes from artifact
  metadata instead of internal history alone
- staged-curation selection now shows prior review status, rating, notes, and
  prompt-change context when available
- imported review images can carry normalized portable review context forward
  into later staged-curation flows
- internal learning-record review history still takes precedence when both
  internal and portable review data exist

## Guardrails Preserved

- internal learning records remain the canonical review feedback store
- portable review metadata is used as a rehydration source, not a replacement
- GUI surfaces stay read-only for prior review context and delegate precedence
  resolution to controller/service layers
- artifact-load failures remain non-blocking

## Verification

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/review/test_review_metadata_service.py tests/controller/test_learning_controller_review_feedback.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_learning_tab_state_persistence.py -q`