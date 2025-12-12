PR-CORE1-A — Single Source of Truth Purification(v2.6).md

Version: v2.6-CORE
Tier: Tier 2 (controller + builder wiring + GUI read-only binding)
Author: ChatGPT (Planner)
Approved by: Rob
Date: 2025-12-XX
Depends on:

Architecture_v2.6 (PromptPack-Only, NJR-Only pipeline)

Governance_v2.6

Builder Pipeline Deep-Dive v2.6

PromptPack Lifecycle v2.6

DebugHub_v2.6

StableNew Strategy v2.6

Roadmap v2.6 (Phase 1: Unification)

1. Summary / Executive Abstract

PR-CORE1-A is the foundational unification PR.
It eliminates all competing or legacy “sources of truth,” and enforces a single canonical pipeline state format: NormalizedJobRecord (NJR).

This PR makes the following structural improvements:

All GUI panels (Preview, Queue, History, RunningJob) become read-only projections of UnifiedJobSummary(NJR)

All job creation flows (Run Now, Add to Queue, Restore from History) must go through JobBuilderV2 → NJR[]

All execution flows (Runner/JobService/History) must operate solely on NJRs

All legacy/partial job models, draft bundles, or direct-run paths are formally deprecated and removed

This is the PR that stops the bleeding.
After this PR, no part of the system is allowed to invent, mutate, or construct its own representation of a job.

Everything becomes predictable, testable, unified.

2. Problem Statement

StableNew still contains four different competing execution paths and multiple shadow state representations, including:

PipelineConfigBundle (legacy)

JobDraftBundle (legacy)

StateManager._draft_bundle.parts

GUI-level job drafts and prompt assemblies

History entries storing partial or non-reproducible records

Runner receiving non-normalized job configs

Preview reading from GUI state instead of normalized summaries

This violates:

Architecture_v2.6 §3 (Single Source of Truth)

Governance_v2.6 (No pipeline logic inside GUI)

Strategy_v2.6 (Layer 1 — Unification)

The result:
breakage, fragility, unpredictable job states, broken queue/runner behavior.

This PR eliminates all non-canonical representations and enforces:

All jobs start as NJRs, run as NJRs, and end as NJRs. Always. No exceptions.

3. Goals
Primary Goals

Enforce NJR-Only Pipeline State

Eliminate all secondary/legacy job constructs

Align GUI panels to display UnifiedJobSummary(NJR) only

Controller becomes pure orchestrator: GUI → Builder → Queue

Preview panel works consistently and accurately

Queue panel reflects actual job state using life-cycle events

History is fully reconstructable from NJR snapshots

Remove the “job draft bundle” concept entirely

Non-Goals

No changes to Builder internals (that happens in PR-CORE1-B)

No Queue/Runner repairs (PR-CORE1-C)

No DebugHub enhancements (PR-CORE1-D)

No Config Sweep or Randomizer UI work (those are PR-CORE2)

4. Architecture Alignment Requirements (Mandatory)

This PR must satisfy:

A. PromptPack-Only Input

GUI may only pass:

prompt_pack_id

config_snapshot_id

optional sweep/randomizer metadata
NOT raw prompt text.

B. NJR-Only Execution

Every job MUST be constructed by JobBuilderV2 and stored as:

NormalizedJobRecord {
   job_id,
   pack_id,
   merged_config,
   resolved_prompt,
   stage_chain,
   seed,
   variant_index,
   batch_index,
   ...
}

C. GUI Read-Only Rendering

GUI cannot compute:

prompts

negatives

stage chains

variants

seeds

batch/variant counts

All must come from UnifiedJobSummary(NJR).

D. No Legacy Draft Bundles

All of the following must be deleted or disabled:

_draft_bundle.parts

add_single_prompt_to_draft()

“free-text prompt to preview” flows

any PipelineController path that reads old fields

5. Detailed Implementation Plan
5.1 Remove Legacy Draft Systems

Files to modify or remove:

src/controller/pipeline_controller.py

src/controller/app_controller.py

src/gui/sidebar_panel_v2.py

src/gui/app_state_v2.py

Actions:

Delete _draft_bundle, .parts, .add_part, .enqueue_draft_bundle

Remove any call to add_single_prompt_to_draft

Remove “Add to Job” legacy path that constructs prompts directly

After this PR, the only “draft” is a list of PromptPack selections stored in AppStateV2.

5.2 Introduce PipelineRunRequest DTO

A clean controller input type:

