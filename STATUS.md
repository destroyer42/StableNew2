# StableNew status

Updated: 2026-09-07

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
gates, and one transactional SQLite authority for job lifecycle state. Queue
and history are repository projections, and legacy JSON/JSONL state has an
offline backup-first importer. It is not yet an MVP: PromptPack storage still
has paired-file assumptions, and the image/video vertical slices lack
clean-machine real-backend acceptance. PR-MVP-045 restored the PromptPack
draft-to-preview-to-queue path; one-file storage remains the next blocker.

## Runtime invariants

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is queue-first.
- NJR is immutable authorized work.
- Mutable lifecycle/result state belongs outside NJR.
- PromptPack identity is conditional on PromptPack source.
- Replay uses a new NJR with parent lineage.
- GUI/controllers do not create alternate runner paths.

## Current work

Repository convergence, simplification, transactional job persistence, and the
PR-MVP-045 PromptPack draft/preview/queue repair are complete. New work starts
from `main` on one short-lived outcome branch. The next outcome is one-file
PromptPack convergence; do not revive the recovery, hygiene, or QOL branches as
alternate sources of truth.

## Highest-value debt

1. PromptPack native storage has remaining paired TXT/JSON assumptions.
2. The image create-to-replay journey lacks recorded real-WebUI acceptance.
3. Legacy CLI/compatibility and superseded JSON migration tests assert pre-cutover NJR
   fields and payload shapes; the broad suite is therefore not green.
4. Ruff still has a bounded legacy baseline; repository-wide mypy is not clean.

## Now / next / later

**Now / Next**

- `PR-MVP-050`: converge PromptPack native storage on one versioned JSON file.

**Later**

- `PR-MVP-060`: reliable image create/queue/run/artifact/history/replay slice.
- `PR-MVP-070`: native SVD XT product slice and hardware preflight.
- `PR-MVP-080`: operator UX, setup, diagnostics, and bounded lint cleanup.
- `PR-MVP-090`: clean-machine release proof and zero Ruff baseline.

## Verification state

Latest verified baseline for the converged product state:

- repository completeness: 427 tracked Python source files; verification passed
  on the committed branch;
- strict collection: 3,019 tests plus 2 optional-OpenCV module skips on the
  supported Python 3.11 and 3.12 environments;
- required smoke: 87 passing on Python 3.11 and 3.12;
- bounded mypy smoke: passing;
- Ruff 0.14.9 baseline: 1,842 findings against a maximum of 2,208.

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
