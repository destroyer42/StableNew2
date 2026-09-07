# StableNew Coding and Testing Standards v2.6

Status: Canonical, Binding
Updated: 2026-09-05

## 0. Purpose

These standards govern implementation and verification during MVP recovery.
They optimize for reproducibility, clean boundaries, recoverable data, and tests
that prove the architecture rather than preserve accidental behavior.

## 1. Required runtime shape

Production work follows:

`Typed Intent DTO -> Compiler -> NJR -> JobService -> JobRepository/Queue -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Code and tests must enforce:

- NJR is the only public executable envelope;
- fresh work is queue-only;
- `Run Now` is immediate-start submission policy;
- NJR is immutable and contains no status/results/progress/output paths;
- PromptPack identity is required only for `source.kind == "prompt_pack"`;
- persistence is reached through `JobRepository`;
- runner handlers do not own persistence or GUI state;
- no fallback to legacy dictionaries, `DIRECT`, or alternate runner entries.

## 2. Repository completeness and hygiene

- Every imported production module must be tracked by Git and present in a
  tracked-files-only checkout.
- Ignore rules for runtime data must be rooted and narrow. A rule such as
  `state/` that also hides `src/state/` is forbidden; use `/state/` for a
  repository-root runtime directory.
- Generated queue/history databases, caches, outputs, logs, model files, and
  local secrets are not source.
- Tests write only to temporary workspaces or explicitly injected stores.
- A test must restore any process-level environment, singleton, working
  directory, logging handler, or module patch it changes.
- Importing a production or test module must not start workers, open GUI loops,
  call the network, probe a GPU, mutate persistence, or parse command-line
  arguments.

Repository-completeness and no-import-side-effect checks are release gates.

## 3. Contract and model rules

Use typed dataclasses, enums, protocols, or validated schema models at system
boundaries. Do not pass open-ended dictionaries between GUI, compilers,
`JobService`, repository, and runner.

### 3.1 NJR

The NJR core is defined in `ARCHITECTURE_v2.6.md`. Requirements:

- explicit schema version;
- complete and deterministic serialization;
- validation on construction and deserialization;
- immutable nested values after submission;
- explicit source/workload matching;
- new record plus lineage for replay or modification;
- no mutable queue/history fields.

Any schema change requires versioned fixtures, migration tests, and synchronized
canonical docs.

### 3.2 Job execution record

Mutable state belongs to a separate repository-owned record. Lifecycle
transitions must be explicit, transactional, and validated. Terminal states do
not transition back to running; retry creates a deliberate new attempt or job
according to the approved repository contract.

### 3.3 Intent compilers

Compilers are deterministic and side-effect-free apart from explicitly injected
read-only registries. They resolve all authoring choices before submission and
return structured errors. They do not enqueue, execute, or mutate source files.

## 4. Persistence and migration

- Application code depends on the `JobRepository` interface, not SQLite calls or
  JSON files outside the repository implementation.
- SQLite transactions own multi-field lifecycle updates.
- Schema version and migration state are explicit.
- Legacy import is offline and backup-first; it supports dry-run, validation,
  idempotence, and conflict reports.
- Migration tests compare record counts, stable identities, important hashes,
  statuses, NJR snapshots, artifact links, and errors.
- Live dual-read, dual-write, or silent fallback is forbidden.
- Destructive cleanup of legacy data is never part of automatic startup.

## 5. Error handling and diagnostics

Errors crossing a boundary must carry a stable code, a user-safe message, and
diagnostic context without secrets. Exceptions are handled at the layer that
can add meaning or recover; broad catch-and-ignore behavior is forbidden.

Queue and runner diagnostics must include job identity, workload kind, stage,
transition, elapsed time when known, and failure code. Logs must not contain
tokens, full secret-bearing environment dumps, or unbounded backend payloads.

Expected missing dependencies are capability/preflight results, not import-time
crashes. A failed job reaches a durable terminal state and never falls back to a
second execution path.

## 6. GUI and concurrency

- GUI callbacks call controller/application methods, not builders, repositories,
  or runner methods directly.
- Workers never mutate widgets. State changes are marshalled through the GUI
  scheduler/event boundary.
- Queue submission is non-blocking.
- Cancellation, timeout, and shutdown behavior are bounded and tested.
- Polling loops require a termination condition and must not use arbitrary sleep
  calls as correctness mechanisms.
- UI projections may be cached for display but are not execution authority.

## 7. Backend rules

Backends implement typed runner-facing ports. Network clients, WebUI payloads,
SVD pipeline objects, subprocess commands, and backend workflow JSON remain
inside adapters/handlers.

Tests use deterministic fakes by default. Real WebUI/GPU/model tests are marked,
opt-in, bounded, and record environment/version evidence. They are required for
release acceptance but not for hermetic unit CI.

For MVP video, only native SVD XT may be on the advertised path. Memory-related
settings and dependency checks must be explicit and testable without downloading
or loading a model during normal unit collection.

## 8. Test taxonomy

### 8.1 Unit

Fast, hermetic tests for models, validation, compilers, repository operations,
and pure services. No real filesystem outside a temp directory, network, GPU,
subprocess, display, or sleep.

### 8.2 Contract

Tests that lock system boundaries:

- NJR round-trip, immutability, and conditional identity;
- compiler output and side-effect freedom;
- JobRepository transition semantics;
- runner port request/result types;
- artifact and history linkage;
- migration version behavior.

### 8.3 Integration

Multiple real StableNew components with fake external backends and temporary
persistence. These prove compiler-to-queue-to-runner-to-history behavior.

### 8.4 GUI journey

User-visible flows with fake backends and controlled GUI scheduling. Assertions
cover visible state and application outcomes, not private widget implementation.

### 8.5 Real-backend acceptance

Explicit manual/opt-in journeys against configured WebUI and native SVD XT on
the target machine. Each run records app commit, Python/dependency versions,
backend/model identifiers, hardware, command/workflow, result, and artifacts.

### 8.6 Quarantine

A quarantined test must have a reason, owner, expiry/deletion PR, and marker. It
cannot define current architecture or satisfy an MVP gate.

## 9. Required test properties

- deterministic inputs, ordering, seeds, and clocks where relevant;
- no reliance on test execution order;
- no mutation of tracked repository files;
- no arbitrary sleeps;
- no real external call unless explicitly marked;
- failure assertions include state, error code, and absence of fallback;
- serialization tests compare the complete supported contract;
- migration tests run at least twice to prove idempotence;
- clean-checkout tests run without ignored local source files.

Tests must not assert `pack_required` for a non-PromptPack source. A test that
preserves superseded architecture must be removed or rewritten in the same PR
that implements the replacement contract, not before.

## 10. Baseline command policy

`pyproject.toml` is the only pytest configuration authority. Use a supported
Python 3.11 or 3.12 environment and record the interpreter. The required gate
is the following ordered command set:

```text
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_mypy_smoke.py
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
```

The required pytest runner uses an explicit positive target list. It must not
start with the full suite and subtract exclusions. Collection and required
smoke run from a disposable working directory with no-WebUI/test-mode defaults,
bytecode/cache suppression, temporary pytest paths, and repository-content
snapshots. A hang, crash, collection error, real backend call, or repository
mutation is a failed run even if earlier assertions passed.

Default collection includes active development, integration, journey, and
headless-safe GUI v2 modules. It excludes archive, quarantine, manual scripts,
legacy GUI, and legacy-only directories. Collection does not make a test
canonical or required. Real WebUI/SVD acceptance requires the `real_backend`
marker, explicit operator opt-in, and a separate recorded target-machine run.

Formatting, lint, and type-check commands must use repository-pinned
configuration. Existing contract-test debt is assigned to its owning MVP PR in
`tests/TEST_SURFACE_MANIFEST.md`; new or touched-file violations are not
permitted.

Ruff is pinned to 0.14.9. `tools/ci/ruff_baseline.json` records 2,208
pre-existing findings by source path and rule; the required baseline runner
fails a version mismatch, any new key, or any increased count. Decreases do not
require snapshot regeneration. MVP runtime PRs leave every touched source file
clean, PR-MVP-080 owns bounded cleanup of untouched findings, and PR-MVP-090
deletes the baseline only after raw `ruff check src` succeeds.

PR-MVP-010 validation used disposable Python 3.11.16 and 3.12.14 environments.
Both passed repository completeness, the Ruff baseline gate, the bounded mypy
gate, strict isolated collection, and all 73 positively selected required
tests. The collection runners reported 3,083 tests with two explicit
optional-OpenCV skips and left repository contents unchanged.

PR-MVP-020 validation on Python 3.11.16 added immutable NJR contract and
mutation-enforcement coverage. PR-MVP-030 then migrated all enabled source
families to typed compiler/NJR submission, added replay/training compiler
coverage, and removed the superseded generic request path. Its focused set
passed 31 tests; isolated collection reported 3,096 tests with the same two
optional-OpenCV skips; the required positive smoke passed 75 tests on both
Python 3.11 and 3.12; bounded mypy smoke passed; and the pinned Ruff debt fell
to 1,860 findings without increasing the approved ceiling.

## 11. PR verification record

Every implementation PR records:

- exact commands and interpreter;
- pass/fail/skip counts;
- relevant fixture or migration versions;
- whether real backends were used;
- tracked-file status before and after tests;
- known failures with owner and closing PR;
- docs and architecture-gap rows updated.

“Tests pass” without this context is not adequate closeout evidence.

## 12. Review checklist

- Does the change use the single intent/NJR/queue/runner path?
- Are DTOs and ownership boundaries typed?
- Is NJR immutable and free of runtime results?
- Is source identity conditional and valid?
- Is persistence transactional and recoverable?
- Does a clean checkout include every production dependency?
- Are tests isolated, deterministic, and architecture-current?
- Are external dependencies preflighted rather than imported eagerly?
- Are user data and unrelated work preserved?
- Are canonical docs, roadmap, and PR closeout synchronized?
