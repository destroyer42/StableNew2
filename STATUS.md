# StableNew status

Updated: 2026-09-08

## Repository

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Product name: StableNew
- Default branch: `main`
- Current release line: v2.6 MVP recovery (converged baseline)
- Authoritative branch: `main`

`main` is the consolidated product baseline. It contains the reconciled
architecture, repository-completeness repair, trustworthy test harness,
immutable NJR core, typed compiler/submission cutover, repository simplification,
and the selected QOL PromptPack updates used by the verified image-generation
baseline. Superseded main/QOL deltas were dispositioned rather than merged into
the working tree wholesale.

## Product state

StableNew has a verified queue-first NJR/runner spine, trustworthy bounded CI
gates, one transactional SQLite authority for job lifecycle state, and one
versioned JSON authority for authored PromptPacks. Queue and history are
repository projections, and legacy persistence has offline backup-first
migration. It is not yet an MVP: the image/video vertical slices still lack
clean-machine real-backend acceptance.

## Runtime invariants

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is queue-first.
- NJR is immutable authorized work.
- Mutable lifecycle/result state belongs outside NJR.
- PromptPack identity is conditional on PromptPack source.
- Replay uses a new NJR with parent lineage.
- GUI/controllers do not create alternate runner paths.

## Current work

Repository convergence, simplification, transactional job persistence,
PR-MVP-045 PromptPack draft/preview/queue repair, and PR-MVP-050 one-file JSON
PromptPack convergence are complete. PR-MVP-060 Phase 1 and Phase 2A/2B/2C are
verified on `mvp/060-image-vertical-slice`: progress/cancellation, durable
failure/retry/FIFO/reopen behavior, queue manipulation, and exact-artifact
thumbnail behavior are covered. Developer workflow retains a task-oriented code
map, one-command local required gate, canonical Python 3.11/3.12 CI verdict, and
a controller-surface ratchet. Do not revive recovery, hygiene, or QOL branches
as alternate sources of truth.

## Highest-value debt

1. The image create-to-replay journey lacks recorded real-WebUI acceptance.
2. Legacy CLI/compatibility and superseded JSON migration tests assert pre-cutover NJR
   fields and payload shapes; the broad suite is therefore not green.
3. Ruff still has a bounded legacy baseline; repository-wide mypy is not clean.

## Now / next / later

**Now / Next**

- `PR-MVP-060 Phase 2D`: consolidated lifecycle acceptance across draft, preview,
  queue, dispatch, model synchronization, progress/cancellation, failure/retry,
  queue controls, thumbnails, and replay.

**Later**

- `PR-MVP-070`: native SVD XT product slice and hardware preflight.
- `PR-MVP-080`: operator UX, setup, diagnostics, and bounded lint cleanup.
- `PR-MVP-090`: clean-machine release proof and zero Ruff baseline.

## Verification state

Latest verified baseline for the converged product state:

- repository completeness: 431 tracked Python source files; verification passed
  on the committed branch;
- strict local collection: 3,066 tests plus 2 optional-OpenCV module skips;
- required smoke: 95 passing on Python 3.11 and 3.12;
- bounded mypy smoke: passing;
- Ruff 0.14.9 baseline: 1,610 findings against a maximum of 2,208.

Phase 2C branch verification collected 3,066 tests and passed 97 required smoke
tests on the available local interpreter; required Python 3.11/3.12 CI was not
rerun in this phase.

Run focused tests, then `python tools/ci/run_pr_gate.py`. GitHub required CI on
Python 3.11 and 3.12 is the canonical integration verdict.

The focused repository, queue, history, and migration sweep passes 125 tests.
Superseded JSON/JSONL persistence and pre-NJR compatibility tests were removed
or rewritten against the current repository contract. A repository-wide test
run was not used as an acceptance gate for this bounded PR.

The local WebUI image path has completed a fixed-seed queue-to-runner smoke.
Occasional runner stalls and queue errors have been observed outside that
controlled run and remain known operational instability; convergence did not
claim to resolve them.

Run the commands in `docs/StableNew_Coding_and_Testing_v2.6.md` rather than
copying these numbers elsewhere. Update this section only after a comparable
verified run.

## Update rule

Any change that materially alters repository direction, active work, roadmap
status, or verified baseline updates this file. Keep it current and concise;
use Git history and `CHANGELOG.md` for history.
