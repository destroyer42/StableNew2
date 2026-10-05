# Finalized MVP Roadmap — StableNew v2.6

Status: CURRENT AND ACTIVE
Owner: Rob
Updated: 2026-09-16

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

Post-v2.6 `PR-LEARN-300` is COMPLETE / ACCEPTED / INTEGRATED. Its evidence-integrity and workflow
slices now have immutable preview-to-queue evidence, one normal batch admission,
focused rating lineage, canonical live resource projection, readable Learning
output naming, grouped experiment review, deterministic Next Unrated navigation,
and controlled-versus-observational recommendation rules. Working Draft autosave
is separated from queue-admitted Experiment Library history; experiment
conclusions derive from saved sample ratings and controlled validity. Matrix
freeze is selected-row-aware, including random-mode packs. Discovered Outputs
now use durable Done/Dismiss semantics, availability counts, protected explicit
missing-reference cleanup, and a resizable review-first layout. Confirmed Staged
Curation suggestions affect only the selected derived-job intent through the
existing NJR/JobService path. Bounded physical A1111 seed acceptance is PASS:
three CFG variants x one image used frozen seed `12345`, each returned
`all_seeds=[12345]`, and each remained controlled. Final operator acceptance
also passed for the responsive Learning workflow, current Global Prompt policy
execution, and a real LoRA Strength experiment with executed-prompt readback.
`PR-VID-110` is COMPLETE / ACCEPTED / INTEGRATED; `PR-VID-120` (neutral, capability-aware video
execution contract; no production Wan/VACE integration) is COMPLETE / ACCEPTED / INTEGRATED. `PR-VID-130 — Wan2.2 Experimental Prompt-Directed I2V Vertical Slice` is COMPLETE / ACCEPTED / INTEGRATED. Wan2.2 `wan22_ti2v_5b_i2v_v1` v1.0.0 is an EXPERIMENTAL Comfy workflow, never generally approved: each job needs durable explicit `video_execution.experimental_opt_in=true`; disabled workflows stay non-runnable; governance, dependency checks and an observe-only resource-readiness guard (10,000 MiB GPU memory available to Comfy, 16 GB host RAM; not a scheduler/lease) fail before Comfy queue dispatch; external A1111/Comfy are never adopted, terminated or restarted. Native SVD remains the default production video backend; VACE stays NO-GO and unregistered. `VideoWorkflowController` now emits neutral `video_execution` intent; the historical stage bridge remains for the SVD producer, AnimateDiff, prompt-pack/reprocess-built `video_workflow` stages and historical replay, and is retired only once every producer is neutral and replay normalization is proven. Real Wan2.2 acceptance on the RTX 4070 Ti 12 GB produced a valid 480x832/49-frame/24 fps MP4 in ~83.4 s (peak 11,630 MiB VRAM, min 1.45 GB free RAM, no GPU fault). `PR-VID-190` adds `wan22_ti2v_5b_i2v_v1@1.1.0`: the StableNew-owned Comfy is released after every job (so queued jobs run back to back without a manual kill) and the length is a frozen, operator-selectable `4n+1` frame count (17-81 frames, default 49, 24 fps; 81 frames accepted on the 12 GB card); `@1.0.0` remains registered, byte-identical, for replay. `PR-VID-191` (implemented locally, pending stacked publication after PR-VID-190) registers experimental Wan-Animate-2 prompt-motion and driving-video workflows that run on a machine-local qualified ComfyUI v0.37.0 configuration (`--disable-pinned-memory` required; tracked settings unchanged); the driving-video mode is `EXECUTION_PASS / PRODUCT_QUALITY_PARTIAL` with an observed duplicate-subject artifact and its motion quality is not accepted; the desktop ComfyUI upgrade remains an owner decision. `PR-VID-110`
directed-motion qualification evidence is recorded in
`docs/Subsystems/Video/PR-VID-110_Directed_Motion_Qualification.md` (qualification only, no
integration): on the RTX 4070 Ti 12-GB, Wan2.2 TI2V-5B (stock Comfy) is **CONDITIONAL**
(gesture-level directed motion with identity preserved, ~1 min per 2 s clip, VRAM near the
ceiling); Wan2.1 VACE-1.3B is **NO-GO** for identity preservation in reference-only,
stock-Canny and pose-skeleton-only control modes (pose control removes the scene/silhouette
leak and gives clean anatomy but the source person is still not reproduced, so the limit is
VACE's reference binding); SCAIL-2/Wan Animate 2 are deferred (14B, no credible 12-GB
path). Wan2.2 is the only currently qualified directed-motion candidate. A GPU loss during
qualification is one of about 15 unexplained hard resets on the
workstation since 2026-09-07 (suspects: DDR5-6000 memory OC, power delivery, driver; see the
doc). Whether to integrate any candidate is a product-owner decision; native SVD remains the
only accepted video backend.

