# Secondary Motion Executable Roadmap v2.6

Status: Active planning document
Updated: 2026-03-20

## Purpose

Turn the secondary motion design memo into an executable PR series that can be
handed to an implementation agent without inventing a new stage type, widening
GUI scope, or leaking backend behavior outside `src/video/`.

This roadmap assumes `PR-HARDEN-224` through `PR-HARDEN-229` are complete
before execution begins. The individual PR specs under `docs/PR_Backlog/` are
the execution handoff artifacts.

## Current Repo Truth

StableNew already has the core seams this tranche needs:

- `PipelineRunner._execute_video_stage(...)` builds a `VideoExecutionRequest`
  and dispatches to `VideoBackendRegistry` for the existing video stages
  `animatediff`, `svd_native`, and `video_workflow`.
- `VideoExecutionRequest` already carries `prompt`, `negative_prompt`,
  `motion_profile`, `workflow_id`, `backend_options`, and `context_metadata`.
- `src/video/svd_postprocess.py` and `src/video/svd_postprocess_worker.py`
  already provide a structured postprocess pipeline for SVD.
- `src/pipeline/executor.py` already writes AnimateDiff frames to disk before
  MP4 assembly.
- `src/video/workflow_compiler.py` and `src/video/workflow_catalog.py` already
  support StableNew-owned bindings from request fields, including nested
  `context_metadata.*`, into managed workflow payloads.
- `src/video/container_metadata.py` already embeds compact StableNew-owned
  video metadata and is the right place for a small motion summary.

StableNew does not yet have the secondary motion layer itself:

- no canonical `intent_config["secondary_motion"]` contract
- no StableNew-owned `src/video/motion/` subsystem
- no runner-owned motion policy carrier distinct from the existing
  `motion_profile`
- no shared deterministic motion engine reused by SVD, AnimateDiff, and
  workflow-video paths
- no canonical replay, container-metadata, or learning provenance for motion
  decisions and outcomes

## Critical Appraisal of the Design Memo

The design memo identified the correct subsystem seam, but its first-pass plan
was still too broad to execute directly.

### Weakness 1: It did not cleanly separate `motion_profile` from secondary motion

The repo already uses `motion_profile` as a stage-facing video control. The
memo introduced a new secondary-motion concept without first freezing a separate
outer contract, which would blur existing workflow semantics and replay meaning.

Incorporated correction:

- the improved plan adds one canonical nested
  `intent_config["secondary_motion"]` payload
- `motion_profile` keeps its current meaning as a backend/stage-facing control
- the runner derives a separate motion policy instead of overloading
  `motion_profile`

### Weakness 2: It risked treating secondary motion like a new canonical stage

StableNew already has the correct video seam: policy belongs inside the
existing video-stage execution path, not as a fourth video backend stage with
its own ordering rules.

Incorporated correction:

- no new stage type is introduced
- no canonical stage-order changes are allowed
- motion planning and application are layered onto existing `animatediff`,
  `svd_native`, and `video_workflow` stages

### Weakness 3: It made workflow-native Comfy work and GUI work too early

The memo mixed shared postprocess work, workflow-native Comfy branching, and UI
exposure in the same early phase. That would freeze unstable semantics across
the highest-risk surfaces before the core engine and provenance contract were
stable.

Incorporated correction:

- the improved plan lands the shared deterministic engine before any backend
  wiring
- workflow-video parity lands before any workflow-native Comfy node dependency
- GUI exposure is explicitly deferred outside the runtime tranche

### Weakness 4: It under-specified replay, manifest, and metadata carriers

The memo described replayability and learning, but it did not define one
canonical motion carrier across runner metadata, manifests, replay fragments,
container metadata, and learning summaries.

Incorporated correction:

- the series freezes one canonical `secondary_motion` carrier shape first
- manifests remain the detailed truth
- container metadata carries only a compact summary
- replay fragments and learning records reuse the same summary keys instead of
  inventing parallel payloads

