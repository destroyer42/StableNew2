# StableNew MVP Golden-Path Test Matrix v2.6

Status: Canonical Tier 3
Updated: 2026-09-05
Scope: active MVP only

## 0. Purpose

This matrix defines the minimum end-to-end proof for the MVP architecture. It
replaces the older broad stage-combination matrix as the active release gate.
Additional feature tests may remain, but they do not expand MVP scope.

All fresh journeys follow:

`Visible Intent -> Typed Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifact/History Projection`

## 1. Layer legend

| Layer | Proof |
|---|---|
| A | Intent/editor and validation |
| B | Compiler and NJR contract |
| C | JobService, repository, and queue lifecycle |
| D | Runner and typed backend handler |
| E | Artifact, history, replay, and restart |
| F | GUI responsiveness and operator diagnostics |
| G | Migration and rollback |

## 2. Active journeys

| ID | Journey | Backend | Required layers | Automated | Real acceptance |
|---|---|---|---|---|---|
| GP-MVP-01 | Launch with dependencies available | Fake/preflight | A, F | Yes | Yes |
| GP-MVP-02 | Launch with WebUI unavailable | Fake failure | A, F | Yes | Yes |
| GP-MVP-03 | Create/save/reload JSON PromptPack | None | A | Yes | Manual smoke |
| GP-MVP-04 | Import legacy TXT/TSV/paired pack | None | A, G | Yes | Manual smoke |
| GP-MVP-05 | Compile one deterministic image NJR | None | A, B | Yes | No |
| GP-MVP-06 | Add one image to queue | Fake image | B, C, F | Yes | No |
| GP-MVP-07 | Run Now image | Fake image | B, C, D, E, F | Yes | Yes, WebUI |
| GP-MVP-08 | FIFO two-image queue | Fake image | B, C, D, E, F | Yes | Optional |
| GP-MVP-09 | Image backend failure and retry | Fake failure | C, D, E, F | Yes | Manual smoke |
| GP-MVP-10 | Cancel queued/running image | Blocking fake | C, D, E, F | Yes | Manual smoke |
| GP-MVP-11 | Restart with durable queue/history | Fake image | C, E | Yes | Manual smoke |
| GP-MVP-12 | Replay completed image | Fake image | B, C, D, E | Yes | Yes, WebUI |
| GP-MVP-13 | Non-pack reprocess/image-edit identity | Fake image | A, B, C, D, E | Yes | Manual smoke |
| GP-MVP-14 | Selected image to SVD XT clip | Fake video | A–F | Yes | Yes, native SVD |
| GP-MVP-15 | Missing SVD model/capability | Fake preflight | A, C, F | Yes | Yes |
| GP-MVP-16 | Legacy job-store import and rollback | None | C, E, G | Yes | Rehearsal |
| GP-MVP-17 | Tracked-files-only startup/import | None | A, B, C | Yes | Clean machine |

PR-MVP-020 closes the reusable NJR-core portion of layer B: exact eight-field
shape, recursive immutability, typed workload/source validation, complete
round-trip serialization, conditional PromptPack identity, explicit legacy
migration, and runner non-mutation are automated. PR-MVP-030 closes the
source-specific compiler and submission proof for GP-MVP-05/06: enabled sources
submit complete NJRs through `JobService.submit_njrs` and Run Now remains
queue-first. Repository durability and real-backend acceptance remain open.

## 3. Common invariants for every execution journey

- Exactly one NJR is the authorized execution envelope per job.
- `Run Now` creates a queued execution record before runner invocation.
- Only `PipelineRunner.run_njr` is called as the public runner entry.
- Queue/history state changes do not mutate the NJR snapshot.
- PromptPack identity exists only for PromptPack sources.
- Errors reach a durable state and do not trigger a legacy fallback.
- Produced artifacts link to job, attempt, workload, stage, and provenance.
- GUI updates occur through the GUI-thread/event boundary.
- Tests use temporary repository and artifact roots.

## 4. Journey acceptance details

### GP-MVP-03 — One-file PromptPack

