# StableNew Migration Closure Executable Backlog v2.6

Status: Migration closure sequence completed  
Updated: 2026-03-20

## Purpose

This document records the v2.6 migration-closure sequence that carried the repo
from mixed legacy/runtime state to the current NJR-only, queue-only production
architecture.

The active forward-looking product queue now lives primarily in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Final Migration-Closure Result

The planned `PR-UNIFY-201` through `PR-POLISH-214` sequence is now complete.

What that means in practice:

- one active architecture story
- queue-only fresh execution
- NJR as the only outer execution contract
- no live archive execution seam
- no live `submit_direct()` path
- no live `PipelineConfigPanel` runtime shim path
- canonical config layering present
- image/video diagnostics and replay aligned
- canonical tests separated from compat tests

Current collection baseline:

- `pytest --collect-only -q` -> `2540 collected / 0 skipped`

## Completed PR Sequence

### `PR-UNIFY-201-Canonical-Docs-Reset-and-Architecture-Constitution`

Reset the active documentation set so the repo had one authoritative runtime story.

### `PR-NJR-202-Queue-Only-Submission-Contract`

Collapsed fresh submission to queue-only semantics.

### `PR-MIG-203-One-Time-History-Queue-Migration-Tool`

Added explicit queue/history migration tooling and fixed the history-store race.

### `PR-MIG-204-Delete-Live-Legacy-Execution-Seams`

Removed live archive execution seams and legacy adapter paths from runtime code.

### `PR-CTRL-205-Controller-Decomposition-and-Port-Boundaries`

Extracted the first controller services and reduced top-level controller bulk.

### `PR-CONFIG-206-Canonical-Config-Unification`

Established the canonical config-layer contract across intent, execution config,
and backend options.

### `PR-PERF-206A`, `PR-PERF-206B`, `PR-PERF-206C`

Fixed preview/queue-path performance regressions:

- preview reuse during enqueue
- prompt-pack builder caching
- async debounced preview rebuild

### `PR-VIDEO-207-NJR-Video-Contract-Completion`

Aligned runtime and docs on NJR-driven video execution.

### `PR-COMFY-208`, `PR-COMFY-209`, `PR-COMFY-210`

Completed the first managed Comfy/LTX path:

- workflow registry and compiler
- managed local Comfy runtime
- first pinned LTX workflow

### `PR-TEST-211-Test-Taxonomy-and-Suite-Normalization`

Separated canonical suites from compat suites and enforced archive-free canonical tests.

### `PR-OBS-212-Image-Video-Diagnostics-and-Replay-Unification`

Unified result summaries, replay descriptors, and diagnostics bundles across image and video.

### `PR-GUI-213-GUI-Queue-Only-and-Video-Surface-Cleanup`

Removed the last live GUI runtime seam from the archived pipeline-config panel and
added the dedicated workflow-video tab.

### `PR-POLISH-214-AAA-Stability-and-Performance-Pass`

Finished the final convergence cuts for the original migration plan:

- removed `JobService.submit_direct()`
- removed dead `run_njrs_direct()` compatibility naming
- removed `AppStateV2.is_direct_run_in_progress`
- made `AppStateV2.set_run_config(...)` mirror canonical config layers
- deleted the obsolete `PipelineConfigPanel` shim module and shim-only tests
- updated compat/queue tests to reflect queue-normalized legacy run-mode behavior

## Remaining Non-Migration Debt

The following items are still real, but they are no longer migration blockers:

- `src/controller/app_controller.py` is still oversized
- `src/controller/pipeline_controller.py` is still oversized
- `AppStateV2.run_config` still exists as a derived compatibility projection,
  but it is now adapter-backed rather than treated as the primary GUI config surface
- `tests/compat/` still preserves temporary migration behaviors
- long-form video sequencing, stitching, continuity, and story-planning remain future work

These now belong to the post-unification roadmap, not to migration closure itself.

## Closure Standard

Migration closure was considered complete once the repo had all of the following:

- one outer job contract
- one fresh submission path
- one production runner entrypoint
- one canonical artifact/history/replay contract
- one active architecture document
- one test taxonomy that separates canon from temporary compatibility coverage

That standard is now met.
