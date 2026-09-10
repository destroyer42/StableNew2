# Finalized MVP Roadmap — StableNew v2.6

Status: CURRENT AND ACTIVE
Owner: Rob
Updated: 2026-09-10

This is the only active roadmap. `STATUS.md` identifies the work happening now;
Git history preserves completed plans and earlier sequencing.

## MVP outcome

Deliver a dependable local desktop application that can:

1. launch from a documented clean checkout;
2. create, import, edit, validate, and select one-file JSON PromptPacks;
3. compile image intent into an immutable NJR;
4. submit Add to Queue and Run Now through the same queue path;
5. execute a conservative still-image job through WebUI;
6. persist queue/history state through one SQLite repository;
7. show progress, actionable errors, artifacts, and history responsively;
8. replay a completed image job with explicit parent lineage;
9. turn a selected image into a short native SVD XT video;
10. survive restart without corrupting identities, history, or artifacts.

The MVP is this reliable vertical slice, not completion of every existing
feature.

## Architectural basis

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is queue-first.
- NJR is immutable and versioned.
- Queue/history own mutable lifecycle and results.
- PromptPack is one typed source rather than universal identity.
- StableNew owns orchestration; backends execute typed requests.
- MVP execution is same-process and single-node.
- Native SVD XT is the only MVP video backend.

## Definition of done

- Production modules are tracked and importable from a clean checkout.
- No fresh path bypasses the queue or `PipelineRunner.run_njr`.
- NJR round-trips completely and contains no mutable lifecycle/result state.
- One SQLite-backed `JobRepository` owns lifecycle persistence.
- Legacy job and PromptPack migration is backup-first, idempotent, and
  conflict-reporting, with no live fallback.
- A mocked image journey and recorded real-WebUI smoke pass.
- A mocked SVD journey and recorded target-hardware smoke pass.
- Restart/replay preserves identity, lineage, status, and artifacts.
- Setup, preflight, errors, rollback, and recovery are documented.
- The architecture gap register has no open MVP rows.

## Active sequence

| Order | Work | Status | Outcome |
|---:|---|---|---|
| 0 | Architecture reconciliation | Complete | Evidence-based v2.6 canon |
| 1 | `PR-MVP-000` | Complete | Recoverable tracked-source baseline |
| 2 | `PR-MVP-005` | Complete | Later deltas classified without bulk merge |
| 3 | `PR-MVP-010` | Complete | Trustworthy isolated verification gates |
| 4 | `PR-MVP-020` | Complete | Immutable eight-part NJR contract |
| 5 | `PR-MVP-030` | Complete | Typed compilers and NJR-only submission |
| 6 | `PR-MVP-040` | Complete | SQLite repository and offline legacy import |
| 7 | `PR-MVP-045` | Complete | PromptPack draft, preview, and queue repair |
| 8 | `PR-MVP-050` | Complete | One-file JSON PromptPack convergence |
| 9 | `PR-MVP-060` | Complete | Image create-to-replay vertical slice |
| 10 | `PR-MVP-070` | Next | Native SVD XT vertical slice |
| 11 | `PR-MVP-080` | Planned | Operator UX, setup, diagnostics, lint cleanup |
| 12 | `PR-MVP-090` | Planned | Clean-machine release acceptance |

Roadmap progress is 10 of 13 rows (77%). Functional MVP remains incomplete
because native SVD XT, operator readiness, and clean-machine release proof
remain.

### PR-MVP-045 — PromptPack draft, preview, and queue repair

The production PromptPack workflow now expands Matrix selections into immutable
NJR provenance, compiles valid drafts into executable previews, preserves stage
override precedence, coalesces preview refreshes, and submits through the
SQLite-backed JobService path. Incomplete generic GUI state is non-runnable and
quiet rather than routed through the retired ConfigAssembler.

### PR-MVP-050 — PromptPack convergence

Versioned schema-1 JSON is now the sole native PromptPack authority. Normal save
creates no text sidecar; discovery and compilation ignore same-stem TXT/TSV;
Matrix and PR-MVP-045 preview/queue behavior run from JSON alone. TXT/TSV are
explicit flattened interchange, and the repository pair migration is
backup-first, semantic, conflict-reporting, and idempotent.

Exit achieved: author/import/save/reload/compile works from JSON alone.

### PR-PACKS-001 — external PromptPack storage hygiene

This intervening repository and user-data hygiene PR converged the active
PromptPack library, preserved migration backup and quarantine evidence, moved
production authority to `%LOCALAPPDATA%\StableNew\PromptPacks`, and retired
superseded PromptPack worktrees and branches. It did not renumber the MVP
sequence.

### PR-MVP-060 — image vertical slice

The conservative txt2img path, optional stages, queue policy, progress,
cancellation, artifacts, history, replay, and real-WebUI GUI acceptance are
complete and accepted.

## Remaining work

### PR-MVP-070 — native SVD XT

Keep video behind the NJR runner handler and productize only native SVD XT for
MVP. Add model/license/setup guidance, capability preflight, memory-conscious
defaults, cancellation, artifacts, and actionable failures.

Exit: deterministic tests and a short real clip pass on the target 12 GB GPU.

### PR-MVP-080 — operator readiness

Expose or clearly label only supported paths. Add first-run guidance, dependency
diagnostics, queue/history recovery controls, and bounded mechanical Ruff
cleanup. This is workflow polish, not a GUI rewrite.

### PR-MVP-090 — release proof

Run clean-machine setup, migration rehearsal, canonical gates, real image/video
smokes, restart/replay, and artifact inspection. Remove the Ruff baseline only
after raw lint is clean, then publish one acceptance record with limitations and
rollback steps.

## Risk controls

- Never bulk-merge comparison branches; adopt changes by current need and test.
- Never migrate user data without dry-run, backup, verification, idempotence,
  conflict reporting, and rehearsed rollback.
- Keep required CI hermetic; real backends are separate explicit acceptance.
- Keep video to one backend and one MVP journey.
- Do not revive the failed child runtime host or add distributed execution.
- Do not let historical feature breadth block the defined vertical slice.

## Deferred until after MVP

- ComfyUI/LTX and additional video backends;
- AnimateDiff, secondary motion, multi-shot continuity, and stitching;
- daemon, cluster, child-host, or multi-node execution;
- full training-product UX;
- automated closed-loop learning decisions;
- broad GUI or performance rewrites unrelated to measured MVP blockers.

## Next action

Specify/execute `PR-MVP-070` as the next coherent product slice. PromptPack
authorship and durable job state now have single authorities, and the accepted
image vertical slice is complete.
