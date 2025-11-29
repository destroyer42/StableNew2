---
name: "S3-C CI pipeline"
about: "GitHub Actions: ruff, black, mypy, pytest, pre-commit on PRs"
title: "S3-C CI pipeline: "
labels: [sprint-3, ci, infra]
assignees: ""
---


## Goal
Ensure every PR runs formatting, type checks, linting, and tests.

## DoD
- Workflow YAML runs ruff/black/mypy/pytest + pre-commit.
- Caches Python deps; fails on test/lint errors.
- Badges in README.

## Tasks
- [ ] Add `.github/workflows/ci.yml`.
- [ ] Cache pip; configure matrix for Python 3.11.
- [ ] Add status badges to README.

## Test commands
- Push a failing dummy branch; verify CI fails appropriately.
