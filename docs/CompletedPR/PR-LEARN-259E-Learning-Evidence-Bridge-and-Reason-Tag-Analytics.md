# PR-LEARN-259E - Learning Evidence Bridge and Reason Tag Analytics

Status: Completed 2026-03-21

## Summary

Turned staged-curation advancement behavior into structured learning evidence
without collapsing it into the stronger designed-experiment lane.

## Delivered

- added [learning_bridge.py](/c:/Users/rob/projects/StableNew/src/curation/learning_bridge.py)
  as the canonical staged-curation -> learning-record translator
- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  so staged-curation decisions append durable learning records immediately
- extended [recommendation_engine.py](/c:/Users/rob/projects/StableNew/src/learning/recommendation_engine.py)
  so `staged_curation_event` records participate as observational evidence,
  not as strong experiment evidence
- extended [learning_analytics.py](/c:/Users/rob/projects/StableNew/src/learning/learning_analytics.py)
  and [learning_analytics_panel.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_analytics_panel.py)
  with evidence-class, decision, and reason-tag summaries

## Outcomes

- staged advancement now contributes durable recommendation evidence
- final ratings remain distinct from advancement decisions
- reason-tag usage is visible in analytics instead of being trapped inside
  selection-event payloads
- staged curation remains weaker observational evidence than controlled
  designed-experiment data

## Guardrails Preserved

- no new learning record schema was introduced outside the existing JSONL path
- staged curation does not bypass the canonical Learning subsystem
- recommendation automation still requires strong experiment evidence

## Verification

- `pytest tests/curation/test_learning_bridge.py tests/learning_v2/test_learning_analytics.py tests/learning_v2/test_recommendation_engine_evidence_tiering.py tests/learning_v2/test_analytics_panel.py tests/gui_v2/test_discovered_review_inbox.py -q`
- `python -m compileall src/curation src/learning src/gui/controllers/learning_controller.py src/gui/views/learning_analytics_panel.py tests/curation/test_learning_bridge.py tests/learning_v2/test_learning_analytics.py tests/learning_v2/test_recommendation_engine_evidence_tiering.py tests/learning_v2/test_analytics_panel.py tests/gui_v2/test_discovered_review_inbox.py`
