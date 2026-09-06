# StableNew v2.6 — Executor Brief

Status: Canonical active machine-facing summary
Updated: 2026-09-05

Read `AGENTS.md` before changing this repository. Then read the active canonical
documents and the approved PR spec. This file summarizes; it does not override
them.

## Current architecture

`Typed Intent -> Compiler -> NJR -> JobService -> Queue/JobRepository -> PipelineRunner.run_njr -> Typed Handler -> Artifacts -> History/Learning/Diagnostics`

- NJR is immutable authorized work, not mutable queue/history state.
- PromptPack identity is conditional on a PromptPack source.
- Fresh work is queue-only; `Run Now` means immediate-start queue policy.
- There is one public runner entry and one persistence boundary.
- MVP execution is same-process; native SVD XT is the only MVP video backend.
- Architecture target gaps are explicit in `docs/ARCHITECTURE_v2.6.md`; do not
  mistake them for already-implemented behavior.

## Execution rules

- Treat owner-approved PR specs as binding.
- Modify only allowed files and preserve unrelated changes/data.
- Stop if a required edit, design choice, or migration falls outside the spec.
- Do not add `DIRECT`, alternate job/runner/persistence paths, universal pack
  requirements, live legacy fallbacks, or backend payload leakage.
- Do not use stale tests or completed plans to override active canon.
- Do not rewrite tests merely to hide missing implementation.
- Close runtime PRs with tests, clean-checkout evidence, roadmap/gap updates,
  and one CompletedPR record.

## Repository map

- `src/gui*/`: presentation and event wiring
- `src/controller/`: controller adapters and application coordination
- `src/pipeline/`: NJR, compilers/builders, runner, and stage orchestration
- `src/queue/` and `src/history/`: transitional queue/history code converging on
  the repository boundary
- `src/state/`: source-owned workspace/output state helpers; must be tracked
- `src/video/`: typed video handlers/adapters
- `src/learning/`: post-execution learning consumers
- `tests/`: isolated unit, contract, integration, GUI, and acceptance tests
- `docs/`: canonical, subsystem, roadmap, PR, and historical records

## Verification defaults

Use the project-managed Python 3.11 environment. Run targeted tests first. The
canonical baseline is being established by `PR-MVP-010`; do not repeat stale
collection counts as current truth.

Expected gate shape:

```text
python -m compileall src
pytest --collect-only -q
pytest -m "not real_backend and not quarantine" -q
```

Tests must not call real networks/models at collection time, sleep as a
correctness mechanism, mutate tracked data, or write GUI widgets from workers.
Real WebUI/SVD acceptance is opt-in and recorded separately.

## Scoped instructions

Also follow the matching `.github/instructions/*.instructions.md` file for any
path you edit. The complete inventory and precedence are in
`.github/INSTRUCTION_SURFACE.md`.
