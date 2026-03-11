# PR-AGENT-001: Agent Governance Consolidation

**Status**: Specification
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Process
**Date**: 2026-03-11

## Context & Motivation

StableNew currently exposes overlapping agent governance through root, docs, and `.github` copies of `AGENTS.md`, plus additional SOP and project-instruction files. Active duplicates create instruction drift.

## Goals & Non-Goals

### Goals
1. Keep one active governance source of truth.
2. Rewrite active executor guidance to match v2.6 architecture.
3. Archive duplicate active governance files.

### Non-Goals
1. No runtime code changes.
2. No architecture changes.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| docs/OpenSpec/PR-AGENT-001-Agent-Governance-Consolidation.md | PR spec | 100 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| .github/copilot-instructions.md | Rewrite active executor brief | 120 |
| .github/PULL_REQUEST_TEMPLATE.md | Align GitHub template with v2.6 PR template | 60 |
| docs/DOCS_INDEX_v2.6.md | Point to active surviving guidance | 40 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| src/ | No runtime behavior change |

## Implementation Plan

### Step 1: Rewrite active GitHub guidance
Update `.github/copilot-instructions.md` and `.github/PULL_REQUEST_TEMPLATE.md` to reflect current v2.6 governance and PR expectations.

### Step 2: Remove active duplicate governance files
Archive duplicate `AGENTS.md` copies and stale guidance files out of active instruction paths.

### Step 3: Update docs index
Ensure `docs/DOCS_INDEX_v2.6.md` points to the active surviving guidance files.

## Testing Plan

### Manual Testing
- Confirm only one active `AGENTS.md` remains in an instruction-discoverable position.
- Confirm archived files are outside active `.github/agents/`.

## Verification Criteria

### Success Criteria
1. Root `AGENTS.md` is the active governance contract.
2. `.github/copilot-instructions.md` matches v2.6 terminology.
3. Duplicate active governance docs are archived.

## Risk Assessment

### Medium Risk Areas
⚠ Guidance changes may remove wording users rely on.
- **Mitigation**: preserve operator help in `docs/agentic/USAGE_GUIDE.md`.

### Rollback Plan
Revert the doc-only changes and restore archived files to prior locations.
