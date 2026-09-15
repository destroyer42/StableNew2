# Finalized MVP Roadmap — StableNew v2.6

Status: CURRENT AND ACTIVE
Owner: Rob
Updated: 2026-09-14

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

The accepted first post-v2.6 image architecture direction is one typed image
backend per image NJR. That work begins only after the MVP/release proof is
accepted; it does not expand the current v2.6 release gate.

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
| 11 | `PR-MVP-080` | Complete | Operator readiness and runtime recovery closeout |
| 12 | `PR-MVP-090` | Complete | Clean-machine release acceptance |

Roadmap progress is 13 of 13 MVP rows complete (100%). Native SVD, operator
readiness, and clean-machine release proof are complete and integrated into
`main`.

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

## Remaining MVP work

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

### PR-MVP-080 — operator readiness — COMPLETE

Expose or clearly label only supported paths and finish the operator-readiness
outcome. The accepted outcome includes:

- accepted evidence: one real portrait source-aware native-SVD production run
  selected `832x1216 -> 640x960`, produced an exact `640x960` center-cropped
  prepared image, and completed with a verified 14-frame portrait MP4 through
  the canonical queue-first runner path;
- accepted RIFE interpolation semantics: optional and disabled by default;
  duration-preserving temporal smoothing with bounded 2x and 4x factors only;
  unsupported factors are rejected before expensive generation; final artifact
  cadence reflects interpolation;
- accepted evidence: native-SVD MP4 provenance is self-contained enough for
  later inspection and recovery when sidecars or original paths are
  unavailable, with verified machine payload, source-content identity,
  available parent/source-generation lineage, SVD execution/preprocess/
  postprocess provenance, media-stream verification, and isolated MP4-only
  recovery; embedded provenance remains an audit/recovery copy, not lifecycle
  authority;
- accepted evidence: conservative interrupted-running restart recovery preserves
  durable queue order for queued jobs, records ambiguous running work as
  terminal action-required `FAILED` history with
  `INTERRUPTED_RESTART_ACTION_REQUIRED`, preserves available recovery evidence,
  prevents automatic requeue/replay, and renders the record as `Interrupted`;
  explicit Replay creates a new NJR/job identity with parent lineage;
- accepted evidence: queue/history action-state and no-op cleanup combines
  legal state, callable boundaries, and real artifact/replay evidence; manual
  Send Job remains available with Auto-run OFF when safely dispatchable; stale,
  direct, keyboard, and context-menu paths cannot bypass the predicates; and
  false Remove/Clear success is not reported;
- accepted repair at `d2909e752faaa34f20a49fccc9865a8412c21b15`: terminal result
  publication requires durable `RUNNING` ownership, so accepted cancellation or
  return-to-queue decisions cannot acquire late successful result data, artifact
  references, or `final_output` checkpoints; normal success, replay lineage,
  lifecycle/schema, and architecture remain unchanged; physical cancelled-job
  bytes may remain as non-authoritative residue when no safe generic cleanup
  authority exists;
- final operator-facing journey verification, documentation consistency,
  required CI, and fast-forward integration into `main`.

The final operator journey is **PASS / ACCEPTED**. Rob manually verified one
normal queue-first run with Auto-run OFF and a second back-to-back run; both
completed successfully. Queue/history action-state, replay identity/parent
lineage, cancellation safety, and the shutdown persistence-order repair remain
accepted evidence. StableNew CI run 317 passed with the required Python 3.11
and 3.12 jobs. The accepted feature line is integrated into `main` by
fast-forward only.

This is workflow polish, not a GUI rewrite.

### PR-MVP-090 — release proof

PR-MVP-090 is **COMPLETE / ACCEPTED / INTEGRATED**. The final release proof completed
without production source changes. Its Phase 0 runtime/bootstrap prerequisite
was accepted early for dependency sequencing:

- repository-owned Windows Python 3.11/3.12 bootstrap with CUDA-enabled Torch
  installation ordering;
- disposable RTX 4070 Ti bootstrap and established-runtime check-only passes;
- Diffusers SVD pipeline and production-resolved FFmpeg/ffprobe available;
- accepted plain XT detected through the production cache authority and
  production local-only preflight passing without blockers or warnings.

The final image proof used one durable queue-first job, completed at 768x1024,
and preserved checkpoint provenance for
`juggernautXL_ragnarokBy.safetensors [dd08fa32f9]`. The image SHA-256 was
`57a1b6f14ab483a3d981df3e35304ef9d26bbe0478b8abb7c3a12f4513eec76f`.

