StableNew_Coding_and_Testing_v2.6.md

Canonical Engineering Standards & Developer Guide
Last Updated: 2025-12-09
Status: Canonical / Required**

0. Purpose

This document defines the coding, testing, validation, and review standards for the StableNew v2.6 architecture. It governs:

How code is written

How tests must be structured

What invariants must be respected

What tech-debt cleanup rules must be followed

How LLM agents (Codex, ChatGPT) operate within strict boundaries

Every PR, every refactor, every feature must conform to this.

1. The Four Iron Laws of StableNew v2.6

These laws cannot be violated anywhere in the repo.

1.1 The PromptPack-Only Law

There is only one source of prompts:

PromptPack TXT rows

Forbidden everywhere:

GUI free-text prompt entry

Controller-provided prompt strings

Legacy job_draft.prompt

DraftBundle-based prompts

Any job payload containing custom text

If code creates a prompt from anywhere except a PromptPack row → PR rejected.

1.2 The Single Builder Law

There is only one job-building path:

JobBuilderV2 → produces NormalizedJobRecord (NJR)

Forbidden:

direct runner payload dicts

“simple job” helper constructors

custom wrappers used by old controllers

parallel job formats

legacy prompt resolution code

Legacy RunPayload/job.payload helpers were removed in PR-CORE1-B5 and must not reappear in new code or tests.

All jobs must pass through:

RandomizerEngineV2
ConfigVariantPlanV2
UnifiedPromptResolver
UnifiedConfigResolver
JobBuilderV2

1.3 The Immutable Job Law

A NormalizedJobRecord:

is immutable after creation

may not be edited by GUI, controllers, or runner

must contain all fields needed for execution

If metadata must change → build a new NJR.
Never mutate an NJR.

1.4 The Determinism Law

Given identical input:

same PromptPack

same matrix selection

same config variants

same batch size

same seed rules

→ the builder must produce byte-for-byte identical NJRs.

Any nondeterminism = bug.

2. Repo Coding Standards

These apply repo-wide.

2.1 Single Responsibility per Module

Every module must represent exactly one conceptual purpose:

Module	Purpose
config_variant_plan_v2.py	Sweep variant logic
job_builder_v2.py	NJR construction
resolution_layer.py	Prompt + config merging
randomizer_v2.py	Matrix variant expansion
job_models_v2.py	Strongly-typed DTOs
pipeline_controller.py	Pipeline orchestration
webui_connection_controller.py	Backend communication

If a module mixes responsibilities → PR must split it.

2.2 No Dead Code / No Shims / No Legacy Paths

Forbidden:

DraftBundle, legacy JobDraft, RunPayload

Legacy UnifiedConfig rules

Old PromptResolver

GUI widgets that produce anything except state transitions

“Temporary” shims in controller

Partial refactors that leave alternate paths in place

If it can’t be deleted, it must be explicitly documented in TECH_DEBT.md.

2.3 Explicit Data Models Only

No dict-of-dict-of-dict structures.
Use Pydantic models everywhere:

Clear schema

Validation builtin

Type safety

IDE assistance

Traceability in DebugHub

2.4 No Circular Dependencies

This was one of the largest sources of instability in v2.5.

Rules:

Controllers may depend on pipeline modules

Pipeline modules may never depend on GUI

Runner may depend on NJR, but not controllers

Config and model layers must remain bottom-most

2.5 Logging Standards

Every subsystem produces logs via:

logger = logging.getLogger(__name__)


Levels:

Level	Use
INFO	normal operations
WARNING	user-fixable issues
ERROR	run-blocking conditions
CRITICAL	fatal errors only

Debug logs should include context IDs:

job_id

pack_name

config_variant_label

matrix_variant_index

3. Testing Standards

Testing is structured according to the Builder Pipeline and Golden Path.

3.1 Test Hierarchy
tests/
  unit/
    pipeline/
    controller/
    utils/
  integration/
    builder/
    controller/
    runner/
  e2e/
    golden_path/

3.2 Unit Tests (Required for Every PR)

Every function in:

RandomizerEngineV2

ConfigVariantPlanV2

UnifiedPromptResolver

UnifiedConfigResolver

JobBuilderV2

must have:

happy-path test

failure-path test

Examples:

✔ slot substitution
✔ negative layering
✔ override merging
✔ stage chain validation
✔ seed determinism

Forbidden:

using the runner in unit tests

filesystem UI integration

mocking PromptPack incorrectly

3.3 Integration Tests

