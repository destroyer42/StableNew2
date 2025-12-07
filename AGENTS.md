AGENTS.md — StableNew v2.5 LLM Governance File

#CANONICAL
(This document governs ChatGPT, Copilot Chat, and all LLM agents interacting with the repo.)

Executive Summary (8–10 lines)

This file defines how AI agents must behave when generating code, analyzing architecture, or producing PRs for the StableNew project.
Agents must follow the canonical documentation set (Architecture_v2.5, Governance_v2.5, Roadmap_v2.5, etc.) and must never reference archived docs.
Agents must not guess or infer architecture — they must request snapshots when file contents or structure are unclear.
Subsystem boundaries (GUI → Controller → Pipeline → Queue → Runner) are strictly enforced to prevent drift and regression.
All PRs must follow the project’s PR template, include required tests, and respect risk tier classifications.
This file ensures AI-generated contributions remain deterministic, safe, maintainable, and consistent with StableNew’s long-term design.

PR-Relevant Facts (Quick Reference)

Canonical docs = *-v2.5.md + #CANONICAL header.

Archived docs = #ARCHIVED → must be ignored completely.

AI agents must request latest repo snapshot + repo_inventory.json before producing code.

Every PR must include tests and follow the official structure.

No agent may modify pipeline execution, stage order, or queue semantics without explicit approval.

Agents must strictly honor subsystem boundaries.

============================================================

1. Purpose of AGENTS.md

============================================================

This document provides:

A unified rule set for ChatGPT, Copilot Chat, and any automated agents.

A consistent interpretation of canonical documentation.

Safeguards to prevent structural or architectural drift.

Guardrails for code generation, refactoring, and PR assistance.

A stable baseline for all future LLM-based development.

It must be consulted before producing any code or PR.

============================================================

2. Canonical Documentation Rule

============================================================

AI agents may only rely on the following documents in the /docs directory:

Canonical Documents (Authoritative)

DOCS_INDEX_v2.5.md

ARCHITECTURE_v2.5.md

Governance_v2.5.md

Roadmap_v2.5.md

StableNew_Agent_Instructions_v2.5.md

StableNew_Coding_and_Testing_v2.5.md

Randomizer_Spec_v2.5.md

Learning_System_Spec_v2.5.md

Cluster_Compute_Spec_v2.5.md

Agents must ignore:

Any document starting with #ARCHIVED

Any document in docs/archive/

Any pre-v2.5 documentation

Any automatically generated docs not marked canonical

If a user quotes or references legacy material, the agent must reinterpret it using the canonical v2.5 constraints.

============================================================

3. Snapshot Discipline

============================================================

Before modifying or generating code:

Agents must ask for the latest repo snapshot + repo_inventory.json when unsure.

Agents must not rely on memory of past versions.

Agents must not hallucinate file locations or contents.

If uncertain:

“Please upload the latest snapshot and repo_inventory.json so I can reference the correct file structure.”

============================================================

4. Subsystem Boundaries (Strict Enforcement)

============================================================

AI agents must understand and respect the StableNew v2.5 architecture:

4.1 GUI Layer

Creates widgets, panels, callbacks.

May read/write AppState.

Must not run pipeline or queue logic.

Must not construct jobs or variants.

4.2 Controller Layer

Orchestrates actions: build jobs, submit queue, update preview.

Must call ConfigMergerV2 → JobBuilderV2 → JobService.

Must not embed merging or pipeline logic.

4.3 Pipeline Layer

Pure logic: config merging, randomizer, job building.

No GUI imports.

No queue imports.

No mutation of global state.

4.4 Queue Layer

State machine for job execution.

Manages pending/running/completed jobs.

Must not alter run configs or build jobs.

4.5 Runner Layer

Executes the pipeline deterministically in canonical stage order.

No randomization, no config mutation.

Must not change job identity or metadata.

Violating any boundary requires AI to refuse the request.

============================================================

5. PR Requirements for AI Agents

============================================================

Every PR MUST include:

Title

Summary

Problem statement

Intent / rationale

Allowed files

Forbidden files

Step-by-step implementation

Required tests

Acceptance criteria

Rollback plan

Risk Tier assignment

Agents must NEVER:

Mix refactors + feature changes in the same PR.

Produce PRs that cross subsystem boundaries.

Modify test behavior without explicit justification.

============================================================

6. Coding Standards for AI Agents

============================================================

AI-generated code must follow:

@dataclass usage for structured data.

Purity rules (no side effects).

Immutability principles for configs.

Deterministic behavior across executions.

Clear naming conventions.

No floating logic between layers.

Only documented APIs may be used.

Agents must ensure:

Pipeline logic is pure and isolated.

Controller logic invokes correct helpers.

GUI logic never mutates configs beyond AppState.

============================================================

7. Testing Standards

============================================================

AI agents MUST create tests when modifying logic:

Unit Tests

For RandomizerEngineV2

For ConfigMergerV2

For JobBuilderV2

For NormalizedJobRecord conversions

Integration Tests

For PipelineControllerV2

For JobService interactions

GUI Tests (Behavior)

On Randomizer panel

On Preview panel

On Queue panel

Principles

Write failing tests first

Cover edge cases

Maintain existing behavior unless spec updates

============================================================

8. When AI Must Ask for Clarification

============================================================

AI must pause and request clarification when:

Requested behavior contradicts canonical docs.

File structure is missing or ambiguous.

Snapshot is unavailable.

Request touches executor/runner internals.

User proposes breaking subsystem boundaries.

AI must respond:

“This request conflicts with canonical architecture/governance.
Please clarify or adjust the design.”

============================================================

9. Forbidden Actions for AI Agents

============================================================

Agents must never:

Invent new modules or APIs without user approval.

Change the job lifecycle.

Add or remove pipeline stages.

Modify stage ordering.

Embed business logic in GUI components.

Override seeds or randomizer logic.

Alter queue or runner semantics.

Modify canonical docs without updating DOCS_INDEX_v2.5.md.

Use archived documentation.

============================================================

10. Drift Detection and Self-Check

============================================================

Before producing any answer, the AI must verify:

Am I using ONLY canonical v2.5 docs?

Am I respecting subsystem boundaries?

Am I avoiding hallucinated file paths or structures?

Should I request a snapshot?

Does the PR include tests?

Did I follow the StableNew PR template?

Am I accidentally modifying stage ordering or pipeline semantics?

If any answer is no, the agent must NOT produce the code.

============================================================

11. Versioning & Documentation Rules

============================================================

Canonical docs must end with v2.5.md.

Any architecture or governance changes must update:

DOCS_INDEX_v2.5.md

The corresponding subsystem spec

AI must not introduce undocumented behaviors.

============================================================

12. Escalation Protocol (Unsafe Request Handling)

============================================================

When user requests:

Runner internal modification

Queue algorithm changes

Pipeline semantics alteration

Multi-subsystem refactor

Behavior contradicting specs

AI must reply:

“This request is unsafe or violates canonical architecture.
Here is why, and here are compliant alternatives…”

No exceptions.

End of AGENTS.md

#CANONICAL