# PR-MAR26-004 Contextual Recommendation Engine v2

## Objective
Upgrade recommendations from global averages to context-aware ranking.

## Scope
- Add context features (stage/model/style/resolution/prompt similarity bucket).
- Compute confidence with sample volume + variance.
- Expand apply-map coverage in learning controller.

## Files
- src/learning/recommendation_engine.py
- src/gui/controllers/learning_controller.py
- tests/learning/test_recommendation_engine_v2.py (new)

## Acceptance
- Recommendations differ by context and expose confidence rationale.
