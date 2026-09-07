# Finalized MVP Roadmap — StableNew v2.6

Status: **CURRENT AND ACTIVE**
Owner: Rob
Updated: 2026-09-07
Supersedes: all earlier active roadmap, mini-roadmap, and backlog ordering claims

## 0. Roadmap authority

This is the single active execution roadmap for StableNew. Files in
`docs/CompletedPlans/`, `docs/archive/`, and unlisted files in
`docs/PR_Backlog/` are historical or untriaged inputs, not competing plans.

Work may enter the active sequence only through an owner-approved amendment to
this file. PR status claims in older documents do not override repository
evidence or this roadmap.

## 1. Outcome

Deliver a dependable local desktop MVP that can:

1. start from a clean checkout using documented setup;
2. create, import, edit, validate, and select one-file JSON PromptPacks;
3. compile image intent into an immutable NJR;
4. submit both **Add to Queue** and **Run Now** through one queue path;
5. execute a basic still-image job against a configured Stable Diffusion WebUI;
6. persist queue/history state through one SQLite repository;
7. show progress, actionable errors, artifacts, and history without UI stalls;
8. replay a completed image job through the same NJR/queue/runner path;
9. turn a selected image into a short native SVD XT video on the target machine;
10. survive restart without corrupting job identity, history, or artifacts.

The MVP is a reliable vertical slice, not completion of every existing feature.

## 2. Architectural basis

The canonical runtime is:

`Typed Intent -> Compiler -> NJR -> JobService -> Queue/JobRepository -> PipelineRunner.run_njr -> Typed Handler -> Artifacts -> History/Learning/Diagnostics`

The roadmap preserves the parts of the codebase that have shown stable behavior:

- queue-only fresh execution;
- a single `run_njr` runner entry;
- StableNew-owned orchestration;
- same-process, single-node execution;
- backend-specific typed handlers behind the runner.

It corrects the migration seams that caused compensating behavior:

- PromptPack identity becomes conditional on a PromptPack source;
- the broad mutable NJR becomes a small immutable execution envelope;
- queue/history mutable state moves to a job execution record;
- pack-shaped generic requests become source-specific DTOs and compilers;
- queue and history converge on one SQLite repository;
- unified PromptPack JSON becomes native; TXT/TSV become interchange only;
- video is narrowed to native SVD XT for MVP.

## 3. Evidence-based recovery point

Repository audit on 2026-09-05 found:

- `f919cb4` (`Finally stable again, small issues left, no GUI stall`) is the best
  demonstrated behavioral baseline before the later issue/QOL changes;
- commits `5634849`, `75ffb27`, `303cbdb`, and `fab810b` chronicle the failed
  child-runtime-host cutover and repeated instability;
- the current `QOL-Work` branch at `1a9eb49` and `main` at `d452a2a` must be
  preserved as comparison sources, not overwritten or accepted wholesale;
- `24063b7` contains later fixes that require individual audit;
- production imports depend on `src/state/__init__.py`,
  `src/state/workspace_paths.py`, and `src/state/output_routing.py`, but an
  unanchored `state/` ignore rule prevents those files from being tracked;
- current NJR and `JobService` behavior still mixes old and new identity/state
  assumptions;
- test collection and execution do not yet provide trustworthy release proof.

Recovery therefore starts from `f919cb4` plus the approved architecture-doc
commit and explicitly audited recovery files. It does not reset, delete, or
rewrite the existing branches.

## 4. MVP definition of done

### 4.1 Product acceptance

- A new user can follow one setup guide and launch the application.
- Missing WebUI, model, ffmpeg, or SVD dependencies produce bounded preflight
  failures with corrective instructions.
- A valid JSON PromptPack produces a deterministic one-image queue job.
- `Run Now` and `Add to Queue` differ only in scheduling policy.
- Queue state transitions are visible and remain responsive.
- A completed image appears in artifacts and history with correct NJR lineage.
- Replay creates a new NJR with a parent reference and uses the same runtime.
- A selected image can produce the supported native SVD XT smoke clip on the
  12 GB RTX 4070 Ti target using memory-safe defaults.
- Restart preserves durable queue/history data without duplicate execution.
- No MVP flow requires a fabricated PromptPack identity.

### 4.2 Engineering acceptance

- All production Python modules are tracked and importable in a clean checkout.
- No fresh path bypasses queue or `PipelineRunner.run_njr`.
- NJR round-trips every field and contains no mutable execution/result state.
- One SQLite-backed `JobRepository` owns lifecycle persistence.
- Legacy JSON/JSONL and paired PromptPack inputs have backup-first, idempotent,
  conflict-reporting migration tools; there is no live fallback.
- Test collection has zero unexpected errors and zero import-time side effects.
- All non-quarantined canonical tests pass from a disposable workspace.
- Real-backend image and SVD smoke results are recorded on the target machine.
- The architecture gap register has no open MVP rows.

