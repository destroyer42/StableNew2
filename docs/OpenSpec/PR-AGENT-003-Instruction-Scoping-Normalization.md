# PR-AGENT-003: Instruction Scoping Normalization

**Status**: Specification
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Process
**Date**: 2026-03-11

## Context & Motivation

The repo already has path-scoped instruction files, but only some are explicitly scoped and several do not reference the current architecture accurately.

## Goals & Non-Goals

### Goals
1. Add valid path scoping to active instruction files.
2. Normalize content around current v2.6 invariants.
3. Add missing randomizer and docs instruction files.

### Non-Goals
1. No runtime code changes.
2. No test behavior changes beyond instruction text.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| .github/instructions/randomizer.instructions.md | Randomizer path guidance | 40 |
| .github/instructions/docs.instructions.md | Docs path guidance | 40 |
| docs/OpenSpec/PR-AGENT-003-Instruction-Scoping-Normalization.md | PR spec | 100 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| .github/instructions/archive.instructions.md | Add scoping and archive rules | 25 |
| .github/instructions/controller.instructions.md | Add scoping and v2.6 controller rules | 30 |
| .github/instructions/gui.instructions.md | Add scoping and current GUI rules | 35 |
| .github/instructions/learning.instructions.md | Add scoping and learning rules | 30 |
| .github/instructions/pipeline.instructions.md | Add scoping and pipeline rules | 35 |
| .github/instructions/tests.instructions.md | Normalize test rules | 30 |
| .github/instructions/tools.instructions.md | Add scoping and tool rules | 25 |
| .github/instructions/utils.instructions.md | Add scoping and utility rules | 25 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/ | No product code changes |

## Implementation Plan

### Step 1: Normalize surviving instruction files
Rewrite existing instruction files with explicit scoping and current repo-accurate content.

### Step 2: Add missing domains
Create randomizer and docs instruction files.

## Testing Plan

### Manual Testing
- Confirm all surviving `.instructions.md` files start with front matter.
- Confirm instructions mention current canonical docs and current source tree.

## Verification Criteria

### Success Criteria
1. Every active instruction file is scoped and current.
2. Randomizer and docs have dedicated path guidance.

## Risk Assessment

### Low Risk Areas
✅ Instruction-only change.

### Rollback Plan
Revert the instruction files to their prior contents.
