ARCHITECTURE_v2.6.md
 (Canonical)

StableNew – Core Architecture Specification (v2.6)
Last Updated: 2025-12-09
Status: Canonical, Binding**

0. Purpose

This document defines the only valid architecture for StableNew’s execution pipeline, UI → backend flows, state ownership, and model boundaries.

v2.6 replaces all earlier architectures and renders all legacy pathways invalid, including:

V1 pipeline paths

GUI prompt-entry–based jobs

Legacy JobBundle-based flows (retired; AppStateV2.job_draft is the canonical draft state, and JobBuilderV2 produces all NJRs)

Legacy StateManager usage

Legacy Job.payload–based execution

pipeline_config–derived jobs

Direct runner invocation from UI/controllers

Any partial migration layers

Every subsystem in StableNew must comply with this document.

1. System Overview

StableNew is composed of five primary layers:

GUI Layer (Tkinter V2)

Controller Layer

Application State (AppStateV2)

Builder Pipeline Layer

Execution Layer (Queue + Runner + Outputs)

Post-Execution Layer (History, Learning, DebugHub)

Only one unified path exists for job creation and execution:

Advanced Prompt Builder →
PromptPack (TXT + JSON) →
Pipeline Tab →
Config + Overrides + Sweeps →
Builder Pipeline →
NormalizedJobRecord[] →
JobService Queue →
Runner →
Outputs + History →
Learning System


There are no exception paths, no alternate flows, and no legacy compatibility routes.

2. PromptPack-Only Input Model
2.1 PromptPack is the sole source of prompt text

All generation begins with a Prompt Pack:

{pack_name}.txt — contains prompt rows

{pack_name}.json — contains metadata:

matrix slots

allowed randomization values

tags, style metadata

default config block (optional)

There are no GUI text fields for prompts, no “manual mode,” no fallback prompt sources.

This invariant is enforced across:

GUI

Controllers

Builder pipeline

Job construction

Testing

Documentation

2.2 Prompt Pack Lifecycle (Summary)

Prompt Packs are created/edited only in the Advanced Prompt Builder.
Pipeline Tab cannot modify packs.

Editing a PromptPack means:

Editing the TXT (prompt rows)

Editing the JSON (matrix / defaults)

Packs are immutable at runtime during job execution.

3. Application State Architecture (AppStateV2)
3.1 AppStateV2 is the only runtime state container

AppStateV2 contains:

Loaded Prompt Packs

Selected PromptPack + selected row index

Pipeline overrides & sweep configurations

Global negative

UI panel state

JobDraft (a description of the pipeline run being assembled)

3.2 Controllers must never store draft state

PipelineController must not contain _draft_bundle

No controller may mutate or own job state

All draft manipulation flows through:

app_state.job_draft

3.3 StateManager and legacy V1 state systems are forbidden

All usage must be removed.

3.4 Controller Event API (PR-CORE1-C4A)

Controllers expose a fixed set of entrypoints that the GUI binds to. AppController now implements `on_run_now`, `on_add_to_queue`, `on_clear_draft`, `on_add_to_job`, and `on_update_preview`; PipelineController exposes `start_pipeline`, `enqueue_draft_jobs`, `build_preview_summary`, `add_packs_to_draft`, `remove_pack_from_draft`, and `clear_draft`. These methods call into AppStateV2 and PipelineController without guessing handler names or using reflection (`getattr`, `_invoke_controller`, etc.). Any new controller requirements must be wired through this explicit API, not via string-based dispatch or dynamically injected attributes.
GUI components must call these typed controller entrypoints directly; string-based dispatch has been retired in PR-CORE1-C4B and will not be reintroduced.

4. Builder Pipeline Architecture (Canonical)

The builder pipeline is the single source of truth for constructing jobs.

There is one, and only one, allowed sequence:

4.1 ConfigMergerV2
4.2 RandomizerEngineV2
4.3 UnifiedPromptResolver
4.4 UnifiedConfigResolver
4.5 JobBuilderV2
→ N NormalizedJobRecord objects


Each step is pure, stateless, deterministic, and validated.

4.1 ConfigMergerV2

Inputs:

Pack-level defaults

AppStateV2 pipeline settings

Global Negative flag

Sweep/Variant plan

Outputs:

A single MergedBaseConfig

A ConfigVariantPlanV2 describing sweep expansions

Rules:

Never reads prompts

Never reads GUI text fields

Must not mutate PromptPack JSON

4.2 RandomizerEngineV2

Works only with:

Matrix slots from PromptPack JSON

Randomization settings configured in Pipeline Tab

Output:

RandomizationPlanV2 describing variant expansions of matrix slots

Rules:

Expansion is deterministic

Variants are applied to prompt templates in UnifiedPromptResolver

