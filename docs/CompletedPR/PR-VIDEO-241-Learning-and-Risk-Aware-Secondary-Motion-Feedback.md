# PR-VIDEO-241 - Learning and Risk-Aware Secondary Motion Feedback

Status: Completed 2026-03-22

## Summary

This PR closed the loop on secondary motion by retaining only compact scalar
motion summaries in learning records and allowing recommendation context to
stratify on motion policy and application path without weakening the existing
evidence-tier model.

## Delivered

- added compact secondary-motion learning metrics extraction
- persisted bounded motion summaries into `LearningRecord.metadata`
- extended recommendation query and record scoring context with motion policy
  and application-path fields
- kept learning retention scalar-only and free of raw frame or dense motion
  payloads

## Key Files

- `src/video/motion/secondary_motion_metrics.py`
- `src/learning/learning_record_builder.py`
- `src/learning/recommendation_engine.py`
- `tests/learning/test_learning_record_builder.py`
- `tests/learning/test_recommendation_engine_v2.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/learning/test_learning_record_builder.py tests/learning/test_recommendation_engine_v2.py -q`
- result: included in the final focused tranche run with `58 passed`