#CANONICAL
ARCHITECTURE_v2.6.md
StableNew – Canonical Software Architecture (Updated for PromptPack-Only Model)

Version: 2.6
Status: Canonical
Last Updated: 2025-12-08
Supersedes: ARCHITECTURE_v2.5.md

0. Overview

StableNew is structured into clear, decoupled subsystems:

GUI V2 → Controllers → Builder Pipeline (PR-CORE-B) → JobService → Queue → Runner → Executor
                                  ↘ Learning
                                  ↘ Debug Hub
                                  ↘ History


The system is governed by PromptPack-Only execution:

All pipeline jobs MUST originate from a saved Prompt Pack.
No free-text prompts are allowed in the Pipeline Tab.
All jobs must be fully normalized before entering the Queue or Runner.

This architecture ensures:

Deterministic, reproducible image generation

Stable testing and debugging

Clean subsystem boundaries

Reliable Queue/Runner execution

Meaningful Learning records

GUI consistency and simplicity

1. High-Level System Diagram
 ┌────────────┐     ┌──────────────────┐     ┌─────────────────────┐
 │  GUI V2    │ --> │   Controllers    │ --> │  Builder Pipeline    │
 │            │     │ (App + Pipeline) │     │ (CORE-B components)  │
 └─────┬──────┘     └─────────┬────────┘     └──────────┬──────────┘
       │                        │                         │
       │ UnifiedJobSummary      │ NormalizedJobRecord     │
       ▼                        ▼                         ▼
 ┌──────────────┐       ┌─────────────────┐       ┌───────────────────┐
 │ Preview Pane │       │   JobService    │ ----> │      Queue        │
 └──────────────┘       └──────┬──────────┘       └─────────┬─────────┘
                                │                            │
                                ▼                            ▼
                         ┌─────────────┐            ┌────────────────────┐
                         │ RunnerDriver│ ---------> │    Executor         │
                         └──────┬──────┘            └─────────┬──────────┘
                                │                             │
                                ▼                             ▼
                     ┌────────────────┐                ┌────────────────┐
                     │   History      │                │   Learning     │
                     └────────────────┘                └────────────────┘
                                         ▲
                                         │
                                  ┌──────────────┐
                                  │   Debug Hub  │
                                  └──────────────┘

2. Canonical Invariants

These invariants govern the entire system:

2.1 PromptPack-Only Execution (MANDATORY)

All pipeline jobs must reference:

prompt_pack_id

prompt_pack_row_index

GUI cannot accept or store free-text prompts.

Prompt Packs are parsed and resolved only by the Builder Pipeline.

No job may enter JobService without full normalization.

2.2 Controllers Are the Single Source of Truth

Controllers govern:

App state transitions

PromptPack selection

Config snapshot selection

RunMode decisions

Submission of fully normalized jobs to JobService

Controllers never:

modify prompts

construct payloads for Executor

re-interpret stage configs

2.3 Builder Pipeline Produces Final Job Records

The builder (PR-CORE-B) is the only subsystem allowed to:

Merge configs

Resolve prompts

Select matrix variants

Compute seeds

Build StageChain

Construct NormalizedJobRecord objects

Queue/Runner must not perform builder logic.

2.4 Queue & Runner Consume NormalizedJobRecords Only

Queue/Runner treat jobs as:

Immutable

Fully resolved

Complete execution specifications

They never:

build configs

derive prompts

resolve LoRAs

synthesize negative prompts

modify jobs

2.5 GUI Must Be Purely Declarative

GUI:

Reads data

Displays summaries

Invokes controllers via explicit events

GUI must not:

resolve prompts

merge configs

modify job objects

build any part of a job request

3. Subsystem Descriptions
3.1 GUI V2

GUI is strictly a view layer.

3.1.1 Pipeline Tab

Displays:

PromptPack selector

Config snapshot selector

UnifiedJobSummary preview

Cannot:

Accept free-text prompts

Construct job objects

3.1.2 Queue Panel

Displays:

Jobs in SUBMITTED/QUEUED/RUNNING states

Derived from UnifiedJobSummary + lifecycle events

3.1.3 Running Job View

Displays:

Active job’s UnifiedJobSummary

Stage progress

Current image previews

3.1.4 History Panel

Displays:

Completed jobs

Canonical history entries based on NormalizedJobRecord

3.1.5 Debug Hub

Displays:

Structured lifecycle events

“Explain Job” using job summaries and records

3.2 Controllers

Controllers enforce system rules:

Validate UI input

Enforce PromptPack-only constraint

Request job construction from builder

Call JobService to enqueue jobs

Push summaries and state changes back to GUI

Controllers do not:

Build job records

Modify NormalizedJobRecord fields

Handle runner logic

3.3 Builder Pipeline (PR-CORE-B)

The builder pipeline consists of:

