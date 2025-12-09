GOVERNANCE_v2.6.md
StableNew — Canonical Development & Decision-Making Model

Status: Authoritative**
Updated: 2025-12-09

0. Purpose of Governance_v2.6

Governance_v2.6 defines:

How decisions are made

What counts as canonical truth

What LLM agents may and may not do

How PRs must be structured, approved, and executed

How we enforce architectural boundaries

How documentation is updated and validated

How we guarantee deterministic, stable evolution of StableNew

This document is binding on:

Codex (Executor Agent)

ChatGPT (Planner Agent)

All human contributors

All future agents

No PR, code path, or architectural decision may contradict this file.

1. Canonical Truth Hierarchy

StableNew has a strict hierarchy of “sources of truth.”

Changes must follow this priority order:

1.1 Top-Level Canonical Documents (unchallengeable)

ARCHITECTURE_v2.6.md

Roadmap_v2.6.md

Governance_v2.6.md

PromptPack_Lifecycle_v2.6.md

Builder Pipeline Deep-Dive_v2.6.md

DebugHub_v2.6.md

StableNew_Coding_and_Testing_v2.6.md

PR_TEMPLATE_v2.6.md

Agents_v2.6.md

Copilot-Instructions_v2.6.md

If any PR or generated code contradicts these → it must be rejected or rewritten.

1.2 Secondary Canonical References

Randomizer_Spec_v2.6

Learning_System_Spec_v2.6

Cluster Compute Spec v2.6

All PR-CORE specs

These may be updated, but must obey the top-level documents.

1.3 Lowest-Level Truth

Implementation code

Unit and integration tests

E2E golden-path tests

If implementation disagrees with top-level docs, implementation must be changed, never the reverse (unless the design itself is evolving deliberately).

2. Governance Pillars

This governance model ensures StableNew remains:

Deterministic

Testable

Maintainable

Architecturally unified

Free of legacy drift

There are 7 governing pillars.

2.1 Pillar 1 — Single Source of Prompt Truth

Only PromptPacks may supply prompt text.
This is enforced by:

Architecture_v2.6

Builder Pipeline Deep Dive

PromptPack Lifecycle v2.6

PR Template compliance checks

Any PR introducing new prompt sources is automatically rejected.

2.2 Pillar 2 — NJR as the Sole Execution Format

All controllers, runners, queues, and debug tooling operate exclusively on:

NormalizedJobRecord (NJR)

No alternate job format is allowed.
Any additional formats → must be deleted.

2.3 Pillar 3 — Deterministic Builder Pipeline

The builder pipeline is the only path for job construction.
Any deviation → governance violation.

Tests must enforce determinism across:

randomizer variants

sweep variants

stage chains

seed allocation

config merges

2.4 Pillar 4 — Zero Tech-Debt Drift

StableNew employs a simple rule:

No PR may create, preserve, or expand tech debt.
If tech debt is encountered, it must be resolved immediately.

Required:

All legacy paths must be deleted

All partial migrations must be resolved

All “temporary shims” are forbidden

Any discrepancy triggers a TECH-DEBT section in the PR

Failure to comply = PR rejection.

2.5 Pillar 5 — Strict Subsystem Boundaries

Subsystems must never violate boundaries:

GUI

may display NJR summaries

may emit PackJobEntry selections

must never construct prompts/configs

Controllers

orchestrate operations

never modify NJRs

never build configs manually

Builder

exclusive responsible entity for constructing NJRs

Queue

manages lifecycle

consumes NJRs

never mutates them

Runner

executes NJRs

never builds config

never modifies NJRs

DebugHub

introspection only

never shapes execution

Subsystem coupling is a violation punishable by mandatory refactor.

2.6 Pillar 6 — Golden Path Compliance (Non-Negotiable)

The 12 Golden Path tests represent:

The minimum acceptable definition of a functional StableNew pipeline.

Every PR must pass:

Unit tests

Integration tests

Golden Path tests

If a PR breaks Golden Path → revert or reject.

