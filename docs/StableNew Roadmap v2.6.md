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
| 11 | `PR-MVP-080` | IN PROGRESS | Operator readiness and runtime recovery closeout |
| 12 | `PR-MVP-090` | Planned | Clean-machine release acceptance |

Roadmap progress is 11 of 13 MVP rows complete (approximately 85%). Native SVD
is complete; operator readiness is in progress and clean-machine release proof
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
- remaining queue/history action-state + no-op cleanup;
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

## Approved post-v2.6 value roadmap

This direction was accepted on 2026-09-13 after reviewing backend neutrality,
Asset Intelligence, Learning/quality efficiency, controller/executor debt,
household compute, cloud bursting, and directed-motion video. It is not part of
the current MVP completion count and must not begin until PR-MVP-080 and
PR-MVP-090 are accepted and integrated.

The post-MVP optimization objective is **useful-output efficiency**, not feature
count or raw images per second. Prefer work that reduces time/GPU cost per keeper
or unlocks a material new capability without increasing architectural coupling.
Useful measurements include keeper rate, GPU-minutes per keeper, wall-clock time
to curated final, failed/aborted-job rate, operator interventions per final,
repeated model/checkpoint loads, and generation-to-refine-to-final conversion.

Before authorizing each implementation wave, re-check the exact integrated repo
state and rewrite the bounded implementation contract from live evidence. The
labels below are roadmap outcomes, not permission to execute discovery-era file
lists, schemas, or Codex prompts unchanged.

| Order | Work | Status | Outcome |
|---:|---|---|---|
| P0 | Post-v2.6 efficiency baseline | Approved measurement gate | Establish keeper/latency/GPU/failure/intervention baseline and re-check the dominant bottleneck before new implementation |
| P1 | `PR-IMG-100` | Approved / Not started | One typed image backend per image NJR; preserve A1111 behind a StableNew-owned backend contract and simplify touched generic execution responsibilities |
| P2 | Asset Intelligence + Quality Efficiency | Approved planning direction; discovery reference exists | Hash-backed local asset inventory, family/role metadata, deterministic VAE policy, compatibility preflight, known-good operating profiles, controlled Learning evidence, and curation-derived quality signals |
| P3 | Execution Placement v1 | Approved planning direction; architecture discovery required | Central StableNew capability-aware placement across local/LAN workers with a contract that can later support cloud workers without a second queue/lifecycle authority |
| P4 | Directed Motion Video | Approved planning direction; technology qualification required | StableNew-owned motion-intent/control semantics translated through video backends for articulated body/limb motion beyond SVD |
| P5 | Evidence-selected backend/model expansion | Decision-gated | Qualify and productionize only image/video runtimes or model families that materially improve useful-output efficiency or unlock an accepted capability |

The earlier fixed sequence `PR-IMG-110 -> PR-IMG-120 -> PR-IMG-130` is
superseded before implementation. Those labels must not be executed as a
pre-authorized Ideogram-first chain. Modern image qualification remains valid
work, but it now belongs under the evidence-selected P5 decision gate and must
compare whatever credible candidates exist when that decision is reached.

### P0 — post-v2.6 efficiency baseline

This is a measurement/reprioritization checkpoint, not a broad instrumentation
rewrite. Use existing manifests, history, timing/provenance, curated outcomes,
and a bounded representative corpus where possible. Establish enough evidence
to answer which bottleneck dominates useful-output cost after v2.6: bad
configuration/model/adapter choices, execution latency, refinement churn,
manual review effort, repeated loading, or another measured source of waste.

Do not let P0 become an indefinite analytics project. Its purpose is to verify
that the accepted value sequence still matches observed post-090 reality.

### P1 — PR-IMG-100 backend-neutral image execution

Accepted architecture remains **COA B — one typed image backend per image NJR**.

The PR introduces StableNew-owned image backend capabilities/request/result/
interface/registry responsibilities below `PipelineRunner.run_njr`. Newly
compiled image NJRs explicitly persist image backend identity in the existing
immutable `backend_options` layer. Historical v2.6 image NJRs that lack backend
identity resolve to `a1111_webui` through one bounded compatibility rule.

A1111/WebUI remains the only production backend delivered by PR-IMG-100 and must
preserve current txt2img, img2img, ADetailer, upscale, model/VAE verification,
managed/external ownership, cancellation, stall/recovery, ambiguous-POST,
artifact, history, and replay behavior. A deterministic fake backend proves the
boundary before the A1111 adapter cutover; final acceptance includes a real
queue-first A1111 golden path.

One backend owns all image stages in an NJR for this PR. Unsupported stages fail
before dispatch. There is no implicit cross-backend fallback.

PR-IMG-100 is also the first deliberate opportunity to reduce execution coupling:
A1111-specific responsibility should move behind the backend adapter where the
accepted outcome requires it. Do **not** turn this into a broad `executor.py` or
controller LOC cleanup; extraction is justified by responsibility, not line
count.

Its architecture contract is:

`docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`

Any phase prompt/template inside that document must be revalidated and rewritten
from the exact post-v2.6 parent before use; the accepted architecture outcome is
binding, but discovery-era SHAs/file lists/implementation assumptions are not.

### P2 — Asset Intelligence + Quality Efficiency

The daily-use objective is to prevent known-bad or poorly supported generation
decisions before spending GPU time and to learn which configurations actually
produce keepers.

The planning target includes:

- one local Asset Registry for checkpoints, VAEs, LoRAs, and embeddings with
  exact hash-backed identity and incremental change detection;
- factual family/role/provenance metadata with optional external enrichment OFF
  by default unless the user explicitly opts in;
- deterministic checkpoint/VAE resolution before NJR authorization;
- compatibility projection for models/adapters/embeddings without silently
  mutating authored Prompt intent;
