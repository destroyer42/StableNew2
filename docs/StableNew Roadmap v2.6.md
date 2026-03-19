StableNew Roadmap v2.6.md
(Canonical Edition)

Status: Authoritative
Updated: 2026-03-18
Applies To: Codex, Copilot, ChatGPT Planner, Human Contributors

0. Strategic Objective

Turn StableNew into a polished local orchestrator for image and video creation
with:

- one architecture
- one outer job model
- one queue-first submission path
- one runner
- one canonical artifact/history contract
- one coherent documentation and testing surface

North Star runtime:

`Intent Surface -> Builder/Compiler -> NJR -> JobService Queue -> PipelineRunner -> Stage/Backend Execution -> Canonical Artifacts -> History/Learning/Diagnostics`

1. Core Outcomes

1.1 Final NJR unification

- NJR is the only outer executable job contract
- image and video both use NJR
- replay, reprocess, CLI, learning, and image edit all converge to NJR

1.2 Queue-only execution

- fresh execution is queue-only
- `Run Now` becomes queue submit + immediate auto-start
- no dual-path runtime semantics

1.3 StableNew-owned orchestration

- StableNew owns intent, queue, runner, history, artifacts, diagnostics, and replay
- external runtimes and backends execute only

1.4 Config unification

- intent config
- normalized execution config
- backend-local options

These layers must be separate and explicit.

1.5 Simpler testing and debugging

- canonical suites define runtime truth
- compat suites exist only to migrate old persisted data
- quarantine is explicit and not allowed to define architecture

2. Current Starting Point

The repo already has important strengths:

- NJR-first queue/runner backbone
- canonical artifact/manifests substrate
- replay and reprocess substrate
- `src/video/` backend seam for video execution
- healthy collection baseline: `2338 collected / 1 skipped`

The biggest remaining debt seams are:

- `src/controller/app_controller.py` remains oversized
- `src/controller/pipeline_controller.py` remains oversized
- live archive `PipelineConfig` imports remain in source and tests
- `src/pipeline/legacy_njr_adapter.py` is still present
- `DIRECT` still exists in code/tests and older docs
- active docs still contradict each other

3. Roadmap Phases

Phase 0 - Canonical docs reset

Goal:

- one active architecture story
- one active roadmap
- one active migration backlog
- one active Comfy/video backlog
- one operator-facing README

Primary PR:

- `PR-UNIFY-201-Canonical-Docs-Reset-and-Architecture-Constitution`

Phase 1 - NJR and submission-path closure

Goal:

- remove live `DIRECT` execution
- introduce queue-only fresh submission
- add one-time migration tooling for old queue/history data
- delete live archive execution seams

Primary PRs:

- `PR-NJR-202-Queue-Only-Submission-Contract`
- `PR-MIG-203-One-Time-History-Queue-Migration-Tool`
- `PR-MIG-204-Delete-Live-Legacy-Execution-Seams`

Phase 2 - Controller, config, and test unification

Goal:

- decompose controller ownership
- publish one canonical config model
- normalize test taxonomy and CI gates

Primary PRs:

- `PR-CTRL-205-Controller-Decomposition-and-Port-Boundaries`
- `PR-CONFIG-206-Canonical-Config-Unification`
- `PR-TEST-211-Test-Taxonomy-and-Suite-Normalization`

Phase 3 - Video contract completion and Comfy foundation

Goal:

- finalize NJR-driven video alignment
- add workflow registry/compiler
- add managed local Comfy runtime
- ship the first pinned LTX workflow

Primary PRs:

- `PR-VIDEO-207-NJR-Video-Contract-Completion`
- `PR-COMFY-208-Workflow-Registry-and-Compiler`
- `PR-COMFY-209-Managed-Comfy-Runtime-and-Dependency-Probes`
- `PR-COMFY-210-First-Pinned-LTX-Workflow`

Delivered progress:

- `PR-PERF-206A`, `PR-PERF-206B`, and `PR-PERF-206C` removed the most obvious
  preview/queue-path regressions before the next migration and video tranche
- `PR-VIDEO-207` completed the generic NJR-driven video artifact/history
  contract while keeping stage-specific compatibility summaries alive

Phase 4 - Observability and GUI completion

Goal:

- unify image/video diagnostics and replay
- remove residual runtime legacy GUI seams
- add the dedicated workflow video surface

Primary PRs:

- `PR-OBS-212-Image-Video-Diagnostics-and-Replay-Unification`
- `PR-GUI-213-GUI-Queue-Only-and-Video-Surface-Cleanup`

Phase 5 - AAA polish and release readiness

Goal:

- throughput tuning
- restart/recovery cleanliness
- model-switch minimization
- deterministic outputs
- full golden-path confidence
- docs harmonization and release posture

Primary PR:

- `PR-POLISH-214-AAA-Stability-and-Performance-Pass`

4. Near-Term Priorities

The immediate order of operations is:

1. reset the docs and remove contradiction
2. collapse fresh execution to queue-only
3. replace live legacy runtime support with one-time migration tooling
4. remove archive DTO and legacy adapter seams
5. decompose controllers after ownership rules are documented

This keeps architectural cleanup ahead of Comfy expansion.

5. Mid-Term Outcomes

After migration closure, StableNew should support:

- backend-agnostic video execution through the existing `src/video/` seam
- a managed local Comfy runtime
- a pinned LTX workflow compiled from StableNew-native inputs
- deterministic sequence planning, clip stitching, and future continuity/story planning

6. Done Definition

StableNew v2.6 unification is only complete when all of the following are true:

- no live archive imports remain
- no live `DIRECT` execution remains
- no live `pipeline_config` execution remains
- image and video both run through NJR -> queue -> runner
- artifacts/history/replay share one canonical contract
- canonical tests are green and archive-free
- compat tests are temporary, explicit, and shrinking
- `README.md`, `docs/ARCHITECTURE_v2.6.md`, and `docs/DOCS_INDEX_v2.6.md` all tell the same story

7. Guiding Principle

Prefer doing it right over doing it easy.

Every PR should make StableNew:

- simpler to reason about
- easier to test
- easier to debug
- more reliable under long queue runs
- faster to evolve without architectural drift
