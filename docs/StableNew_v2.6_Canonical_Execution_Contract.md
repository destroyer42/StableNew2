# StableNew v2.6 – Canonical Execution Contract
**Status:** CANONICAL · ENFORCED  
**Applies To:** All PRs, Executors, Agents, Tests, and Runtime Paths  
**Attach This Document To:** Every PR request, every executor prompt

---

## 0. Purpose & Authority

This document is the **single authoritative execution contract** for StableNew v2.6.

If there is a conflict between:
- this document
- any PR description
- any test expectation
- any executor interpretation

**This document wins.**

---

## 1. Scope

This contract governs:

- Architecture execution rules
- NJR-only runtime enforcement
- PromptPack lifecycle invariants
- Pipeline execution semantics
- Queue + Runner behavior
- Diagnostics & watchdog behavior
- Executor (LLM / human) obligations
- Golden Path enforcement

---

## 2. Definitions

### 2.1 Canonical
Required for correctness. Non-negotiable.

### 2.2 Executor
Any agent implementing a PR (LLM or human).

### 2.3 NJR
`NormalizedJobRecord` — the **only** valid runtime job representation.

### 2.4 Golden Path
End-to-end user-visible behavior that must always work.

---

## 3. Executor Verifiability & Proof (MANDATORY)

### 3.1 Proof Requirement

Every **MUST** in this contract requires **machine-verifiable proof**.

Valid proof includes:
- `git diff` (full)
- `git status --short`
- pytest command + output
- grep output for forbidden symbols
- file + line references for behavior changes

**Statements without proof are invalid.**

---

## 4. Architectural Invariants

### 4.1 NJR Is Canonical

- All execution paths MUST use NJR
- `PipelineConfig` is **forbidden** in execution
- Dict-based configs are **forbidden** in execution

### 4.2 Legacy Code Classification (MANDATORY)

Every PR touching legacy code MUST classify it as exactly one:

#### A. DELETED
- File removed
- All references removed
- Tests updated or deleted

#### B. VIEW-ONLY
- File header: `# VIEW-ONLY (v2.6)`
- No execution paths
- No mutation
- No bridging

Silence is forbidden.

---

## 5. PromptPack Lifecycle (Canonical)

### 5.1 Lifecycle Stages

Author → Select → Draft → NJR → Queue → Run → History → Replay

### 5.2 Invariants

- PromptPacks are immutable after NJR creation
- Randomization resolves **before** queueing
- Queue stores **resolved NJRs only**

---

## 6. RunPlan Contract

### 6.1 Purpose

RunPlan is the **only** structure that defines execution order.

### 6.2 Construction

- Built exclusively from NJR
- No PipelineConfig usage
- No runtime inference

### 6.3 Required Fields

RunPlan MUST include:
- ordered `stages[]`
- per-stage enable flags
- resolved per-stage config
- variant metadata
- artifact destinations

### 6.4 Forbidden Responsibilities

RunPlan MUST NOT:
- mutate NJR
- inspect UI state
- consult defaults at runtime

---

## 7. PipelineRunner Contract

### 7.1 Entry Point (MANDATORY)

PipelineRunner MUST:
- expose `run_njr(njr, cancel_token)`
- reject all other entrypoints

### 7.2 Forbidden Behavior

PipelineRunner MUST NOT:
- accept PipelineConfig
- accept dict configs
- infer stages
- reorder execution
- resolve variants

### 7.3 Return Type

PipelineRunner MUST return:
- `PipelineRunResult` (typed)
- NEVER a dict

---

## 8. Queue & Runner Semantics

### 8.1 Queue

- Stores NJRs only
- No config mutation
- Thread-safe
- Deterministic ordering

### 8.2 Runner

- Single execution authority
- Reports heartbeats
- Updates job state atomically

---

## 9. Cancellation Semantics

- CancelToken MUST be threaded through:
  - Runner
  - Pipeline
  - Stage executor
- Cancellation MUST short-circuit execution
- Partial artifacts are allowed but recorded

---

## 10. Diagnostics & Watchdog

### 10.1 Watchdog Threading

- Watchdog MUST run on its own thread
- MUST NOT block UI or runner

### 10.2 Triggers

Diagnostics MUST trigger on:
- UI heartbeat stall
- Runner inactivity stall
- Deadlock detection

### 10.3 Diagnostics Bundle

On trigger:
- `stablenew_diagnostics_<timestamp>.zip`
- Logs, queue state, thread dump, metadata

Failure to emit = bug.

---

## 11. Golden Path Enforcement

### 11.1 Required Tests (MANDATORY)

Executors MUST run and pass:

- `tests/journeys/test_jt01_prompt_pack_authoring.py`
- `tests/journeys/test_jt03_txt2img_pipeline_run.py`
- `tests/journeys/test_jt06_prompt_pack_queue_run.py`
- `tests/gui_v2/test_main_window_smoke_v2.py`
- `tests/system/test_watchdog_ui_stall.py`

Test output MUST be shown.

---

## 12. History & Replay

- History stores NJR snapshots only
- Replay MUST rebuild RunPlan from NJR
- Legacy history is view-only

---

## 13. Explicit Executor Prohibitions (ANTI-DRIFT)

Executors MUST NOT:

- Modify only one file when PR scope lists multiple
- Skip required deletions
- Claim tests ran without output
- Stop after “core logic” changes
- Replace required behavior with refactors
- Ignore failing tests

Violation = PR rejection.

---

## 14. PR Compliance Checklist (MANDATORY)

Every PR MUST include:

- Files modified (exact list)
- Files deleted (exact list)
- Tests run (exact commands + output)
- Legacy classification decisions
- Golden Path confirmation

---

## 15. Drift Arrest Mechanism

### 15.1 Detection

If drift is detected:
- PR is halted
- Drift is documented

### 15.2 Recovery

Next PR MUST:
- Repair drift
- Add regression tests
- Not add features

---

## 16. Authority

This document is:
- Canonical
- Enforced
- Non-optional

If an executor cannot comply:
**They must stop.**
