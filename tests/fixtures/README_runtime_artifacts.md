# tests/fixtures — Committed Test Fixtures

This directory holds **committed** fixture files used by the automated test suite.

## What belongs here

- Static JSON/JSONL samples representing well-formed `LearningRecord`, `NormalizedJobRecord`, or other model objects
- Minimal mock data sets that tests need to read deterministically
- Any fixture that is **version-controlled by design** and not produced at runtime

## What does NOT belong here

The following categories of files are **runtime artifacts** and must never be
committed to version control:

| Category | Location | Why excluded |
|---|---|---|
| Active experiment sessions | `data/learning/experiments/` | Produced at runtime; machine-specific |
| Photo optimize assets | `data/photo_optimize/assets/` | User-provided originals + generated outputs |
| Mutable UI / queue state | `state/` | Written at runtime; conflicts across workstations |
| Queue persistence | `state/queue_state_v2.json` | Runtime payload; not source |
| Sidebar / preview state | `state/sidebar_state.json`, `state/preview_panel_state.json` | UI layout; user-local |

All three top-level paths above are excluded via `.gitignore` as of PR-CLEANUP-LEARN-045.

## Rule

> If a file is produced by running the application, it must not be committed.
> Add it to `.gitignore` before the first commit touches it.

See `docs/StableNew_Coding_and_Testing_v2.6.md` for the canonical policy.
