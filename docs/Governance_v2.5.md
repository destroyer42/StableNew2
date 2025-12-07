#CANONICAL
GOVERNANCE_v2.5.md
(This is the authoritative policy and governance document for StableNew v2.5.
Agents must not reference any other governance document.)

Executive Summary (8–10 lines)

StableNew v2.5 governance defines how contributors, maintainers, and AI agents collaborate safely, predictably, and consistently.
It establishes clear rules for PR creation, subsystem boundaries, architectural invariants, test requirements, documentation expectations, and long-term stability guarantees.
This governance file separates human-facing rules from AI agent execution instructions (which live in StableNew_Agent_Instructions_v2.5.md) to minimize ambiguity and drift.
The governance model ensures that every change is layered, tested, traceable, reversible, and consistent with canonical architecture.
All development follows a "Single Source of Truth" design: Architecture_v2.5, Governance_v2.5, Roadmap_v2.5, and the LLM Access Layer define allowed operations.
Stage ordering, job normalization, queue semantics, and interaction boundaries are strictly enforced.
This document provides PR guardrails, development doctrine, risk-tier rules, and subsystem ownership definitions that prevent architectural regressions and broken UI/UX paths.
It is binding for all current and future phases of StableNew development.

PR-Relevant Facts (Quick Reference)

Canonical governance lives only here; older versions are archived.

A PR must never violate:
Architecture_v2.5, JobSpec pipeline path, Queue-first execution model, Subsystem boundary rules, or LLM Access Layer.

Tests are mandatory for any change that affects logic, merging, building, queueing, or user-visible behavior.

No PR may introduce a second source of truth for configs, queue state, job metadata, or pipeline sequencing.

Agents should consult this governance file before generating PRs.

Humans should reference this file when performing reviews or validating PR correctness.

============================================================

0. TLDR / BLUF — Concise Governance Summary (Option C Layer)

============================================================

This section exists for rapid human and AI consumption.

0.1 What Governance Controls in StableNew v2.5

Governance defines:

How PRs are structured

What boundaries developers must respect

Required tests and validation

What documents are canonical

What subsystems may interact

How to avoid architectural drift

How LLM agents must behave when generating diffs or PRs

Governance does not define runtime behavior — that is handled by architecture.

0.2 Most Important Rules (Top-Level)

Architecture-first development
No change may contradict ARCHITECTURE_v2.5.md.

Single job construction path
All jobs must pass through:
RunConfig → PipelineConfigAssembler + ConfigMergerV2 → JobBuilderV2 → JobSpecV2 → JobService → Queue → Runner

Queue-first execution
Direct mode is allowed but queue semantics must remain canonical.

Subsystem boundaries must be respected:
GUI ↔ Controllers ↔ Pipeline ↔ Queue ↔ Runner.

Every PR requires tests: unit + integration if affected.

Only documents marked #CANONICAL may be used for decision-making.

Rollback paths are mandatory for all changes.

0.3 TLDR PR Guardrails

PRs must define: scope, files modified, forbidden files, test plan, rollback.

No PR may modify main.py, runners, or executor unless approved by roadmap.

GUI PRs may not define pipeline logic.

Pipeline PRs must remain pure and GUI-independent.

Controllers may not bypass services or manipulate queue internals.

Randomizer modifications must preserve deterministic output.

0.4 TLDR Risk Tiers

Tier 1 — Low
Visual/UI-only, minor attribute updates.

Tier 2 — Medium
Controller logic, config assembly, builder paths.

Tier 3 — High
Pipeline runner, executor, queue persistence, asynchronous behavior.

A Tier dictates guardrail strictness.

0.5 TLDR Documentation Governance

Canonical docs are versioned with suffix v2.5.md.

Older docs must be archived under /docs/archive/ and marked #ARCHIVED.

Every canonical file must begin with an executive summary + PR-Relevant facts.

============================================================

1. Purpose of Governance

============================================================

Governance ensures StableNew develops in a predictable, stable, reversible, and testable manner.

Its responsibilities:

Maintain architectural integrity across PRs.

Ensure contributors follow the same boundaries and expectations.

Prevent regression loops and context drift.

Keep AI agents aligned with human intent.

Provide test coverage guidelines.

Manage risk across complex subsystems.

Maintain documentation consistency and hierarchy.

StableNew is a long-lived product, not a set of scripts — governance ensures professional-grade engineering discipline.

============================================================

2. Governance Scope & Exclusions

============================================================

Included:

PR structure

Boundary rules

Documentation rules

Testing standards

Rollback rules

Risk tiering

LLM access rules

Contributor expectations

Excluded:

Runtime architecture details (see Architecture_v2.5.md)

Roadmap sequencing (see Roadmap_v2.5.md)

Agent instruction specifics (in StableNew_Agent_Instructions_v2.5.md)

============================================================

3. Subsystem Ownership Rules

============================================================

Subsystems:

GUI Layer

Controllers

Pipeline Builder Layer

Job/Queue Layer

Runner Layer

Learning Layer (Phase 2+)

Cluster Layer (Phase 3+)

Ownership Principles:

3.1 GUI Layer

Owns widgets, layout, styling, and AppState.

Must not contain pipeline construction logic.

Cannot interact with queue directly except through controller APIs.