## 5. Active PR sequence

| Order | PR | Status | Exit outcome |
|---:|---|---|---|
| 0 | `PR-ARCH-MVP-001` | **Implemented; merge review pending** | Reconciled canon committed as `45b8d07` and carried to recovery as `14d1071` |
| 1 | `PR-MVP-000` | **Completed** | Recoverable clean baseline with all production source tracked and independently verified |
| 2 | `PR-MVP-005` | **Completed** | 115 later changed-file occurrences classified into 17 binding dispositions without runtime adoption |
| 3 | `PR-MVP-010` | **Completed** | Trustworthy isolated test gates plus a pinned non-increasing lint baseline |
| 4 | `PR-MVP-020` | **Completed** | Reduced immutable NJR and complete versioned serialization |
| 5 | `PR-MVP-030` | **Completed 2026-09-07** | Typed compilers and NJR-only JobService submission contract |
| 6 | `PR-MVP-040` | Planned | SQLite JobRepository with verified offline legacy import |
| 7 | `PR-MVP-050` | Planned | One-file JSON PromptPack and conflict-safe migration |
| 8 | `PR-MVP-060` | Planned | Reliable image create/queue/run/artifact/history/replay slice |
| 9 | `PR-MVP-070` | Planned | Native SVD XT image-to-video slice and hardware preflight |
| 10 | `PR-MVP-080` | Planned | MVP operator UX, setup, diagnostics, and recovery polish |
| 11 | `PR-MVP-090` | Planned | Clean-machine release candidate and signed acceptance record |

`PR-ARCH-MVP-001` and `PR-MVP-000` were owner-approved and have been
implemented. `PR-MVP-005`, `PR-MVP-010`, and `PR-MVP-020` are complete.
`PR-MVP-030` is complete. Its implementation migrated enabled source families
to NJR-only submission, removed the superseded generic request/preview adapter,
and passed the focused suite, 3,096-test collection, 75-test required smoke on
Python 3.11 and 3.12, bounded mypy smoke, repository completeness after staging,
and the pinned Ruff gate (1,860 findings, down from the 2,208 baseline). Later
rows require their own exact specs and owner approval.

## 6. Phase details

### Phase 0 — Canon and recovery control

#### PR-ARCH-MVP-001 — v2.6 canon amendment

Synchronize architecture, governance, lifecycle, builder, coding/testing,
golden paths, agent briefs, docs index, README, and this roadmap. Explicitly
separate current evidence from target contracts. No runtime files may change.

#### PR-MVP-000 — Recovery baseline and repository completeness

Create a non-destructive recovery branch rooted at `f919cb4`, carry the approved
docs amendment, correct the ignore rule, audit and track the three required
`src/state/` modules, and prove imports from a clean disposable worktree. Preserve
`main`, `QOL-Work`, user state, and all comparison commits.

Exit gate: a clone/worktree containing tracked files only can compile and import
the application modules covered by the spec.

Completion evidence: the root ignore rule is now `/state/`; three `src/state/`
modules and two previously hidden focused tests are tracked; the completeness
guard reports 435 tracked Python source files; and a second tracked-files-only
worktree passed compile, imports, and 42 focused tests without creating root
state or changing tracked files. Python 3.11 environment certification remains
with `PR-MVP-010`; the available run used Python 3.10.6.

#### PR-MVP-005 — Delta disposition

Compare `24063b7`, `d452a2a`, and `1a9eb49` to the recovery branch. Classify each
MVP-relevant change with tests and architecture rationale. Adopt nothing by bulk
merge. Any runtime adoption that exceeds an approved allowlist becomes a
separate spec before implementation.

Approved disposition: carry the WebUI startup/error handling, empty-queue UI,
diagnostic collision, and tracked-probe cleanup behaviors only through their
named future PRs; rewrite submission acceptance, batch scheduling, preview
cardinality, and stale-preview handling on the typed compiler/NJR contracts;
defer ADetailer, multi-character, and learning work unless later roadmap gates
admit them; reject PromptPack-identity fallbacks, fabricated video prompts,
generated state, paired-pack fixture mutations, stale completion claims, and
wholesale pack deletion. The detailed file coverage and owners are binding in
`docs/CompletedPR/PR-MVP-005-Post-Baseline-Delta-Disposition.md`.

Exit gate: no unidentified later-branch dependency can surprise the contract
migration.

Completion evidence: all 115 changed-file occurrences are covered by 17 logical
slices (4 adopt, 4 rewrite, 3 defer, 6 reject); each raw historical snapshot
reproduced the missing-`src/state` collection failure, and each focused suite
passed after applying only the `PR-MVP-000` completeness repair. No comparison
branch or runtime file was changed.

### Phase 1 — Make verification trustworthy

