# PR-LEARN-259F - Replay, Diagnostics, and Workflow Summaries for Staged Curation

Status: Completed 2026-03-21

## Summary

Made staged curation inspectable from the existing Learning and diagnostics
surfaces by adding workflow summaries, candidate replay-lineage views, and
curation-aware replay/diagnostics descriptors.

## Delivered

- added [workflow_summary.py](/c:/Users/rob/projects/StableNew/src/curation/workflow_summary.py)
  for canonical workflow-summary and replay-lineage payload generation
- extended [learning_controller.py](/c:/Users/rob/projects/StableNew/src/gui/controllers/learning_controller.py)
  with:
  - `get_staged_curation_workflow_summary(...)`
  - `get_staged_curation_candidate_replay_summary(...)`
- extended [learning_tab_frame_v2.py](/c:/Users/rob/projects/StableNew/src/gui/views/learning_tab_frame_v2.py)
  so staged curation shows:
  - workflow summary
  - selected-candidate replay chain / lineage summary
- extended [result_contract_v26.py](/c:/Users/rob/projects/StableNew/src/pipeline/result_contract_v26.py)
  so replay and diagnostics descriptors carry curation provenance from NJR
  snapshot metadata
- extended [job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py)
  and [diagnostics_bundle_v2.py](/c:/Users/rob/projects/StableNew/src/utils/diagnostics_bundle_v2.py)
  so diagnostics bundles now persist curation replay details when present

## Outcomes

- staged-curation workflows can now be summarized without opening raw JSON
- selected candidates expose replay-chain details directly in Learning
- derived staged-curation jobs now surface curation lineage in replay and
  diagnostics outputs
- diagnostics can localize failures by candidate and target stage when the job
  originated from staged curation

## Guardrails Preserved

- no new replay system or diagnostics path was introduced
- all provenance still flows through NJR snapshot / result descriptor surfaces
- staged curation remains on the canonical Learning and diagnostics surfaces

## Verification

- `pytest tests/curation/test_workflow_summary.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_learning_tab_state_persistence.py tests/pipeline/test_result_contract_v26.py tests/utils/test_diagnostics_bundle_v2.py -q`
- `python -m compileall src/curation src/gui/controllers/learning_controller.py src/gui/views/learning_tab_frame_v2.py src/pipeline/result_contract_v26.py src/controller/job_service.py src/utils/diagnostics_bundle_v2.py tests/curation/test_workflow_summary.py tests/gui_v2/test_discovered_review_inbox.py tests/gui_v2/test_learning_tab_state_persistence.py tests/pipeline/test_result_contract_v26.py tests/utils/test_diagnostics_bundle_v2.py`