3.2 Controllers

Central integrators.

Communicate GUI → Pipeline → Queue.

Must not implement pipeline merging or runner logic.

Must not contain hard-coded stage sequencing.

3.3 Pipeline Builder Layer

Owns ConfigMergerV2, overrides, Randomizer integration, JobBuilderV2.

Must remain pure and GUI-independent.

Receives only typed dataclasses, never Tk objects.

3.4 Job/Queue Layer

Owns job lifecycle, executing queue semantics, job states.

Controllers can request queue actions but may not manipulate queue internals.

3.5 Runner Layer

Executes canonical pipeline order.

Must remain stable and rarely changed.

Cannot be modified in GUI PRs.

3.6 Learning Layer

Must not influence job construction.

Receives post-run signals only.

3.7 Cluster Layer

Owns distributed scheduling only.

Must depend on normalized jobs exclusively.

============================================================

4. PR Structure and Requirements

============================================================

Every PR must include:

4.1 Required Sections

Title

Intent / Summary

Problem Statement

Solution Overview

Allowed Files

Forbidden Files

Step-by-Step Implementation

Tests Required (Failing First)

Acceptance Criteria

Rollback Plan

Risk Tier

4.2 Additional Requirements

PRs modifying pipeline behavior must include tests.

GUI PRs modifying widgets must include screenshot or behavior tests where possible.

Controllers must include integration tests.

Queue modifications must include ordering and lifecycle tests.

4.3 Forbidden in All PRs

Introducing new “magic paths” that bypass canonical flow.

Creating second config systems.

Mutating JobSpec or PipelineConfig after queue submission.

Adding new stage types without architecture discussion.

============================================================

5. Subsystem Boundary Enforcement

============================================================

Governance enforces strict boundaries:

5.1 GUI ↔ Controller Boundary

GUI cannot:

Build PipelineConfig

Call JobService directly

Execute runner code

Perform randomization logic

5.2 Controller ↔ Pipeline Boundary

Controller cannot:

Perform config merging (must call ConfigMergerV2)

Implement randomizer (must call RandomizerEngineV2)

Modify queue internals

Modify JobSpec post-creation

5.3 Pipeline ↔ Queue Boundary

Pipeline cannot:

Know about queue ordering or running state

Know about GUI

Queue cannot:

Modify PipelineConfig

Modify job metadata structure (only state/ordering)

============================================================

6. Risk Tier System (Tier 1–3)

============================================================

Tier 1 — Low Risk

Minor visual changes, dark mode corrections, layout polish.
Tests: visual consistency checks or widget existence.

Tier 2 — Medium Risk

Controllers, merging logic, job building, part of queue UI.
Tests: unit + integration + snapshot where needed.

Tier 3 — High Risk

Runner modifications, queue persistence, async behavior, learning hooks.
Tests: full suite required.
Approval: must be reviewed by architecture owner.

============================================================

7. Testing Governance

============================================================

Every PR must include failing-first tests.

7.1 Required Test Types

Unit Tests for pure logic

Integration Tests for controller → queue paths

GUI Tests for panel behavior

End-to-End Tests for PR-204+ series work

Snapshot Tests where relevant

7.2 CI Requirements

No PR may merge with failing tests

No modification of “expected failure” tests without explicit approval

7.3 Coverage Expectations

Pipeline logic: near 100%

GUI: selective but important behavior paths

Queue: ordering, lifecycle, persistence tests (Phase 3)

============================================================

8. Documentation Governance

============================================================

8.1 Canonical Docs

Each canonical doc must:

Begin with #CANONICAL

Include executive summary

Include PR-Relevant Facts

Have stable filename ending in v2.5.md

8.2 Archived Docs

Must be placed in /docs/archive/
Must begin with #ARCHIVED
Not used by agents for reasoning.

8.3 Index Governance

DOCS_INDEX_v2.5.md defines allowed docs and access rules.

============================================================

9. LLM Access Layer Governance

============================================================

LLMs must follow:

Only use canonical docs

Ignore any file marked #ARCHIVED

Always consult index file

Prefer summaries and PR-Relevant Facts sections for context

Follow architectural boundaries

Never invent missing files; ask for snapshot instead

Always prefer single-source-of-truth files

This prevents drift, hallucination, and invalid PR generations.

============================================================

10. Change Management & Rollback Requirements

============================================================

Every PR must:

Identify breaking changes

Provide rollback instructions

Ensure data migration safety

Avoid destructive behavior by default

Rollback Plans must be:

Executable

Reversible

Testable

============================================================

11. Conflict Resolution & Canonical Precedence

============================================================

If two documents conflict:

Architecture_v2.5.md has highest precedence.

Governance_v2.5.md is next.

Roadmap_v2.5.md is next.

A PR spec is never authoritative unless canonical docs are updated.

============================================================

12. Deprecated Concepts (Archived)

============================================================
#ARCHIVED
(Informational only — agents must ignore this section for decision-making.)

Deprecated:

V1 governance model (largely undocumented, ad-hoc decisions)

Monolithic MainWindow governance from V1

Previously used ad-hoc randomizer rules

V1 runner config semantics

Old non-normalized job model

Replaced by v2.5’s normalized, testable, layered system.

End of Governance_v2.5.md