`PR-RUNTIME-100 — Owned GPU Runtime Transition Policy` is COMPLETE / ACCEPTED /
INTEGRATED. It adds one narrow, target-driven coordinator that asks the
existing A1111, Comfy, and SVD owners to release only conflicting runtime state
they prove StableNew owns; a live/occupied configured endpoint without an owned
manager handle is an immutable external conflict, so it never adopts or mutates
external processes, does
not restore a previous runtime after a job, and does not add a scheduler, lease,
queue authority, backend routing, or diagnosis of the separate workstation GPU
reset problem.

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
PR-IMG-110 completed its separate qualification; its Ideogram 4 target-hardware
no-go was corrected by PR-IMG-110R (PASS — CONSTRAINED, explicit residency policy).
Do not begin PR-IMG-120 from either result.

| Order | Work | Status | Outcome |
|---:|---|---|---|
| P1 | `PR-IMG-100` | Complete / Accepted / Integrated | One typed image backend per image NJR; existing A1111 path preserved behind a StableNew-owned backend contract |
| P1a | `PR-SVD-100` | Complete / Accepted / Integrated | Non-recursive SVD folder batch submission through ordinary per-source NJRs and one existing JobService batch call |
| P2 | `PR-IMG-110` | Complete / Ideogram 4 verdict superseded | Generic Diffusers substrate passed; the Ideogram 4 "hardware no-go" was not supported (see P2a); no production backend added |
| P2a | `PR-IMG-110R` | Complete / Accepted / Integrated | Ideogram 4 NF4 PASS — CONSTRAINED on RTX 4070 Ti 12GB up to 1024x1024 `V4_QUALITY_48` with an explicit residency policy (two independent implementations, bit-identical repeats); shipped all-resident and documented offload paths impractical |
| P3 | `PR-IMG-120` | Not authorized; eligible for a separate owner decision | Any Diffusers production slice needs an explicit product-owner decision (custom GPU residency lifecycle/lease, structured-JSON prompt mapping, Ideogram 4 non-commercial license) |
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

### PR-SVD-100 — Folder Batch Submission (complete / accepted / integrated)

This bounded SVD utility package adds non-recursive folder discovery/admission
and compiles one ordinary immutable `svd_native` NJR per valid source before one
existing `JobService.submit_njrs` call. It does not change SVD inference, model
loading, queue/repository schema, lifecycle, artifact/history/replay, or GPU
runtime authority. Its contract is
`docs/Subsystems/Video/PR-SVD-100_Folder_Batch_Submission.md`.

### PR-IMG-110 — Diffusers / Ideogram 4 qualification

This completed target-machine qualification found a viable generic Torch/CUDA /
Diffusers SDXL control. Its Ideogram 4 NF4 "target-hardware no-go" (normal CUDA,
model CPU offload and group offload attempts) is **superseded**: PR-IMG-110R showed
those attempts were all-resident VRAM overcommit (Windows shared-memory spill),
Diffusers offload/loader behaviour and a group-offload software fault. No production
Diffusers backend was added. Evidence:
`docs/Subsystems/Image/PR-IMG-110_Diffusers_Ideogram4_Qualification.md`.

### PR-IMG-110R — Ideogram 4 definitive requalification

Complete / accepted / integrated: **PASS — CONSTRAINED**. The official `ideogram4` code
(pinned commit) and Diffusers 0.40.0 both completed 512x512 through 1024x1024
`V4_QUALITY_48` on the RTX 4070 Ti 12GB, with bit-identical repeats, when the text
encoder is used first and released and only one transformer is GPU-resident at a
time. Latency after load: about 60 s (768x1024 Turbo), 116-130 s (1024x1024 Default),
279-312 s (1024x1024 Quality); peak VRAM 10.4-11.5 GiB of 12.0 GiB. The shipped
all-resident and documented offload paths give ~60 s per step (spill). Full evidence:
`docs/Subsystems/Image/PR-IMG-110R_Ideogram4_Requalification.md`.