4.3 UnifiedPromptResolver

Inputs:

PromptPack TXT row

RandomizationPlanV2

Global negative (from settings)

Outputs:

ResolvedPositivePrompt

ResolvedNegativePrompt

Rules:

All substitutions happen here

Matrix values must be applied exactly once

Global negative merges into negative prompt only

No mutation of PromptPack or config occurs here

4.4 UnifiedConfigResolver

Inputs:

MergedBaseConfig

ConfigVariantPlanV2

Stage toggles

Pack defaults

Outputs:

Fully resolved stage-by-stage config:

txt2img

refiner

hires

upscale

adetailer (if enabled)

Rules:

Must output a complete, immutable config tree

Builder pipeline does not permit missing fields

4.5 JobBuilderV2

This is the final expansion stage.

Inputs:

Resolved prompts

Resolved config

Randomization variants

Config variants

Batch size

Seeds

Output:

List[NormalizedJobRecord] (immutable)

Rules:

No mutation downstream

Job IDs assigned here

Stage chain stored in final NJR

5. NormalizedJobRecord (NJR)

The NJR is the only valid job representation for execution.

It contains:

PromptPack metadata

Source prompt row

Resolved prompts

Resolved config + all stages

Randomization slot values

Config sweep values

Batch index

Variant index

Seeds

Execution metadata

5.1 NJRs are immutable

Controllers, queue, runner, and history may not modify them.

6. Execution Layer

The execution layer consists of:

JobService (Queue Manager)

Queue

Runner

There is no alternate path.

6.1 JobService

Responsibilities:

Accept lists of NJRs

Enqueue NJRs (FIFO)

Track lifecycle states:

SUBMITTED

QUEUED

RUNNING

COMPLETED

FAILED

JobService performs no job mutation.

6.2 Queue

Pure FIFO.

Only NJRs may enter

No legacy job types

No “payload jobs”

No pipeline_config jobs

No reconstruction inside queue

6.3 Runner

Runner:

Consumes NJRs

Does not interpret or modify config

Calls API/WebUI exactly as described by NJR

Emits:

Output images

Logs

Timing data

Errors

### 6.4 **CORE1 Execution State** (Updated PR-CORE1-B2, December 2025)

**Current Reality:**

StableNew execution model in v2.6:

**Build & Display Path (NJR-only):**
- PromptPack → GUI state → JobBuilderV2 → **NormalizedJobRecord[]**
- Preview/Queue/History panels display jobs via **NJR-driven DTOs**:
  - UnifiedJobSummary
  - JobQueueItemDTO
  - JobHistoryItemDTO
- All display data comes from NJR snapshots, NOT from pipeline_config

**Execution Path after B2 (NJR-only for new jobs):**

**For new queue jobs (v2.6+):**
```
Job (with normalized_record) →
AppController._execute_job
  → if normalized_record present → PipelineController._run_job → PipelineRunner.run_njr
  → on failure → return error status (NO fallback to pipeline_config)
```
This Job object no longer exposes a `pipeline_config` field; `_normalized_record` is the only execution payload carried between subsystems.

**For legacy jobs (pre-v2.6 or imported):**
```
Job (with only pipeline_config, no normalized_record) →
AppController._execute_job
  → _run_pipeline_via_runner_only(pipeline_config) → PipelineRunner.run_njr(legacy NJR adapter)
```

**Controller Chain (PR-CORE1-C5):**
- PipelineController → JobExecutionController → JobQueue / SingleNodeJobRunner is the single queue execution path now.
- QueueExecutionController has been removed; PipelineController calls JobExecutionController directly for submission, status observation, and cancellation.

**PR-CORE1-B2 Changes:**

- **NJR is the SOLE execution payload for all new jobs created in v2.6**
- If a job has `_normalized_record`, execution uses NJR path ONLY
- If NJR execution fails, the job is marked as failed (no pipeline_config fallback)
- The queue `Job` model no longer defines `pipeline_config`; new jobs never expose or persist this field (PR-CORE1-C2).
- Any remaining `pipeline_config` payloads live in legacy history entries and are rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.

**PR-CORE1-B3 Changes:**

- The queue `Job` model no longer exposes `pipeline_config`; `PipelineController._to_queue_job()` instantiates NJR-only jobs without storing pipeline_config.
- Queue/JobService/History treat `pipeline_config` as legacy metadata; only imported pre-v2.6 jobs may still store a non-null value via manual assignment.
- **PR-CORE1-B4 Changes:**
- PipelineRunner no longer offers a public `run(config)` entrypoint; `run_njr(record, cancel_token)` is the sole execution API.
- Legacy `PipelineConfig` executions pass through `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()` and then run through `run_njr`, ensuring the runner core only sees NJRs.