PresetConfig + PackConfig + RuntimeOverrides
    ↓
ConfigMergerV2
    ↓
RandomizationPlanV2
    ↓
RandomizerEngineV2 → VariantConfig
    ↓
PromptPack TXT Row
    ↓
UnifiedPromptResolver
    ↓
UnifiedConfigResolver
    ↓
JobBuilderV2
    ↓
list[NormalizedJobRecord]

PromptPackNormalizedJobBuilder orchestrates this chain inside PipelineController: it loads the pack config/rows, feeds them through the resolvers, applies randomization metadata, and hands deterministic variants to JobBuilderV2 so each NormalizedJobRecord carries prompt_pack provenance, embeddings/LoRAs, matrix slot selections, stage chain details, and aesthetic metadata before JobService persists or queues it.


Each NormalizedJobRecord is:

Complete

Deterministic

Immutable

Ready for queue

This pipeline is pure and testable.

3.4 JobService & Queue

JobService:

Accepts lists of NormalizedJobRecord

Validates them

Emits SUBMITTED/QUEUED events

Queue:

FIFO storage

Holds immutable records

Does not mutate jobs

3.5 Runner & Executor

RunnerDriver:

Pulls jobs from queue

Sends requests to Executor

Produces output metadata

Emits RUNNING → COMPLETED/FAILED events

Writes history entries

Executor:

Talks to Stable Diffusion WebUI / API

Produces images

No architectural authority

3.6 History System

History stores:

Immutable job record (full schema)

Output paths

Start/stop timestamps

Failure messages

Supports:

Learning tab consumption

Re-run pipelines

Debugging workflows

3.7 Learning System

Consumes:

Full NormalizedJobRecord

User ratings

Derived learning features

Learning depends critically on PromptPack provenance and matrix metadata.

3.8 Debug Hub

Receives:

Lifecycle events

Canonical job summaries

Error/failure events

Payload constructions (debug mode only)

Supports:

Explain Job

Job reconstruction

Sequence diagrams

4. Key Data Models
4.1 UnifiedJobSummary (GUI-facing)

Contains:

prompt_pack_id & name

prompt preview

negative preview

stage chain preview

seed, sampler, model

matrix slot summary

variant_index, batch_index

status

Summaries are read-only and derived.

4.2 NormalizedJobRecord (Queue/Runner-facing)

Full job spec including:

PromptPack provenance

Fully resolved positive/negative prompts

Embedding tags

LoRA tags

Matrix slot values

StageChain with stage configs

Sampler, scheduler, cfg, steps

Seed, resolution

Loop semantics

Variant & batch indices

randomization metadata

run_mode, queue_source

This is the canonical execution contract.

5. Core Architectural Flows
5.1 Pipeline Job Construction Flow
GUI selects Prompt Pack + Config Snapshot
    ↓
Controller requests builder
    ↓
Builder returns list[NormalizedJobRecord]
    ↓
Controller sends to JobService
    ↓
Queue stores records
    ↓
Runner executes

5.2 Lifecycle Event Flow
JobService SUBMITTED → GUI Queue Panel
JobQueue QUEUED → GUI Queue Panel
Runner RUNNING → GUI Running Panel + Debug Hub
Runner COMPLETED / FAILED → GUI History Panel + Debug Hub

5.3 Re-run Flow

History → Controller → Builder → New jobs

GUI cannot modify old jobs.

6. Error Handling & Validation

Missing PromptPack → hard error

Missing required config → hard error

Empty prompt after resolution → error

Invalid stage configs → error

Queue never accepts incomplete jobs

Runner catches failures and reports via Debug Hub

7. Testing Guidance

Testing must verify:

Determinism of builder pipeline

Reproducibility of job records

Lifecycle correctness

GUI receives correct UnifiedJobSummary objects

All flows functional under PromptPack-only constraint

8. Appendix A — Diagrams
8.1 Builder Pipeline Expanded
Preset     Pack JSON     Overrides
   \         |              /
    \        |             /
     └── ConfigMergerV2 ──┘
               ↓
      RandomizationPlanV2
               ↓
      RandomizerEngineV2
               ↓
  PromptPack TXT Rows (N)
           × Variants (V)
           × Batches (B)
               ↓
      UnifiedPromptResolver
               ↓
      UnifiedConfigResolver
               ↓
      JobBuilderV2
               ↓
 list[NormalizedJobRecord]

9. Appendix B — Forbidden Couplings

The following are strictly forbidden:

GUI constructing job objects

Runner modifying job records

Queue invoking resolver logic

Controller reconstructing prompts

Learning modifying history records

Any subsystem generating prompts outside builder

10. Versioning & Governance

This file supersedes all previous architectural definitions.

Future changes must:

Pass through governance review

Update this canonical document

Update tests and PR templates accordingly

END — ARCHITECTURE_v2.6.md