PR-IMG-120 is not authorized by either result; it is eligible for a separate
product-owner decision.

### PR-IMG-120 — conditional Diffusers production slice

Not authorized. PR-IMG-110 established that generic Diffusers is viable and
PR-IMG-110R that Ideogram 4 NF4 is constrained-viable on the supported target
(explicit residency policy, exclusive GPU). A separate product-owner decision on the
residency lifecycle, prompt mapping and license is required before this production
slice can be proposed.

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

## Current one-active-package frontier

The former three concurrent lanes are retired as an execution model; Lane
A/B/C labels below are backlog/topic categories only. Work proceeds as one
active short-lived branch/workspace at a time, landing and merging before the
next package starts. Actual PromptPacks, settings, SQLite, and configured
endpoints still require explicit isolation or authorization; deliberate
real-model inference and platform/hardware changes remain serialized and
separately owner-authorized regardless of which package is active.

### Runtime & developer-experience modernization (ordered)

The runtime/DEVEX sequence is intentionally staged so CI policy, dependency
reproducibility, optional legacy restoration, and interpreter promotion remain
separately diagnosable:

| Order | Work | Status | Outcome |
|---:|---|---|---|
| R1 | `PR-DEVEX-100` | **COMPLETE / ACCEPTED / INTEGRATED** | CPython 3.12.x as the deterministic bridge runtime (superseded by R4); quiet-on-success/detailed-on-failure validation; focused / local-gate / GitHub-integration levels; one PR-triggered CI workflow per head with superseded runs cancelled |
| R1b | `PR-DEVEX-CI-110` | **IMPLEMENTED** (risk-proportionate CI, cross-boundary contract gate and test census; no test deleted; later consolidation needs separate owner authorization) | the GitHub workflow consumes the repository-owned validation plan; docs-only cheap path; required contract gate plus affected lanes; full census for broad changes, Mon/Wed/Fri on main, on dispatch and on request |
| R2 | `PR-RUNTIME-DEPS-100` | **COMPLETE / ACCEPTED / INTEGRATED** | Reproduce the already-qualified Windows/CUDA 13.0 ML stack from repository-owned exact constraints (introduced as `windows-py312-cu130.txt`, now `constraints/windows-py314-cu130.txt`), a pinned resolver, and a drift verifier, so rebuilding the StableNew environment does not silently change runtime behavior |
| R3 | `PR-POSTPROC-100` | **COMPLETE / ACCEPTED / INTEGRATED** | Core native SVD no longer requires the legacy restoration stack: restoration/upscale is an optional `-WithPostprocess` profile behind StableNew-owned adapters (`src/video/restoration/`). RealESRGAN and the CodeFormer network are modernized through Spandrel with bit-identical output; the torchvision compatibility shim, `sys.path`/CWD mutation and site-packages weight copies are removed. The CodeFormer face helper (`facelib` from the `codeformer` wheel) is retained and isolated because upstream `facexlib` changes output materially; GFPGAN is unavailable before and after. See `docs/Subsystems/Video/PR-POSTPROC-100_Restoration_Isolation.md` |
| R4 | `PR-PY314-100` | **COMPLETE / ACCEPTED / INTEGRATED** | Standard-GIL CPython 3.14.x promoted as the sole StableNew application/native-SVD interpreter after the exact accepted package set reproduced unchanged (same 57 core / 63 postprocess pins), restoration output stayed bit-identical, and the broad suite passed; free-threaded Python and the experimental JIT remain off. Constraints renamed to `windows-py314-cu130.txt`; PEP 695 syntax cleanup |
| R5 | `PR-COMFY-RUNTIME-100` | **COMPLETE / ACCEPTED / INTEGRATED** | Modernize the StableNew-managed ComfyUI environment independently from the StableNew application venv: ComfyUI `v0.38.0` on official standard-GIL CPython 3.13.x with Torch `2.14.0+cu130`, no custom nodes, a runtime contract (`config/managed_comfy_runtime.json`), separate exact constraints, a separate bootstrap/verifier, and new `@1.2.0` workflow versions (the `@1.1.0` graphs, v0.38.0 provenance; older versions byte-identical). Qualified by a two-candidate comparison and three physical runs; an external Comfy runtime is never mutated or adopted and A1111/Forge are not coupled to this sequence. See `docs/Subsystems/Video/PR-COMFY-RUNTIME-100_Managed_Comfy_Runtime.md` |

