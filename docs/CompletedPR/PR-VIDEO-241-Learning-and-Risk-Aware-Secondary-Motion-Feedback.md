# PR-VIDEO-241 - Learning and Risk-Aware Secondary Motion Feedback

Status: Completed 2026-03-24

## Summary

This PR closed the loop on secondary motion by retaining only compact scalar
motion summaries in learning records and making recommendation matching treat
backend, policy, application path, and status as real evidence cohorts instead
of mixing incomparable runtime outcomes.

## Delivered

- added compact secondary-motion learning metrics extraction
- persisted bounded motion summaries into `LearningRecord.metadata`
- extended recommendation query and record scoring context with backend,
  policy, application-path, and status cohorts
- excluded unavailable or skipped motion runs from positive applied-motion
  tuning evidence while keeping learning storage scalar-only
- kept learning retention scalar-only and free of raw frame or dense motion
  payloads

## Key Files

- `src/video/motion/secondary_motion_metrics.py`
- `src/learning/learning_record_builder.py`
- `src/learning/recommendation_engine.py`
- `tests/learning/test_secondary_motion_metrics.py`
- `tests/learning/test_learning_record_builder.py`
- `tests/learning/test_learning_record_builder_secondary_motion.py`
- `tests/learning/test_recommendation_engine_v2.py`
- `tests/learning/test_recommendation_engine_secondary_motion.py`
- `tests/learning/test_learning_hooks_pipeline_runner.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/learning/test_secondary_motion_metrics.py tests/learning/test_learning_record_builder_secondary_motion.py tests/learning/test_recommendation_engine_secondary_motion.py tests/learning/test_learning_record_builder.py tests/learning/test_recommendation_engine_v2.py tests/learning/test_learning_hooks_pipeline_runner.py -q`
- result: `15 passed in 4.25s`