### Weakness 5: It combined deterministic postprocess and prompt/native bias ideas

Prompt-only illusion, latent/native bias, and deterministic postprocess have
different determinism, testing, and rollback characteristics. Treating them as
one implementation lane would make the first tranche too risky.

Incorporated correction:

- the first executable tranche is deterministic shared postprocess only
- prompt bias and workflow-native/native-backend motion remain follow-on work
- rollout modes are explicit: `disabled`, `observe`, `apply`

## Improved Execution Strategy

The series follows eight execution rules.

1. Freeze one nested `secondary_motion` intent contract before any output
   changes.
2. Keep secondary motion inside the existing video-stage path; do not add a new
   stage type.
3. Separate runner-owned policy planning from backend-owned motion application.
4. Reuse adaptive refinement prompt/subject analysis when present, but require a
   null-safe fallback when it is absent.
5. Keep `motion_profile` and `secondary_motion` semantically distinct.
6. Land one shared deterministic engine before wiring SVD, AnimateDiff, or
   workflow-video application paths.
7. Persist one compact motion summary across result metadata, replay fragments,
   manifests, container metadata, and learning records.
8. Make the feature skip-safe: unsupported backends or missing local
   prerequisites record an explicit skip reason instead of silently disappearing
   or killing the job.

## PR Sequence Overview

| PR | Title | Core outcome | Depends on |
| ---- | ----- | ------------ | ---------- |
| `PR-VIDEO-236` | Secondary Motion Intent Contract and Observation-Only Policy Carrier | Canonical `intent_config["secondary_motion"]`, pure policy planning, builder persistence, runner observation metadata | `PR-HARDEN-224` through `PR-HARDEN-229` |
| `PR-VIDEO-237` | Shared Secondary Motion Engine and Provenance Contract | StableNew-owned deterministic engine, worker contract, compact provenance helpers, replay/container summary contract | `PR-VIDEO-236` |
| `PR-VIDEO-238` | SVD Native Secondary Motion Postprocess Integration | First real runtime application path, injected as SVD postprocess stage zero with canonical provenance | `PR-VIDEO-237` |
| `PR-VIDEO-239` | AnimateDiff Secondary Motion Frame Pipeline Integration | Shared engine inserted between frame write and encode, with skip-safe provenance | `PR-VIDEO-238` |
| `PR-VIDEO-240` | Workflow Video Secondary Motion Parity and Replay Closure | Workflow-video extract/apply/re-encode parity path, canonical replay closure, no new Comfy node dependency | `PR-VIDEO-239` |
| `PR-VIDEO-241` | Learning and Risk-Aware Secondary Motion Feedback | Scalar motion metrics in learning records and recommendation stratification by backend/application path | `PR-VIDEO-240` |

## Higher-Order Effects and Incorporated Mitigations

### Second-Order Effects

Secondary motion adds real frame-processing cost, temporary disk churn, and
more metadata per video artifact.

Incorporated correction:

- the shared engine lands before backend wiring so performance and payload shape
  are measured once
- manifests hold detailed runtime facts while container metadata stays compact
- skip-safe reason codes distinguish `disabled`, `not_applicable`, and
  `unavailable` states

### Third-Order Effects

Once the feature spans three backends, parity and comparability become a
product problem, not just a code problem.

Incorporated correction:

- the plan records `backend_id`, `application_path`, `policy_id`, and skip
  reasons in one canonical summary
- workflow-video parity uses the same summary shape as SVD and AnimateDiff
- learning stratifies by backend and application path instead of pretending the
  same policy always means the same runtime behavior

### Fourth-Order Effects

Future workflow-native Comfy nodes, prompt bias, or latent motion controls
could drift away from the shared engine and make the recommendation system
learn incomparable semantics.

Incorporated correction:

- this tranche freezes around `shared_postprocess_v1`
- workflow-native and prompt/native bias paths are explicitly deferred
- GUI exposure waits until the shared carrier and parity semantics are stable