`PR-TEST-TRUTH-210 — Pre-Forge Execution & Test Truth` is the narrow truth gate
before Forge: it makes RunPlan construction fail closed (no implicit `txt2img`
authorization) and retires permanent placeholder skips so the active
deterministic suite reflects the product that exists. It adds no product
capability and does not reorder the sequence below; after explicit owner
acceptance/integration the next product package remains `PR-IMG-FORGE-100`,
then Forge promotion, then the Forge-vs-Comfy qualification.

Python 3.12 was the stabilization bridge; Python 3.14 (R4) is the supported endpoint once accepted.
A1111 and ComfyUI retain independent runtime ownership; changing the StableNew
application interpreter or its dependency constraints does not authorize
rewriting either backend's environment.

`PR-TEST-TRUTH-120`/`PR-TEST-TRUTH-121`, `DIAG-GPU-130` closeout,
`PR-ASSET-120`, and `WP-PACK-AUDIT-100` are all **COMPLETE / ACCEPTED /
INTEGRATED**; see `STATUS.md` for their current-state summary and
`docs/Subsystems/PromptPacks/WP-PACK-AUDIT-100_PromptPack_Saved_Settings_Quality_Census.md`
for the census's full evidence and candidate follow-on packages.
`PR-PACK-110` synchronized the `pipeline.adetailer_enabled`/`adetailer.enabled`
persistence contradiction and reconciled all five sources
`WP-PACK-AUDIT-100` originally flagged: one canonical PromptPack
(`SDXL_epic_structures_Fantasy`) and four repository standalone presets
(`Juggernaut_MedievalHeroes_RandomizerAligned_v1b`,
`Photoreal_Character_Juggernaut_SDXL`, `Testing`, `default`), each
byte-backed-up and corrected with a semantic-diff guard limiting the change
to the ADetailer enablement mirrors. See
`docs/Subsystems/PromptPacks/PR-PACK-110_ADetailer_Stage_Enablement_Persistence_Repair.md`.
`PR-PACK-120` triaged the census's 24 `missing_file_backed_asset` findings
into 24 exact, occurrence-mapped, candidate-enriched items read-only (no
reconciliation performed) and is deliberately scoped to that read-only
triage plus a decisions template; an earlier draft mutation engine was
removed before merge rather than carried as unnecessary risk ahead of any
actual owner decision. See
`docs/Subsystems/PromptPacks/PR-PACK-120_Missing_Asset_Reference_Triage.md`.
`PR-PACK-130` then executed the owner-approved subset of those 24 items
with a purpose-built, one-time tool (not a rebuild of the removed generic
engine): removed 67 structured LoRA entries determined to be
checkpoint/model identities mistakenly recorded as LoRAs, and cleared 4
literal `"None"` refiner placeholders, across 15 PromptPack sources.
`DreamyStyle_xl` (9 items, 63 occurrences) was deliberately left
unresolved. `missing_file_backed_asset` moved 24 -> 9; census total 1,010
-> 995. Once verified, the one-time tool and its tests were removed from
the repository -- no source-write capability remains from this package.
See
`docs/Subsystems/PromptPacks/PR-PACK-130_Approved_Missing_Reference_Reconciliation.md`.

### Product Quality & Deterministic Engineering (backlog category)

1. Owner decision for the remaining `DreamyStyle_xl` missing-reference set
   (9 `PR-PACK-120`/`PR-PACK-130` items, 63 occurrences) -- identity and
   original role are unknown; no automatic action is authorized until the
   owner decides, followed by a bounded, separately authorized package to
   execute that decision.
2. Later: compatibility/advisory UX and targeted Learning improvements
   justified by clean inputs and evidence.