#### PR-MVP-010 — Test harness recovery

Remove collection-time script behavior, isolate filesystem and runtime state,
define test taxonomy/markers, establish deterministic fakes, and add architecture
guards for repository completeness and the one execution path.

Approved scope: delete the competing `pytest.ini` and consolidate strict marker,
import, and exclusion policy in `pyproject.toml`; replace the exclusion-based
2,413-test required command with an exact positive smoke list; make fake/no-WebUI
behavior the default; redirect cache and log writes to temporary paths; make
collection and smoke fail on repository pollution; remove three import-executed
root scripts; untrack the machine-local WebUI cache; and delete the 30 tracked
files under the five `tmp_prompt_pack_probe*` roots. The exact allowlist and
acceptance gates and evidence are preserved in
`docs/CompletedPR/PR-MVP-010-Test-Harness-Recovery.md`.

Audit evidence: the active `pytest.ini` path collected 3,092 tests while warning
that it ignored `pyproject.toml`. Forcing the stricter configuration collected
3,141 tests but exposed three archive/quarantine import errors. The old required
smoke selected 2,413 tests, failed after 87.70 seconds in legacy compatibility
coverage, modified tracked `data/webui_cache.json`, created root `output/`, and
ran backend emergency cleanup. These counts document the broken baseline; they
are not future count assertions.

Completion evidence: disposable Python 3.11.16 and 3.12.14 environments each
pass repository completeness for 435 tracked Python source files, the Ruff
0.14.9 baseline gate over 2,208 findings, the 10-file mypy smoke, strict
collection of 3,083 tests with two explicit optional-OpenCV skips, and all 73
required smoke tests without repository pollution. The repaired regression
module passes its three tests, and a synthetic new Ruff bucket is rejected.

Approved amendment: repair only the duplicate plugin registration in the one
regression test and replace the impossible raw Ruff command with a Ruff 0.14.9
file/rule-count ratchet over all 2,208 existing findings. New or increased lint
debt fails immediately. Every later runtime PR must leave touched files at zero
Ruff findings; `PR-MVP-080` owns remaining mechanical cleanup and `PR-MVP-090`
requires an empty baseline before release certification.

Exit gate: `pytest --collect-only -q` succeeds in a disposable workspace; a
small positively selected canonical smoke suite runs without network, backend,
GPU, GUI display, or mutation of tracked or untracked repository contents; the
required CI matrix passes on Python 3.11 and 3.12.

### Phase 2 — Repair the core contract

#### PR-MVP-020 — NJR core

Introduce the versioned eight-part NJR core, typed source descriptors,
workload-specific specs, conditional source identity, immutability, complete
round-trip serialization, and an explicit migration reader. Move mutable facts
out of NJR types rather than aliasing them indefinitely.

Exit gate: image, video, training, replay, and non-pack source examples validate;
all NJR fields round-trip; `pack_required` exists only in PromptPack-source
validation.

Completion evidence: one recursively frozen eight-field model now represents
image, video, and training work; snapshots use its single complete serializer;
the explicit legacy reader drops status/error/output facts; builders, replay,
submission, and runner do not mutate NJR; non-pack work validates without
PromptPack identity. The focused contract/integration set passed 69 tests,
isolated collection found 3,094 tests with two optional-OpenCV skips, required
smoke passed 75 tests, and the Ruff 0.14.9 raw count fell from 2,208 to 1,866.

#### PR-MVP-030 — Compilers and submission

Create source-specific DTO/compiler seams and change `JobService` to accept NJR
plus submission policy. Migrate source families in explicit slices and remove
the pack-shaped generic request when its last caller is gone.

Exit gate met: every enabled source reaches the queue as NJR, no compiler or GUI
path invokes the runner, and the old pack-shaped request path is gone.

### Phase 3 — Establish one durable state authority

#### PR-MVP-040 — SQLite JobRepository

Implement a transactional SQLite repository for NJR snapshots and mutable job
execution records. Make queue and history projections use it. Add a backup-first,
dry-run-capable, idempotent importer for legacy queue/history JSON/JSONL with
count, identity, checksum, and conflict reporting. Remove live fallback in the
same cutover.

Exit gate: restart, failure, cancellation, retry metadata, artifacts, and replay
survive correctly; rollback to backups is demonstrated in a disposable copy.

### Phase 4 — Deliver the image vertical slice

#### PR-MVP-050 — PromptPack convergence

Make versioned JSON the only native PromptPack authority. Provide explicit
TXT/TSV import/export and a conflict-reporting paired-file migration. Remove
runtime paired-file and universal identity assumptions together.

Exit gate: author/import/save/reload/compile works from JSON alone; conflict and
rollback fixtures pass.

#### PR-MVP-060 — Image golden path

