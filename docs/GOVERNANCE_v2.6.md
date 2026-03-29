GOVERNANCE_v2.6.md
StableNew - Canonical Development and Decision-Making Model

Status: Authoritative
Updated: 2026-03-19

## 0. Purpose

Governance v2.6 defines:

- how canonical truth is ranked
- what architecture invariants may not be violated
- what agents and humans may and may not do
- how PRs must be planned, executed, reviewed, and documented
- how StableNew avoids legacy drift and contradictory runtime stories

This document is binding on:

- human contributors
- Codex
- ChatGPT
- Copilot
- any future automation acting on the repository

No code path, PR, or subsystem spec may contradict this file.

## 1. Canonical Truth Hierarchy

### 1.1 Tier 1 - Constitutional documents

These define the current product and runtime truth:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`

### 1.2 Tier 2 - Execution and workflow canon

These explain how the constitutional runtime is applied:

- `docs/PROMPT_PACK_LIFECYCLE_v2.6.md`
- `docs/Builder Pipeline Deep-Dive (v2.6).md`
- `docs/DEBUG HUB v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `docs/Canonical_Document_Ownership_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `AGENTS.md`
- `.github/copilot-instructions.md`

### 1.3 Tier 3 - Active subsystem references

- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md`
- `docs/Movie_Clips_Workflow_v2.6.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md`
- `docs/Subsystems/Testing/KNOWN_PITFALLS_QUEUE_TESTING.md`
- `docs/Subsystems/Testing/E2E_Golden_Path_Test_Matrix_v2.6.md`

### 1.4 Tier 4 - Backlogs, PR records, and archive

- `docs/PR_Backlog/`
- `docs/CompletedPR/`
- `docs/archive/`

These are important for planning and history but do not outrank Tier 1-3.

## 2. Core Governance Pillars

### 2.1 One outer execution contract

`NormalizedJobRecord` is the only outer executable job contract.

Fresh execution, replay, reprocess, image edit, learning submissions, CLI
submissions, and video workflow submissions must all converge to NJR before
execution.

### 2.2 Queue-only fresh execution

Fresh production execution is queue-only.

`Run Now` is a UX behavior, not a separate runtime path:

- build NJR-backed work
- submit it to `JobService`
- auto-start processing if allowed

### 2.3 StableNew is the orchestrator

StableNew owns:

- intent intake
- builder and compiler logic
- queue and lifecycle policy
- runner orchestration
- artifacts and manifests
- history, replay, learning, and diagnostics

Backends execute only.

### 2.4 PromptPack is primary, not universal

PromptPack remains the primary image authoring surface.

It is not the only valid source of intent across the product. Other valid
surfaces include:

- reprocess
- image edit
- history replay
- learning-generated submissions
- CLI submissions
- video workflow submissions

What remains forbidden is inventing prompt/config construction in GUI code or
creating alternate execution architectures outside the canonical pipeline.

### 2.5 No live legacy execution model

The runtime must not rely on:

- `DIRECT` fresh execution
- archive DTOs as active runtime dependencies
- `PipelineConfig` as an execution contract
- `legacy_njr_adapter`
- backend workflow JSON as a public contract

Persisted legacy data is handled by migration tooling, not indefinite runtime
compatibility.

### 2.6 Zero drift

No PR may knowingly:

- leave contradictory docs active
- preserve duplicate runtime stories
- keep both old and new execution paths alive
- add shims without an explicit deprecation and removal owner

## 3. Role Boundaries

### 3.1 Planner

The planner must:

- produce executable PR specs
- preserve architecture invariants
- keep documentation synchronized
- identify and remove tech debt

### 3.2 Executor

The executor must:

- implement only approved scope
- refuse contradictory or underspecified work
- avoid architectural invention
- run verification and report real results

### 3.3 Human owner

The human owner sets priority, approves direction, and resolves intentional
design changes.

## 4. Required PR Behavior

Every meaningful PR must:

- state goals and non-goals
- define allowed and forbidden files
- state tests to run
- state documentation changes
- state rollback and deferred-debt ownership

PR planning and execution format is defined by `docs/PR_TEMPLATE_v2.6.md`.

## 5. Documentation Sync Rules

If runtime truth changes, update the affected docs in the same PR.

At minimum:

- architecture or runtime truth -> Tier 1 docs
- builder or PromptPack truth -> PromptPack and builder docs
- testing policy -> coding/testing docs and test-specific references
- doc movement or active-set changes -> `docs/DOCS_INDEX_v2.6.md`

Historical records and stale analysis belong in `docs/CompletedPR/` or
`docs/archive/`, not in the active root doc set.

## 6. Enforcement Summary

Reject or rewrite any PR that:

- introduces a second execution path
- introduces a second job model
- reintroduces live legacy execution seams
- lets GUI code construct prompts or runtime configs directly
- changes behavior without updating the active docs

## 7. Practical Reading Order

For active development, read in this order:

1. `docs/DOCS_INDEX_v2.6.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/GOVERNANCE_v2.6.md`
4. `docs/StableNew Roadmap v2.6.md`
5. `docs/PR_TEMPLATE_v2.6.md`

Then read subsystem docs relevant to the change.