Integration tests verify:

a pack → NJRs

NJRs → queue

queue → runner

Tests must include:

multi-stage pipelines

multi-variant sweeps

multiple matrix combinations

global negative toggle

error conditions

3.4 E2E Golden Path Tests (Mandatory)

All Golden Path tests GP1–GP12 must pass:

ID	Scenario
GP1	single-row, simple job
GP2	queue-only FIFO
GP3	batch expansion
GP4	randomizer variants
GP5	randomizer × batch
GP6	full SDXL multi-stage
GP7	adetailer integration
GP8	stage toggle correctness
GP9	runner failure path
GP10	learning integration
GP11	mixed queue
GP12	history replay

Every PR must state whether it impacts Golden Path.
If yes → tests must be updated.

3.5 Test Fixtures (Canonical)

Fixtures include:

prompt_pack_fixture()

randomizer_fixture()

config_variant_plan_fixture()

builder_fixture()

runner_stub_fixture()

These fixtures:

never embed UI

always produce deterministic results

return typed objects, not dicts

3.6 Seed Determinism Testing

Seed resolution must satisfy:

fixed seed → identical outputs

no seed → builder assigns random, but logged

sweep variants must not share seed unless specified

Tests must validate these conditions.

4. Tech Debt Elimination Rules

StableNew v2.6 has a strict stance:

No PR is allowed to introduce new tech debt.
If a PR depends on cleaning tech debt → it must do so immediately.

4.1 Immediate Cleanup Requirement

Every PR must contain:

## TECH-DEBT IMPACT
- Does this PR remove tech debt?
- Does this PR introduce new tech debt?
- If yes, the following cleanup was performed in this PR:


Deferred cleanup is not allowed.

4.2 Allowed Exceptions (Only 2)

Exception 1 — Blocking external dependency
Exception 2 — Requires architectural PR (CORE-level)

Both require:

JUSTIFICATION:
RATIONALE:
CLEANUP DEADLINE:

4.3 Removal Requirements

Components that must be removed:

RunPayload

Old Controller JobDraft / DraftBundle

2023 PromptResolver

v1 prompt pack schema loader

Multi-path job creation

GUI → runner direct calls

Legacy “simple_job.py” helpers

Any reference to “manual prompt mode”

Before removal, tests must be updated.

Controller-focused tests must construct controllers without injecting `StateManager`/`GUIState`; GUI state machinery belongs in `tests/gui` (see `tests/gui/test_state_manager_legacy.py` for the legacy coverage removed from controller specs). These tests must also avoid JobBundle/JobBundleSummaryDTO assertions—coverage should rely on AppStateV2.job_draft + `NormalizedJobRecord` outputs instead of legacy bundles.

5. Controller Integration Rules

Controllers:

may not generate or mutate prompts

may not build config dicts

may not directly interact with runner

must call builder for everything

must accept only canonical DTOs

Controller responsibilities:

  capture UI state
 
  build config variant plans
 
  pass context to builder
  
  rely on AppStateV2.job_draft + JobBuilderV2; do not maintain `_draft_bundle` or JobBundle state in controllers.
 
  enqueue NJRs

Controllers do not:

assemble payloads

execute payload-based jobs (RunPayload / `Job.payload`)

build pipeline configs

merge dictionaries

create stage chains
- depend on `src/gui.state.StateManager` or `GUIState`; controller tests must use AppStateV2-only fixtures, and GUI state coverage exists in `tests/gui/test_state_manager_legacy.py`

### Controller Event API (PR-CORE1-C4A)

Controller tests must interact with controllers via their explicit event methods (`on_run_now`, `on_add_to_queue`, `on_clear_draft`, `on_update_preview`, etc.) rather than probing for optional handler names with `getattr`/`hasattr`. Dynamic attribute injection and string-based dispatch are forbidden in both implementation and tests, so the tests focus on AppStateV2 + NJR outcomes instead of legacy reflection.

GUI tests must assert that UI actions call these explicit controller hooks; reflection-based wiring or `_invoke_controller` helpers are no longer used.

Controllers also must consume `JobExecutionController` directly for queue execution; introducing façade layers such as a `QueueExecutionController` that merely proxies into `JobExecutionController` is forbidden (PR-CORE1-C5 collapsed that chain).

### 5.1 **NJR-Only Execution Invariants** (PR-CORE1-B2)

New rules for queue execution path after B2:

**Execution Path - NJR-ONLY for New Jobs:**

