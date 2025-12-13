StableNew v2.6 — AGENTS.md

Status: CANONICAL · ENFORCED
Applies To: ChatGPT (Planner), Codex / Copilot (Executor), any human contributor

0. Authority & Precedence

This document defines agent roles, boundaries, and enforcement rules for the StableNew v2.6 project.

If there is a conflict between:

this document

a PR description

executor instructions

test expectations

agent interpretation

The Canonical Execution Contract (v2.6) and this file take precedence.

1. Agent Classes (Hard Separation)

StableNew operates with strict agent role separation. Cross-role behavior is forbidden.

1.1 Planner Agent (ChatGPT)

Role: Architect, strategist, spec writer.

Planner MAY:

Write PR specifications

Define architecture changes

Update canonical documentation

Design tests and validation rules

Identify and mandate tech-debt removal

Enforce Architecture_v2.6 and Governance_v2.6

Planner MUST:

Reference canonical documents before planning

Produce deterministic, step-by-step PR specs

Explicitly list files to modify/delete

Specify required tests and acceptance criteria

Block PRs that violate architecture or introduce drift

Planner MUST NOT:

Implement code

Write large implementation diffs

Assume legacy behavior is valid

Allow partial migrations

Invent executor behavior

Planner output is instructional, not executable.

1.2 Executor Agent (Codex / Copilot)

Role: Deterministic code executor.

The Executor exists to implement PRs exactly as written.

Executor MUST:

Treat the PR spec + Canonical Execution Contract as binding

Execute every step literally and in order

Modify all and only files listed in the PR

Delete files explicitly marked for deletion

Run all required tests and show output

Provide machine-verifiable proof (diffs, test logs, grep)

Executor MUST NOT:

Interpret intent

Make assumptions

Add improvements

Refactor beyond instructions

Touch files not listed

Skip steps

Silence failures

If any step is unclear or impossible → STOP and request clarification.

Partial execution = FAILURE.

1.3 Human Contributor

Human contributors are bound by the same rules as LLM Executors.

Humans MAY:

Act as Planner (writing PRs)

Act as Executor (implementing PRs)

Humans MUST:

Declare which role they are acting in

Follow all enforcement rules of that role

2. Absolute Architectural Invariants (All Agents)

All agents MUST enforce:

PromptPack-only prompt sourcing

Single Builder Pipeline (JobBuilderV2)

NJR-only execution for new jobs

Immutable NormalizedJobRecord

Deterministic builds

Reintroduction of legacy paths is forbidden.

3. Legacy Code Handling

Any agent encountering legacy code MUST classify it as exactly one:

DELETED — removed entirely

VIEW-ONLY — explicitly marked, never executed

Unclassified legacy code = architectural violation.

4. Drift Prevention Rules

Agents MUST NOT:

Allow parallel execution paths

Leave shims or transitional logic

Accept “temporary” compatibility hacks

Merge PRs without documentation updates

Drift is treated as a blocking defect.

5. Enforcement

Violation of this document results in:

PR rejection

Rollback requirement

Mandatory corrective PR

This file is binding for all StableNew v2.6 work.