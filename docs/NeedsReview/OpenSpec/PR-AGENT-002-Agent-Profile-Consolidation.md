# PR-AGENT-002: Agent Profile Consolidation

**Status**: Specification
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Process
**Date**: 2026-03-11

## Context & Motivation

`.github/agents/` currently contains canonical candidates, duplicates, and one-off task files. The active agent surface should be small and deterministic.

## Goals & Non-Goals

### Goals
1. Rewrite the canonical specialist set in place.
2. Add a missing runtime specialist.
3. Archive duplicate or stale agent profiles.

### Non-Goals
1. No runtime code changes.
2. No new workflow semantics beyond agent profile cleanup.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| .github/agents/pipeline_runtime.md | Runtime specialist profile | 60 |
| docs/OpenSpec/PR-AGENT-002-Agent-Profile-Consolidation.md | PR spec | 100 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| .github/agents/controller_lead_engineer.md | Rewrite as canonical planner/orchestrator | 80 |
| .github/agents/implementer.md | Rewrite as canonical implementer | 60 |
| .github/agents/gui.md | Rewrite as canonical GUI specialist | 60 |
| .github/agents/tester.md | Rewrite as canonical tester | 60 |
| .github/agents/docs.md | Rewrite as canonical docs specialist | 50 |
| .github/agents/refactor.md | Rewrite as canonical refactor specialist | 40 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/ | No product code changes |

## Implementation Plan

### Step 1: Rewrite the canonical set
Update planner, implementer, GUI, tester, docs, and refactor profiles in place.

### Step 2: Add runtime specialist
Create `pipeline_runtime.md`.

### Step 3: Archive duplicates
Move stale or duplicate agent files out of `.github/agents/`.

## Testing Plan

### Manual Testing
- Confirm `.github/agents/` contains only the active specialist set.
- Confirm archived profiles are outside the active discovery path.

## Verification Criteria

### Success Criteria
1. Only the canonical specialist set remains active.
2. Archived files cannot be mistaken for active Copilot agents.

## Risk Assessment

### Low Risk Areas
✅ This is instruction-surface cleanup only.

### Rollback Plan
Move archived profiles back and revert rewritten agent files.
