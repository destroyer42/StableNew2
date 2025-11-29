
# Summary
Describe what this PR changes and why.

# Layers & Boundaries
- Layers touched (per docs/architecture/ARCHITECTURE_v2.md): GUI / Controller / Pipeline / Integration.
- Forbidden boundary check: confirm no direct calls across layers (e.g., GUI -> pipeline internals) and flag any scope creep early.

# Linked Issues
- Closes # (list the issues this PR addresses)

# Type of change
- [ ] Feature
- [ ] Bugfix
- [ ] Refactor
- [ ] Docs / CI
- [ ] Tests

# Validation
- [ ] I ran `pre-commit run --all-files` and fixed findings.
- [ ] I ran `pytest -q` and **0 failures** locally.
- [ ] New/changed behavior has tests (unit and/or GUI headless where applicable).
- [ ] No main-thread blocking (Tk); heavy work is in threads/subprocesses with queue callbacks.
- [ ] Cooperative cancel is honored in new/changed paths.

## Test Plan (write failing tests first)
- Enumerate deterministic failing tests to add under `tests/<domain>/` following docs/Testing_Strategy_v2.md.
- Note any mocks/stubs needed to avoid flakiness or forbidden dependencies (e.g., network/UI threads).

## Test commands used
```
pytest -q
pytest tests/gui -q
pytest tests/editor -q
```

# Screenshots / GIF (if UI changes)
(attach images)

# Docs
- [ ] README/ARCHITECTURE updated where relevant.
- [ ] In-app Help updated (pulled from README sections).

# Risk & Rollback
- Risk level: Low / Medium / High
- Rollback plan: Revert this PR; archived unused files unchanged; config backward compatible.

---
Created: 2025-11-03 23:41:49
