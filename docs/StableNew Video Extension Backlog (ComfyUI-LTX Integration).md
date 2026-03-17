StableNew Video Extension Backlog (ComfyUI - LTX Integration)
Purpose

This document defines the post-stability video extension roadmap for StableNew, specifically:

introducing ComfyUI as a targeted video backend

enabling anchor-based multi-frame workflows (LTX)

supporting longer-form, sequence-based video generation

preserving StableNew’s PromptPack → NJR → Contract → Backend → Artifact architecture

This is a sidecar extension plan, not a platform migration.

Core Principles (MUST NOT VIOLATE)
1. StableNew remains the orchestrator

StableNew owns:

PromptPack

NJR / normalized job contract

validation / builder logic

artifact + history + replay

UI / user-facing semantics

Backends (A1111, SVD, AnimateDiff, Comfy) are execution targets only.

2. Workflow JSON is NOT a contract

Comfy workflows:

are implementation details

must be wrapped in WorkflowSpec

must be accessed only via backend adapter + compiler

No direct workflow mutation from UI, controller, or pipeline layers.

3. NJR / VideoJob is the source of truth

All execution paths must flow through:

PromptPack → NJR → VideoExecutionRequest → BackendAdapter

Never:

UI → Comfy workflow → execution
4. Backend isolation is enforced

UI cannot import backend internals

Controller cannot branch on backend-specific logic

Backend adapters must be the only integration boundary

5. Determinism and replayability are first-class

Every video execution must:

produce a replayable manifest

include backend + workflow metadata

support deterministic reprocess (where possible)

Execution Order

These PRs MUST be executed in order.

Do not skip or reorder without explicit architectural review.

PR-VIDEO-078
Canonical Video Backend Contract
BLUF

Introduce a StableNew-owned video backend abstraction layer.

Goal

All video execution (SVD, AnimateDiff, Comfy) must conform to a single contract.

Scope

Define VideoJobRecord (or extension of NJR)

Define VideoExecutionRequest

Define VideoExecutionResult

Define VideoBackendInterface

Add backend registry + selection logic

Success Criteria

Multiple backends can be registered

No backend-specific logic leaks outside adapter layer

Existing SVD/AnimateDiff paths can conform (or be migrated)

Guardrails

Do NOT over-generalize into full “media engine”

Keep scope strictly video

PR-VIDEO-079
Workflow Registry + Specification Model
BLUF

Create a StableNew workflow registry system to manage Comfy workflows safely.

Goal

Prevent workflow JSON from becoming uncontrolled architecture.

Scope

Define WorkflowSpec

Define WorkflowRegistry

Add:

input binding spec

output binding spec

dependency requirements

capability tags

Example Capability Tags
single_image_to_video
multi_frame_anchor_video
pose_guided_video
segment_stitchable
Success Criteria

Workflow lookup by ID

Dependency validation possible

Duplicate workflow IDs rejected

Guardrails

No direct Comfy JSON execution yet

No UI coupling to workflow schema

PR-VIDEO-080
Comfy Backend Adapter (Foundation)
BLUF

Introduce Comfy as a video backend via adapter, not as a platform.

Goal

Establish stable execution path:

StableNew → Adapter → Comfy API → Result → StableNew
Scope

Comfy API client

Backend registration

Health checks

Execution submission + polling

Output retrieval + normalization

Error handling

Success Criteria

Adapter passes contract tests

Backend health can be checked

Results map cleanly into StableNew artifacts

Guardrails

No UI exposure yet

No complex workflow logic yet

Adapter-only PR

PR-VIDEO-081
Workflow Compiler / Binding Layer
BLUF

Map StableNew video jobs into workflow inputs deterministically.

Goal

Translate:

VideoExecutionRequest → WorkflowSpec → CompiledWorkflowRequest
Scope

Workflow compiler

Input binding engine

Validation of required inputs (e.g. anchors)

Output mapping definitions

Success Criteria

Deterministic mapping from job → workflow

Failure when required inputs missing

No direct workflow mutation outside compiler

Guardrails

No “magic mapping”

No implicit defaults without validation

PR-VIDEO-082
LTX Multi-Frame Anchor Workflow Integration
BLUF

Integrate first real Comfy value-add: multi-frame anchor video generation.

Goal

Enable anchor-based motion:

start frame

optional mid frames

end frame

Scope

