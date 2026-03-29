# PR-MAR26-003 Review-Learning Feedback Bridge

## Objective
Make Review tab outcomes part of learning data.

## Scope
- Add rating/quality annotation in Review tab.
- Persist review feedback into learning records store.
- Capture prompt/config deltas as structured metadata.

## Files
- src/gui/views/review_tab_frame_v2.py
- src/gui/controllers/review_controller.py (new if needed)
- src/learning/learning_record.py
- src/gui/controllers/learning_controller.py

## Test Plan
- New tests for review feedback persistence and retrieval.

## Acceptance
- Review actions create retrievable learning feedback records.
