# PR-MAR26 UI Refresh PySide6 Migration Critique + Revised Plan

**Status**: 🟡 Specification
**Priority**: CRITICAL
**Effort**: LARGE (multi-PR)
**Phase**: UI Migration Program
**Date**: 2026-03-09

## Context & Motivation

### Problem Statement
The initial PySide6 migration sequence is directionally correct but under-specifies risk controls for event-loop concurrency, parity validation, and branch governance.

### Why This Matters
StableNew already has strict v2.6 architecture invariants. A GUI toolkit migration can destabilize queue lifecycle, learning/review workflows, and shutdown behavior if done without explicit gates.

### Current Architecture
GUI is currently Tk V2. Core runtime path remains canonical:
PromptPack -> Builder -> NJR -> Queue -> Runner -> History -> Learning.

### Reference
- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`
- `docs/PR_MAR26/PR-MAR26-UI-REFRESH-001-Migration-Accelerator.md`

## Critique of Initial 10-Phase Plan

### PR-PS6-001 (Architecture/Governance)
Top 3 weaknesses:
1. No explicit cutover readiness matrix.
2. No anti-drift guardrails for mixed Tk/Qt runtime in the same process path.
3. No owner for architectural exception handling.

Fix:
1. Add a migration readiness checklist with hard merge gates.
2. Add import-path/runtime policy that forbids mixed host in mainline runtime.
3. Require explicit architecture sign-off section in each PR summary.

### PR-PS6-002 (Contract Extraction)
Top 3 weaknesses:
1. Scope too broad without inventory baseline.
2. No measurable contract-completeness target.
3. Risk of leaving logic in widgets.

Fix:
1. Define per-surface inventory with status.
2. Require 100% contract coverage for selected surfaces before moving on.
3. Add lint/test checks for toolkit-specific logic leakage.

### PR-PS6-003 (UI Dispatcher Abstraction)
Top 3 weaknesses:
1. Missing strict thread-affinity contract.
2. Undefined behavior for sync calls from background threads.
3. No stress test plan.

Fix:
1. Define `UiDispatcher` contract with required semantics.
2. Document strict behavior for invoke/schedule semantics.
3. Add threading stress tests in controller integration.

### PR-PS6-004 (Qt App Spine)
Top 3 weaknesses:
1. Spine may accidentally duplicate controller wiring.
2. No startup/shutdown parity criteria.
3. No temporary branch isolation strategy.

Fix:
1. Reuse existing controller attach points only.
2. Add startup/shutdown parity checklist.
3. Keep this PR on migration branch only until parity gates pass.

### PR-PS6-005 (Prompt + Pipeline Port)
Top 3 weaknesses:
1. High blast radius (core authoring + execution config UX).
2. No deterministic behavior assertions against Tk baseline.
3. Missing test fixture portability plan.

Fix:
1. Split by tab subsection internally with staged acceptance.
2. Add baseline parity tests for emitted controller calls/state transitions.
3. Introduce `pytest-qt` fixtures mirroring existing GUI contracts.

### PR-PS6-006 (Review + Learning Port)
Top 3 weaknesses:
1. Complex stateful workflow with undo/resume features.
2. Missing durability/recovery parity checkpoints.
3. Batch actions may diverge silently.

Fix:
1. Add state-transition matrix for review/learning.
2. Add explicit persistence/resume parity tests.
3. Add batch-operation diff tests before cutover.

### PR-PS6-007 (Queue/History/Preview/DebugHub Port)
Top 3 weaknesses:
1. Runtime event-heavy surfaces prone to threading bugs.
2. Missing performance baseline for render/update cadence.
3. No policy for failed event rendering.

Fix:
1. Add event replay tests and high-frequency update simulation.
2. Record baseline update latency and cap regressions.
3. Add non-fatal rendering failure handling requirements.

### PR-PS6-008 (Dialogs/Settings)
Top 3 weaknesses:
1. Modal behavior differences can deadlock UX.
2. File dialog and path handling parity not specified.
3. Incomplete shutdown sequencing around WebUI process manager.

Fix:
1. Add modal lifecycle testing checklist.
2. Add path normalization tests.
3. Require shutdown sequence tests including managed process termination.

### PR-PS6-009 (Cutover)
Top 3 weaknesses:
1. Single-step cutover too risky without dry-run gate.
2. No dual-branch release hardening window.
3. Missing rollback trigger thresholds.

Fix:
1. Require green dry-run release candidate in migration branch.
2. Add short stabilization window before merge to main.
3. Define explicit rollback triggers (crash rate, GP regressions, startup failures).

### PR-PS6-010 (Packaging/CI)
Top 3 weaknesses:
1. CI GUI environment assumptions unclear.
2. No pinned dependency policy for Qt plugins.
3. Missing smoke tests for install/start/run/close.

Fix:
1. Standardize CI display strategy for GUI tests.
2. Pin PySide6 stack versions and document upgrade cadence.
3. Add smoke pipeline in CI and local scripts.

## Revised Program Plan (Gate-Driven)

1. `PR-PS6-001` Governance + readiness gates.
2. `PR-PS6-002` Contract extraction completion with measurable coverage.
3. `PR-PS6-003` Dispatcher abstraction + thread tests.
4. `PR-PS6-004` Qt spine in migration branch.
5. `PR-PS6-005` Prompt/Pipeline parity migration.
6. `PR-PS6-006` Review/Learning parity migration.
7. `PR-PS6-007` Queue/History/Preview/DebugHub parity migration.
8. `PR-PS6-008` Dialog/settings + shutdown parity.
9. `PR-PS6-009` Cutover with rollback gates.
10. `PR-PS6-010` Packaging/CI hardening.

## Final Re-Evaluation

Residual weaknesses after revision:
1. Execution duration remains large and multi-sprint.
2. Risk remains medium-high for event-loop integration phases (PS6-005 through PS6-008).
3. Requires strict discipline to avoid temporary mixed-runtime shortcuts.

Assessment:
The revised plan is feasible and high-value with controlled risk, provided all gate criteria are enforced and no PR bypasses parity testing.