**Invariants (PR-CORE1-B2):**

- ✅ NJR is canonical for preview/queue/history display (PR-CORE1-A3)
- ✅ JobBuilderV2 is the only job builder
- ✅ Display DTOs never introspect pipeline_config (use NJR snapshots)
- ?o. NJR is the ONLY execution path for new jobs (PR-CORE1-B2)
- ?o. Jobs created via queue pipeline have `_normalized_record` attached
- ?o. NJR execution failures return error status (no silent fallback)
- ??O `pipeline_config` is removed from queue `Job` instances (PR-CORE1-C2); NJR snapshots are the only executable payloads.
- ??O History load path is NJR hydration only; legacy history entries are auto-migrated to NJR snapshots before replay.

**Legacy Support (retired in CORE1-D1):**

Legacy history formats are migrated in-memory to NJR snapshots via `HistoryMigrationEngine`. Replay paths no longer accept `pipeline_config` or draft-bundle structures; hydration is NJR-only.

7. Post-Execution Layer
7.1 History

Stores immutable job execution summaries:

NJR snapshot

Execution metadata

Output paths

Duration

Error data

History → Restore replays job by reconstructing NJR from snapshot. History load is NJR hydration only; any legacy fields (pipeline_config, draft bundles) are stripped and normalized on load.

7.2 Learning System

Consumes History entries:

Prompts

Config snapshot

Rating metadata

Outcome scoring

Learning system never alters NJRs.

7.3 DebugHub

Receives:

Builder pipeline trace

Resolved config trees

Resolved prompts

Randomizer + sweep expansions

Runner logs

Error traces

DebugHub is read-only.

8. GUI Architecture
8.1 Pipeline Tab

Pipeline Tab is responsible for:

Selecting PromptPack + row

Configuring sweeps and variants

Configuring stage toggles

Previewing resolved job summaries (UnifiedJobSummary)

Pipeline Tab does NOT:

Hold draft job objects

Construct jobs

Read/write prompt text

Store builder logic

It only manipulates AppStateV2.job_draft.

8.2 Advanced Prompt Builder

This is the only place where:

Prompt text is edited

Matrix slots added/removed

Pack-level defaults edited

PromptPack TXT and JSON are updated

Pipeline Tab merely consumes these packs.

8.3 Queue / History / Learning UIs

Must present:

UnifiedJobSummary

Job lifecycle data

Execution metadata

Ratings (Learning Tab)

Must not reconstruct or mutate NJRs.

9. Forbidden Systems and Code Paths

The following MUST NOT exist in repo code:

GUI prompt text fields

Any job created outside the builder pipeline

pipeline_config or legacy config union models

Legacy draft-bundle flow (enqueue_draft_bundle_legacy, controller-owned draft bundles) has been retired; AppStateV2.job_draft is now the only draft state, and JobBuilderV2 builds the NJRs that flow through the queue.

Controller-managed draft bundles no longer exist; AppState job_draft plus pipeline controller refreshes drive previews and queue submissions.

StateManager usage is restricted to the GUI layer and must not bleed into controllers or shared subsystems.

DTOs representing job summaries outside NJR/UJS

Direct runner calls bypassing JobService

Shims bridging v1→v2 pipeline behavior

Any such code must be removed during PRs.

10. Versioning & Architectural Change Protocol
10.1 Architecture versioning

This document is v2.6.
Any architectural modification requires:

Planner agent issues Architecture Change Proposal

Update to:

ARCHITECTURE_v2.X.md

PROMPT_PACK_LIFECYCLE_v2.X.md

Builder Deep-Dive

Roadmap

Codex receives explicit authorization to modify architecture

Codex must never modify architecture without Planner-delivered updates.

11. Golden Path (Execution Guarantee)

Every PR and every change must preserve:

1. User selects PromptPack
2. User selects row
3. Pipeline Tab configures overrides/sweeps
4. Builder pipeline constructs NJRs
5. JobService enqueues NJRs
6. Runner executes NJRs
7. Outputs + History are written
8. Learning consumes History
9. DebugHub provides traces and introspection


If this path breaks, a PR must fix it immediately.

12. Summary of Architectural Invariants
12.1 All jobs come from Prompt Packs

No alternate prompt source exists.

12.2 There is one builder pipeline

All jobs must pass through it.

12.3 NJRs are the only execution units

Queue + Runner only consume NJRs.

12.4 No mutation past JobBuilder

NJR is final.

12.5 AppStateV2 is the only mutable runtime state

Controllers do not own draft state.

12.6 No legacy systems may remain

Shims, parallel codepaths, V1 state, V1 job models → delete them.

12.7 Documentation must match implementation

No drift allowed.

END OF ARCHITECTURE_v2.6.md (Canonical Edition)
