# PR Template Guide v2.6

**Status**: CANONICAL  
**Version**: 2.6  
**Date**: 2025-12-26

---

## Purpose

This document defines the standard structure for Pull Request (PR) documentation in StableNew v2.6+. All PRs must follow this template to ensure consistency, traceability, and maintainability.

---

## PR Document Structure

Every PR document must contain the following sections in order:

### 1. Header

```markdown
# PR-{CATEGORY}-{NUMBER}: {Title}

**Status**: {Status}
**Priority**: {Priority}
**Effort**: {Effort}
**Phase**: {Phase}
**Date**: {Date}
**Implementation Date**: {Date} (if implemented)
```

**Fields**:
- `Status`: 🟡 Specification | 🔵 In Progress | ✅ Implemented | ❌ Cancelled
- `Priority`: LOW | MEDIUM | HIGH | CRITICAL
- `Effort`: SMALL (1-2 days) | MEDIUM (1 week) | LARGE (2+ weeks)
- `Phase`: Phase number or category (e.g., "Post-Phase 4 Enhancement")
- `Date`: Specification date
- `Implementation Date`: Actual completion date (add after implementation)

**Categories**:
- `CORE`: Core architecture changes
- `GUI`: GUI changes
- `TEST`: Testing infrastructure
- `CLEANUP`: Code cleanup/refactoring
- `PROCESS`: Process improvements
- `CI`: CI/CD changes
- `DOCS`: Documentation only

### 2. Context & Motivation

```markdown
## Context & Motivation

### Problem Statement
{What problem are we solving?}

### Why This Matters
{Why is this important? What's the impact?}

### Current Architecture
{What does the system look like today?}

### Reference
{Links to related docs, issues, discussions}
```

### 3. Goals & Non-Goals

```markdown
## Goals & Non-Goals

### ✅ Goals
1. {Specific, measurable goal}
2. {Another goal}

### ❌ Non-Goals
1. {What we explicitly won't do}
2. {Scope limitations}
```

### 4. Allowed Files

```markdown
## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| {path} | {description} | {count} |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| {path} | {description} | {count} |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| {path} | {why forbidden} |
```

**Rationale**: Explicitly listing allowed/forbidden files prevents scope creep and accidental architecture violations.

### 5. Implementation Plan

```markdown
## Implementation Plan

### Step 1: {Title}
{Detailed step description}

**Create**: {files}
**Modify**: {files}

```language
{code snippets if helpful}
```

### Step 2: {Title}
{Next step}

...
```

**Guidelines**:
- Break implementation into logical, sequential steps
- Include code snippets for complex changes
- Specify exact files for each step
- Order steps by dependency (do prerequisites first)

### 6. Testing Plan

```markdown
## Testing Plan

### Unit Tests
{Test coverage requirements}

### Integration Tests
{Integration test requirements}

### Journey Tests
{E2E test requirements}

### Manual Testing
{Manual verification steps}
```

### 7. Verification Criteria

```markdown
## Verification Criteria

### ✅ Success Criteria
1. {Specific, testable criterion}
2. {Another criterion}

### ❌ Failure Criteria
{What constitutes failure?}
```

### 8. Risk Assessment

```markdown
## Risk Assessment

### Low Risk Areas
✅ {Area}: {Why low risk}

### Medium Risk Areas
⚠️ {Area}: {Risk description}
- **Mitigation**: {How to mitigate}

### High Risk Areas
❌ {Area}: {Risk description}
- **Mitigation**: {How to mitigate}

### Rollback Plan
{How to undo changes if needed}
```

### 9. Tech Debt Analysis

```markdown
## Tech Debt Removed
✅ {Issue resolved}

## Tech Debt Added
⚠️ {New tech debt (with justification)}

**Net Tech Debt**: {+/- count}
```

### 10. Architecture Alignment

```markdown
## Architecture Alignment

### ✅ Enforces Architecture v2.6
{How this PR aligns with canonical architecture}

### ✅ Follows Testing Standards
{How testing follows standards}

### ✅ Maintains Separation of Concerns
{How SoC is maintained}
```

