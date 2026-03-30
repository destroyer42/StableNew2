ARCHITECTURE_v2.6.md
(Canonical)

StableNew Core Architecture Specification (v2.6)
Last Updated: 2026-03-30
Status: Canonical, Binding

0. Purpose

This document defines the only valid target architecture for StableNew's
runtime, submission path, ownership boundaries, and backend model.

It replaces contradictory or narrower descriptions that treated StableNew as:

- PromptPack-only
- image-only
- dual-path (`QUEUE` plus `DIRECT`) at runtime
- controller-assembled around legacy `pipeline_config` DTOs
- backend-driven rather than StableNew-orchestrated

This document is the constitutional source of truth. Migration debt that still
exists in source or tests is not architecture; it is tracked debt to remove.

1. Non-Negotiable Invariants

1.1 Single outer execution contract

`NormalizedJobRecord` (NJR) is the only executable outer job contract.

Fresh execution, replay, reprocess, learning submissions, CLI submissions,
image edits, and video submissions must all converge to NJR before execution.

1.2 Queue-only fresh execution

Fresh production execution is queue-only.

`Run Now` is defined as:

- submit to `JobService`
- enqueue NJR-backed work
- auto-start processing immediately when allowed

UI code may synchronously watch the queued job, but that is not a second
execution path.

1.3 Single production runner entrypoint

`PipelineRunner.run_njr(...)` is the only production runner entrypoint.

No controller, GUI component, compatibility DTO, or backend may define a second
production execution route.

1.4 StableNew is the orchestrator

StableNew owns:

- intent intake
- builder/compiler logic
- queue and lifecycle policy
- runner orchestration
- artifacts and manifests
- history and replay
- learning and diagnostics

Backends execute only.

1.5 No live legacy execution model

The final runtime must not rely on:

- `pipeline_config` execution
- archive DTO imports as active runtime dependencies
- `legacy_njr_adapter` as a live runtime bridge
- raw backend workflow JSON as a public contract

Old persisted queue/history data is handled by one-time migration tooling, not
by indefinite live runtime compatibility.

2. Canonical Runtime Topology

The canonical runtime is:

`Intent Surface -> Builder/Compiler -> NJR -> JobService Queue -> PipelineRunner -> Stage/Backend Execution -> Canonical Artifacts -> History/Learning/Diagnostics`

Each layer has one role:

- intent surfaces collect user or system intent
- builders/compilers normalize that intent
- NJR freezes executable state
- `JobService` owns submission and queue policy
- `PipelineRunner` owns run orchestration
- stage executors and video backends perform execution
- artifacts/manifests persist outputs
- history, replay, learning, and diagnostics consume canonical results

There is no second runtime story for image versus video.

Current production deployment shape after `PR-PERF-502` is a local midpoint,
not a second execution architecture:

- the GUI process owns Tk surfaces, `AppStateV2` draft state, and the local
  runtime-host client
- the GUI launches a bounded-handshake child runtime host before enabling
  runtime-backed actions
- the child runtime host owns `JobService`, queue state, runner execution,
  history, watchdogs, and managed WebUI/Comfy lifecycle
- the same-process local adapter remains DI-only and test-only until daemon
  promotion replaces the child-host midpoint

3. Intent Surfaces And Builders/Compilers

StableNew supports multiple intent surfaces. They are all valid, but they do
not get separate execution architectures.

Supported surfaces:

- PromptPack image generation
- character training submissions
- reprocess
- image edit / masked edit
- history replay / restore
- learning-generated submissions
- video workflow submissions
- CLI submissions

PromptPack remains the primary image authoring surface. It is not the sole
source of valid intent across the whole system.

Every intent surface must end at a builder or compiler that emits canonical
NJR-backed work. Intent surfaces do not own queue, runner, artifact, or
backend logic.

4. NJR Contract And Lifecycle

NJR is the only outer executable job envelope.

An NJR is responsible for carrying:

- normalized prompts or prompt provenance
- immutable execution config for enabled stages
- stage ordering and execution metadata
- source/provenance information
- run labeling and output-routing intent
- replayable context sufficient for canonical execution

Queue entries, history entries, reprocess jobs, replay jobs, and learning jobs
must all rely on NJR snapshots or NJR-derived records rather than raw
`pipeline_config` payloads.

Image and video jobs are both NJR-driven. Video-specific execution details may
be compiled into internal video requests, but that does not create a second
outer job model.

Standalone training jobs are also NJR-driven. A `train_lora` NJR remains queue
submitted and runner executed; external trainer CLIs are subprocess
dependencies, not alternate outer job contracts.

5. Queue-Only Submission Model

5.1 Fresh submission

All fresh submission flows must enter through `JobService` and the queue.

The final `PipelineRunRequest` contract is queue-only for fresh execution.

5.2 Run Now semantics

`Run Now` remains a UX affordance, not a distinct runtime mode. It means:

- build NJR-backed work
- submit to queue
- request immediate processing
- optionally wait for completion at the UI/service layer

5.3 Replay and recovery

Replay and resume remain canonical queue/runner consumers. They do not rebuild
legacy config objects or bypass NJR hydration.

6. Runner Ownership And Stage Orchestration

`PipelineRunner` owns:

- run-plan construction from NJR
- stage sequencing
- output layout selection
- stage-level metadata and checkpoints
- backend dispatch for video stages
- recovery coordination and canonical result assembly

Preferred still-image chain:

`txt2img -> optional img2img -> optional adetailer -> optional final upscale`

The `train_lora` stage is a valid standalone NJR stage. It must not be mixed
with still-image or video stages inside the same execution chain.

Refiner and hires remain supported as advanced `txt2img` metadata, not as a
parallel job architecture.

Model and option changes are expected at NJR boundaries or explicit stage
configuration boundaries. Unintentional intra-job model churn is forbidden.

7. Image/Video Backend Model

7.1 Image execution

Image stages execute through StableNew-owned stage orchestration and executor
logic. External image runtimes do not own queue, history, or artifacts.

7.2 Video execution

Video execution uses the `src/video/` backend seam. `VideoExecutionRequest` and
`VideoExecutionResult` are internal runner-to-backend contracts, not public job
models.

7.3 Backend ownership boundary

Backends may own:

- backend-local request translation
- backend-local health/dependency checks
- backend-local execution polling and result normalization

Backends may not own:

- queue semantics
- controller contracts
- GUI state
- history schemas
- artifact governance
- replay architecture

External training scripts follow the same rule. They may execute as
runner-owned subprocesses, but they do not define public StableNew job models,
controller contracts, or artifact governance.

7.4 Comfy-specific rule

Comfy workflow JSON is backend-internal. It must not become a GUI/controller or
top-level runtime contract.

8. Canonical Config Layering

StableNew uses three config layers:

8.1 Intent config

User-facing or system-facing intent from PromptPacks, reprocess, learning,
video workflow surfaces, CLI flags, or history replay inputs.

In the live runtime, this is carried as `intent_config` metadata on NJR-backed
records and in queue/history snapshots.

8.2 Normalized execution config

Immutable, stage-ready config persisted on the NJR and consumed by runner and
stage execution. This is the only executable config layer.

In the live runtime, this is `NormalizedJobRecord.config`.

8.3 Backend-local options

Executor-specific options that live under backend-owned metadata or compiled
request payloads. These may influence execution but do not replace NJR as the
outer contract.

In the live runtime, backend-local options are carried separately from the
executable config and may be derived into `NormalizedJobRecord.backend_options`
or compiled backend request payloads.

Presets, UI state, PromptPack JSON defaults, and backend JSON are not
executable by themselves.

9. Artifacts, History, Learning, And Diagnostics

9.1 Canonical artifacts

Image and video outputs must conform to one canonical artifact model. Stage
manifests enrich this contract; they do not replace it.

9.2 History

History stores NJR-backed snapshots and canonical result summaries. It must not
depend on raw `pipeline_config` execution payloads.

9.3 Replay

Replay hydrates NJR-backed records and re-enters the same queue/runner
architecture. There is no special-case replay executor path.

9.4 Learning

Learning consumes canonical outputs, canonical history, and NJR provenance. It
must not depend on controller-local or legacy result shapes.

9.5 Diagnostics

Diagnostics bundles, crash bundles, watchdog bundles, and runtime snapshots
must describe the same queue/runner/artifact truth for both image and video
workloads.

When production runs through the local child runtime host, diagnostics must
also distinguish GUI-client transport state from host-owned runtime state,
including protocol/version, host pid, startup or disconnect errors, and
managed-runtime snapshots.

10. Migration Boundary

The current repo may still contain migration seams. They are debt, not canon.

Examples of tracked debt:

- archive `PipelineConfig` imports
- `legacy_njr_adapter`
- `DIRECT`-labeled request and test paths
- large controller ownership surfaces
- compatibility-only tests that still define old behavior

The only sanctioned compatibility bridge for old persisted data is one-time
migration tooling with backup, dry-run, validation, and rollback guidance.

Live runtime compatibility branches are not the end-state.

11. Controller And Service Ownership

11.1 AppController

AppController owns application composition, UI binding, and high-level
orchestration. It must not remain the long-term owner of legacy config
assembly, direct execution semantics, or archive DTO bridging.

11.2 PipelineController

PipelineController owns preview/build/submit coordination. It must not remain a
long-term bridge for archive config DTOs or mixed execution paths.

11.3 Queue/execution services

`JobService`, job execution control, queue persistence, replay, and history
services own lifecycle behavior and canonical runtime data exchange.

11.4 Video services

Video backend registry, workflow registry/compiler, runtime adapters, and
dependency probes belong under `src/video/`.

Controller decomposition must follow this ownership map, not ad hoc file
splitting.

12. Forbidden Patterns And Architecture Enforcement

Forbidden patterns:

- fresh execution outside queue
- live `DIRECT` runtime path
- live `pipeline_config` execution
- archive DTO imports as long-term runtime dependencies
- GUI or controllers importing backend internals
- GUI invoking runner entrypoints directly
- second video job model parallel to NJR
- backend-owned history or artifact contracts
- controller-local replay shortcuts
- duplicate active architecture documents

Architecture enforcement tests must tighten over time until the remaining
migration seams reach zero.

13. Summary

StableNew is the orchestrator.

NJR is the only outer executable job contract.

Queue is the only fresh submission path.

Runner is the only production execution path.

Backends execute only.

Artifacts, history, learning, replay, and diagnostics all consume the same
canonical runtime truth.
