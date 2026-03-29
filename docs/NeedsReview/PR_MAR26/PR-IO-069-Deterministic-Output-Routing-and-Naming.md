# PR-IO-069: Deterministic Output Routing and Naming

## Goal

Reduce artifact-path drift in the canonical execution path by making output routing
and stage naming derive from stable job context instead of hidden in-memory state
or wall-clock-based filename suffixes.

## Scope

Allowed runtime changes in this PR:

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/utils/file_io.py`
- focused pipeline/filename regression tests

Out of scope:

- queue/history schema changes
- new folder layout
- replacing the current route taxonomy
- broad UI changes

## Problems Addressed

1. `PipelineRunner` reused pack folders through a process-local cache only.
   That meant reuse behavior depended on whether the current process had already
   seen the pack/model/vae combination.

2. `PipelineRunner` ignored `NormalizedJobRecord.path_output_dir` when choosing
   the route root, preferring the runner default base directory.

3. `build_safe_image_name()` still embedded a timestamp suffix, so identical
   calls could produce different filenames depending on call time.

4. Direct executor helper fallbacks still used timestamp-based names for some
   stage outputs when an explicit `image_name` was not supplied.

## Implementation

### 1. Filesystem-aware run-dir resolution

`PipelineRunner` now:

- resolves the route root from `njr.path_output_dir` first, then falls back to
  the runner base dir
- derives a stable canonical folder key from route + pack/model/vae or learning id
- reuses a recent matching folder by scanning the filesystem, not just the
  process-local cache
- keeps the existing timestamp-prefixed folder layout instead of introducing a
  new directory scheme

This preserves the current output-folder structure while making reuse behavior
stable across fresh runner instances.

### 2. Deterministic image-name helper

`build_safe_image_name()` now:

- removes the wall-clock timestamp suffix
- remains path-safe and length-bounded
- preserves pack-name context when available
- includes a stable hash token when seed or matrix values contribute identity
- keeps explicit batch suffixes

This makes naming deterministic for the same canonical inputs.

### 3. Deterministic fallback names in executor helpers

Executor fallback stage names now derive from the input image stem rather than
`datetime.now()`, so direct helper execution is no longer clock-driven when
`image_name` is omitted.

### 4. Save-path coercion

Executor manifest-writing paths now normalize truthy non-`Path` return values
from `save_image_from_base64()` back to the intended fallback path. This keeps
tests and call sites that stub the save helper with `True` from breaking manifest
path handling.

## Tests

Added/updated coverage:

- `tests/pipeline/test_output_folder_structure.py`
  - folder reuse survives a fresh runner instance
  - `njr.path_output_dir` overrides runner default base dir
- `tests/utils/test_filename_generation.py`
  - pack-name + seed combinations remain distinct
- `tests/pipeline/test_executor_adetailer.py`
  - fallback naming uses the input image stem deterministically

Regression suite run:

- `pytest tests/utils/test_filename_generation.py tests/test_filename_fix.py tests/pipeline/test_output_folder_structure.py tests/pipeline/test_executor_n_iter_filenames.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_pipeline_runner.py -q`
- `pytest --collect-only -q`

## Outcome

The canonical pipeline path now has:

- stable route-root selection
- stable recent-folder reuse across runner restarts
- deterministic stage filename generation
- better robustness around manifest path derivation

The next planned PR in sequence remains `PR-RES-070`.
