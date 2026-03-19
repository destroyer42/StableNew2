# StableNew Migration Closure Executable Backlog v2.6

Status: Active backlog
Updated: 2026-03-18

## Purpose

This backlog drives the repo from its current mixed migration state to the
final NJR-only, queue-only, archive-free runtime described in
`docs/ARCHITECTURE_v2.6.md`.

This document is the active execution backlog for migration closure. It is not
an archival note.

## Current Debt Seams

As of the current repo snapshot:

- `src/controller/app_controller.py` is still about `5587` LOC
- `src/controller/pipeline_controller.py` is still about `1566` LOC
- `src/controller/job_service.py` still carries `submit_direct()` as a queue-normalizing compatibility shim
- active tests still import archive `PipelineConfig` DTOs
- some archive-leaning tests still codify legacy `DIRECT` or `PipelineConfig`
- a few GUI shim surfaces still carry `PipelineConfigPanel` naming/history

Important correction:

- older migration notes claiming `pytest --collect-only -q` was badly broken are stale
- the current collection baseline is healthy: `2348 collected / 1 skipped`

This means migration can now be aggressive, but it must still be sequenced.

## Deferred Debt Map

The following intentionally deferred items now have explicit future owners:

- `submit_direct()` compatibility shim in `JobService`
  Owner PR: `PR-POLISH-214`
- remaining archive DTO imports in active/non-canonical tests
  Owner PR: `PR-TEST-211`
- residual `PipelineConfigPanel` naming/shim history in GUI surfaces
  Owner PR: `PR-GUI-213`
- remaining controller monolith reduction after the run/preview submission slice
  Owner PRs: `PR-GUI-213` and `PR-POLISH-214`
- `AppStateV2.run_config` and preset-facing GUI surfaces still expose a dict
  façade over the canonical config layers
  Owner PR: `PR-GUI-213`
- richer backend-owned config compilation for Comfy/LTX remains future work
  beyond the current derived `backend_options` contract
  Owner PRs: `PR-COMFY-208`, `PR-COMFY-209`, and `PR-COMFY-210`

## Global Invariants

These rules apply to the whole backlog:

1. `PipelineRunner.run_njr(...)` remains the only production runner entrypoint.
2. Fresh production execution becomes queue-only.
3. Old persisted queue/history data is handled by one-time migration tooling.
4. No PR may introduce new archive DTO imports, new `DIRECT` execution paths,
   or new legacy runtime bridges.
5. Canonical tests must move toward archive-free imports and queue-first truth.
6. Compat coverage may exist temporarily, but only around persisted-data
   migration and only with explicit exit criteria.

## Prioritized PR Queue

### 1. `PR-UNIFY-201-Canonical-Docs-Reset-and-Architecture-Constitution` `(Completed 2026-03-18)`

Rewrite the active docs set so the repo has one authoritative architecture
story, one roadmap, one migration backlog, one Comfy backlog, and one operator
README.

Success criteria:

- no duplicate active architecture story
- docs explicitly define queue-only fresh execution as the target
- older stale migration claims are retired

### 2. `PR-NJR-202-Queue-Only-Submission-Contract` `(Completed 2026-03-18)`

Remove real `DIRECT` execution from fresh runtime submission.

Implementation targets:

- `PipelineRunRequest`
- controller run-mode handling
- run-now semantics
- tests and docs that still define `DIRECT` as a real executor path

Success criteria:

- `Run Now` uses queue submit + immediate auto-start
- no fresh runtime branch invokes a distinct `DIRECT` executor
- payload construction is unchanged except for submission-path collapse

Verification:

- targeted controller/queue/pipeline tests
- `pytest --collect-only -q`

### 3. `PR-MIG-203-One-Time-History-Queue-Migration-Tool` `(Completed 2026-03-18)`

Add explicit tooling to upgrade old queue/history data before compat code is
deleted.

Required behavior:

- dry-run mode
- backup output
- version detection
- upgrade report
- rollback/operator guidance

Success criteria:

- old persisted queue/history data can be upgraded once
- runtime no longer needs to keep broad live compat for those formats

### 4. `PR-MIG-204-Delete-Live-Legacy-Execution-Seams` `(Completed 2026-03-18)`

Delete the live runtime bridges that still keep legacy execution semantics
around.

Primary targets:

- `legacy_njr_adapter`
- archive `PipelineConfig` imports in live source
- `allow_legacy_fallback`
- live `pipeline_config` execution helpers

Success criteria:

- zero live source imports from `src.controller.archive.*`
- zero live `legacy_njr_adapter`
- zero fresh runtime support for `pipeline_config` execution

### 5. `PR-CTRL-205-Controller-Decomposition-and-Port-Boundaries` `(Completed 2026-03-18)`

Break oversized controller ownership into typed services and ports that match
the canonical architecture.

Primary outcomes:

- smaller AppController
- smaller PipelineController
- clearer boundaries for build/submit/history/runtime concerns

Success criteria:

- controller files materially shrink
- controller responsibilities are mapped to named services/ports
- runtime semantics do not regress

### 6. `PR-CONFIG-206-Canonical-Config-Unification` `(Completed 2026-03-18)`