Register ltx_multiframe_anchor_v1

Bind anchor frames into workflow

Validate dependencies

Collect outputs into StableNew artifacts

Success Criteria

User can generate video from multiple anchor images

Workflow dependency issues clearly surfaced

Artifacts fully tracked in history

Guardrails

Only ONE pinned workflow in this PR

No multi-workflow explosion

PR-VIDEO-083
UI + Config Binding for Anchor-Based Video
BLUF

Expose StableNew-native UI for anchor workflows (not Comfy UI).

Goal

Users interact with:

source image
anchor frames
backend selection
workflow preset
motion profile

NOT:

nodes
graph edges
workflow JSON
Scope

UI controls for anchor selection

Backend/workflow selector

Validation messaging

Config persistence

Success Criteria

No Comfy concepts exposed directly

UI binds only to StableNew contracts

Guardrails

UI must not import workflow internals

No direct graph manipulation

PR-VIDEO-084
Segment Orchestration (Longer Clips)
BLUF

Enable multi-segment video generation for longer outputs.

Goal

StableNew owns:

segment planning

carry-forward logic

seed strategy

sequence manifest

Scope

VideoSequenceJob

segment plan model

carry-forward policies:

last frame

anchor carry-forward

seed strategies

sequence runner

Success Criteria

Multi-segment videos can be generated deterministically

Sequence manifest tracks all segments

Guardrails

Keep deterministic first

No “smart continuity correction” yet

PR-VIDEO-085
Stitching, Overlap, and Interpolation
BLUF

Smooth transitions between segments.

Goal

Introduce:

overlap handling

seam blending

interpolation stage

Scope

stitch planner

seam policy

interpolation interface (pluggable)

artifact routing:

raw segments

stitched output

interpolated output

Success Criteria

Seam transitions improve visual continuity

Outputs are tracked distinctly

Guardrails

Do NOT hardwire a specific interpolation tool

Keep pluggable

PR-VIDEO-086
Replay, Diagnostics, and Dependency Health
BLUF

Make Comfy workflows operationally reliable.

Goal

Replayable executions

Dependency validation

Strong diagnostics

Scope

workflow replay descriptor

dependency checks

node/model validation

improved error surfaces

manifest enrichment

Success Criteria

Failed workflows provide actionable diagnostics

Replay reproduces behavior

Guardrails

No silent failures

No hidden dependency assumptions

PR-VIDEO-087
Continuity Pack Foundation
BLUF

Introduce reusable character + scene consistency containers.

Goal

Support:

character identity

wardrobe consistency

scene continuity

reference image sets

Scope

ContinuityPack

reference pack models

linkage to video jobs

basic UI/config support

Success Criteria

Packs can be attached to jobs

Packs persist across sequences

Guardrails

Do NOT attempt full intelligence yet

Data model first

PR-VIDEO-088
Story / Shot Planning Foundation
BLUF

Add planning layer for long-form generation.

Goal

Represent:

Story → Scene → Shot → Sequence → Video
Scope

StoryPlan

ScenePlan

ShotPlan

mapping from shot → sequence jobs

anchor planning

Success Criteria

Manual shot planning works

Plans map to executable jobs

Guardrails

No auto-planning yet

Deterministic structure first

Global Execution Gates (ALL PRs)

Every PR must pass:

pytest (targeted subsystems)
pytest --collect-only -q
import/compile sanity
grep invariants for architecture boundaries
docs updated if architecture changes

Additional video-specific gates:

backend contract tests remain green
artifact/manifest schema validation passes
no UI/controller direct backend coupling
workflow registry validation passes
Final Guidance to Codex Agent
Do NOT:

introduce backend-specific logic outside adapters

treat workflow JSON as source of truth

bypass NJR or VideoJob contracts

couple UI directly to workflow structure

expand scope across multiple backends in one PR

ALWAYS:

preserve StableNew contract boundaries

prefer explicit over implicit mapping

validate inputs before execution

produce replayable outputs

keep changes minimal and atomic per PR

Strategic Intent

This sequence is designed to:

add ComfyUI only where it provides clear value

preserve A1111 + existing image pipeline

unlock anchor-based motion and longer sequences

build toward story-consistent animation capability

without destabilizing the system.

If you follow this sequence and the guardrails strictly, StableNew will evolve into a multi-backend, contract-driven media generation system rather than fragmenting into tool-specific pipelines.