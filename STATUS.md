# StableNew status

Updated: 2026-09-07

## Repository

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Product name: StableNew
- Default branch: `main`
- Current release line: v2.6 MVP recovery
- Current recovery baseline: `recovery/mvp-baseline` at `9f1be49`

The recovery branch is ahead of `main` with the reconciled architecture,
repository-completeness repair, test-harness recovery, immutable NJR core, and
typed compiler/submission cutover. It intentionally did not bulk-merge the two
later `main` commits; their relevant deltas were dispositioned separately.

## Product state

StableNew has a verified queue-first NJR/runner spine and trustworthy bounded CI
gates. The immutable NJR and source-specific submission boundary are complete.
It is not yet an MVP: queue/history persistence has not converged on SQLite,
PromptPack storage still has paired-file assumptions, and the image/video
vertical slices lack clean-machine real-backend acceptance.

## Runtime invariants

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is queue-first.
- NJR is immutable authorized work.
- Mutable lifecycle/result state belongs outside NJR.
- PromptPack identity is conditional on PromptPack source.
- Replay uses a new NJR with parent lineage.
- GUI/controllers do not create alternate runner paths.

## Current work

Repository simplification is being performed on
`repo/simplification-and-hygiene`, based on `9f1be49`. Its purpose is to reduce
instructions, historical documentation, generated artifacts, and obsolete
maintenance clutter without changing runtime behavior. After review/merge,
delete the short-lived branch and update this section.

## Highest-value debt

1. JSON/JSONL queue and history stores still compete with the target SQLite
   repository authority.
2. PromptPack native storage has remaining paired TXT/JSON assumptions.
3. The image create-to-replay journey lacks recorded real-WebUI acceptance.
4. Legacy CLI/compatibility and migration tests still assert pre-cutover NJR
   fields and payload shapes; the broad suite is therefore not green.
5. Ruff still has a bounded legacy baseline; repository-wide mypy is not clean.

## Now / next / later

**Now**

- Complete and review repository simplification.

**Next**

- `PR-MVP-040`: implement transactional SQLite `JobRepository` plus a
  backup-first, dry-run-capable, idempotent legacy importer.

**Later**

- `PR-MVP-050`: one-file JSON PromptPack convergence.
- `PR-MVP-060`: reliable image create/queue/run/artifact/history/replay slice.
- `PR-MVP-070`: native SVD XT product slice and hardware preflight.
- `PR-MVP-080`: operator UX, setup, diagnostics, and bounded lint cleanup.
- `PR-MVP-090`: clean-machine release proof and zero Ruff baseline.

## Verification state

Latest verified baseline including this repository-hygiene change:

- repository completeness: 429 tracked Python source files;
- strict collection: 3,086 tests plus 2 optional-OpenCV module skips on the
  supported Python 3.11 and 3.12 environments;
- required smoke: 74 passing on Python 3.11 and 3.12;
- bounded mypy smoke: passing;
- Ruff 0.14.9 baseline: 1,859 findings against a maximum of 2,208.

A Python 3.11 broad diagnostic stopped at the configured first 10 failures
after 215 passes and 2 optional-OpenCV skips. The failures are in unchanged
legacy CLI/compatibility/migration tests whose expectations predate the typed
NJR cutover; they are not part of the required green gate.

Run the commands in `docs/StableNew_Coding_and_Testing_v2.6.md` rather than
copying these numbers elsewhere. Update this section only after a comparable
verified run.

## Update rule

Any change that materially alters repository direction, active work, roadmap
status, or verified baseline updates this file. Keep it current and concise;
use Git history and `CHANGELOG.md` for history.
