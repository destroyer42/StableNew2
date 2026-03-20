# Summary
Describe the problem, the change, and why the change is required.

# Canonical References
- `AGENTS.md`
- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/PR_TEMPLATE_v2.6.md`

# Goals
- List the concrete outcomes this PR delivers.

# Non-Goals
- List what this PR does not do.

# Allowed Files
- List every file created.
- List every file modified.
- List every file deleted.

# Forbidden Files
- List files or directories that must not be touched.

# Implementation Plan
1. Describe the ordered implementation steps.
2. Keep steps specific and verifiable.

# Tests
- List unit, integration, and journey coverage required.
- Include exact commands used.

```bash
python -m compileall src
pytest -q
```

# Acceptance Criteria
- List the conditions that must be true for merge.

# Docs
- Note which canonical docs or operator guides changed.
- Confirm `docs/DOCS_INDEX_v2.6.md` was updated if the active doc map changed.

# Risk And Rollback
- State the main risks.
- State the rollback approach.

# Architecture Check
- Confirm no new prompt or executable-config construction was introduced outside canonical builders/compilers.
- Confirm NJR-only execution remains intact.
- Confirm no duplicate runtime path was introduced.
