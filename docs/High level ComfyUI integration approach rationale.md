High level ComfyUI integration approach rationale.md
3/16/2026

Not “make ComfyUI the platform.”

Instead, the appended tranche should do this in order:

formalize backend-agnostic video execution

add a workflow/template registry concept

add a Comfy video adapter

integrate one pinned LTX multi-frame workflow

expose anchor-based video generation through StableNew contracts

add continuity-oriented segment orchestration

add replay/diagnostics hardening for the Comfy path

That sequence preserves StableNew’s core identity:
StableNew remains the orchestrator; Comfy is just one execution backend for the workflows where it adds value.

Recommended appended PR sequence

Below is the in-depth appended backlog, starting after your current actual end:

PR-EDIT-077

So these begin at:

PR-VIDEO-078

and continue forward

PR-VIDEO-078
Title

Introduce canonical video backend contract and backend selection model

BLUF

Before adding Comfy-specific workflow execution, StableNew needs a StableNew-owned video backend abstraction so SVD, AnimateDiff, and future Comfy/LTX execution paths all conform to one contract.

Why this PR exists

Even if PR-VIDEO-074 and PR-VIDEO-075 land, those earlier video PRs are likely to be somewhat implementation-first. Before adding Comfy, you want to explicitly harden the idea that:

video jobs are first-class StableNew jobs

video outputs are first-class StableNew artifacts

execution backend is a pluggable implementation detail

workflow JSON is not the source of truth

This PR is the main “architectural firewall” that prevents Comfy integration from spreading graph-runtime assumptions all over the repo.

Scope

define a canonical video job execution contract

define a VideoBackendInterface or equivalent abstraction

define backend capability metadata

define backend selection rules

formalize how video jobs are represented after builder/normalization and before execution

unify common execution result structure across existing video backends

Expected conceptual outputs

VideoJobRecord or extension of current job contract for video

VideoBackendInterface

VideoExecutionRequest

VideoExecutionResult

VideoBackendCapabilities

backend registry / selector

What it should standardize

A video backend should receive something stable like:

source image(s)

prompt / negative prompt if applicable

motion controls

anchor frames if applicable

backend config

output routing directives

replay metadata hooks

and return:

primary video artifact

optional frame sequence

optional preview artifact

execution metadata

backend-native diagnostic payload

replayable manifest fragment

Dependencies

Assumes prior backlog landed:

artifact contract work

reprocess subsystem

SVD Phase 1

AnimateDiff Phase 1

Execution gates

targeted tests for video contracts and backend registry

collect-only green

architecture invariant: UI and controller layers cannot directly invoke backend-native workflow internals

docs updated for video backend abstraction

Caveats

Do not over-generalize into a mega “all media backend interface.” Keep this sharply focused on the video path.

PR-VIDEO-079
Title

Add workflow template registry and pinned workflow specification model

BLUF

StableNew needs a workflow registry layer before any serious Comfy integration so that pinned, known-good workflow templates can be managed as StableNew resources rather than ad hoc JSON blobs.

Why this PR exists

ComfyUI is graph-first. StableNew is contract-first.

The workflow registry is the bridge.

Without this layer, the repo will drift into:

random workflow JSON files

hidden custom-node assumptions

unclear input/output mapping

workflow version chaos

This PR creates a StableNew-owned representation of:

workflow identity

required backend

required nodes/models

input mapping contract

output mapping contract

compatibility metadata

pinned version expectations

Scope

define workflow specification model

define workflow registry API

support static registration of workflow templates/specs

define template metadata for Comfy workflows

define input/output mapping descriptors

define capability tagging, such as:

single_image_to_video

multi_frame_anchor_video

pose_guided_video

segment_stitchable

Expected conceptual outputs

WorkflowSpec

WorkflowRegistry

WorkflowInputBindingSpec

WorkflowOutputBindingSpec

WorkflowDependencySpec

compatibility / health-check metadata

What it should enable later

By the time you get to LTX integration, StableNew should be able to say:

choose workflow ltx_multiframe_anchor_v1

validate required nodes

validate required models

compile inputs into that workflow

parse outputs back into StableNew artifacts

Execution gates

tests for registry lookup and spec validation

tests for duplicate workflow ID rejection