Stabilize one conservative txt2img path first, then add only already-supported
optional stages that pass deterministic contract tests. Wire artifacts, history,
replay, progress, cancellation, and actionable WebUI failures end-to-end.

Exit gate: mocked CI journey passes and a recorded real-WebUI smoke completes
from the GUI on the target machine.

### Phase 5 — Deliver the video vertical slice

#### PR-MVP-070 — Native SVD XT

Keep video behind the NJR runner handler, remove MVP dependence on Comfy/LTX,
and productize native SVD XT image-to-video with model/license/setup guidance,
preflight, offload, chunking, cancellation, artifacts, and failure diagnostics.

Exit gate: deterministic contract tests pass and a short real SVD XT clip is
recorded on the 12 GB target without application or UI failure.

### Phase 6 — Productize and release

#### PR-MVP-080 — Operator UX and recovery

Expose only the MVP-supported paths, add first-run and dependency guidance,
clarify queue/history/errors, provide safe retry/cancel controls, and remove or
label non-MVP surfaces. This is workflow polish, not a GUI rewrite.

#### PR-MVP-090 — Release candidate

Run clean-machine setup, migration rehearsal, canonical tests, real image/video
smokes, restart/replay, and artifact inspection. Freeze versions and publish one
acceptance record containing commands, environment, results, known limitations,
and rollback instructions.

## 7. Critical review and strengthened controls

### Weakness: the chosen baseline may omit valuable later fixes

**Control:** preserve every current branch, recover from `f919cb4`, then use
`PR-MVP-005` to evaluate later deltas individually. No bulk merge or history
rewrite is part of recovery.

### Weakness: a “stable” local tree may depend on ignored files

**Control:** `PR-MVP-000` makes repository completeness the first runtime gate.
All future release verification runs from a tracked-files-only worktree.

### Weakness: NJR and service migration could become another big-bang rewrite

**Control:** freeze the NJR core first, migrate one typed compiler at a time,
retain one queue/runner route throughout, and require deletion of the superseded
branch in the same source-family slice.

### Weakness: persistence convergence risks user data loss

**Control:** separate import from cutover; require dry-run, backup, checksums,
counts, conflict reports, idempotence, and rollback rehearsal. Never dual-write
or delete source files during migration.

### Weakness: existing tests can be green for the wrong architecture or can
damage repository state

**Control:** recover collection and isolation before contract work. Contract
tests assert responsibilities and forbidden paths, while real-backend tests are
explicit, bounded, and separate from hermetic CI.

### Weakness: video can consume the roadmap

**Control:** one backend and one journey only: selected image to short native
SVD XT clip. Comfy, LTX, AnimateDiff, sequencing, stitching, and secondary
motion are explicitly post-MVP.

### Weakness: model availability, license, and 12 GB GPU behavior are external
risk

**Control:** the model is not bundled; preflight verifies installation and
capability. Release proof includes the target RTX 4070 Ti and memory-safe
settings. Failure remains actionable and does not corrupt queue state.

### Weakness: synchronized documents can drift again

**Control:** every target gap has a closing PR. Closeout must update the gap
register, roadmap, index, and affected Tier 2 docs in the same change. Code is
not “done” while active docs claim the old behavior.

### Weakness: broad historical scope can prevent an MVP forever

**Control:** release scope is the definition of done in section 4. Training
productization, distributed execution, closed-loop learning, backend expansion,
and broad UI redesign do not block MVP.

## 8. Release gates by layer

| Layer | Required proof |
|---|---|
| Repository | Clean tracked-files-only checkout imports and compiles |
| Contracts | Versioned NJR/source/workload round-trip and forbidden-field tests |
| Persistence | Transaction, restart, migration, idempotence, and rollback tests |
| Application | Typed compiler -> JobService -> queue -> runner integration tests |
| Image | Mocked journey plus recorded real WebUI smoke |
| Video | Mocked journey plus recorded native SVD XT target-hardware smoke |
| GUI | Responsive queue/progress/error/replay smoke without worker-thread UI writes |
| Operations | Setup, dependency preflight, logs, data location, backup, and recovery guide |
| Documentation | No open MVP gap-register row or contradictory active source |

## 9. Explicitly deferred until after MVP

- ComfyUI/LTX and additional video backends;
- AnimateDiff, secondary motion, multi-shot continuity, and stitching;
- child runtime host, daemon, cluster, or multi-node scheduling;
- full training-product UX;
- automated closed-loop learning decisions;
- large controller or GUI framework rewrites not required by the vertical slice;
- broad performance optimization without measured MVP bottlenecks.

## 10. Next action

Generate and approve the exact `PR-MVP-040` specification. Implement the
SQLite `JobRepository` and backup-first offline legacy importer before adding
the one-file PromptPack migration or claiming restart/replay durability. Keep
the repository cutover atomic: no live dual-read, dual-write, or fallback.
