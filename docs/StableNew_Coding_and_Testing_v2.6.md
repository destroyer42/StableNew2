# StableNew coding and testing v2.6

Status: Active
Updated: 2026-09-07

This file is the concise development and verification authority. Architecture
rules live in `ARCHITECTURE_v2.6.md`; current priorities live in `STATUS.md` and
the active roadmap.

## Coding principles

- Deliver coherent product outcomes, not disconnected file edits.
- Preserve the canonical path:
  `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler`.
- Use typed DTOs at architectural boundaries. Avoid open-ended dictionaries as
  public compiler, controller, service, or runner contracts.
- Keep NJRs immutable and free of status, errors, progress, retries, timestamps,
  and produced artifact paths.
- Keep GUI presentation thin, non-blocking, and GUI-thread safe.
- Keep controllers focused on coordination rather than backend payload building.
- Keep compilers deterministic and free of queue, runner, GUI, persistence, or
  network side effects.
- Keep backend-specific payloads inside backend adapters.
- Remove superseded compatibility paths when replacement behavior is proven.
- Avoid import-time network, process, model/GPU, GUI-loop, or repository writes.
- Preserve unrelated working-tree changes.

## Supported Python

Use Python 3.11 or 3.12. Create a local virtual environment and install the
project requirements before validation. CI pins tool versions in
`pyproject.toml` and workflow configuration.

## Test configuration

`pyproject.toml` is the only pytest configuration authority. Do not add a
second `pytest.ini`, `tox.ini`, or setup-file pytest configuration.

Tests are grouped by purpose:

- unit/contract tests for models, validation, compilers, serializers, and pure
  services;
- integration tests for compiler-to-queue-to-runner-to-history behavior;
- headless GUI tests for view/controller wiring and thread boundaries;
- system/safety tests for architecture, repository completeness, CI truth, and
  runtime-state hygiene;
- opt-in real-backend journeys for WebUI, SVD, models, and hardware.

Every test must be deterministic for fixed inputs. Use temporary state,
artifact, cache, and output roots. Do not use real networks, WebUI, models,
GPUs, persistent user data, or GUI displays in the required gate.

## Standard gate

Run targeted tests first, then:

```text
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_mypy_smoke.py
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
```

Use `python -m pytest -q <targets>` for focused behavior. Run the broadest
practical suite when runtime code changes, but do not claim a full green suite
when environment-dependent tests were not executed.

## Repository completeness

Every imported production module must be tracked in Git. Source packages may
not be hidden by broad ignore patterns. The completeness gate compares tracked
and working-tree source and fails on missing or untracked Python modules.

## Collection and smoke

Collection runs in an isolated disposable directory and must not change the
repository. The required smoke runner uses an exact positive list covering:

- repository completeness and architecture enforcement;
- CI configuration truth;
- runtime-state hygiene and workspace routing;
- the queue-first core run path;
- queued execution and error handling.

Adding a test to required smoke is a deliberate reliability decision, not a
way to approximate the entire historical suite.

## Lint and types

Ruff 0.14.9 is pinned. `tools/ci/run_ruff_baseline.py` is a non-increasing
file/rule-count ratchet over legacy debt. A new bucket or increased count fails.
Every touched source file should be left clean. `PR-MVP-080` owns bounded
cleanup of untouched findings; `PR-MVP-090` removes the baseline after raw Ruff
is clean.

`tools/ci/run_mypy_smoke.py` checks the typed architecture seams. A broad mypy
run is useful diagnostic evidence but is not yet a repository-wide green gate.
New typed seams should not add to that debt.

## Runtime and GUI testing

- Fake runtime ports must match the production protocol.
- Queue tests assert enqueue-before-run and stable NJR snapshots.
- Replay tests assert a new job identity and parent lineage.
- Failure tests assert durable terminal state and no legacy fallback.
- GUI tests must be headless-safe, non-blocking, and free of worker-thread
  widget mutation.
- Replace timing sleeps with events, fakes, bounded polling, or explicit state
  transitions.
- Close threads, clients, loggers, temporary servers, and process handles.

## Real-backend acceptance

Real WebUI/SVD tests require explicit opt-in and must record:

- command and interpreter;
- relevant dependency/model versions;
- target hardware and memory settings;
- pass/fail/skip counts;
- artifact location and inspected metadata;
- timeout/cancellation behavior;
- any environment blocker.

Real-backend checks never run during collection and never silently download
models or alter user data.

## Verified baseline

The latest comparable verification including repository-hygiene cleanup reported:

- 429 tracked Python source files;
- 3,086 collected tests plus 2 optional-OpenCV module skips on the supported
  Python 3.11 and 3.12 environments;
- 74 required smoke tests passing on Python 3.11 and 3.12;
- bounded mypy smoke passing;
- 1,859 Ruff findings against the maximum baseline of 2,208.

The broad suite is not a green gate yet. A Python 3.11 diagnostic stopped after
10 failures, 215 passes, and 2 optional-OpenCV skips. The first failures are in
legacy CLI submission, compatibility-mode execution, and queue/history
migration expectations that predate the typed NJR cutover.

Update this section and `STATUS.md` together only after running the comparable
commands. Do not repeat counts in other active documents.

## Change review

Before completion, verify:

- the requested behavior is actually delivered;
- architecture ownership remains clear;
- obsolete code/tests/docs were removed where safe;
- migration and rollback are safe when data changes;
- targeted and standard gates were run as applicable;
- the working tree contains only intended changes;
- `STATUS.md` reflects any material direction or verification change;
- known failures and environment blockers are reported precisely.