tests for required dependency declarations

collect-only green

Caveats

Do not put actual large workflow JSON authoring logic here yet. This PR should define the registry/spec structure first.

PR-VIDEO-080
Title

Implement Comfy video adapter foundation and API-safe execution path

BLUF

Add the first StableNew → Comfy execution adapter, but keep it narrow: API-safe execution, health checks, workflow submission, polling, output collection, and normalized error handling.

Why this PR exists

This is the first PR where Comfy becomes an actual backend, but still only as an implementation target behind the new video backend contract.

This should not yet attempt full LTX authoring complexity. It should establish:

how StableNew talks to Comfy

how workflow execution is submitted

how results are collected

how failures are surfaced cleanly

how backend diagnostics are recorded

Scope

Comfy server client

health check / availability probe

backend registration into video backend registry

API-safe execution foundation

workflow submission and execution polling

output collection and normalization

diagnostics capture

backend-specific error handling

What this PR should explicitly avoid

massive UI exposure

multiple workflow families at once

long-form orchestration

replacing A1111 image execution

allowing raw workflow blobs to leak into business logic

Expected conceptual outputs

ComfyVideoBackendAdapter

ComfyApiClient

workflow submission service

polling/result retrieval service

backend-native status normalization

execution logs that map back into StableNew observability

Execution gates

integration tests with mocked or controlled Comfy responses

adapter contract tests against the canonical video backend interface

collect-only green

architecture invariant: only adapter layer may talk to Comfy client directly

Caveats

Keep it backend-only. You are proving the adapter, not the whole product flow yet.

PR-VIDEO-081
Title

Add workflow compilation layer from StableNew video contract to workflow inputs

BLUF

StableNew now needs a compiler/mapper that takes canonical video job inputs and binds them into workflow-template inputs without making workflow JSON the source of truth.

Why this PR exists

The key architectural challenge is not “call Comfy.” It is:
map StableNew job intent into a pinned workflow template deterministically.

This PR adds that mapping layer.

Scope

create workflow compiler / binder

translate canonical video job fields into workflow input mutations

support source image binding

support anchor frame binding

support prompt binding where relevant

support motion parameter binding

support output routing binding

support validation when required inputs are missing

Expected conceptual outputs

WorkflowCompiler

CompiledWorkflowRequest

input-binding engine

validation of required anchor/image slots

normalized workflow parameter injection

Important design rule

The compiler should consume:

VideoExecutionRequest

WorkflowSpec

and produce:

CompiledWorkflowRequest

not:

random Comfy graph edits from UI code

Execution gates

unit tests for workflow compilation

tests for missing required input failure

tests for stable mapping from canonical job fields to workflow slots

collect-only green

Caveats

Keep compilation deterministic and explicit. Avoid magical implicit heuristics.

PR-VIDEO-082
Title

Integrate first pinned LTX multi-frame anchor workflow

BLUF

Add the first real value-add Comfy workflow: a pinned LTX multi-frame anchor workflow integrated through the backend adapter and workflow registry.

Why this PR exists

This is the first PR that gives you the thing you actually want:

anchor-based controlled video generation

more structured motion than plain SVD

a real reason to use ComfyUI without replatforming StableNew

Scope

register first pinned LTX multi-frame workflow spec

support source/start/end/mid anchor frames as applicable

validate required node/model availability

bind job inputs into that workflow

collect resulting video/frame artifacts

capture backend-native execution metadata

add clear failure messages when dependencies are not installed

Functional target

User should be able to do something like:

choose a set of anchor images

choose LTX multi-frame mode

run through StableNew

get a video result plus proper manifest/history metadata

Expected conceptual outputs

ltx_multiframe_anchor_v1 workflow spec

backend capability mapping

anchor slot validation

artifact import back into StableNew history/output model

Execution gates

targeted LTX integration tests

dependency/health-check tests

collect-only green

docs update for first Comfy/LTX video workflow

Caveats

Keep this to one pinned workflow first. Resist the urge to add multiple advanced variants in one PR.

PR-VIDEO-083
Title

Expose anchor-based video job configuration and UI binding for Comfy/LTX path

BLUF

Now that the backend path exists, expose StableNew-owned controls for anchor-based video generation without exposing raw Comfy graph complexity to end users.

