# PR-LEARN-259C - Review/History Import and Large Compare Surface

Status: Completed 2026-03-21

## Summary

Reduced the main learning friction by letting Review import prior runs into
staged curation and by giving Review a larger rapid-compare surface for old
images.

## Delivered

- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with canonical staged-curation import bridges for:
  - explicit review image paths
  - recent history entries
- extended [review_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/review_tab_frame_v2.py)
  with:
  - `Import Selected to Learning`
  - `Import Recent Job`
  - larger preview surface
  - prev/next navigation
  - large rapid-compare viewer

## Outcomes

- old runs can now be brought into staged curation without regenerating images
- Review can import currently selected images directly into the Learning staged
  curation workflow
- Review can import recent history jobs by output artifacts instead of forcing
  manual folder traversal
- image inspection in Review is no longer constrained to the small legacy
  preview size

## Guardrails Preserved

- imports still land in the canonical discovered/staged-curation store
- `Review` remains the canonical advanced reprocess workspace
- no second queue or execution path was introduced

## Verification

- `pytest tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_reprocess_panel_v2.py tests/gui_v2/test_review_tab_prompt_modes.py -q`
- `python -m compileall src/gui/controllers/learning_controller.py src/gui/views/review_tab_frame_v2.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_reprocess_panel_v2.py`