Define and implement one canonical config layering model:

- intent config
- normalized execution config
- backend-local options

Success criteria:

- stage-ready execution config is clearly distinguished from UI/preset state
- video and image work share the same outer config story
- backends do not become top-level config owners

Delivered:

- canonical config-layer contract added under `src/pipeline/config_contract_v26.py`
- NJRs and snapshots now persist `intent_config`, executable config, and
  `backend_options` distinctly
- queue submission and prompt-pack/run-request builders now emit the canonical
  config-layer metadata by default

### 6A. `PR-PERF-206A-Preview-Reuse-and-Queue-Submit-Batching` `(Completed 2026-03-18)`

Removed a redundant preview rebuild from enqueue flows and coalesced queue
updated emission during preview batch submission.

Delivered:

- enqueue now reuses cached preview NJRs when available
- preview-to-queue submission now batches queue-updated emission
- add-to-queue no longer pays one full queue summary rebuild per submitted job

### 6B. `PR-PERF-206B-PromptPack-Builder-Caching` `(Completed 2026-03-18)`

Added file-aware caching to prompt-pack NJR building.

Delivered:

- cached parsed pack rows
- cached pack metadata/config loads
- cached resolved config layers keyed by pack source and runtime params
- controller reuse of the prompt-pack builder so caches survive repeated UI actions

### 6C. `PR-PERF-206C-Async-Debounced-Preview-Rebuild` `(Completed 2026-03-18)`

Moved preview recomputation off the UI thread while keeping final preview state
authoritative.

Delivered:

- async preview rebuild path in `AppController`
- request-id guard so stale preview results cannot overwrite newer ones
- add-to-job no longer forces synchronous preview rebuilds

### 7. `PR-VIDEO-207-NJR-Video-Contract-Completion` `(Completed 2026-03-18)`

Finish the last image/video contract gaps so docs and runtime say the same
thing.

Delivered:

- `PipelineRunner` now emits generic `video_artifacts` and
  `video_primary_artifact` metadata while preserving stage-specific compatibility
  keys
- history and GUI consumers now prefer generic video artifact summaries before
  falling back to legacy `svd_native_artifact` or `animatediff_artifact`
- docs and runtime now agree that image and video both remain NJR-driven, with
  `VideoExecutionRequest` staying internal to the runner/backend seam

### 8. `PR-COMFY-208-Workflow-Registry-and-Compiler`

Add workflow registry and compiler on top of the existing `src/video/` backend
seam.

Success criteria:

- backend-internal workflow compilation exists
- NJR remains the outer contract
- no Comfy leakage outside `src/video/`

### 9. `PR-COMFY-209-Managed-Comfy-Runtime-and-Dependency-Probes`

Add StableNew-managed local Comfy lifecycle, health checks, and dependency
reporting.

Success criteria:

- local Comfy can be supervised by StableNew
- backend health is explicit and testable
- dependency failures are actionable

### 10. `PR-COMFY-210-First-Pinned-LTX-Workflow`

Ship one pinned LTX workflow routed through NJR, queue, runner, artifacts,
history, and diagnostics.

Success criteria:

- one real end-to-end LTX workflow exists
- replay metadata is sufficient
- history visibility matches image/video contract rules

### 11. `PR-TEST-211-Test-Taxonomy-and-Suite-Normalization`

Split tests into:

- canonical runtime suites
- compat-migration suites
- quarantine/archive suites

Success criteria:

- canonical suites do not import archive DTOs
- compat suites are clearly marked temporary
- default CI gates prefer canonical runtime truth

### 12. `PR-OBS-212-Image-Video-Diagnostics-and-Replay-Unification`

Unify diagnostics and replay across image and video workloads.

Success criteria:

- crash/recovery bundles describe one runtime truth
- replay descriptors are backend-aware without leaking backend details
- image/video failures are equally actionable

### 13. `PR-GUI-213-GUI-Queue-Only-and-Video-Surface-Cleanup`

Remove runtime legacy GUI seams and add the dedicated video workflow surface
after backend/compiler stability exists.

Primary targets:

- residual `pipeline_config_panel_v2` coupling
- queue-only run surface assumptions
- dedicated workflow-driven video surface

### 14. `PR-POLISH-214-AAA-Stability-and-Performance-Pass`

Final platform hardening pass focused on polish and release readiness.

Primary outcomes:

- restart cleanliness
- model-switch minimization
- deterministic output routing
- queue stability under long runs
- golden-path confidence

## Verification Rules

Every PR in this backlog must pass:

- targeted pytest for touched subsystems
- `pytest --collect-only -q`
- compile/import sanity for touched modules
- architecture enforcement tests
- doc updates in the same PR when architectural truth changes

Additional closure gates:

- zero live archive source imports
- zero live `DIRECT` execution branches
- zero canonical tests depending on archive DTO imports
- migrated persisted data verified by explicit migration tooling, not runtime fallback

## Completion Standard

Migration closure is complete only when StableNew has:

- one outer job contract
- one fresh submission path
- one production runner entrypoint
- one artifact/history/replay contract
- one active architecture document
- one test taxonomy that cleanly separates canon from temporary migration support
