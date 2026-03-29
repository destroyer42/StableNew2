# PR-VIDEO-074: SVD Artifact / History Contract Completion

## Goal

Finish SVD Phase 1 as a serious video path by aligning native SVD manifests,
pipeline metadata, and recent-history extraction with the canonical artifact
contract introduced in v2.6.

## Why This PR

The SVD runtime/controller/UI path was already broadly functional, but it still
carried a parallel contract in three places:

- `src/video/svd_registry.py` wrote a standalone manifest without the canonical
  `artifact` block.
- `src/pipeline/pipeline_runner.py` summarized SVD outputs in a custom
  `svd_native_artifact` dict without preserving the per-variant canonical
  artifact records.
- `src/controller/app_controller.py` could only build recent SVD history from
  the queue/result summary path, not from the standalone manifest fallback.

That made SVD work, but not yet feel like a first-class video path.

## Implementation

### Runtime / Registry

- `src/video/svd_registry.py`
  - Added canonical `artifact` payloads to standalone SVD manifests.
  - Added compatibility fields for `output_paths`, `video_paths`, `gif_paths`,
    `manifest_paths`, `frame_path_count`, and `count`.
  - Expanded `build_svd_history_record()` to emit the richer SVD artifact shape.

### Pipeline Metadata

- `src/pipeline/pipeline_runner.py`
  - `svd_native_artifact` now includes:
    - `primary_path`
    - `artifacts` (canonical per-variant artifact blocks)
  - Existing summary keys remain intact for compatibility.

### History / UI Consumption

- `src/controller/app_controller.py`
  - Recent SVD history now rebuilds from:
    - `svd_native_artifact` summary metadata
    - canonical variant `artifact` blocks
    - standalone SVD manifest JSON as a fallback
  - Covers MP4, GIF, and frames-only outputs.

## Tests

- New:
  - `tests/video/test_svd_registry.py`
- Updated:
  - `tests/controller/test_app_controller_svd.py`
  - `tests/pipeline/test_pipeline_runner.py`

## Verification

Passed:

```bash
pytest tests/video/test_svd_registry.py tests/pipeline/test_pipeline_runner.py tests/controller/test_app_controller_svd.py tests/video/test_svd_runner.py tests/pipeline/test_svd_runtime.py tests/controller/test_svd_controller.py tests/gui_v2/test_svd_tab_frame_v2.py -q
python -m compileall src/video/svd_registry.py src/pipeline/pipeline_runner.py src/controller/app_controller.py tests/video/test_svd_registry.py tests/controller/test_app_controller_svd.py tests/pipeline/test_pipeline_runner.py
```

## Result

SVD now has one coherent story across:

- stage result metadata
- standalone manifests
- queue/history-driven recent-run reconstruction
- SVD tab recent-history display

This finishes the remaining contract drift without changing the underlying SVD
inference runtime.