2.7 Pillar 7 — Mandatory Documentation Sync

Documentation is part of the codebase.
Every PR must:

update the relevant canonical documents

keep architecture consistent

include diagrams where appropriate

update the PR template checklist

If a PR changes behavior without updating docs → reject.

3. LLM Agent Governance

StableNew development uses two cooperating agents:

ChatGPT (Planner Agent)

Codex (Executor Agent)

Governance mandates their roles.

3.1 ChatGPT Planner (High-Level Reasoner)

ChatGPT MUST:

Generate PR specs

Produce architecture documents

Ensure subsystem boundaries

Validate reasoning against canonical docs

Never generate code directly unless building test stubs

Never bypass the PR workflow

Never encourage shortcuts that produce drift

ChatGPT MUST NOT:

modify the repository

produce final implementation code

contradict governance documents

3.2 Codex Executor (Implementation Engine)

Codex MUST:

implement PRs strictly as written

delete legacy code instead of preserving it

update tests & documentation

follow the architectural boundaries

correct structural weaknesses during implementation

reject incomplete specs

Codex MUST NOT:

infer architecture from outdated code

create new execution pathways

leave TODOs, partial migrations, or temporary hacks

accept ambiguous PRs

If Codex identifies ambiguity → it must request clarification through the PR spec.

3.3 Interaction Rules

ChatGPT writes PR specs → Codex executes

Codex never writes architecture docs

ChatGPT never directly modifies code

Both agents must obey Architecture_v2.6 above all else

All design changes must pass through governance review

4. PR Governance

PR Template v2.6 is mandatory.
Every PR must include:

Intent

Architectural impact

File modification list

Step-by-step implementation plan

Test plan

Documentation plan

TECH-DEBT IMPACT analysis

Rollback plan

PRs must always:

reduce code surface area

remove unused code

simplify subsystem responsibilities

improve determinism

increase test coverage

clarify architecture

Forbidden PR behaviors:

adding new system states

ambiguous builder logic

new prompt sources

partial refactors

“quick fixes” that bypass architecture

undocumented changes

5. Release Governance

StableNew uses semantic versioning for architecture:

v2.6 — Deterministic Core Recovery

v2.7 — Enhanced Diagnostics & Learning

v3.0 — Cluster Execution & Distributed Learning

Every release must meet the following:
Requirement	Description
Canonical Docs Updated	All v2.6 docs validated
Tech Debt Near-Zero	No major leftover debt
Golden Path Green	All 12 tests pass
GUI V2 Complete	No V1 code present
PromptPack Lifecycle Clean	No duplicate prompt paths
Builder Deterministic	Verified via hashing
6. Governance Enforcement Rules

Governance_v2.6 is binding.
Violations require immediate correction.

6.1 Automatic Violations

If a PR:

introduces prompt drift

creates a second builder path

constructs configs in GUI

mutates NJR

bypasses Queue

adds new legacy compatibility layers

introduces nondeterminism

leaves dead code

contradicts Architecture_v2.6

→ PR is automatically rejected or must be rewritten.

6.2 Continuous Refactor Mandate

If governance is violated by existing code:

Contributors are obligated to eliminate the violation

The fix must occur before merging new features

7. Amending Governance

Governance may only be updated when:

Reason reviewed by ChatGPT Planner

Architectural impact evaluated

Roadmap alignment confirmed

PR explicitly titled PR-GOVERNANCE-X

Full system-wide reasoning documented

Governance cannot drift silently.

8. Summary

Governance_v2.6 ensures:

StableNew remains predictable, testable, and maintainable

Architecture stays unified and pure

NJR remains the only execution format

PromptPack remains the only prompt source

Builder remains deterministic

PRs remain disciplined

Tech debt is aggressively eliminated

Agents operate within strict, non-overlapping roles

Documentation stays in sync with code

StableNew succeeds only when every subsystem, every PR, and every agent follows Governance_v2.6.

END — Governance_v2.6 (Canonical Edition)