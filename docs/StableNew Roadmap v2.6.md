# Finalized MVP Roadmap — StableNew v2.6

Status: CURRENT AND ACTIVE
Owner: Rob
Updated: 2026-09-13

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
| 10 | `PR-MVP-070` | Complete | Native SVD XT vertical slice |
| 11 | `PR-MVP-080` | IN PROGRESS | Operator readiness and runtime recovery closeout |
| 12 | `PR-MVP-090` | Planned | Clean-machine release acceptance |

Roadmap progress is 11 of 13 rows complete (approximately 85%). Native SVD is
complete; operator readiness is in progress and clean-machine release proof
remains planned.

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

### PR-MVP-070 — native SVD XT — COMPLETE

Native SVD XT is accepted as the MVP video backend. The completed vertical
slice preserves queue-first immutable NJR execution through the native
Diffusers backend, user-scoped/local-only model and cache policy, truthful
cancellation/progress/failures, exact artifacts/history, and replay lineage.
The conservative validated baseline is 14 frames at 7 fps, 25 inference
steps, 1024x576 center-crop, decode chunk 2, fp16, CPU model offload ON, and
forward chunking ON for approximately 12 GB. A real RTX 4070 Ti acceptance
passed; 25-frame XT remains an explicit higher-memory capability. Exact MP4
export preserves the requested 14-frame sequence.

### PR-MVP-080 — operator readiness

Expose or clearly label only supported paths and finish the operator-readiness
outcome. Remaining work is:

- accepted evidence: one real portrait source-aware native-SVD production run
  selected `832x1216 -> 640x960`, produced an exact `640x960` center-cropped
  prepared image, and completed with a verified 14-frame portrait MP4 through
  the canonical queue-first runner path;
- accepted RIFE interpolation semantics: optional and disabled by default;
  duration-preserving temporal smoothing with bounded 2x and 4x factors only;
  unsupported factors are rejected before expensive generation; final artifact
  cadence reflects interpolation;
- portable video provenance and parent artifact lineage: make produced MP4
  provenance self-contained enough for later inspection and recovery when
  sidecars or original paths are unavailable; embedded provenance remains an
  audit/recovery copy, not lifecycle authority;
- queue/history recovery UX;
- final operator journey, documentation, required CI, and integration.

This is workflow polish, not a GUI rewrite.

### PR-MVP-090 — release proof

PR-MVP-090 remains planned overall. Phase 0 — enabling prerequisite, pulled
forward for dependency sequencing only — COMPLETE / ACCEPTED:

- repository-owned Windows Python 3.11/3.12 bootstrap with CUDA-enabled Torch
  installation ordering;
- disposable RTX 4070 Ti bootstrap and established-runtime check-only passes;
- Diffusers SVD pipeline and production-resolved FFmpeg/ffprobe available;
- accepted plain XT detected through the production cache authority and
  production local-only preflight passing without blockers or warnings.

Pulling forward Phase 0 does not complete or broadly start PR-MVP-090.
Remaining clean-machine/release-proof work stays after PR-MVP-080:

- clean-checkout release proof;
- migration/recovery rehearsal;
- final image/SVD smokes;
- restart/replay/artifact proof;
- final limitations and rollback documentation.

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

Complete portable video provenance and parent artifact lineage. PromptPack authorship,
durable job state, image generation, native SVD XT, the Phase 0 runtime/bootstrap
prerequisite, real portrait source-aware SVD geometry, and duration-preserving
RIFE interpolation semantics already have single accepted product paths.