**REQUIRED:** If a Job has `normalized_record`, the queue execution path MUST use `run_njr` via `_run_job`.

**FORBIDDEN:** Controllers, JobService, and Queue/Runner MUST NOT reference `pipeline_config` on `Job` instances; the field no longer exists in the queue model (PR-CORE1-C2).

**FORBIDDEN:** If NJR execution fails for an NJR-backed job, the execution path MUST NOT fall back to `pipeline_config`. The job should be marked as failed.

**LEGACY-ONLY:** `pipeline_config` execution branch is allowed ONLY for jobs without `_normalized_record` (imported from old history, pre-v2.6 jobs).

AppController._execute_job MUST check for `_normalized_record` FIRST. If present, use NJR path exclusively.

**Job Construction:**

All jobs created via `PipelineController._to_queue_job` MUST have `_normalized_record` attached.

`pipeline_config` field no longer exists on Job objects created via JobBuilderV2; new jobs rely solely on NJR snapshots (PR-CORE1-C2). Legacy pipeline_config data lives only in history entries and is rehydrated via `legacy_njr_adapter.build_njr_from_legacy_pipeline_config()`.

**PR-CORE1-B4:** `PipelineRunner.run(config)` no longer exists. Tests (both unit and integration) must exercise `run_njr()` exclusively and may rely on the legacy adapter if they need to replay pipeline_config-only data.

**Testing Requirements:**

All golden-path E2E tests MUST assert NJR execution is used for new queue jobs.

Tests MUST verify that `_run_job` is called when `_normalized_record` is present.

Tests MUST verify that NJR execution failures result in job error status (NO fallback to pipeline_config).
Tests MUST verify that new queue jobs do not expose a `pipeline_config` field (PR-CORE1-C2); any legacy coverage should work through history data only.
Tests MUST NOT reference `pipeline_config` or legacy job dicts in persistence/replay suites; all history-oriented tests hydrate NJRs from snapshots.

Tests MUST capture logs or use stub runners to verify whether `run_njr` vs `run(config)` was invoked.

Tests for legacy jobs (without NJR) MUST verify `pipeline_config` branch still works.

6. GUI Integration Rules

GUI V2 only communicates in terms of:

PromptPack IDs

Selected rows

Sweep variants

Stage toggles

Global negative toggle

GUI may never:

construct prompts

construct NJRs

modify config objects

mutate packs

GUI must:

reflect summary state

differentiate “preview” vs “draft”

trigger controller actions only

7. DebugHub Integration Requirements

DebugHub exposes:

prompt layering

matrix value maps

sweep variants

final config

stage chain

seeds

NJR preview

DebugHub must never:

alter job execution

mutate NJRs

access GUI state

accept arbitrary dicts

It is purely diagnostic.

8. LLM Agent Rules (ChatGPT + Codex)
8.1 ChatGPT (Planner)

ChatGPT generates:

PR specs

architecture docs

definitions

refactor plans

clean code stubs

test scaffolds

ChatGPT may not:

modify repo directly

execute code

produce delta patches that skip PR requirements

8.2 Codex (Executor)

Codex implements:

PRs exactly as written

test suites

refactors

removals

Codex must:

follow PR template

remove dead code, not preserve it

follow canonical architecture

never create alternate paths

resolve imports properly

Codex may NOT:

add partial features

make design decisions

resurrect legacy paths

9. Quality Gates

Before merging, PRs must:

Pass all unit tests

Pass all integration tests

Pass Golden Path tests

Have no lints

Remove tech debt touched by PR

Comply with Architecture v2.6

Document changes in CHANGELOG

Update any canonical spec files if impacted

If any fail → PR rejected.

10. Example: Valid PR Checklist
[X] All builder logic passes unit tests
[X] New sweep parameters validated
[X] Prompt resolves through PromptPack-only path
[X] NJRs created via JobBuilderV2
[X] No GUI prompt code added
[X] Tech debt removed (draftbundle.py deleted)
[X] Docs updated: Builder Deep Dive v2.6
[X] Golden Path tests updated and passing
[X] Codex executor instructions included

11. Summary

This document exists to ensure:

no regressions

no alternate paths

no silent merges

no prompt drift

no legacy job formats

no accidental mutations

StableNew v2.6 requires:

Single prompt source

Single builder path

Deterministic NJR creation

Immutable job records

Clear boundaries between GUI → Controller → Builder → Runner

Everything in StableNew depends on these rules being enforced.

END — StableNew_Coding_and_Testing_v2.6 (Canonical Edition)
