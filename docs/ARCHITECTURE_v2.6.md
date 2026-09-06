# StableNew Architecture v2.6

Status: Canonical, Binding
Updated: 2026-09-05
Decision: MVP architecture reconciliation

## 0. Purpose and truth model

This document defines the architecture StableNew is converging on for its MVP.
It is intentionally narrower than earlier v2.6 designs and is grounded in the
parts of the repository that have demonstrated stable behavior.

Every architectural statement is one of two things:

- a **preserved invariant**, which new code must obey immediately; or
- a **target contract**, whose remaining implementation gap is named in this
  document and scheduled in the active roadmap.

Documentation must never imply that a target contract is already implemented.
The gap register in section 13 is authoritative until the corresponding PR is
completed and verified.

## 1. Architecture decision

StableNew will not make the current code the architecture merely because it
runs, and it will not preserve the earlier PromptPack-only model merely because
it was documented. The selected approach is an evidence-based amendment:

1. retain the queue-first NJR/runner spine that has worked;
2. reduce NJR to an immutable execution envelope;
3. move mutable lifecycle state to queue/history records;
4. make PromptPack one typed source of intent rather than a universal identity;
5. keep execution in one process for MVP;
6. use one repository boundary backed by SQLite;
7. limit MVP video to native SVD XT;
8. remove compensating adapters and duplicate paths as each replacement lands.

The failed child-runtime-host migration from March 2026 is historical evidence,
not a foundation to finish. The recovery baseline and exact commit evidence are
recorded in `docs/StableNew Roadmap v2.6.md` and `PR-MVP-000`.

## 2. Canonical runtime

The single production path is:

`Intent Surface -> Typed Intent DTO -> Compiler -> NJR -> JobService -> Queue -> PipelineRunner.run_njr -> Typed Stage Handler -> Artifacts -> History/Learning/Diagnostics`

Preserved invariants:

- all fresh execution is submitted to the queue;
- `Run Now` means enqueue with immediate-start policy, not direct execution;
- `NormalizedJobRecord` (NJR) is the only public executable envelope;
- `PipelineRunner.run_njr(...)` is the only public production runner entry;
- StableNew owns orchestration, persistence, artifacts, history, and diagnostics;
- a backend executes a typed request and does not define a parallel job model;
- replay and retry re-enter the same NJR/queue/runner path;
- GUI code captures intent and presents projections; it does not build backend
  payloads, write queue state, or invoke the runner.

`DIRECT`, alternate runner entrypoints, raw workflow dictionaries as public
contracts, and live legacy fallbacks are forbidden.

## 3. Intent and compiler boundary

An intent surface owns user-facing draft data only. Active source kinds are:

- `prompt_pack`
- `image_edit`
- `reprocess`
- `history_replay`
- `learning`
- `video_workflow`
- `cli`
- `training`

Each surface has a typed intent DTO and a compiler. A compiler validates intent,
resolves defaults and model references, expands deterministic variants, and
emits one or more NJRs. A compiler may call shared normalization services, but
it must not enqueue or execute work itself.

The old pack-shaped `PipelineRunRequest` is not the generic application
submission contract. It may survive only while its PromptPack compiler callers
are migrated. The target `JobService` accepts an NJR plus a small submission
policy such as priority and immediate-start preference.

## 4. NormalizedJobRecord

### 4.1 Responsibility

NJR answers: **what immutable work was authorized?** It does not answer: **what
happened while that work ran?**

The v2.6 MVP NJR core contains:

| Field | Contract |
|---|---|
| `schema_version` | Explicit NJR schema version |
| `job_id` | Stable unique execution identity |
| `workload_kind` | `image`, `video`, or `training` |
| `source` | Typed source descriptor |
| `workload` | Typed, immutable workload execution specification |
| `stages` | Ordered, validated stage descriptions |
| `output_plan` | Stable output naming/routing intent, not produced paths |
| `provenance` | Reproducibility inputs, versions, seeds, and parent lineage |

The source descriptor contains:

- `kind` from the supported source-kind set;
- optional `id` and `revision` appropriate to that kind;
- optional parent job/artifact references.

`source.id` is required when `source.kind == "prompt_pack"`. It is not required
for unrelated source kinds. A generic `prompt_pack_id` requirement is forbidden.

### 4.2 Immutability and serialization

An NJR is immutable after submission. Changes create a new NJR with explicit
lineage. Serialization must round-trip every core and workload-specific field;
silent omission is a contract failure. Schema upgrades are explicit, tested,
and one-way at the repository boundary.

### 4.3 State that is not NJR

The following are mutable runtime facts and belong to queue/history execution
records, not NJR:

- status and progress;
- created, queued, started, finished, and updated timestamps;
- retry count and retry policy state;
- errors and cancellation state;
- produced output paths, thumbnails, and result summaries;
- worker/runtime ownership and transient diagnostics.

## 5. Queue, repository, and history

`JobRepository` is the single persistence boundary for jobs and execution
records. Its canonical MVP backend is SQLite.

- Queue is a projection of repository records in runnable states.
- History is a projection of terminal execution records.
- The GUI observes application-level projections; it does not read persistence
  files directly.
- Repository transactions own lifecycle transitions and durable results.
- Queue workers operate in the StableNew process for MVP.

Existing JSON/JSONL state is migration input only. The migration is backup-first,
offline, idempotent, and conflict-reporting. There is no live JSON fallback after
cutover. Legacy files remain untouched until import validation succeeds, then
are retained as recoverable backups according to the migration runbook.

## 6. Runner and stage execution