The final native plain-SVD-XT proof used SVD job
`4df7d2a73ea04e42a09294a81dfe8897`, the accepted image as its source, and the
public controller → immutable NJR → JobService → SQLite → PipelineRunner path.
The source-aware target and prepared geometry were 576x1024, using resize plus
center-crop without padding. The completed MP4 decoded at exactly 14 frames,
7 fps, and 576x1024. The profile was 25 steps, motion bucket 48, noise 0.01,
decode chunk 2, fp16, CPU offload and forward chunking enabled, local-only
enabled, and all optional postprocessing disabled. SQLite, history, artifact
manifest, JSON sidecar, embedded portable provenance, and filesystem agreed;
the embedded source provenance retained the parent image job identity and
source SHA-256. Visual smoke confirmed portrait orientation without obvious
stretch, squash, or gross corruption.

The disposable native-SVD bootstrap/check-only run established Python 3.11.9,
CUDA Torch 2.14.0+cu130, Diffusers 0.40.0, Transformers 5.17.0, Accelerate
1.15.0, production-resolved FFmpeg/ffprobe, and the RTX 4070 Ti. Plain XT was
already complete in the production cache; no model download occurred.

Required CI run 331 remains the source-SHA evidence. Migration, GP-MVP-17,
Ruff, controller ratchet, and A1111 image validation were reused unchanged;
the repaired acceptance harness and final SVD/image smokes supplied the
remaining release proof. The earlier high-pressure 832x1216 rejection remains
expected guardrail behavior.

The release-harness integrity checkpoint is **COMPLETE / ACCEPTED**. Modern
NJR journeys use the immutable contract and the canonical
`JobService.submit_njrs` → SQLite queue/repository → production dispatch path;
history is persisted and read back rather than fabricated. Shutdown journeys
disable backend autostart and process assertions are scoped to explicit
test-owned StableNew or managed-backend processes. The Windows bootstrap and
journey wrappers retain their approved interpreter/dependency normalization.
Focused validation passed; no real A1111, ComfyUI, SVD, or GPU execution was
introduced by this checkpoint.

The PR-MVP-090 raw-Ruff portion is **COMPLETE / ACCEPTED**. Pinned Ruff
0.14.9 reached zero findings across the active repository, and the legacy
non-increasing baseline was removed. Both the local PR gate and required CI
now enforce direct raw `ruff check .`; no controller ceiling was increased.
StableNew CI run 328 passed both required Python 3.11 and 3.12 jobs;
informational full-suite legacy failures remain non-blocking.

The managed-runtime ownership safety repair is also **COMPLETE / ACCEPTED**.
WebUI and ComfyUI termination/restart paths now require explicit manager
ownership of the launched process/session. ComfyUI bootstrap uses a healthy
existing external endpoint unmanaged without launching a duplicate, rejects an
occupied invalid endpoint without killing or replacing its occupant, and starts
managed ComfyUI only when the endpoint is free. Automatic port,
working-directory, process-appearance, and orphan/reparented-process kill
heuristics were removed from runtime recovery and shutdown. Deterministic tests
cover unmanaged external runtimes, owned roots/descendants, orphan monitoring,
and isolated emergency cleanup without using a real backend. StableNew CI run
330 passed both required Python 3.11 and 3.12 jobs; informational full-suite
legacy failures remain non-blocking.

## Approved post-v2.6 sequence

This sequence records the post-v2.6 architecture line. PR-IMG-100 is complete /
accepted / integrated on `main`.
Do not begin PR-IMG-110 until that integration and a separate qualification
decision.

| Order | Work | Status | Outcome |
|---:|---|---|---|
| P1 | `PR-IMG-100` | Complete / Accepted / Integrated | One typed image backend per image NJR; existing A1111 path preserved behind a StableNew-owned backend contract |
| P1a | `PR-SVD-100` | Complete / Accepted on feature branch; integration pending | Non-recursive SVD folder batch submission through ordinary per-source NJRs and one existing JobService batch call |
| P2 | `PR-IMG-110` | Planned decision-gated qualification | Diffusers / Ideogram 4 runtime qualification on target hardware; no production backend yet |
| P3 | `PR-IMG-120` | Conditional | First Diffusers production image vertical slice if PR-IMG-110 proves viable |
| P4 | `PR-IMG-130` | Conditional | Capability-aware image backend/model UI and compiler projections |

### PR-IMG-100 — backend-neutral image execution (complete / accepted / integrated)

Accepted architecture: **COA B — one typed image backend per image NJR**.

The PR introduces StableNew-owned image backend capabilities/request/result/
interface/registry contracts below `PipelineRunner.run_njr`. Newly compiled image
NJRs explicitly persist image backend identity in the existing immutable
`backend_options` layer. Historical v2.6 image NJRs that lack backend identity
resolve to `a1111_webui` through one bounded compatibility rule.

