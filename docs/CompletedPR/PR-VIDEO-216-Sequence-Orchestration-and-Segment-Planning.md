# PR-VIDEO-216 - Sequence Orchestration and Segment Planning

Status: Completed 2026-03-19

## Summary

This PR added StableNew-owned long-form video planning above the existing
workflow-video backend path while preserving NJR as the only outer executable
contract.

One workflow-video job can now carry deterministic sequence intent, execute
ordered segment plans through the runner, and persist per-segment provenance
plus a sequence-level manifest.

## Delivered

- added `src/video/sequence_models.py` for typed sequence, segment, and
  provenance contracts
- added `src/video/sequence_planner.py` for deterministic planning, segment ID
  generation, and carry-forward policy handling
- added `src/video/sequence_manifest.py` for StableNew-owned sequence manifest
  writing
- updated `src/video/comfy_workflow_backend.py` with segment-scoped execution
  support and provenance stamping
- updated `src/pipeline/config_contract_v26.py`,
  `src/pipeline/job_models_v2.py`, `src/pipeline/stage_sequencer.py`, and
  `src/pipeline/pipeline_runner.py` so sequence intent can stay NJR-backed and
  runner-owned

## Key Files

- `src/video/sequence_models.py`
- `src/video/sequence_planner.py`
- `src/video/sequence_manifest.py`
- `src/video/comfy_workflow_backend.py`
- `src/pipeline/config_contract_v26.py`
- `src/pipeline/job_models_v2.py`
- `src/pipeline/stage_sequencer.py`
- `src/pipeline/pipeline_runner.py`

## Tests

Focused verification passed for:

- `pytest tests/video/test_sequence_models.py tests/video/test_sequence_planner.py tests/video/test_sequence_manifest.py tests/pipeline/test_pipeline_runner.py tests/pipeline/test_stage_sequencer_plan_builder.py -q`
- `pytest tests/video/test_comfy_workflow_backend.py -q`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Deferred Debt

Intentionally deferred:

- stitched/interpolated assembled outputs over sequence artifacts
  Future owner: `PR-VIDEO-217`
- continuity-aware linkage above sequence jobs
  Future owner: `PR-VIDEO-218`
- story and shot planning above sequence intent
  Future owner: `PR-VIDEO-219`