`PipelineRunner.run_njr(...)` validates the envelope, creates a run plan, and
delegates to typed internal handlers. One public entrypoint does not require one
monolithic implementation.

Permitted internal handlers include image, video, and training handlers. They:

- receive typed input derived from NJR;
- report progress and results through runner-owned callbacks/contracts;
- return canonical artifact/result descriptions;
- do not mutate the NJR;
- do not own queue state or history persistence;
- do not accept GUI objects or source-authoring DTOs.

A child runtime host, daemon, distributed scheduler, or multi-node executor is
post-MVP work and requires a new architecture decision.

## 7. Image execution and PromptPack

PromptPack is the primary authored image source, not the identity of every job.
Its canonical storage is one versioned JSON document containing prompts,
negative prompts, authoring metadata, matrix definitions, and defaults.

TXT and TSV are import/export interchange formats only. They are not paired
runtime authorities and are never consulted after NJR construction. Migration
from legacy paired files must report conflicts instead of silently choosing one
side.

The canonical still-image stage order is:

`txt2img -> optional img2img/refine -> optional adetailer -> optional upscale`

Only stages implemented and covered by the MVP golden path may be advertised as
MVP-supported.

## 8. Video execution

Video uses the same outer path and NJR lifecycle as image work. Video-specific
intent and execution types are legitimate typed boundaries, not NJR substitutes.

The MVP video backend is **native Stable Video Diffusion XT (SVD XT) only**.
The model is not bundled. Setup must provide:

- an explicit download/install path;
- license and usage notice;
- capability and model preflight;
- memory-conscious defaults, offload, and chunking appropriate for a 12 GB GPU;
- a deterministic smoke workflow and actionable failure messages.

ComfyUI, LTX, AnimateDiff, multi-shot sequencing, stitching, and secondary-motion
systems are post-MVP. Existing code for them may remain quarantined during
recovery but must not be on the MVP execution path or presented as MVP-ready.

Raw backend workflow JSON is private to its backend adapter. It must not leak
into NJR core, controllers, GUI state, queue records, or history as a public
StableNew contract.

## 9. Training execution

Training is a valid typed NJR workload and may delegate to a runner-owned local
subprocess. External trainer tools do not define queue records or public job
models. Training is not an MVP release gate unless the active roadmap is amended
by the owner.

## 10. Artifacts, replay, and learning

Artifacts carry stable job identity, workload kind, stage identity, source
provenance, model/config fingerprints, seeds where applicable, and parentage.
Produced paths and mutable inspection state live in execution results.

Replay creates or hydrates a valid NJR, records parent lineage, and submits it
through `JobService`. Learning consumes canonical artifacts and history; it does
not modify PromptPacks or NJRs in place.

## 11. Application and GUI ownership

Application services coordinate compilers, repository operations, queue policy,
and runner lifecycle. Controllers remain thin adapters between GUI events and
application services. GUI state may cache display projections but may not become
a second source of execution truth.

The MVP remains a single-process desktop application. Threaded work must marshal
UI changes onto the GUI thread and expose bounded cancellation/error behavior.

## 12. Forbidden patterns

- requiring PromptPack identity for non-PromptPack jobs;
- mutable execution/result fields on NJR;
- queue and history persistence with competing authorities;
- live dual-read or dual-write migration modes;
- GUI-built prompts, normalized configs, or backend payloads;
- direct fresh runner invocation;
- runner fallback to legacy job/config dictionaries;
- using video workflow DTOs as alternate executable identities;
- import-time network calls, worker startup, or repository mutation;
- untracked production modules hidden by broad `.gitignore` rules;
- reviving the failed child runtime host during MVP recovery.

## 13. Current implementation gap register

Audit date: 2026-09-05. These gaps mean the target contract is not yet fully
implemented:

| Gap | Status | Current evidence | Closing roadmap item |
|---|---|---|---|
| Repository completeness | **Closed 2026-09-05** | All imported `src/state/` modules and focused tests are tracked; the root ignore rule is anchored; a tracked-files-only worktree passed completeness, compile, import, and 42 focused tests | `PR-MVP-000` |
| NJR scope | Open | Current NJR mixes executable input with mutable status/results and has incomplete serialization | `PR-MVP-020` |
| Source identity | Open | `JobService` still emits `pack_required` for valid non-pack shapes | `PR-MVP-020` / `PR-MVP-030` |
| Submission DTO | Open | `PipelineRunRequest` remains pack-shaped and broad | `PR-MVP-030` |
| Persistence | Open | Queue/history have multiple JSON/JSONL-era stores rather than one SQLite repository | `PR-MVP-040` |
| PromptPack format | Open | Paired TXT/JSON assumptions remain in docs/code/tests despite unified JSON behavior | `PR-MVP-050` |
| Test truth | Open | Collection includes script-style failures, broad pollution risk, stale architecture assertions, and conflicting pytest configuration surfaces | `PR-MVP-010` and each contract PR |
| Video scope | Open | Several video paths exist; only native SVD XT is selected for MVP | `PR-MVP-070` |
| Release proof | Open | No clean-checkout, end-to-end image/video MVP acceptance record exists | `PR-MVP-090` |

Closing a row requires implementation evidence and tests. Updating prose alone
does not close a gap.

## 14. Change control

Architecture changes require an approved PR spec, synchronized amendments to
all affected canonical documents, verification against repository truth, and
owner approval. Compatibility bridges must have a named deletion PR and may not
create a second live execution path.

This amendment preserves version v2.6 because it corrects the unfinished v2.6
migration instead of adding a new runner or distributed-execution architecture.