A1111/WebUI remains the only production backend delivered by PR-IMG-100 and must
preserve current txt2img, img2img, ADetailer, upscale, model/VAE verification,
managed/external ownership, cancellation, stall/recovery, ambiguous-POST,
artifact, history, and replay behavior. A deterministic fake backend proves the
boundary before the A1111 adapter cutover; final acceptance includes a real
queue-first A1111 golden path.

One backend owns all image stages in an NJR for this PR. Unsupported stages fail
before dispatch. There is no implicit cross-backend fallback.

The binding acceptance contract and historical execution record are in:

`docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`

### PR-SVD-100 — Folder Batch Submission (complete / accepted on feature branch)

This bounded SVD utility package adds non-recursive folder discovery/admission
and compiles one ordinary immutable `svd_native` NJR per valid source before one
existing `JobService.submit_njrs` call. It does not change SVD inference, model
loading, queue/repository schema, lifecycle, artifact/history/replay, or GPU
runtime authority. Its contract is
`docs/Subsystems/Video/PR-SVD-100_Folder_Batch_Submission.md`.

### PR-IMG-110 — Diffusers / Ideogram 4 qualification

This is a separate runtime qualification after PR-IMG-100. It must determine,
on the actual supported target environment, model access/license flow, minimum
known-good Diffusers version, local cache behavior, VRAM/RAM/offload strategy,
1024-class viability, latency, seed behavior, progress/cancellation, model
unload/reload, and coexistence with the existing A1111/SVD GPU lifecycle.

Qualification does not authorize production integration. PR-IMG-120 begins only
if the evidence is acceptable and Rob approves the production slice.

### PR-IMG-120 — conditional Diffusers production slice

If qualified, add `diffusers` as a second image backend behind the PR-IMG-100
contract. Ideogram 4 is the first candidate model family, not a public backend
class. The initial slice should remain `txt2img`-only unless evidence supports a
broader capability contract.

### PR-IMG-130 — conditional capability-aware UX/compiler

After a real second backend exists, make backend/model capabilities explicit in
intent/UI/compiler projections so A1111-only controls are not presented as
universal image settings. Do not redesign PromptPack storage merely to support
capability-aware compilation.

## Deferred image-backend options

- **COA C — per-stage backend composition:** potentially valuable for explicit
  chains such as Diffusers base generation followed by A1111 detail work, but it
  requires its own design for artifact handoff, capability negotiation, replay,
  provenance, resource lifecycle, and failure semantics.
- **COA D — ComfyUI-centric image execution:** ComfyUI may later be a useful
  image backend for selected model families/workflows, but it must remain behind
  StableNew-owned orchestration and may not replace the compiler, NJR, queue,
  runner, artifact, history, replay, cancellation, or process authorities.

Neither COA C nor COA D is authorized inside PR-IMG-100.

## Risk controls

- Never bulk-merge comparison branches; adopt changes by current need and test.
- Never migrate user data without dry-run, backup, verification, idempotence,
  conflict reporting, and rehearsed rollback.
- Keep required CI hermetic; real backends are separate explicit acceptance.
- Keep MVP video to one backend and one MVP journey.
- Do not revive the failed child runtime host or add distributed execution.
- Do not let historical feature breadth block the defined vertical slice.
- Historical guardrail: PR-IMG-100 began only after the accepted v2.6 release
  baseline existed.
- PR-IMG-100 must preserve A1111 rather than combine backend-neutralization with
  image-quality changes, a broad executor rewrite, or another real backend.

## Deferred until after MVP

- ComfyUI/LTX and additional video backends;
- AnimateDiff, secondary motion, multi-shot continuity, and stitching;
- daemon, cluster, child-host, or multi-node execution;
- full training-product UX;
- automated closed-loop learning decisions;
- broad GUI or performance rewrites unrelated to measured MVP blockers;
- per-stage image backend composition and ComfyUI image execution until their
  own post-v2.6 decisions/acceptance contracts are approved.

## Next action

`PR-SVD-100 — Folder Batch Submission` is complete / accepted on its feature
branch; main integration is pending explicit authorization. PR-IMG-110 remains
planned, decision-gated, and not started.
PR-MVP-080 is COMPLETE / ACCEPTED / INTEGRATED; its final operator journey, required CI, and
documentation closeout are complete. Queue/history action-state and no-op cleanup is
accepted, alongside PromptPack authorship, durable job state, image generation,
native SVD XT, the Phase 0 runtime/bootstrap prerequisite, real portrait
source-aware SVD geometry, and duration-preserving RIFE interpolation semantics.

PR-MVP-080, PR-MVP-090, and PR-IMG-100 are accepted and integrated. PR-IMG-100
was executed as one coherent work package.