- controlled Learning templates and exact provenance for model/VAE/LoRA/
  embedding comparisons;
- known-good operating profiles by model/task/context when evidence supports
  them;
- curation-funnel evidence so configurations are judged by whether candidates
  survive refinement to useful finals, not only isolated ratings.

The seven-phase Asset Intelligence workbook and plan are discovery/reference
material only. Before implementation, re-ground them against the actual
post-PR-IMG-100 repository and collapse, split, reorder, or discard discovery
phases as current code makes appropriate.

### P3 — capability-aware Execution Placement v1

The first distribution goal is independent-job parallelism across hardware that
already exists, not pooled VRAM or distributed model-parallel inference.

Central StableNew must continue to own intent, compilation, immutable NJR,
JobService, SQLite queue/lifecycle, scheduling, lineage, replay,
cancellation policy, artifacts/history, and provenance. A remote machine is an
execution worker, not another StableNew queue/history/compiler authority.

Worker eligibility should be capability-aware and based on hardware/runtime,
supported backend/task capabilities, load/availability, and exact local asset
identity. The Asset Registry direction is intentionally reusable for worker
asset/capability manifests rather than creating a second model scanner.

Design LAN and cloud as one execution-placement concept: local, LAN-worker, and
future cloud-worker targets implement the same StableNew-owned placement/
execution contract. Provider-specific queues/APIs remain transport details and
must not become lifecycle authority. This roadmap approval does **not** itself
approve a distributed scheduler architecture; perform a fresh bounded
architecture decision before implementation.

### P4 — directed-motion video

Native SVD XT remains the reliable lightweight baseline. Do not keep extending
SVD or whole-frame secondary-motion postprocessing as though it can provide
articulated subject actions.

The next major video capability should represent StableNew-owned motion intent
independently from backend/model choice. Candidate concepts include
prompt-directed body action, driving/performance video, pose/control video,
keyframes/anchors, trajectory, depth/control signals, and camera motion as
supported by qualified technology.

At implementation time, qualify the strongest current open/runtime candidates
against actual hardware and worker/cloud options. ComfyUI, DiffSynth, or another
runtime may be used where they add value, but raw workflow graphs and backend
queues remain private adapters and may not replace the StableNew
compiler/NJR/queue/runner/artifact/history authorities.

### P5 — evidence-selected backend/model expansion

Do not organize StableNew around the fashionable model of the month.
Backend/runtime, model family, and exact model identity remain separate.

When modern image or video expansion is reconsidered, compare the strongest
current candidates using a controlled qualification matrix that includes:

- keeper/output quality on representative tasks;
- VRAM/RAM and offload behavior on supported targets;
- cold/warm latency and throughput;
- local/offline completeness and network dependencies;
- license/usage constraints;
- editing/control support and adapter/LoRA ecosystem;
- deterministic replay/seed behavior where applicable;
- progress/cancellation and unload/reload semantics;
- exact model/revision provenance;
- LAN/cloud suitability and cost.

Ideogram-, Qwen-, FLUX-, Wan-, and successor families are examples of possible
candidates, not preselected product destinations. Production integration occurs
only if evidence beats the current pathway on useful-output efficiency or
unlocks a material capability.

## Responsibility-extraction rule

Large controller/executor surfaces are real structural debt, but broad cleanup is
not a roadmap outcome by itself. Every major post-v2.6 feature should pay down
only the cohesive responsibility it materially touches:

- backend-neutral image work extracts backend-specific execution;
- Asset Intelligence converges fragmented resource discovery/metadata;
- quality/Learning work extracts scoring/evidence logic from GUI/controller
  surfaces as needed;
- Execution Placement isolates placement/lease/capability concerns from job
  coordination;
- directed-motion work isolates motion-intent translation from GUI/workflow
  authoring.

Do not refactor solely for LOC reduction. If a ratcheted surface shrinks, lower
its checked-in ceiling.

## Deferred image-backend options

- **COA C — per-stage backend composition:** potentially valuable for explicit
  cross-backend chains, but it requires its own design for artifact handoff,
  capability negotiation, replay, provenance, resource lifecycle, and failure
  semantics.
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
- Do not revive the failed child runtime host during MVP recovery.
- Do not let historical feature breadth block the defined vertical slice.
- Do not begin post-v2.6 work before the accepted v2.6 release baseline exists.
- PR-IMG-100 must preserve A1111 rather than combine backend-neutralization with
  image-quality changes, broad cleanup, or another real backend.
- Do not begin LAN/cloud execution without a new bounded architecture decision
  for placement, lease/failure semantics, security, artifact transfer, and
  exact capability/asset verification.
- Do not let model popularity outrank measured useful-output efficiency.

## Deferred until after MVP / later decision gates

- per-stage image backend composition;
- full training-product UX;
- broad GUI or performance rewrites unrelated to measured blockers;
- automated closed-loop learning decisions beyond accepted evidence gates;
- multi-shot continuity/stitching beyond an accepted directed-motion/video
  contract;
- true distributed/model-parallel inference across multiple GPUs unless a
  separate measured use case justifies it.

## Next action

Complete queue/history action-state + no-op cleanup. PromptPack authorship,
durable job state, image generation, native SVD XT, the Phase 0 runtime/bootstrap
prerequisite, real portrait source-aware SVD geometry, and duration-preserving
RIFE interpolation semantics already have single accepted product paths.

After PR-MVP-080 and PR-MVP-090 are accepted and integrated, verify the exact
post-v2.6 parent SHA, establish the bounded P0 efficiency baseline, and then
rewrite/authorize the first PR-IMG-100 implementation phase from that live repo
state. Do not reuse discovery-era SHAs or Codex prompt assumptions as execution
authority.
