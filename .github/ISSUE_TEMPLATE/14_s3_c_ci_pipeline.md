---
name: "S3-C CI pipeline"
about: "GitHub Actions: Ruff, required smoke gate, mypy smoke gate, and optional full-suite truth sync"
title: "S3-C CI pipeline: "
labels: [sprint-3, ci, infra]
assignees: ""
---


## Goal
Keep the documented CI contract aligned with the actual required and optional
GitHub Actions gates.

## DoD
- Workflow YAML runs Ruff plus the named required smoke gate and named mypy smoke gate.
- The required gate fails on real lint and smoke-test errors.
- The mypy smoke gate fails on drift inside the typed seam whitelist.
- Optional full-suite coverage remains visible and accurately documented.

## Tasks
- [ ] Keep `.github/workflows/ci.yml` aligned with the canonical smoke script.
- [ ] Keep `.github/workflows/ci.yml` aligned with the canonical mypy smoke script.
- [ ] Keep docs and templates aligned with the actual CI jobs.
- [ ] Add optional gates only when they are real and documented.

## Test commands
- Push a failing branch and verify the required gate fails.
- Push a type-broken change inside the mypy whitelist and verify the mypy smoke gate fails.
- Verify the optional full-suite job still reports separately.
