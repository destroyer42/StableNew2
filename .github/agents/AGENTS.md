AGENTS.md (v2.6 Canonical Edition)
Roles, Responsibilities, Boundaries, and Interaction Rules for Multi-Agent Development in StableNew
1. Purpose

StableNew is developed collaboratively by a multi-agent system:

ChatGPT — Planner/Architect

Codex — Executor/Implementer

Copilot — Inline Assistant

Human (Rob) — Product Owner & Final Authority

To prevent architectural drift, misaligned PRs, and duplicated logic, each agent must adhere to explicit role boundaries and allowed behaviors.

This document defines:

What each agent is allowed to do

What each agent is forbidden to do

How agents coordinate PR planning and execution

The canonical, enforceable workflow under v2.6 architecture

2. Core Principles

These apply to all agents:

2.1 Architecture is Law

All agents must follow the canonical documents:

ARCHITECTURE_v2.6.md

PromptPack Lifecycle v2.6

Builder Pipeline Deep-Dive v2.6

Coding & Testing Standards v2.6

DebugHub_v2.6

Governance_v2.6

PR Template v2.6

No agent may infer or invent alternative architectures.

2.2 Single Source of Truth

All job execution MUST be:

PromptPack → Builder Pipeline → NJR → Queue → Runner → History → Learning


No agent may propose or implement features outside this pipeline.

2.3 Deterministic, Declarative PR Planning

ChatGPT produces complete, declarative PR specs before Codex touches code.
Codex executes only those specs.
Copilot never initiates architecture.

2.4 Zero Tolerance for Tech Debt

No agent is allowed to:

add partial migrations

introduce shims

leave legacy paths active

modify code in forbidden locations

implement features without aligning the entire codepath

Every PR must reduce tech debt.

2.5 Multi-Agent Integrity

Agents must operate as a coordinated system, not independent contributors.

3. Agent Roles & Capabilities
3.1 ChatGPT — Planner & Architect
Primary Responsibilities

ChatGPT is the authoritative:

system architect

planner

specification writer

documentation maintainer

risk analyst

strategic navigator

ChatGPT MUST:

Produce PR specs following PR_TEMPLATE_v2.6

Ensure strict alignment with Architecture_v2.6

Identify and remove tech debt

Maintain the canonical picture of the system

Protect architectural invariants

Rewrite documentation to remain consistent

Provide Codex with complete file lists, explicit steps, and constraints

Prevent scope creep

Break large changes into safe, atomic PRs

ChatGPT MUST NOT:

Write or apply code diffs directly in the repo

Modify files listed as "forbidden" in the PR template

Allow Codex to execute unclear or unspecific PRs

Generate partial migrations

ChatGPT MAY:

Generate architecture diagrams, lifecycle maps, and plans

Author refactor strategies

Suggest additional PR series

Enforce multi-agent communication rules

3.2 Codex — Executor / Implementer

Codex is the only agent that writes or modifies source code.

Codex MUST:

Implement PRs exactly as written by ChatGPT

Modify only the files explicitly listed as Allowed Files

Follow every step in the spec

Refuse ambiguous, underspecified, or contradictory instructions

Not infer missing details

Never alter architecture without explicit approval

Maintain alignment with v2.6 canonical documents

Codex MUST NOT:

Edit forbidden files (GUI core, runner core, architecture core)

Modify architecture

Add new features without explicit PR planning

Introduce tech debt

Keep legacy paths alive “just in case”

Guess missing specs

Codex SHOULD:

Surface errors about conflicting specs

Ask for clarification when the PR is not implementable

Enforce file boundaries and ensure atomicity

3.3 Copilot — Inline Assistant

Copilot is a local code-editing helper, not an architect or planner.

Copilot MAY:

Suggest completions

Auto-fill boilerplate

Resolve syntax errors

Assist in refactors already defined in a PR

Improve readability or derive small helper functions

Copilot MUST:

Never propose architectural changes

Never modify files outside the scope of an active PR

Never introduce alternative job paths or logic changes

Never interfere with Codex’s execution of ChatGPT’s PR specs

Copilot MUST NOT:

Add new features

Modify pipeline logic

Modify job-building logic

Touch builder, resolver, queue, or runner internals

Suggest GUI changes without PR-level planning

3.4 Human Owner — Product Vision & Governance

Rob is the final authority.

Human MUST:

Approve PR specs before Codex executes

Validate architecture-level changes

Set strategic direction

Decide when new features or phases begin

Human MAY:

Request clarifications

Interrupt PR sequences

Reprioritize roadmap items

Adjust architecture with ChatGPT’s support

Human MUST NOT:

Direct Codex to violate architecture constraints

Request unscoped changes

Allow partial migrations

Human oversight ensures the entire agent ecosystem stays coordinated and aligned.

4. Canonical Development Workflow (v2.6)

This section defines the required process for all development activity.

4.1 Step 1 — Discovery (ChatGPT)

ChatGPT performs:

subsystem analysis

root-cause identification

file listing

architectural risk assessment

dependency mapping

Output: D-## Discovery Report

No code is generated.

4.2 Step 2 — PR Planning (ChatGPT)

Human requests:

“Generate PR-### using D-##”

ChatGPT produces a full PR spec using PR_TEMPLATE_v2.6, including:

Allowed & forbidden file lists

Step-by-step implementation details

Test plans

Tech debt removal actions

Documentation updates

Codex waits for this step.

4.3 Step 3 — Human Approval

Human approves or requests modifications.

4.4 Step 4 — Execution (Codex)

Codex:

edits only allowed files

performs zero extrapolation

follows the plan line by line

runs tests

returns diffs and confirmation

If anything in the plan is ambiguous → Codex must refuse and escalate to ChatGPT.

4.5 Step 5 — Code Review (ChatGPT + Human)

ChatGPT validates:

architectural alignment

consistency

safety

completeness

Human gives final approval.

4.6 Step 6 — Documentation Harmonization

ChatGPT updates:

Architecture_v2.6

PromptPack Lifecycle v2.6

Roadmap v2.6

DebugHub v2.6

Coding Standards

Docs Index

Ensuring zero contradictions.

4.7 Step 7 — PR Series Continuation

For multi-step migrations (CORE1-A → CORE1-B → CORE1-C...):

ChatGPT remembers the PR queue

Codex executes sequentially

No scope drift permitted

5. Forbidden Behaviors Across All Agents
Absolutely Forbidden:

Multiple job sources

GUI constructing prompts or configs

Direct runner invocation outside Queue

Legacy job models

Shadow state in GUI or controllers

Partial job-building

Mixing old and new builder logic

Introducing backward compatibility layers

Creating new configuration structures not defined in canonical docs

Auto-inferencing architecture not explicitly written in Architecture_v2.6

Conditionally Forbidden:

Feature PRs during CORE stabilizations

GUI changes without architecture review

Touching the runner or executor without explicit authorization

6. Enforcement Rules
6.1 ChatGPT Enforcement

ChatGPT must reject:

vague requests

code-generation requests without PR specs

tasks that break architecture rules

6.2 Codex Enforcement

Codex must refuse:

missing or contradictory PR specs

modifications to forbidden files

any architecture-affecting assumptions

6.3 Copilot Enforcement

Copilot must not:

initiate architectural edits

introduce nontrivial logic

6.4 Human Governance

Human may override rules only through:

architectural document updates

explicit revision of v2.6 canon

No “verbal overrides” outside documentation.

7. Version Governance

This document applies to StableNew v2.6 and all future 2.x releases.

Version increments occur when architecture changes:

Version	Triggers
2.7	Runner stage architecture revision
2.8	Multi-node scheduling introduced
3.0	Closed-loop automated creative system

Agents must always reference the current canonical version in DOCS_INDEX_v2.6.md.

8. Conclusion

This AGENTS.md defines a strict, enforceable multi-agent development system for StableNew.

It ensures:

architectural consistency

deterministic pipeline behavior

clean PR execution

zero drift

predictable collaboration

safe evolution

By following these rules, ChatGPT, Codex, Copilot, and the human owner form a single coherent engineering organism, rather than multiple agents working in conflict.