PipelineRunRequest {
   prompt_pack_id: str
   config_snapshot_id: str
   sweep_state: ConfigSweepState (optional)
   randomizer_plan: RandomizationPlanV2 (optional)
}


GUI → Controller always sends one of these.

5.3 Controller Rewrites to NJR-Only Job Construction

Modify:

pipeline_controller.build_and_run_jobs

app_controller.on_pipeline_add_packs_to_job

app_controller.on_pipeline_execute

New flow:
PipelineRunRequest
     ↓
ConfigMergerV2.merge()
RandomizerEngineV2.expand()
JobBuilderV2.build_jobs()
     ↓
list[NormalizedJobRecord]
     ↓
JobService.enqueue(njr)


No GUI state is referenced beyond pack/config selection.

5.4 Preview Panel Rewrite (Strict Summary Rendering)

Modify:

preview_panel_v2.py

Required behavior:

Always render from UnifiedJobSummary

Never read GUI state fields directly

Always reflect:

number of jobs

stages

sweep/variant counts

global negative flag

pack name & row count

Preview becomes 100% deterministic.

5.5 Queue Panel Rewrite

Modify:

queue_panel_v2.py

Changes:

Listens to job_lifecycle_event

Renders summary from NJR → UnifiedJobSummary

No partial job objects allowed

5.6 Running Job Panel Rewrite

Modify:

running_job_panel_v2.py

Changes:

Must highlight active stage based on NJR metadata

Must display variant/batch indexes

Must not compute any prompt text

5.7 History Rewrite

Modify:

history_panel_v2.py

job_history_models_v2.py

Requirements:

Store NJR.to_dict()

On restore:

reconstruct GUI purely from stored NJR fields

No mutation of canonical job state

5.8 Remove Shadow State & Utility Code

Delete:

pipeline_preview_builder.py (if still exists)

config_draft_builder.py (legacy)

job_builder_legacy.py

any unused class under src/utils/ tied to V1 pipeline

Replace with direct calls to NJR builder.

6. Tests
6.1 New Tests (Required)
Unit tests

test_gui_preview_renders_from_summary_only

test_controller_builds_jobs_only_via_njr_builder

test_queue_receives_correct_njr_objects

test_history_persists_and_restores_using_njr_snapshots

Integration tests

test_pipeline_run_request_builds_expected_njrs

test_preview_updates_after_pack_selection

test_queue_updates_on_lifecycle_events

6.2 Delete / Archive Tests

All tests referencing:

draft bundles

free text prompts in pipeline

legacy builder paths

Move into /tests/archive_v1/.

7. Acceptance Criteria

PR-CORE1-A is successful when:

 Preview panel updates only from UnifiedJobSummary(NJR)

 Queue panel lists jobs with correct pack/stage/variant summaries

 History stores/loads NJR snapshots correctly

 PipelineController never accesses legacy draft bundles

 GUI never computes prompts/configs

 Only NJRs flow into JobService/Queue/Runner

 All legacy execution paths are removed or unreachable

 Golden Path GP1, GP2 (Build-only scenarios) pass

8. Risk Assessment
Medium risk

Removal of legacy paths may break features still dependent on them

Mitigation:

Parallel implementation of PR-CORE1-B/C/D

Heavy unit and integration test focus

Archive, not delete, V1 tests

Add Logging v2.6 instrumentation around lifecycle events

9. Documentation Updates

Update:

Architecture_v2.6 → remove legacy representations

Builder Pipeline Deep-Dive → unify on NJR

PromptPack Lifecycle → reflect Pack→NJR flow

DebugHub_v2.6 → ensure NJR summary reading

Roadmap_v2.6 → mark Phase 1A complete

Docs Index → update references

10. CHANGELOG Entry
## [PR-CORE1-A] — Single Source of Truth Purification (v2.6)
### Added
- PipelineRunRequest DTO
- Unified NJR-only execution path
- Summary-only GUI rendering

### Removed
- Legacy draft bundles
- Prompt-building GUI flows
- Multiple legacy job model paths

### Changed
- GUI panels updated to strictly consume UnifiedJobSummary
- Controller flows rewritten around NJR construction
- History rewritten around NJR snapshots

### Notes
This PR establishes the canonical execution backbone for all future CORE1 and CORE2 work.

11. Rollback Plan

Rollback restores:

Draft bundle system

Legacy preview & queue renderers

Prompt reconstruction in GUI

Multiple job execution code paths

Rollback is not recommended because it reintroduces non-determinism and architectural drift.