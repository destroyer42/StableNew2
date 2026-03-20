# PR-VIDEO-219 - Story and Shot Planning Foundation

Status: Completed 2026-03-20

## Summary

This PR added the first StableNew-owned manual planning layer above sequence
jobs and continuity packs without introducing a second outer execution model.

Story, scene, shot, and anchor plans now persist as deterministic JSON records,
compile into `VideoSequenceJob` intent with explicit `plan_origin` metadata,
and preserve that origin through executed sequence result summaries.

## Delivered

- added `src/video/story_plan_models.py` for `StoryPlan`, `ScenePlan`,
  `ShotPlan`, `AnchorPlan`, and summary contracts
- added `src/video/story_plan_compiler.py` for deterministic plan-to-sequence
  compilation with stable sequence IDs and explicit plan-origin metadata
- added `src/video/story_plan_store.py` for deterministic JSON persistence and
  summary listing
- updated `src/video/sequence_models.py` so compiled sequence intent and
  executed sequence artifacts can carry `plan_origin`
- updated `src/pipeline/pipeline_runner.py` to stamp plan-origin metadata into
  executed sequence results when plan-backed sequence metadata is present
- extended continuity helpers in `src/video/continuity_models.py` so story,
  scene, and shot plans can inherit optional continuity linkage deterministically

## Key Files

- `src/video/story_plan_models.py`
- `src/video/story_plan_compiler.py`
- `src/video/story_plan_store.py`
- `src/video/sequence_models.py`
- `src/video/continuity_models.py`
- `src/pipeline/config_contract_v26.py`
- `src/pipeline/pipeline_runner.py`

## Tests

Focused verification passed for:

- `pytest tests/video/test_story_plan_models.py tests/video/test_story_plan_compiler.py tests/video/test_story_plan_store.py tests/pipeline/test_pipeline_runner.py -q`
- `python -m compileall src/video/story_plan_models.py src/video/story_plan_compiler.py src/video/story_plan_store.py src/video/sequence_models.py src/video/continuity_models.py src/pipeline/config_contract_v26.py src/pipeline/pipeline_runner.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Deferred Debt

Intentionally deferred:

- story and shot planning UX/editor surfaces
  Future owner: `PR-GUI-220`
- further controller/config-adapter cleanup around plan-oriented surfaces
  Future owner: `PR-CTRL-221`