Why this PR exists

StableNew users should not have to think in node IDs or graph wiring. They should think in StableNew concepts:

source image

anchor frames

segment length

motion intent

output mode

This PR adds StableNew-level UI/config surfaces for the Comfy/LTX path.

Scope

UI support for selecting anchor frames

config surfaces for multi-frame workflow mode

backend/workflow selection UI

validation messaging

preview of anchor set and expected workflow mode

persistence of recent video settings

Important principle

UI should bind to StableNew contracts, not raw workflow schema.

Expected user-facing concepts

source frame

anchor frame set

interpolation/motion profile

backend selector

workflow preset selector

output options

Execution gates

UI tests / binding tests

collect-only green

invariant: UI does not directly own workflow JSON mutation

Caveats

Do not overfit the UI to one workflow’s internal quirks. Keep it generic enough for future multi-frame backends.

PR-VIDEO-084
Title

Add segment orchestration for longer-form chained video generation

BLUF

Introduce StableNew-controlled segment orchestration so longer clips can be built from multiple video segments while preserving backend independence.

Why this PR exists

This is where you start moving from “single clip” to “sequence generation.”

Since long-form consistency does not come from one short video model alone, StableNew should own the orchestration layer for:

segment planning

carry-forward frame policy

overlap handling

segment seed policy

per-segment metadata

This should remain backend-agnostic where possible.

Scope

segment job model

chain/sequence execution orchestrator

carry-forward policies:

last frame

selected keyframe

anchor carry-forward

overlap metadata

seed strategy handling

sequence-level manifest

backend selection per segment or sequence

Expected conceptual outputs

VideoSequenceJob

VideoSegmentPlan

VideoSequenceRunner

overlap policy

carry-forward policy

sequence artifact manifest

What this enables

longer clips via segment chaining

future continuity-aware reruns

backend mixing in theory, though keep first version simple

Execution gates

sequence planning tests

artifact/manifest tests for segment chains

collect-only green

docs update for chained video generation

Caveats

Do not yet add “smart continuity correction” in this PR. Focus on deterministic segment orchestration first.

PR-VIDEO-085
Title

Add overlap stitching, seam handling, and interpolation integration

BLUF

Longer-form video needs seam smoothing. Add overlap-aware stitching and interpolation as StableNew-owned post-processing stages.

Why this PR exists

Once you have segment orchestration, you need the seam layer:

overlap handling

transition smoothing

interpolation

final assembly

This should not live inside any single backend. It should be a StableNew-owned post-video stage.

Scope

overlap-aware stitcher

seam policy selection

optional interpolation stage integration

artifact routing for:

raw segment outputs

stitched output

interpolated output

sequence manifest enrichment

Expected conceptual outputs

VideoStitchPlan

VideoInterpolatorInterface

seam-handling policy model

stitched_video artifact type

interpolated_video artifact type

Execution gates

tests for sequence artifact routing

tests for stitch plan determinism

collect-only green

Caveats

Keep interpolation pluggable. Do not hardwire your architecture to one interpolation engine.

PR-VIDEO-086
Title

Add replay, diagnostics, and dependency health model for Comfy workflows

BLUF

The Comfy path must become operationally trustworthy: replayable, diagnosable, and dependency-aware.

Why this PR exists

By this point you’ll have a real Comfy/LTX execution path. Now it needs the operational hardening necessary for long-term use:

replayability

dependency checks

diagnostics

backend health visibility

Scope

replay contract for Comfy workflow executions

workflow dependency health checks

node/model availability diagnostics

run manifest enrichment with workflow/version metadata

better failure reporting for misconfigured Comfy environments

observability integration for workflow execution lifecycle

Expected conceptual outputs

workflow replay descriptor

dependency health report

richer backend diagnostics payload

manifest fields for workflow ID, workflow version, dependency state

Execution gates

replay tests

health-check tests

collect-only green

docs update for Comfy/LTX operational support

Caveats

This PR should harden the path, not widen it.

PR-VIDEO-087
Title

Add continuity-pack foundation for character and scene consistency across video sequences

BLUF

Introduce a StableNew-owned continuity-pack concept so longer-form sequences can carry forward structured identity and scene context rather than relying on ad hoc prompt reuse.