Create a pack with one prompt and default image settings, save it, restart the
pack service, and load it from JSON alone. Assert schema version, stable identity,
prompt text, defaults, and no required sibling TXT/TSV file.

### GP-MVP-04 — PromptPack migration

Cover matching and conflicting legacy inputs. Dry-run must not write. Commit
must preserve originals, produce valid JSON, report counts/checksums, and be
idempotent. Conflicts remain unresolved until explicitly selected.

### GP-MVP-05 — Deterministic compilation

Compile identical intent twice with fixed seed/registry inputs. Compare the
complete serialized NJRs while excluding only explicitly generated job identity.
Assert no status, timestamps, progress, errors, results, paths, or retry state.

### GP-MVP-07 — Run Now image

From the visible image workflow, submit a valid PromptPack. Assert repository
creation precedes queue/runner work; lifecycle reaches completed; one canonical
image artifact and history record appear; queue and UI remain responsive.

### GP-MVP-09 — Failure and retry

Fail the image handler with a stable error. Assert failed durable state,
diagnostic projection, no artifact claim, and no fallback. Retry must preserve
parent/attempt lineage and execute through the same queue path.

### GP-MVP-11 — Restart

Persist queued, running/interrupted, completed, and failed fixtures. Restart
application services using the same temporary SQLite database. Assert defined
recovery states, no duplicate execution, intact NJR snapshots, and correct
history projection.

### GP-MVP-12 — Replay

Replay a completed history item. Assert a new job/NJR identity, parent lineage,
equivalent authorized workload, and normal queue/runner execution. No source
file or legacy config reconstruction occurs in the runner.

### GP-MVP-13 — Non-pack identity

Submit reprocess/image-edit intent with its own source descriptor and parent
artifact. Assert successful validation without `prompt_pack_id` and otherwise
identical queue/runner ownership.

### GP-MVP-14 — Native SVD XT

Select an image artifact, compile a video NJR, queue it, invoke only the native
SVD handler, and produce a canonical clip artifact/history result. Real
acceptance records model revision, license notice, GPU, peak-memory observation,
offload/chunk settings, duration, and output.

### GP-MVP-15 — Video preflight failure

With model or capability absent, assert the app still launches, submission is
blocked or fails before model load according to the approved contract, the user
gets corrective instructions, and repository state remains coherent.

### GP-MVP-16 — Job-store migration

Import representative queue/history JSON/JSONL into a new database. Verify
backup, dry-run, counts, stable IDs, statuses, NJR snapshots, errors, artifact
links, conflicts, two-run idempotence, and rollback in a disposable workspace.

### GP-MVP-17 — Repository completeness

Create a disposable worktree from tracked files only. Compile and import the
approved module set without copying ignored local modules or state. Assert test
execution leaves `git status --short` unchanged.

## 5. Test execution classes

### Hermetic gate

Runs without display, network, GPU, model download, WebUI, or repository-local
mutable state. Uses fakes and temporary roots. All journeys except real columns
must have hermetic coverage where meaningful.

### GUI gate

Runs with a controlled GUI environment and fake backends. It verifies visible
state, scheduling, bounded shutdown/cancel, and no worker-thread widget access.

### Real-backend gate

Opt-in and bounded. It never runs during collection. WebUI image and native SVD
acceptance are release requirements and must publish their environment/result
record; a mock-only result cannot close `PR-MVP-090`.

## 6. Failure conditions

The MVP gate fails on:

- any unexpected collection error or hang;
- missing tracked production imports;
- direct runner invocation or alternate execution payload;
- universal PromptPack identity enforcement;
- NJR mutation or incomplete serialization;
- live legacy persistence fallback;
- test mutation of tracked data;
- unbounded GUI wait or worker-thread GUI write;
- real-backend crash that leaves a job non-terminal or data inconsistent;
- missing image or SVD acceptance evidence.

## 7. Post-MVP coverage

Comfy/LTX, AnimateDiff, secondary motion, multi-shot sequencing, stitching,
training productization, and broad stage-combination matrices are not active MVP
gates. They require roadmap admission and their own canonical journeys.