## Top Risks After Revision

### Risk 1: Provenance forks across runner metadata, manifests, and learning

Incorporated mitigation:

- `PR-VIDEO-237` lands shared provenance helpers before any backend applies the
  feature
- all later backend PRs must use those helpers rather than hand-building motion
  payloads

### Risk 2: Semantic confusion between `motion_profile` and `secondary_motion`

Incorporated mitigation:

- `PR-VIDEO-236` freezes a separate outer contract and schema doc
- later manifests and diagnostics must preserve both values explicitly when
  both are present

### Risk 3: Backend parity drift and false equivalence

Incorporated mitigation:

- SVD, AnimateDiff, and workflow-video are landed in separate PRs
- each PR must record `application_path` so replay and learning know whether
  the shared engine ran in-memory, on a frame directory, or via
  extract/re-encode

### Risk 4: Local-runtime brittleness from optional tools

Incorporated mitigation:

- the shared engine must have a deterministic baseline path without new hard
  computer-vision dependencies
- workflow-video parity may use FFmpeg because FFmpeg is already part of the
  existing video/export story, but missing tools must downgrade to recorded
  skip reasons

### Risk 5: Metadata bloat and history/replay degradation

Incorporated mitigation:

- manifests remain the detailed truth
- container metadata stores only a bounded summary
- learning records store scalar metrics and ids only, never raw frames, masks,
  or dense motion fields

## Phase Gates

### Gate A: Contract Freeze

Applies after `PR-VIDEO-236`.

Required before continuing:

- `secondary_motion` survives canonicalization, builder flows, and NJR snapshots
- no new stage types or stage-order changes have landed
- `secondary_motion` is distinct from `motion_profile`
- the runner can emit observation-only motion planning metadata without backend
  behavior change

### Gate B: Engine and Provenance Freeze

Applies after `PR-VIDEO-237`.

Required before continuing:

- the shared engine is deterministic for a fixed seed and policy
- the shared motion summary shape is frozen for manifests, replay fragments,
  container metadata, and learning
- the engine can report `applied`, `skipped`, and `not_applicable` outcomes
  without backend-specific payload forks

### Gate C: Backend Rollout Stability

Applies after `PR-VIDEO-238`, `PR-VIDEO-239`, and `PR-VIDEO-240`.

Required before continuing:

- SVD, AnimateDiff, and workflow-video all use the shared carrier shape
- each backend records `application_path` and skip reasons consistently
- workflow-video parity does not require a new custom Comfy node or leak
  workflow internals outside `src/video/`

### Gate D: Learning Stability

Applies after `PR-VIDEO-241`.

Required before closing the tranche:

- learning records store only scalar motion metrics and policy/application ids
- recommendation logic stratifies by backend/application path
- no binary frame data or dense motion fields are persisted into centralized
  learning storage

## Roadmap Outcome Definition

This tranche is complete when:

- a video job can opt into secondary motion through canonical `intent_config`
  metadata without creating a new job model
- the runner can build a per-stage motion policy for the existing video stages
- SVD, AnimateDiff, and workflow-video can either apply or explicitly skip the
  shared deterministic motion layer with canonical provenance
- manifests, replay fragments, container metadata, and learning records
  preserve a stable motion summary without schema forks
- adaptive refinement outputs improve policy quality when available, but are
  not a hard prerequisite for baseline execution

## Follow-On Work Outside This Series

These items are intentionally deferred so the runtime tranche stays bounded:

- workflow-native Comfy/LTX node integration
- prompt-bias or latent/native-bias motion paths for AnimateDiff or workflow
  backends
- GUI exposure across video surfaces
- richer pose, segmentation, or optical-flow-assisted detectors beyond the
  baseline shared-engine path

Those follow-ons should be planned only after `PR-VIDEO-241` is complete and
the shared motion carrier is stable.