Why this PR exists

This is the first real move toward a story-consistent engine.

Long-form continuity requires something above raw prompts and above single workflow runs. StableNew should own reusable continuity context like:

character identity references

wardrobe references

scene/location references

anchor image packs

continuity tags for a sequence

This PR does not solve all continuity, but it creates the right container for it.

Scope

continuity-pack data model

storage/manifest strategy

linkage from sequence jobs to continuity packs

basic UI/config support for selecting/applying packs

artifact integration with reference images

Expected conceptual outputs

ContinuityPack

CharacterReferencePack

SceneReferencePack

continuity-pack attachment to video jobs

Execution gates

tests for continuity-pack serialization

tests for sequence linkage

collect-only green

Caveats

Do not try to make this fully “smart” yet. This is a data-model and contract PR first.

PR-VIDEO-088
Title

Add story/shot planning foundation for long-form video orchestration

BLUF

Create the first StableNew-owned planning layer above segment execution: scenes, shots, and anchor plans.

Why this PR exists

To get beyond clips and toward story-consistent animation, you need a planner layer:

scenes

shots

anchor requirements

duration/segment plans

continuity requirements

This PR introduces the scaffolding for that.

Scope

story/scene/shot data model

shot plan attachment to continuity packs

mapping from shot plan to sequence jobs

initial non-LLM/manual planning flow

manifest linkage between shot plan and generated outputs

Expected conceptual outputs

StoryPlan

ScenePlan

ShotPlan

AnchorPlan

shot-to-sequence compilation

Execution gates

serialization tests

shot compilation tests

collect-only green

docs update for story/shot architecture

Caveats

Keep the first version manual and deterministic. Do not jump straight to autonomous planning logic.

Recommended execution order of the appended tranche

Run them in this order:

PR-VIDEO-078 — canonical video backend contract

PR-VIDEO-079 — workflow registry/spec model

PR-VIDEO-080 — Comfy adapter foundation

PR-VIDEO-081 — workflow compiler/binder

PR-VIDEO-082 — first pinned LTX multi-frame workflow

PR-VIDEO-083 — UI/config binding for anchor-based workflows

PR-VIDEO-084 — segment orchestration

PR-VIDEO-085 — stitching/interpolation

PR-VIDEO-086 — replay/diagnostics/health

PR-VIDEO-087 — continuity-pack foundation

PR-VIDEO-088 — story/shot planning foundation

That order is important.

It goes:

contract

registry

adapter

compiler

first real workflow

user-facing config

longer-form orchestration

seam handling

operational hardening

continuity

higher-level planning

That is the least chaotic and most StableNew-like sequence.

How these appended PRs relate to your earlier backlog

They assume the earlier work is already done and build directly on it.

They especially depend on the success of:

PR-PIPE-062 central validation and normalization

PR-ARCH-064 architecture enforcement

PR-ART-071 artifact/manifest contract

PR-REPROC-072 reprocess subsystem

PR-VIDEO-074 SVD Phase 1

PR-VIDEO-075 AnimateDiff Phase 1

PR-GUI-076 GUI polish

PR-EDIT-077 extension architecture-first groundwork

So this appended tranche is not a detour; it is the natural continuation after repo stabilization.

Suggested standard execution gates for every appended PR

You already have good gates. I would keep the same pattern.

For every PR in 078–088, require:

targeted pytest for touched subsystem(s)

pytest --collect-only -q

compile/import sanity for touched modules

grep/contract invariants for newly introduced architecture boundaries

docs update if architectural truth changed

Additional video/backend-specific gates to add where applicable

backend contract tests remain green for all registered video backends

manifest/replay schemas validate for new artifact types

workflow registry validation passes

no controller/UI direct dependency on backend-native workflow internals

health-check path exists for every new external dependency introduced

My judgment on this appended sequence

This is a good fit for your repo and your preferences because it:

does not renumber existing backlog

does not destabilize the current A1111 platform role

does not make ComfyUI the new system of record

gives you a path from short clips to anchored multi-frame video

gives you a plausible path toward long-form, continuity-aware animation later

Most importantly, it keeps the architecture aligned with your actual StableNew discipline:
PromptPack/NJR/contracts first, backend/runtime second.