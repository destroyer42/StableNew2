PR-CORE-D — GUI V2 Recovery & Alignment with PromptPack.md

Version: v2.6-CORE
Tier: Tier 2 (GUI + Controller integration, no GUI_core forbidden files touched unless explicitly allowed)
Author: ChatGPT (Planner), approved by Rob
Date: 2025-12-08
Discovery Reference: D-23
Depends on:

PR-CORE-A (UnifiedJobSummary + PromptPack-Only invariant + NormalizedJobRecord schema)

PR-CORE-B (deterministic job construction pipeline)

PR-CORE-C (Queue + Runner lifecycle stabilization)

1. Summary / Executive Abstract

PR-CORE-D is the UI/UX stabilization PR that brings the entire GUI V2 stack into alignment with the new, deterministic, PromptPack-Only execution model established in PR-CORE-A/B/C.

The goal is to restore a functional end-to-end experience where:

User selects a Prompt Pack

Pipeline Tab derives a UnifiedJobSummary

User runs job (Direct or Queue)

Queue Panel and Running Job Panel update using lifecycle events

History shows accurate, reconstructable entries

Debug Hub can “Explain Job” using the same unified DTO

Learning Tab receives proper job payloads

This PR does not introduce new UI features — it corrects the GUI’s interpretation of job data, ensures consistent state propagation, and guarantees that the UI always reflects real system state.

2. Motivation / Problem Statement

Before PR-CORE-A/B/C:

GUI allowed free-text prompts → caused job model drift

Preview Panel often failed to load correct prompt/config summaries

Queue Panel displayed stale or incomplete job objects

Running Job Panel could not show stage progress because job data was malformed

History panel entries lacked prompt provenance → Learning could not rely on them

Debug Hub could not reliably explain a job

Many state transitions relied on GUI-derived job data (forbidden by V2 architecture)

After PR-CORE-A/B/C:

All job objects are complete NormalizedJobRecord instances

GUI must consume, not construct, these objects

GUI must never bypass controllers or pipeline runtime

GUI must render UnifiedJobSummary for preview & job lists

GUI must not manage internal prompt/config fields itself

PR-CORE-D updates all GUI subsystems to reflect this architecture.

3. Scope
In Scope

GUI V2 alignment with PromptPack-Only execution

Pipeline Tab run controls

Preview Panel summary logic

Queue Panel + Running Job Panel updates via lifecycle events

History Panel loading and item expansions

Debug Hub “Explain Job” integration

AppState V2 updates to support required data flows

Controller → GUI event pathways

Not In Scope

Executor changes

Learning logic changes

Stage Card redesign

New UX features

Any modification to forbidden GUI core files such as:

src/gui/main_window_v2.py

src/gui/theme_v2.py

4. Architectural Alignment (Canonical)
4.1 PromptPack-Only Enforcement

GUI must strictly follow:

Pipeline Tab cannot offer free-text prompt entry

Pipeline Tab’s “Run” button is disabled until a Prompt Pack is selected

Preview panel displays only the UnifiedJobSummary produced by the controller

No UI component may construct prompt strings on its own

4.2 Single Source of Truth

All job summaries come from UnifiedJobSummary built by PR-CORE-A/B

All job lifecycle changes come from JobService → lifecycle events (PR-CORE-C)

GUI never mutates NormalizedJobRecord objects

History, Queue, Running Job, Debug Hub all display identical, canonical fields

4.3 GUI V2 Architecture Boundaries

Per ARCHITECTURE_v2.5.md:

GUI → Controller (only)

Controller → Runtime → Queue/Runner

GUI never touches pipeline runtime or job builder directly

PR-CORE-D must strictly enforce this.

5. Detailed Implementation Plan

This is the required sequence of repairs.

5.1 Pipeline Tab Alignment
5.1.1 Remove all free-text prompt inputs

Hide or disable positive/negative prompt fields

Replace textboxes with a read-only summary view showing:

Prompt Pack name

Row count

Selected rows (if applicable)

Prompt preview from UnifiedJobSummary

5.1.2 Run Button Rules

Disabled until:

A Prompt Pack is selected

A config snapshot or preset is selected

Button triggers controller method:

build_and_run_jobs(prompt_pack_id, config_snapshot_id)


UI does not build any job objects.

5.1.3 Preview Panel

Display UnifiedJobSummary only

No reconstruction of prompt/config inside GUI

Show:

Pack name

Positive/negative prompt preview (single or composite)

Stage chain (as human-friendly labels)

Randomization summary (slot:value pairs)

Batch/variant counts

5.2 Queue Panel Updates
5.2.1 Queue Panel Items

Render list of UnifiedJobSummary entries with:

Status: SUBMITTED / QUEUED / RUNNING

Pack name

Prompt preview

Stage chain summary

variant_index / batch_index

seed

5.2.2 Event Subscription

Queue Panel must subscribe to:

job_lifecycle_event with event types:

SUBMITTED

QUEUED

RUNNING

CANCELLED

Update UI accordingly.

