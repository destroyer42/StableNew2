# D-ARCH-004: Codebase Review Top 10 Issues and COAs

**Status**: Discovery
**Date**: 2026-03-11
**Scope**: codebase, structure, documentation, agents, program behavior, functions, and tests

## 1. Purpose

This discovery report captures a broad review of the current StableNew codebase and identifies the top 10 cross-cutting issues affecting maintainability, correctness, governance, and delivery speed.

For each issue, this document includes:
- the issue statement
- the initial course of action (COA)
- the top 5 weaknesses of that initial COA
- the revised/final COA adopted for PR planning

This document is the planning basis for the PR series `PR-CORE-ARCH-047` through `PR-GUI-056`.

## 2. Evidence Summary

Key evidence used in this review:
- oversized active modules:
  - `src/controller/app_controller.py` (~5405 lines)
  - `src/pipeline/executor.py` (~3818 lines)
  - `src/gui/controllers/learning_controller.py` (~2062 lines)
  - `src/gui/views/photo_optimize_tab_frame_v2.py` (~1531 lines)
  - `src/pipeline/pipeline_runner.py` (~1143 lines)
  - `src/gui/main_window_v2.py` (~968 lines)
- active legacy GUI shim:
  - `src/gui/main_window.py`
- dynamic reflection remains common in active runtime paths:
  - `src/gui/controllers/learning_controller.py`
  - `src/gui/preview_panel_v2.py`
  - `src/controller/job_service.py`
- documentation contradiction:
  - `docs/DOCS_INDEX_v2.6.md` still points Tier 3 Learning to `v2.5`
  - `docs/Learning_System_Spec_v2.6.md` already exists
  - `docs/StableNew_Coding_and_Testing_v2.6.md` mandates Pydantic everywhere, but the codebase currently uses none
- test fragmentation:
  - root-level `test_*.py` files outside `tests/`
  - `pytest.ini` collects only `tests/`
  - `pytest.ini` also ignores `tests/gui/`
- CI masking:
  - `.github/workflows/ci.yml` uses `ruff check src || true`
  - `.github/workflows/ci.yml` uses `pytest ... || true`
- runtime persistence coupled to repo working tree:
  - `src/learning/learning_paths.py`
  - `data/learning/experiments/`
  - `data/photo_optimize/assets/`
  - `state/*.json`
- active instruction surface sprawl:
  - `AGENTS.md`
  - `.github/copilot-instructions.md`
  - `.github/agents/`
  - `.github/instructions/`

## 3. Top 10 Issues

### Issue 1: Oversized God Modules In Critical Paths
Active GUI, controller, and execution files are too large and multi-purpose, increasing regression risk and slowing safe change.

Initial COA:
- break large files into smaller modules by subsystem responsibility

Top 5 weaknesses:
1. naive splitting can create churn without improving architecture
2. broad refactors can destabilize runtime wiring
3. tests may be too coupled to current file internals
4. teams may stop halfway and leave new seams plus old logic
5. file-size-only decomposition can produce poor abstractions

Revised COA:
- extract behavior-preserving seams first
- introduce service/contract modules before moving logic
- cap each PR to one vertical slice
- require regression tests before/after each extraction

### Issue 2: Legacy GUI Shim And Compatibility Drift Remain Active
`src/gui/main_window.py` is still an active compatibility shim and monkeypatches `MainWindowV2`, contradicting the no-shims / no-legacy-path stance.

Initial COA:
- delete the shim and move all callers to `MainWindowV2`

Top 5 weaknesses:
1. hidden tests and helper harnesses still import the shim
2. packaging/entrypoint assumptions may still depend on the legacy path
3. abrupt removal could break external scripts
4. GUI tests may rely on compatibility methods
5. deleting first makes diagnosis harder if consumers were missed

Revised COA:
- inventory all remaining shim consumers
- migrate tests/helpers first
- cut over explicit entrypoints
- then delete the shim in a dedicated cleanup PR

### Issue 3: Reflection-Based Wiring Persists In Runtime Paths
Dynamic `getattr`/probing remains common in active code even though the canon now expects explicit controller APIs and typed wiring.

Initial COA:
- ban reflection everywhere immediately

Top 5 weaknesses:
1. too broad to land safely
2. many tests use stubs that rely on loose contracts
3. not all reflection is equally harmful
4. removing all reflection at once would create high merge pressure
5. utility/model introspection would get swept up with runtime wiring

Revised COA:
- target runtime orchestration first
- replace reflection in high-risk paths with explicit ports/contracts
- leave benign data-model introspection for later or document exceptions

### Issue 4: Canonical Documentation Is Contradictory In Places
The docs index, subsystem specs, and coding standards do not fully agree with one another or with the implementation.

Initial COA:
- rewrite all docs in one massive harmonization pass

Top 5 weaknesses:
1. too broad and slow
2. high chance of introducing new contradictions
3. difficult to approve as one unit
4. cannot easily verify the entire set at once
5. mixes governance, implementation, and archival cleanup together

Revised COA:
- create a canonical-document reconciliation PR
- fix only active contradictions first
- add a document ownership map and contradiction checklist

### Issue 5: Agent Guidance Surface Is Fragmented
Machine-facing guidance is spread across multiple active surfaces, increasing the chance of instruction drift.

Initial COA:
- collapse everything into one file

Top 5 weaknesses:
1. one file becomes too long to maintain
2. path-specific nuance would be lost
3. archived guidance may remain referenced elsewhere
4. external tooling may expect current file locations
5. a single mega-file is hard to update safely

