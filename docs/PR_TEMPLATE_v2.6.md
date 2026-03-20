# StableNew PR Template v2.6

Status: Canonical
Updated: 2026-03-19

## Purpose

This template is the required format for executable PR specifications in
StableNew v2.6. It is written for planner-to-executor handoff, including human
review, Copilot execution, and Codex execution.

Every PR spec must be concrete enough that an implementation agent can execute
it without inventing architecture, reviving legacy seams, or widening scope.

## Required Structure

Use the following sections in order.

### 1. Header

```markdown
# PR-{CATEGORY}-{NUMBER} - {Title}

Status: Specification | In Progress | Completed | Cancelled
Priority: LOW | MEDIUM | HIGH | CRITICAL
Effort: SMALL | MEDIUM | LARGE
Phase: {Roadmap phase}
Date: YYYY-MM-DD
```

Accepted category prefixes used by the current repo:

- `UNIFY`
- `NJR`
- `MIG`
- `CTRL`
- `CONFIG`
- `PERF`
- `VIDEO`
- `COMFY`
- `TEST`
- `OBS`
- `GUI`
- `POLISH`
- `HARDEN`

### 2. Context & Motivation

Must include:

- current repo truth
- specific user or architectural problem
- why the PR exists now
- references to canonical docs or previous PRs

### 3. Goals & Non-Goals

Use flat numbered lists.

Goals must be observable and testable.

Non-goals must explicitly fence the scope and prevent architecture drift.

### 4. Guardrails

Must include:

- architecture invariants that this PR must preserve
- boundaries the executor must not cross
- explicit statement about whether NJR, queue, runner, or GUI contracts may be touched

### 5. Allowed Files

Split into:

- Files to Create
- Files to Modify
- Forbidden Files

The list must be explicit enough to prevent scope creep.

File groups may be listed by directory or pattern only when the boundary is
tight and obvious, for example:

- `tests/video/test_sequence_*`
- `src/video/*sequence*.py`

### 6. Implementation Plan

Break the work into ordered steps.

Each step must include:

- what changes
- why it changes
- exact files touched in that step
- whether tests should be added or updated

If a PR has risky edges, include a dedicated hardening step before the final UI
or integration step.

### 7. Testing Plan

Split into:

- Unit tests
- Integration tests
- Journey or smoke coverage
- Manual verification

List concrete pytest commands when known.

### 8. Verification Criteria

Split into:

- Success criteria
- Failure criteria

Success criteria must map back to the goals.

### 9. Risk Assessment

Split into:

- Low-risk areas
- Medium-risk areas with mitigation
- High-risk areas with mitigation
- Rollback plan

### 10. Tech Debt Analysis

Must include:

- debt removed
- debt intentionally deferred
- exact next PR owner for each deferred item

### 11. Documentation Updates

List the docs that must change in the same PR if runtime truth changes.

For documentation-only follow-up, name the follow-up PR explicitly.

### 12. Dependencies

Split into:

- internal module dependencies
- external tools or runtimes

### 13. Approval & Execution

Use:

```markdown
Planner: {Agent}
Executor: {Agent}
Reviewer: {Agent/Human}
Approval Status: Pending | Approved | Implemented
```

### 14. Next Steps

List the immediate next PRs or follow-on tasks.

## Execution Rules

All PR specs must respect the current canon:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

PR specs must not:

- reintroduce `DIRECT`
- create a second job model
- leak backend workflow JSON outside `src/video/`
- revive archive DTOs as active runtime dependencies
- leave both old and new paths active

## Post-Implementation Summary

After implementation, append a short summary section that records:

- what was delivered
- actual files changed
- tests run
- deferred debt and next PR owner
