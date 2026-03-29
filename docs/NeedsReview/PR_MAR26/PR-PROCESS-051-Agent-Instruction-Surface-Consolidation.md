# PR-PROCESS-051: Agent Instruction Surface Consolidation

**Status**: Specification
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Governance and Documentation Cleanup
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Agent guidance is spread across multiple active surfaces, making instruction drift more likely.

### Why This Matters
When multiple machine-facing guidance files remain active without a single manifest, different agents can follow different subsets and still believe they are compliant.

### Current Architecture
Active guidance currently spans:
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `.github/agents/`
- `.github/instructions/`

### Reference
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Create one explicit manifest of active machine-facing instruction sources.
2. Mark superseded or archived instruction files clearly.
3. Preserve scoped guidance where it adds real value.

### ❌ Non-Goals
1. Do not rewrite every agent profile from scratch.
2. Do not remove useful scoped guidance just to reduce file count.
3. Do not change repo architecture or code in this PR.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `.github/INSTRUCTION_SURFACE.md` | active instruction manifest and precedence map | 120 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `AGENTS.md` | point to instruction manifest and clarify active vs scoped surfaces | 30 |
| `.github/copilot-instructions.md` | reduce overlap and reference manifest | 30 |
| `docs/DOCS_INDEX_v2.6.md` | reflect the instruction manifest as the active machine-facing map | 20 |
| selected `.github/agents/*.md` and `.github/instructions/*.md` headers | mark active/superseded status where needed | 40 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/**` | process/docs only |
| `tests/**` | process/docs only |

## Implementation Plan

### Step 1: Define the manifest
Create a single file listing:
- active instruction sources
- precedence order
- archive-only sources
- when scoped instructions apply

### Step 2: Trim overlap in active top-level files
Reduce duplicated guidance between `AGENTS.md` and `.github/copilot-instructions.md` by referencing the manifest instead of re-stating everything.

### Step 3: Mark scoped files clearly
Add short active/superseded headers to scoped agent/instruction files where ambiguity exists.

## Testing Plan

### Unit Tests
- none

### Integration Tests
- none

### Journey Tests
- none

### Manual Testing
1. Start from the manifest and verify a contributor can discover the full active instruction surface without guessing.
2. Confirm archived/superseded files are not presented as active.

## Verification Criteria

### ✅ Success Criteria
1. One manifest defines the active instruction surface.
2. Active top-level guidance no longer overlaps excessively.
3. Scoped files are clearly marked and discoverable.

### ❌ Failure Criteria
- instruction precedence remains ambiguous
- archived/superseded guidance still looks active

## Risk Assessment

### Low Risk Areas
✅ Manifest creation and doc linking

### Medium Risk Areas
⚠️ Trimming overlapping text
- **Mitigation**: preserve meaning, reduce duplication only

### High Risk Areas
❌ Accidentally removing needed scoped nuance
- **Mitigation**: keep scoped files, only clarify precedence

### Rollback Plan
Restore prior guidance files and remove the manifest if consolidation causes confusion.

## Tech Debt Analysis

## Tech Debt Removed
✅ Reduces instruction drift risk
✅ Clarifies the active machine-facing guidance set

## Tech Debt Added
⚠️ One additional manifest file

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Strengthens governance and execution discipline.

### ✅ Follows Testing Standards
Docs/process only.

### ✅ Maintains Separation of Concerns
Does not mix code changes into process cleanup.

## Dependencies

### External
- none

### Internal
- `AGENTS.md`
- `.github/copilot-instructions.md`
- `.github/agents/`
- `.github/instructions/`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| manifest creation | 0.5 day | Day 1 |
| overlap cleanup | 0.5 day | Day 1 |
| header/status cleanup | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Add the instruction manifest.
2. Clarify active vs scoped guidance.
3. Continue with test-suite normalization in PR-052.
