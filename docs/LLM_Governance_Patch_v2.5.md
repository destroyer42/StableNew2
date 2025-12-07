#CANONICAL
# LLM_Governance_Patch_v2.5.md

**Executive Summary**: This document provides governance rules for AI agents (ChatGPT, Copilot, Codex) interacting with StableNew v2.5. It specifies which docs are canonical, snapshot discipline, subsystem boundaries, and forbidden actions. This is the authoritative AI governance patch for the v2.5 architecture.

---

## PR-Relevant Facts (Quick Reference)

Copilot + ChatGPT must consult only canonical docs ending in v2.5.md with #CANONICAL.

All archived docs (marked #ARCHIVED) are off-limits.

AI agents must request the latest snapshot + repo_inventory.json before writing code.

Every PR must include tests and follow the PR template.

Agents must interpret StableNew's architecture as frozen and authoritative.

Forbidden subsystems (executor, runner internals) require explicit authorization.

AI agents must never silently modify stage ordering, job lifecycle, or pipeline semantics.

============================================================

0. BLUF / TLDR: Hard Rules for All LLMs

============================================================

These are the non-negotiable rules Copilot/ChatGPT must obey at all times:

0.1 Canonical Sources Only

Agents may only use:

DOCS_INDEX_v2.5.md

ARCHITECTURE_v2.5.md

Governance_v2.5.md

Roadmap_v2.5.md

StableNew_Agent_Instructions_v2.5.md

StableNew_Coding_and_Testing_v2.5.md

Randomizer_Spec_v2.5.md

Learning_System_Spec_v2.5.md

Cluster_Compute_Spec_v2.5.md

0.2 Never Invent Architecture or APIs

If a file, function, or class is unclear →
Ask the user for a snapshot, do not guess.

0.3 Obey Subsystem Boundaries

GUI → visual + state, never pipeline logic

Controller → orchestration, never merging logic

Pipeline → pure logic, never queue or GUI

JobService → queue semantics, never building jobs

Runner → execution only, never randomization

0.4 All PRs Must Follow the PR Template

With:

Title

Summary

Problem

Solution

Allowed / Forbidden files

Implementation steps

Required tests

Acceptance criteria

Rollback plan

0.5 AI Must Decline Work When Unsafe

If a user requests something that breaks architecture or subsystem rules, AI must politely refuse or request redesign.

============================================================

1. Scope of Governance Patch

============================================================

This patch applies to:

GitHub Copilot

ChatGPT (GPT-5.1 and successors)

Any local LLM agents

Any automated codemods or refactoring tools

This patch does not modify StableNew architecture — it enforces it.

============================================================

2. Canonical Documentation Access Rules

============================================================

Agents:

2.1 Must load DOCS_INDEX_v2.5.md first

This file defines the valid document set.

2.2 Must ignore all docs/archive/ content
2.3 Must enforce documentation priority

Architecture

Governance

Roadmap

Agent Instructions

Coding & Testing

Subsystem Specs

Snapshot

User request

2.4 Must reject contradictions

If a user request contradicts the docs, AI must:

Explain the conflict → propose compliant alternatives.

============================================================

3. Snapshot Discipline

============================================================

AI MUST:

Request latest snapshot + repo_inventory.json if needed

Never assume file content

Never hallucinate directory structure

If unclear:

“Please upload the latest snapshot and repo_inventory.json.”

AI MUST NOT:

Modify code using memory of old versions

Edit files not present in snapshot

============================================================

4. Subsystem Enforcement (Hard Boundaries)

============================================================

4.1 GUI Layer

AI must ensure:

No pipeline logic appears in GUI

No queue logic appears in GUI

GUI calls controller callbacks only

Dark mode tokens used from theme_v2

4.2 Controller Layer

AI must ensure:

Uses ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord

Delegates to JobService for execution

Never mutates pipeline configs directly

Never handles stage logic internally

4.3 Pipeline Layer

AI must ensure:

Pure logic

No GUI imports

No controller or queue imports

Deterministic merging/building

4.4 Queue Layer

AI must ensure:

Only manages ordering, state transitions, persistence

Never performs config merging

Never modifies job definitions

4.5 Runner Layer

AI must ensure:

Executes pipeline stages exactly in canonical order

Never performs randomization or config mutation

Never interacts with GUI

============================================================

5. PR Guardrails for LLM Agents

============================================================

Agents must:

5.1 Evaluate PR Risk Tier

Tier 1 — GUI-only

Tier 2 — controller, merging logic

Tier 3 — runner, executor, queue integrity

Tier 3 PRs require:

Explicit user permission

Extra tests

Extensive safety notes

5.2 Produce Minimal, Atomic PRs

No combined refactor + feature PRs.

5.3 Follow the PR Template Strictly
5.4 Include Tests

No PR modifying logic may omit tests.

5.5 Forbid Hidden Side Effects

AI must avoid:

Introducing new global state

Modifying unrelated modules

Adding utility functions without justification

============================================================

6. Coding Standards for AI Agents

============================================================

Agents must follow:

StableNew_Coding_and_Testing_v2.5.md

Dataclass usage

No duplicate logic

No untyped dicts for structured data

Pure functions for pipeline logic

Testability first

AI-generated code must:

Be deterministic

Avoid side effects

Avoid direct filesystem writes except where appropriate

Preserve immutability of inputs

============================================================

7. Testing Standards for AI Agents

============================================================

Agents must generate:

7.1 Unit Tests

For pure logic subsystems (mergers, builders, randomizer).

7.2 Integration Tests

For controller + pipeline + queue behavior.

7.3 GUI Behavior Tests

For panel interactions and preview updates.

7.4 Required Patterns

Failing-first tests

Explicit edge-case coverage

Test names must describe behavior

============================================================

8. When AI Must Ask for Clarification

============================================================

If any of the following occur, AI must stop and ask:

Underspecified feature

Missing file structure

Ambiguous architecture impact

Conflicting user instructions

Potential violation of subsystem boundaries

============================================================

9. Forbidden Behaviors

============================================================

AI agents must NOT:

Edit or generate code in runner/executor without authorization

Invent APIs, modules, or entire subsystems

Add new stages to pipeline

Change stage ordering

Bypass JobBuilderV2/ConfigMergerV2

Write business logic into GUI widgets

Remove tests

Modify documentation without updating index

============================================================

10. Versioning Rules

============================================================

All canonical docs must end with v2.5.md.

All major behavioral changes must update:

Architecture

Governance

Roadmap

Relevant subsystem spec

AI may not create new canonical docs unless requested.

============================================================

11. Drift Detection Rules

============================================================

AI must detect and reject:

Randomizer logic appearing in controller

Pipeline logic appearing in GUI

New config fields added without updating:

ConfigMergerV2

JobBuilderV2

JobModelV2

RandomizerPlanV2 (if relevant)

LearningRecordV2 (if relevant)

When detected → AI must warn user and propose remediation.

============================================================

12. Escalation Protocol for Unsafe Requests

============================================================

If a request:

Violates architecture

Breaks job lifecycle

Damages queue semantics

Alters pipeline execution

Undermines determinism

Touches executor/runner without permission

AI must respond:

“This request violates canonical architecture or governance.
Here is the conflict and recommended safe alternatives…”

============================================================

13. Agent Self-Check Before Responding

============================================================

Every AI agent must internally verify:

Am I using canonical docs only?

Does this PR violate subsystem boundaries?

Have I confirmed snapshot access?

Is this PR atomic and test-backed?

Am I introducing architecture drift?

Did I follow the PR template?

If any answer is “no” → AI must pause and ask for guidance.

End of LLM_Governance_Patch_v2.5.md