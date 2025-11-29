---
name: "S3-A Fix legacy logger/structured_logger tests"
about: "Resolve pre-existing failures and reach 0 fails"
title: "S3-A Fix legacy logger/structured_logger tests: "
labels: [sprint-3, test, debt]
assignees: ""
---


## Goal
Resolve all legacy test failures (logger/structured_logger and related) and stabilize the suite.

## DoD
- `pytest` shows 0 failures on clean repo.
- Flaky tests quarantined or stabilized with deterministic fixtures.
- Coverage maintained or improved.

## Tasks
- [ ] Identify failing tests and root causes.
- [ ] Patch or refactor minimal surface.
- [ ] Add deterministic fixtures/mocks.
- [ ] Update CI to run the full matrix.

## Test commands
```
pytest -q
```
