# PR-VIDEO-217 - Stitching, Interpolation, and Clip-Assembly Unification

Status: Completed 2026-03-19

## Summary

This PR turned post-video assembly into a StableNew-owned contract layer
instead of leaving sequence outputs, stitched exports, and Movie Clips as
adjacent utilities.

Sequence assembly, interpolation boundaries, and Movie Clips now share one
canonical assembled-video path with explicit provenance to source segments,
export settings, and final output artifacts.

## Delivered

- added `src/video/assembly_models.py` for stitched, interpolated, and
  export-ready assembly contracts
- added `src/video/interpolation_contracts.py` to model interpolation as a
  pluggable provider boundary with a no-op default
- added `src/video/assembly_service.py` to orchestrate canonical post-video
  assembly and manifest writing
- aligned `src/video/movie_clip_models.py`,
  `src/video/movie_clip_service.py`, and `src/video/video_export.py` so Movie
  Clips consumes canonical assembly inputs and emits aligned artifacts
- updated `src/pipeline/pipeline_runner.py`,
  `src/gui/view_contracts/movie_clips_contract.py`, and
  `src/gui/views/movie_clips_tab_frame_v2.py` so assembled outputs and source
  bundles can flow through runner and UI handoff paths
- hardened manifest determinism by writing relative assembly paths and omitting
  volatile nested timestamps from the persisted manifest payload

## Key Files

- `src/video/assembly_models.py`
- `src/video/interpolation_contracts.py`
- `src/video/assembly_service.py`
- `src/video/movie_clip_models.py`
- `src/video/movie_clip_service.py`
- `src/video/video_export.py`
- `src/pipeline/pipeline_runner.py`
- `src/gui/view_contracts/movie_clips_contract.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`

## Tests

Focused verification passed for:

- `pytest tests/video/test_assembly_models.py tests/video/test_interpolation_contracts.py tests/video/test_assembly_service.py tests/video/test_movie_clip_service.py tests/gui_v2/test_movie_clips_tab_v2.py tests/pipeline/test_pipeline_runner.py tests/journeys/test_movie_clips_mvp.py -q`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Deferred Debt

Intentionally deferred:

- continuity-aware assembly presets and linkage
  Future owner: `PR-VIDEO-218`
- story and shot aware planning over continuity-backed video work
  Future owner: `PR-VIDEO-219`
- broader workspace polish around the unified video surfaces
  Future owner: `PR-GUI-220`