5.3 Running Job Panel
5.3.1 Display UnifiedJobSummary for active job

Show:

PromptPack name & row

Stage chain (highlight current stage)

Seeds and matrix slot metadata

Execution timestamps

Image previews when available

Status updates (RUNNING → COMPLETED/FAILED)

5.3.2 Do NOT reconstruct prompts

Only display the summary fields provided by controller/runner.

5.4 History Panel
5.4.1 Show canonical NormalizedJobRecord-derived summaries

History entries should display:

Pack name

Prompt preview

Negative preview

Model & sampler

variant_index and batch_index

Stage chain summary

Execution timestamps

Failure message (if applicable)

5.4.2 Drilldown view

Clicking a history entry loads:

UnifiedJobSummary

Full NormalizedJobRecord details (read-only)

Output image list

No editing allowed.

5.5 Debug Hub Integration
5.5.1 Structured lifecycle events

GUI must display lifecycle events as:

[RUNNING] job_id=..., row=..., variant=..., stage=txt2img

5.5.2 “Explain Job”

Display:

All summary fields

All stage configs

All matrix slot values

All LoRA and embedding metadata

Derived network payload (if debug mode enabled)

Debug Hub must not fetch data from GUI state — only from supplied DTOs.

5.6 App State V2 Changes
5.6.1 AppState must track:

Selected PromptPack ID

Selected Config Snapshot ID

Last UnifiedJobSummary

Job lifecycle events

History entries

5.6.2 Remove all legacy prompt/config shadow state

Any outdated GUI-side mirrors of prompt/config data must be deleted.

6. Allowed / Forbidden Files
Allowed

(Only view models, controllers, panels, app_state)

src/gui/app_state_v2.py

src/gui/panels_v2/pipeline_panel_v2.py

src/gui/panels_v2/preview_panel_v2.py

src/gui/panels_v2/queue_panel_v2.py

src/gui/panels_v2/running_job_panel_v2.py

src/gui/panels_v2/history_panel_v2.py

src/gui/debug/debug_hub_explain_job_v2.py

src/controller/pipeline_controller_v2.py

src/controller/job_controller_v2.py

tests/gui/*.py

Forbidden (unless explicitly authorized)

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/main.py

executor/runner files

pipeline runtime

learning core

7. Test Plan
7.1 Unit Tests
Pipeline Tab

Run button disabled without prompt pack

Preview panel renders UnifiedJobSummary only

No free-text prompt accepted

Queue Panel

Subscribes to lifecycle events

Reflects transitions in correct order

Running Job Panel

Active job displays correct fields

Stage highlighting updates

History Panel

Shows complete metadata

Drilldown displays full job details

Debug Hub

Renders structured lifecycle logs

Explain Job displays canonical fields

7.2 Integration Tests (Golden Path E2E)

Using real Prompt Packs:

Test: Angelic Warriors E2E

Select Prompt Pack

View preview → check summary

Run job

Queue → Running → Completed

History entry appears correctly

Debug Hub shows correct events

Test: Mythical Beasts Randomization

Select Prompt Pack

Select config with randomization enabled

Preview shows variant count

Run job

Queue shows all fanout jobs

History contains correct variant/batch metadata

8. Acceptance Criteria

UI contains no free-text prompt fields

Pipeline Tab run controls disabled until a Prompt Pack is selected

All panels use UnifiedJobSummary exclusively

Queue Panel correctly reflects lifecycle transitions

Running Job Panel displays accurate active job metadata

History shows complete PromptPack provenance

Debug Hub Explain Job works identically across all job sources

GUI never reconstructs any prompt or config — always uses controller-provided DTOs

All tests pass

9. Documentation Updates

Update:

ARCHITECTURE_v2.5.md

Add GUI alignment section describing removal of GUI prompt/config state

Roadmap_v2.5.md

Mark Phase D (GUI Recovery) appropriate to v2.6

DEBUG_HUB_v2.5.md

Add lifecycle log examples

StableNew_Coding_and_Testing_v2.5.md

Add GUI deterministic-state requirements

CHANGELOG.md

10. CHANGELOG Entry
## [PR-CORE-D] - 2025-12-08
GUI V2 Recovery & PromptPack-Only Alignment
- Removed all free-text prompt entry and GUI-side prompt/config construction.
- Pipeline Tab now relies solely on UnifiedJobSummary.
- Queue/Running/History Panels aligned with lifecycle events from JobService.
- Debug Hub Explain Job integrated with NormalizedJobRecord + UnifiedJobSummary.
- AppState cleaned of legacy prompt/config shadow structures.
- UI now fully reflects deterministic builder outputs compliant with PR-CORE-A/B/C.

11. Rollback Plan

Re-enable GUI prompt textboxes (NOT recommended)

Revert UnifiedJobSummary usage in panels

Remove lifecycle event subscriptions from UI

Restore old AppState shadow structures

Revert Preview Panel to reconstructing prompt text (breaks architecture)

Rollback would revert StableNew to a fragile, pre-CORE architecture and is discouraged.