Revised COA:
- establish one active instruction manifest
- keep scoped appendices where needed
- archive or mark superseded files explicitly

### Issue 6: Test Suite Layout Is Fragmented And Partially Unrun
Important tests live outside collected paths or under ignored directories, so the effective test surface is unclear.

Initial COA:
- move every stray test immediately into the canonical hierarchy

Top 5 weaknesses:
1. large noisy moves obscure behavior changes
2. many root tests may be experimental or obsolete
3. GUI/Tk tests may require separate treatment
4. immediate normalization may produce many red builds
5. test renames can disrupt history and blame

Revised COA:
- first classify tests into active, quarantine, or archive
- then move active tests into canonical locations
- eliminate silent ignores gradually and intentionally

### Issue 7: CI Enforcement Is Not Credible
The main CI workflow masks both lint and test failures with `|| true`, so green CI is not a reliable signal.

Initial COA:
- remove all masking immediately

Top 5 weaknesses:
1. current flakes may block all branches
2. contributors may lose velocity if the suite is not partitioned
3. GUI/Tk dependencies may still be brittle in CI
4. full-suite enforcement may be too expensive as a first step
5. hard fail without triage creates a flood of unrelated breakage

Revised COA:
- split CI into required fast gates and optional broader gates
- remove masking from the required subset first
- quarantine known flakes with explicit tracking instead of silent pass-through

### Issue 8: Runtime Persistence Is Coupled To The Repo Working Tree
Learning sessions, photo assets, and UI state persist under the repository root, which mixes source, fixtures, and runtime artifacts.

Initial COA:
- move all runtime data outside the repo immediately

Top 5 weaknesses:
1. path migration can break local expectations
2. tests may assume current relative paths
3. docs and tooling currently point to repo-local locations
4. external override behavior needs a clear design
5. moving paths and cleaning VCS hygiene together may be too much at once

Revised COA:
- first centralize path resolution behind a workspace service
- keep current defaults initially
- then add external-workspace override support and separate fixture/runtime policy

### Issue 9: Learning Analytics Contract Is Incomplete
The Learning UI captures richer structured ratings, but the recommendation layer still mostly consumes aggregate scores. The evidence policy also creates recommendation dead zones for users.

Initial COA:
- rewrite the recommendation engine completely

Top 5 weaknesses:
1. too risky relative to current stability
2. existing records need backward compatibility
3. opaque new scoring logic would reduce trust
4. full rewrite would mix evidence policy, schema, and ranking all at once
5. hard to validate without first stabilizing recommendation semantics

Revised COA:
- first reconcile evidence policy and contract expectations
- then incrementally consume structured rating detail with conservative weighting
- preserve aggregate fallback and explicit evidence tiers

### Issue 10: GUI Ownership And Migration Boundaries Are Unclear
`src/gui`, `src/gui_v2`, legacy tests, and migration-prep work do not yet map to a single clear ownership model.

Initial COA:
- move all V2 code into `src/gui_v2` immediately

Top 5 weaknesses:
1. mass file moves create noisy diffs
2. import churn would be large
3. PySide6 migration plans may change the desired final layout
4. tests/docs currently reference existing paths
5. folder moves alone do not fix boundaries

Revised COA:
- define ownership rules first
- freeze placement for new files
- then move files in planned batches only where the move reduces ambiguity materially

## 4. Final Ranked COAs

1. Extract seams from oversized god modules without behavior change.
2. Retire the active legacy GUI shim and its test dependencies.
3. Replace reflection-heavy runtime wiring with explicit ports/contracts.
4. Reconcile canonical documentation contradictions and ownership.
5. Consolidate the active agent instruction surface.
6. Normalize the test suite layout and collected surface.
7. Restore credible CI gating by removing silent pass-through.
8. Introduce a workspace-path abstraction for runtime persistence.
9. Reconcile and strengthen the Learning analytics contract.
10. Define and clean up GUI ownership/migration boundaries.

## 5. Planned PR Sequence

This discovery feeds the following PR specs:

1. `PR-CORE-ARCH-047-Core-Seam-Extraction-and-Module-Caps.md`
2. `PR-CLEANUP-GUI-048-Retire-Legacy-MainWindow-Shim.md`
3. `PR-CORE-ARCH-049-Explicit-Ports-Over-Reflection.md`
4. `PR-DOCS-050-Canonical-Documentation-Reconciliation.md`
5. `PR-PROCESS-051-Agent-Instruction-Surface-Consolidation.md`
6. `PR-TEST-052-Test-Suite-Normalization-and-Collection-Audit.md`
7. `PR-CI-053-Restore-Credible-CI-Gates.md`
8. `PR-CORE-054-Workspace-Path-Abstraction-and-Runtime-Boundary.md`
9. `PR-CORE-LEARN-055-Learning-Analytics-Contract-Reconciliation.md`
10. `PR-GUI-056-GUI-Ownership-and-Migration-Boundary-Cleanup.md`

## 6. Recommendation

Execute the PRs broadly in this order:

Phase A:
1. PR-050
2. PR-051
3. PR-052
4. PR-053

Phase B:
5. PR-047
6. PR-049
7. PR-048

Phase C:
8. PR-054
9. PR-055
10. PR-056

Rationale:
- fix governance/docs/test signal first
- then tackle code structure and runtime wiring
- then clean persistence, learning analytics, and GUI ownership with clearer constraints
