# PR-AGENT-004: Operator Guide And Setup

**Status**: Specification
**Priority**: MEDIUM
**Effort**: SMALL
**Phase**: Process
**Date**: 2026-03-11

## Context & Motivation

Operator-facing guidance is scattered across several stale files. The repo also has a Copilot setup workflow that should stay aligned with the active stack.

## Goals & Non-Goals

### Goals
1. Add one operator guide for human usage.
2. Merge useful noncanonical guidance into that guide.
3. Keep the Copilot setup workflow aligned with the active stack.

### Non-Goals
1. No product code changes.
2. No architecture changes.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| docs/agentic/USAGE_GUIDE.md | Operator guide | 120 |
| docs/OpenSpec/PR-AGENT-004-Operator-Guide-And-Setup.md | PR spec | 100 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| .github/workflows/copilot-setup-steps.yml | Add minimal smoke validation | 20 |
| docs/DOCS_INDEX_v2.6.md | Register operator guide | 20 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/ | No product code changes |

## Implementation Plan

### Step 1: Create operator guide
Create `docs/agentic/USAGE_GUIDE.md` and make it explicitly subordinate to canonical docs.

### Step 2: Align setup workflow
Keep dependency bootstrap and add a lightweight smoke check.

### Step 3: Archive stale process docs
Move old SOP and project-instruction files to archive.

## Testing Plan

### Manual Testing
- Confirm the workflow YAML remains valid.
- Confirm the operator guide points back to canonical docs.

## Verification Criteria

### Success Criteria
1. One active operator guide exists.
2. Stale SOP-style docs are archived.
3. Setup workflow remains repo-accurate.

## Risk Assessment

### Low Risk Areas
✅ Documentation and workflow only.

### Rollback Plan
Revert the guide and workflow changes and restore the archived docs.
