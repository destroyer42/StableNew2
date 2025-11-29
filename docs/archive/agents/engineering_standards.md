# StableNew Engineering Standards

These standards apply to ALL agents and all code contributions.

## 1. Coding Style

- Follow Python 3.11+ idioms.
- All modules should use type hints (consider `from __future__ import annotations`).
- Avoid long functions (>30 lines) unless unavoidable.
- Avoid deep nesting; prefer early returns.
- No global state except constants.
- No hard-coded filesystem paths.
- Prefer explicit imports over wildcards.

## 2. Directory Rules

- All GUI code lives under `src/gui/`.
- Service logic goes under `src/services/`.
- Utility functions go under `src/utils/`.
- Tests live under `tests/` with clear subfolders:
  - `tests/unit/`
  - `tests/gui/`
  - `tests/integration/`
  - `tests/journey/`
- Avoid cyclic imports between GUI → controller → utils.

## 3. Testing Standards

- All features must have tests.
- All bugfixes must start with a failing test that reproduces the issue.
- Tests must be deterministic and fast.
- GUI tests should rely on mocks or headless environments (e.g., xvfb) where possible.
- Use pytest as the test framework.

## 4. Performance Standards

- Tkinter must never block the UI thread.
- Long operations must be asynchronous or delegated to background threads/controllers.
- File IO in the main thread should be minimal and non-blocking where possible.

## 5. Documentation

- All user-visible behavior must be documented in `docs/` or `README.md`.
- All PRs that affect behavior should update `CHANGELOG.md`.
- Internal design decisions should be captured in appropriate docs for future contributors.

## 6. Security / Safety

- No execution of external binaries unless explicitly intended and documented.
- No use of `eval` on untrusted input.
- No deletion of user files except where explicitly intended with clear warnings.