FLUX/model qualification does not live in this category.

### Platform Stability & Forensics (backlog category)

`DIAG-GPU-130` is closed/integrated; current platform-baseline truth lives in
`STATUS.md`'s "Active diagnostic evidence" entry, not restated here. This
category becomes active again only on a new hardware/platform variable or
recurrence, which needs an owner decision; PR-VID-184/184R/184S may inform
but cannot establish a failure family without supporting evidence.

### Model Qualification & Capability Expansion (backlog category)

Image and video qualification share real GPU/runtime state and
qualification infrastructure, so both belong here when selected.

1. `PR-IMG-FORGE-100 — Forge Compatibility / A1111 Successor Qualification`:
   qualify Forge as the direct successor to the current A1111/WebUI production
   path before comparing architectural alternatives. Preserve the accepted
   StableNew image intent/NJR contract and prove txt2img, img2img, ADetailer,
   LoRA, ControlNet/detail/upscale behavior, model/VAE verification, seeds,
   cancellation, ambiguous-dispatch handling, artifacts/history/replay, and
   managed-versus-external process ownership. Forge receives its own durable
   backend identity (for example `forge_webui`); do not silently reinterpret
   historical `a1111_webui` NJRs as Forge even if both expose compatible APIs.
   Share adapter implementation only where semantics are demonstrably common.
2. If Forge qualification passes, `PR-IMG-FORGE-110 — Forge Production
   Promotion` may make Forge the default A1111-family production backend while
   retaining the existing A1111 backend as a compatibility/replay path until
   explicit retirement criteria are met. Do not combine this promotion with
   ComfyUI integration. **Complete:** `PR-IMG-FORGE-110` made Forge a supported
   production backend and `PR-IMG-FORGE-120` made it the default for new work (managed
   Forge default runtime, identity-aware endpoint, explicit A1111 rollback, historical
   missing identity still A1111, one physical default-path job accepted). A1111 is
   retained as the rollback/compatibility backend; it is not retired.
3. `PR-IMG-BACKEND-QUAL-100 — Forge vs Comfy Modern Still-Image Qualification`:
   compare the qualified Forge production path against ComfyUI as the competing
   modern still-image execution architecture behind the existing PR-IMG-100
   one-backend-per-image-NJR contract. Compare keeper quality, SDXL parity,
   modern-model and editing/control support, LoRA/ControlNet/detail/upscale
   capability, cold/warm latency, checkpoint/model-switch cost, VRAM/RAM,
   deterministic replay/provenance, cancellation and ambiguous outcomes,
   artifact ownership, operator complexity, workflow/versioning burden, and
   suitability for future image/video runtime convergence. Qualification alone
   does not change the default backend.
4. If controlled evidence supports Comfy promotion, `PR-IMG-COMFY-100` becomes
   the bounded production still-image slice. ComfyUI must remain behind
   StableNew-owned intent/compiler/NJR/JobService/SQLite/PipelineRunner/
   artifact-history authority; raw Comfy workflows and Comfy's internal queue
   stay backend private. Preserve Forge/A1111 compatibility until deliberate
   retirement criteria are defined and satisfied.
5. `PR-IMG-130` capability-aware image backend/model UX/compiler work becomes
   actionable once a real second production backend exists.
6. `PR-IMG-115 — FLUX.2 Klein 4B FP8 Target-Hardware Qualification` ran as a
   model/runtime qualification (`FLUX2_KLEIN_4B_FP8_PASS_CONSTRAINED`; product value pending owner review). See
   `docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md`.
   `PR-IMG-116 — FLUX.2 Klein 4B FP8 Forge Production Slice` then promoted the qualified model into the existing
   `forge_webui` backend (text-to-image and one-reference edit; `FLUX2_KLEIN_4B_FP8_PRODUCTION_SLICE_PASS`); multi-reference
   and the Forge-default/selector work remain separate. See
   `docs/Subsystems/Image/PR-IMG-116_FLUX2_Klein_Forge_Production_Slice.md`.
7. Production integration is only for an explicitly selected evidence-backed
   capability, extending PR-RUNTIME-100 ownership/coexistence behavior when a
   runtime actually becomes production. Extract reusable qualification
   primitives only after at least two qualifications show genuinely common
   needs.