### 11. Dependencies

```markdown
## Dependencies

### External
{External libraries, services, tools}

### Internal
{Internal modules, components}
```

### 12. Timeline & Effort

```markdown
## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| {task} | {hours/days} | {date range} |

**Total**: {time estimate}
```

### 13. Approval & Sign-Off

```markdown
## Approval & Sign-Off

**Planner**: {Agent/Person}
**Executor**: {Agent/Person}
**Reviewer**: {Agent/Person}

**Approval Status**: {Status}
```

### 14. Next Steps

```markdown
## Next Steps

1. {Action item}
2. {Action item}
3. {Action item}
```

---

## Post-Implementation: Implementation Summary

**IMPORTANT**: After a PR is implemented, add this section to document actual implementation details:

```markdown
## Implementation Summary

**Implementation Date**: {Date}
**Executor**: {Agent/Person}
**Status**: ✅ COMPLETE | ⚠️ PARTIAL | ❌ FAILED

### What Was Implemented

#### 1. {Feature/Component} ✅
{Description of what was built}
- Key details
- Design decisions
- Deviations from spec (if any)

#### 2. {Next Component} ✅
{Description}

### Design Decisions

1. **{Decision Title}**: {Rationale}
2. **{Another Decision}**: {Rationale}

### Files Created ({count})
1. `{path}` ({lines} lines) - {purpose}
2. `{path}` ({lines} lines) - {purpose}

**Total New Lines**: ~{count}

### Files Modified ({count})
1. `{path}` (+{lines} lines) - {changes}
2. `{path}` (+{lines} lines) - {changes}

**Total Modified Lines**: ~{count}

### Verification

#### {Test Type}
```bash
{command}
```
**Result**: {outcome} ✅/❌

### What Works Now

1. ✅ {Working feature}
2. ✅ {Another feature}

### What's Next

1. {Follow-up task}
2. {Another task}

### Lessons Learned

1. **{Lesson}**: {Description}
2. **{Another Lesson}**: {Description}

### Tech Debt Addressed

- ✅ {Issue resolved}
- ⚠️ {New tech debt added}

**Net Tech Debt**: {+/- count}
```

---

## Examples

See these PRs for complete examples:
- [PR-CI-JOURNEY-001](PR-CI-JOURNEY-001.md): CI journey tests (COMPLETE with implementation summary)
- [PR-PROCESS-001](../docs/archive/completed_prs/PR-PROCESS-001.md): Process cleanup (if exists)

---

## Best Practices

### DO:
- ✅ Be specific and concrete
- ✅ Include code snippets for complex changes
- ✅ List all files that will be touched
- ✅ Provide verification steps
- ✅ Document design decisions
- ✅ Add implementation summary after completion

### DON'T:
- ❌ Leave goals vague or unmeasurable
- ❌ Skip risk assessment
- ❌ Forget to specify forbidden files
- ❌ Omit rollback plan
- ❌ Forget to document tech debt impact
- ❌ Skip post-implementation summary

---

## Template Checklist

Before submitting PR for approval:
- [ ] All sections present
- [ ] Goals are specific and measurable
- [ ] Allowed/forbidden files explicitly listed
- [ ] Implementation steps are sequential and complete
- [ ] Testing plan covers all changes
- [ ] Success/failure criteria defined
- [ ] Risks identified with mitigations
- [ ] Tech debt impact analyzed
- [ ] Architecture alignment verified
- [ ] No contradictions introduced with Tier 1–2 canonical docs (see Canonical_Document_Ownership_v2.6.md §5)

After implementation:
- [ ] Implementation Summary added
- [ ] Status updated to ✅ IMPLEMENTED
- [ ] Implementation Date added
- [ ] Files created/modified documented
- [ ] Verification results included
- [ ] Lessons learned documented
- [ ] Tech debt reconciled

---

## Version History

- **v2.6** (2025-12-26): Added post-implementation summary requirement
- **v2.5** (2024-xx-xx): Initial template structure

---

**Document Status**: ✅ CANONICAL  
**Last Updated**: 2025-12-26
