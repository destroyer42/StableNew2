# StableNew current state

Updated: 2026-09-19

## Repository

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Default/release baseline: `main`
- Current release baseline: `main` (v2.6 MVP/release proof integrated)
- Active objective: `PR-LEARN-300` is IN PROGRESS: deterministic Learning
  workflow coherence is implemented on the feature branch; physical A1111
  operator acceptance remains deferred pending GPU safety clearance.
  `PR-IMG-110` remains integrated with an Ideogram 4 target-hardware no-go.
- Exact branch/head state must be verified from GitHub before planning or executing work.

`main` is the integrated v2.6 release baseline and now contains the accepted
PR-MVP-090 line.
The canonical documentation order is `AGENTS.md`, `STATUS.md`,
`docs/CODEX_MAP.md`, the relevant architecture section, the relevant coding and
testing section, the roadmap for sequencing, and Git history only when current
evidence is insufficient or history is explicitly requested.

## Product state

StableNew has one queue-first NJR/runner spine, transactional SQLite lifecycle
state, versioned JSON PromptPack storage, and accepted image and native SVD XT
vertical slices. PR-MVP-060 is **COMPLETE / ACCEPTED**. PR-MVP-070 is
**COMPLETE / ACCEPTED**. PR-MVP-080 is **COMPLETE / ACCEPTED / INTEGRATED**.
PR-MVP-090 is **COMPLETE / ACCEPTED / INTEGRATED**.

The runtime invariant remains:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Fresh work is queued, NJRs are immutable, lifecycle state belongs to queue and
history, replay creates a new NJR with lineage, and GUI/controllers do not
create an alternate runner path.

`main` now contains the accepted PR-MVP-080 operator-readiness, PR-MVP-090
release-proof, and PR-IMG-100 backend-neutral image lines. The v2.6 MVP/release
proof is complete. PR-IMG-110 is complete: generic Diffusers qualification
passed, but Ideogram 4 NF4 did not qualify on the supported RTX 4070 Ti 12-GB
target. IMG-120 is not authorized.

PR-SVD-100 is the complete / accepted / integrated post-v2.6 SVD
submission-convenience package on `main`. It adds non-recursive folder planning and one
normal queue batch submission while
preserving the accepted SVD runtime, backend, queue, history, replay, and
artifact authorities.

PR-LEARN-300 is **IN PROGRESS**. Its evidence-integrity and workflow slices give Designed
image experiments one durable experiment identity and an immutable preview
snapshot of effective prompt, model/VAE, stage configuration, tested variable,
values, sample count, and a concrete requested seed. Backend-returned seed
vectors establish then validate controlled evidence across variants; they are
not inferred from batch arithmetic. PromptPack work resolves only Matrix
variables referenced by the selected row, freezes the first canonical vector
even when the pack normally uses random mode, and records Matrix as unused when
the selected row references no tokens. All variants compile before one normal
`JobService.submit_njrs` admission; each admitted NJR retains its ordinary
independent SQLite queue lifecycle. Ratings retain exact experiment/variant,
job/artifact, and frozen executed-configuration evidence. Controlled ratings
may recommend only the deliberately tested variable; incomplete historical rows
remain readable but are excluded from recommendation inference. Learning remains image-stage-only, cannot mutate
PromptPacks/NJRs/history, and has no autonomous tuning authority. Resource-backed
Model/VAE/Sampler/Scheduler choices now use the live `AppStateV2` projection and
refresh path. Learning outputs retain full experiment identity in metadata while
using readable experiment-folder and artifact-name labels; all variants of one
experiment remain grouped. Learning filenames include frozen source/prompt row,
model, timestamp, variant, and sample identity. Editable Working Draft state
autosaves independently; only experiments that cross queue admission enter the
default Experiment Library, while old never-run entries remain non-destructive
Draft/Legacy Draft data. Discovered scanner groups have durable origin, expose
total/available/missing counts, use distinct restorable Done and Dismiss
decisions, fit their image preview to a majority-width adjustable review
workspace, and support previewed Clean Missing References and rebuild operations
that preserve controlled/imported worksets and terminal operator decisions. The
review workspace now groups completed samples by
variant/value, exposes rated state and per-variant summaries, supports deterministic
Next Unrated and side-by-side comparison, and preserves the selected target during
background completion. Experiment conclusions derive from saved sample ratings,
exclude drafts, and cannot name a causal winner when controlled seed evidence is
invalid. The ambiguous Resume Last, primary generic recent-record Tags editor,
and global header Automation selector are no longer primary Learning actions.
Staged Curation can preview learned settings and, after confirmation, apply an
allowlisted patch only to one newly built derived-job intent before its normal
NJR/JobService submission. `PR-VID-110` remains a separate product-owner decision.
Deterministic implementation validation is complete; physical A1111 operator
acceptance remains deferred pending GPU safety clearance.

## Approved post-v2.6 direction

The first approved post-v2.6 architecture PR, `PR-IMG-100 — Backend-Neutral
Image Execution`, is complete / accepted / integrated. The accepted course of
action is **one typed image backend per image NJR**.
A1111/WebUI remains the default/current production image backend and its accepted
behavior must be preserved behind the new boundary. Newly compiled image NJRs
will explicitly persist image backend identity through the existing immutable
`backend_options` workload layer; historical v2.6 image NJRs that lack backend
identity will resolve deterministically to A1111 through one bounded compatibility
rule.

`PR-IMG-100` does not implement Ideogram, Diffusers image inference, ComfyUI
still-image execution, or per-stage backend composition. PR-IMG-110 established
that the generic Diffusers substrate is viable but Ideogram 4 NF4 is not viable
on the RTX 4070 Ti 12-GB target; it did not authorize a Diffusers backend.
Per-stage backend composition (COA C) and ComfyUI-centric image execution (COA D)
remain possible future options, but neither may replace StableNew's compiler,
NJR, queue, runner, artifact, history, replay, cancellation, or process authorities.
The full approved acceptance contract and phased Codex prompts are in
`docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`.

## Accepted PR-MVP-080 work

Accepted 080 work includes source-aware SVD target selection, readiness
projection/UI, truthful SVD preset state, explicit SVD geometry enforcement,
HARDEN-009 runtime timeout/watchdog corrections, canonical txt2img cancellation
deterministic proof, a real A1111 operator-cancellation PASS, and the
cancellation/result-publication race repair at
`d2909e752faaa34f20a49fccc9865a8412c21b15`. R1D managed / external WebUI stall
policy is integrated on the active PR-MVP-080 branch.

The cancellation repair keeps terminal result publication behind durable
`RUNNING` ownership. SQLite remains the lifecycle and result authority; a
cancellation or return-to-queue decision that wins before late backend
publication prevents successful result data, artifact references, and
`final_output` checkpoints from being promoted. Normal success, return-to-queue,
and replay lineage remain unchanged. No lifecycle, schema, architecture, or
generic image-output cleanup authority changed. Bytes already written by a
cancelled backend may remain as non-authoritative residue when safe bounded
cleanup is unavailable.

Repair-SHA validation recorded 31 focused queue/repository tests passed and 10
cancellation/replay tests passed. An additional adjacent batch had 27 passed
with 14 unrelated legacy fixture/model-constructor failures. Ruff remained at
the existing non-increasing baseline and the changed test was clean; the
controller ratchet was not applicable. One PR-gate attempt was blocked because
the gate environment could not find local `mypy`. No real A1111 cancellation
rerun was performed because the existing external API was unreachable and was
correctly not launched, adopted, or restarted. No GitHub Actions run exists for
this exact repair SHA, so no Python 3.11/3.12 CI-green claim is made for it.

R1B real-A1111 evidence used WebUI v1.10.1. Operator cancellation during active
sampling worked with one generation POST and one interrupt; SQLite recorded
`CANCELLED`, and no artifact was resurrected.

R1D contracts are ownership-sensitive. For managed A1111, StableNew may restart
only the tracked process that StableNew launched, and only after a proven
post-interrupt wedge. For external A1111, StableNew may use supported
API/progress/interrupt operations but never adopts, kills, or restarts the
process. A stalled external runtime surfaces operator action required.

The canonical `run_img2img_stage` now uses the existing shared
progress/cancellation authority. Active img2img cancellation is deterministically
proven with one generation POST, one interrupt, persisted `CANCELLED`, no
promoted artifact, no later pipeline stage, no process restart/retry, and no
resurrection when a late response succeeds.

Conservative interrupted-job recovery is **PASS / ACCEPTED**. SQLite remains the
single lifecycle/history authority. Jobs persisted as `QUEUED` before restart
remain queued/runnable in durable order. Jobs persisted as `RUNNING` at process
loss have an ambiguous execution outcome: they are never automatically
requeued or replayed, and become terminal `FAILED` records with the machine-
identifiable `INTERRUPTED_RESTART_ACTION_REQUIRED` reason. `FAILED` is the
durable lifecycle encoding, not proof that backend generation definitely
failed. The record requires operator review and preserves available NJR,
fingerprint, lineage, timestamps, execution metadata, checkpoints, results,
artifacts, and diagnostic evidence without incrementing return-to-queue count.
Only genuine queued rows enter the restored runnable projection, so auto-run
cannot dispatch the interrupted record. Pipeline history renders it as
`Interrupted`; explicit Replay remains opt-in and creates new authorized work
with a new NJR/job identity and parent lineage, while the original remains
terminal history. Operator Readiness surfaces persisted interrupted-restart
records as action-required; no acknowledgement mechanism is documented or
assumed. No new SQLite schema/version or second lifecycle authority was
introduced. The former automatic `RUNNING -> QUEUED` restart behavior is
superseded.

Queue/history action-state and no-op cleanup is **PASS / ACCEPTED**. Live Queue
controls now combine legal queue state with callable controller capability.
Manual Send Job remains available with Auto-run OFF when queued work exists, the
queue is unpaused, no job is running, and the manual dispatch boundary exists.
Auto-run and Pause/Resume are not presented as operable without their
application boundaries; reorder, remove, and clear remain restricted to legal
queued work. Direct, keyboard, and stale callback paths re-check legality, and
Remove/Clear do not report success when the underlying action reports no change
or failure.

The live Pipeline Job History surface is `src/gui/job_history_panel_v2.py`.
History actions combine callable controller capability with real persisted,
artifact, and replay evidence. Open Output Folder requires a real surviving
output location; Replay requires a reconstructable persisted NJR, while valid
interrupted-restart records remain explicitly replayable through the existing
new-NJR/lineage rules. Animate with SVD requires a real existing still-image
artifact. Video Workflow and Movie Clips require usable surviving handoff
evidence, Explain requires its callable boundary, and buttons/context-menu
actions share the same predicates. Canonical direct-image artifact discovery
was aligned in the existing AppController handoff helper without adding
controller responsibility. No SQLite, lifecycle, replay-architecture,
acknowledgement, backend, or GPU behavior changed.

## Current acceptance state

PR-MVP-090 Phase 0 runtime/bootstrap is **COMPLETE / ACCEPTED**. The supported
Windows Python 3.11/3.12 bootstrap is repository-owned, and its CUDA-enabled
Torch installation order is encoded. Disposable bootstrap validation passed on
the RTX 4070 Ti, and check-only validation passed on the established runtime.
The accepted runtime evidence includes:

- Diffusers `StableVideoDiffusionPipeline` is available.
- FFmpeg and ffprobe execute through the production resolver.
- The accepted plain XT is detected through the production cache authority.
- Phase 0 acceptance verified that the effective operator profile matched the
  `Recommended 12GB / XT 14f` baseline at acceptance time: plain XT,
  production default per-user Hugging Face cache, 14 frames, 7 fps, 25 steps,
  motion bucket 48, noise 0.01, decode 2, Match Source Aspect with
  `center_crop`, local-only true, and all postprocess stages OFF.
- Production local-only SVD preflight passes with no blockers or warnings.
- No model download or SVD inference was required for Phase 0.
- Required GitHub Python 3.11/3.12 CI, including mypy and smoke gates, passed.

Local PR-gate execution was blocked by missing local `mypy`; the required
GitHub mypy/smoke gates passed, so this is not an active blocker. Zero NJR
submissions and zero SVD inference jobs occurred during Phase 0.

The PR-MVP-090 release-harness integrity checkpoint is **COMPLETE / ACCEPTED**.
The modern NJR journey now uses the immutable NJR contract and traverses
`JobService.submit_njrs` through a temporary SQLite queue/repository and the
production controller-to-runner bridge; history is read back from that
repository rather than synthesized. Shutdown journeys disable backend
autostart, use bounded unavailable endpoints, and inspect only test-owned
processes. Process cleanup is ownership-scoped, so unrelated user A1111,
ComfyUI, and Python processes are ignored and never targeted. Bootstrap and
journey wrappers retain the approved interpreter/dependency normalization.
Focused release-harness validation passed; the disposable `.venv-release-proof`
was removed after confirming no process used it.

The PR-MVP-090 raw-Ruff hygiene checkpoint is **COMPLETE / ACCEPTED**.
Pinned Ruff 0.14.9 found 3,553 active findings on the feature tree; after
reviewed mechanical cleanup and narrow defect repairs, `ruff check .` is zero.
The legacy baseline file and baseline-comparison gate were removed. The local
PR gate and required CI now enforce raw `ruff check .` directly. Controller
ceilings were not increased; the AppController ceiling was tightened by one
physical line. StableNew CI run 328 passed both required Python 3.11 and 3.12
jobs; informational full-suite legacy failures remain non-blocking.

The managed-runtime ownership safety repair is **COMPLETE / ACCEPTED**.
WebUI launch now refuses an occupied configured endpoint without killing or
adopting its process. Stop, restart, orphan monitoring, process-container
teardown, and emergency cleanup require explicit manager ownership and may act
only on the launched root and proven descendants. ComfyUI now has ownership
parity: bootstrap uses an existing healthy external endpoint unmanaged without
launching a duplicate, rejects an occupied invalid endpoint without killing or
replacing its occupant, and launches only when the configured endpoint is free.
The same explicit ownership gate protects ComfyUI cleanup and restart. Machine-
wide port, working-directory, process-appearance, and orphan/reparented-process
kill scans are no longer automatic authorities. Focused ownership/lifecycle/
recovery validation passed using fakes and test-owned disposable processes only.
StableNew CI run 330 passed both required Python 3.11 and 3.12 jobs;
informational full-suite legacy failures remain non-blocking. The legacy test's
live `atexit` registration and global-state leak are confirmed; whether that
callback caused the previously observed external runtime disappearance remains
unresolved.

XT 1.1 remains a distinct supported model and must not be substituted for the
accepted plain-XT baseline merely because it is cached.

The earlier stopped portrait attempt is historical context only; it found local
effective-state drift and submitted no work. After normalization through the
existing UI-state authority, portrait source-aware native-SVD acceptance is now
**PASS / ACCEPTED**. A real StableNew source artifact at `832x1216` selected the
deterministic `640x960` target. The prepared image was exactly `640x960`,
resized and center-cropped without padding. The conservative plain-XT profile
was used: 14 frames, 7 fps, 25 steps, motion bucket 48, noise 0.01, decode 2,
CPU offload and forward chunking enabled, local-only enabled, canonical
production Hugging Face cache, and all postprocess stages disabled.

The fresh job was submitted through the public application/controller boundary
and canonical queue-first `JobService` / SQLite / `PipelineRunner.run_njr`
spine. SQLite job `a46863c56b9e4d8cba8925e96edcb18d` reached `completed`; its
artifact, manifest, preview, and repository result agreed. The MP4 was
non-empty and decoded at `640x960`, `7/1` fps, with exactly 14 frames. Visual
inspection confirmed portrait orientation, plausible center crop, and no
evident stretch or squash. The physical GUI button was not used because the
desktop bridge was unavailable; the approved public submission boundary was
used instead. No production or test source changes were required.

RIFE interpolation semantics are **PASS / ACCEPTED**. RIFE is an optional
native-SVD temporal-smoothing postprocess, not slow motion. MVP operators may
use only 2x or 4x: output frames equal base frames multiplied by the factor,
and output FPS is multiplied by the same factor. Thus 14 frames at 7 fps
becomes 28 at 14 fps for 2x or 56 at 28 fps for 4x; disabled RIFE remains at
the base cadence. Unsupported factors such as 3x are rejected before SVD
model preparation or inference. Effective artifact FPS propagates through
MP4/GIF export, `SVDResult`, manifest/history, and embedded container metadata;
immutable SVD configuration retains base generation FPS. Postprocess metadata
records explicit input/output counts and FPS plus the duration-preserving
semantics. Exact output counts are validated, including the bounded
compatibility path for existing non-v4 RIFE runtimes.

A bounded real RIFE-only check used the accepted 14-frame SVD artifact: 14
frames at 7 fps and 2.00 seconds became 28 frames at 14 fps and 2.00 seconds.
The installed runtime rejected custom `-n`, so the compatibility fallback was
exercised; visual smoke inspection showed no obvious corruption. No SVD
inference, model/runtime download, or queue submission occurred. No GitHub
Actions run is associated with the RIFE commit, so its Python 3.11/3.12 CI
status must not be represented as passed.

Portable native-SVD MP4 provenance and parent artifact lineage are **PASS /
ACCEPTED**. Native-SVD MP4 artifacts embed machine-readable immutable audit /
recovery evidence under `stablenew.video-provenance.v2.6`. The payload uses
canonical JSON, with raw storage for smaller payloads and gzip/base64 for
larger payloads, and verifies its payload SHA-256. It preserves the exact
source-image byte SHA-256, valid embedded StableNew image provenance when
available, current NJR SHA-256 when available, authorized parent job/artifact
IDs, complete SVD configuration, actual preprocess/postprocess results, and
effective RIFE frame/FPS values. Missing, omitted, or corrupt source
provenance is explicit rather than fabricated. The MP4 video media/elementary
stream has an independent SHA-256 that was verified unchanged across metadata
remux; this is not a whole-MP4 file hash. Existing public container metadata
remains available, and the SVD JSON sidecar carries a matching summary.
Failure to embed, read back, or verify required provenance fails SVD export and
uses the existing partial-output cleanup. SQLite remains the live queue,
repository, and history authority; embedded provenance does not authorize
replay or automatically restore history, and paths remain convenience
references rather than durable identity.

A bounded real FFmpeg-only acceptance exercised the production `SVDRunner` with
temporary frames and a fake SVD service. Payload read-back and SHA verification,
source and media hashes, sidecar coherence, isolated MP4-only lineage recovery,
and ffprobe validation of 14 frames at 7 fps all passed. No model download,
GPU/SVD inference, or queue submission was required. Focused validation was
`74 passed`; the local standard PR gate remains blocked by missing local
`mypy`. No GitHub Python 3.11/3.12 CI result is claimed for the provenance
commit `b33d028473f905747ddc19ae394526f5e6531fe8`.

## Remaining sequence

PR-MVP-080 is **COMPLETE / ACCEPTED / INTEGRATED**. The final operator journey
passed: Rob manually verified one normal queue-first run with Auto-run OFF and
a second back-to-back run; both completed successfully. Previously accepted
queue/history, replay-lineage, cancellation, shutdown-persistence, SVD, and
provenance evidence remains valid. The accepted feature line was fast-forwarded
into `main` without a merge commit, rebase, or force push. StableNew CI run 317
passed on the accepted source tree, including required Python 3.11 and 3.12.

1. Maintain the accepted v2.6 and IMG-100 baseline pending explicit product-owner direction.

Next action: **await explicit product-owner direction**.

PR-MVP-090 is **COMPLETE / ACCEPTED / INTEGRATED**. The final real-backend
release proof completed without production source changes.

The accepted final image job was `mvp090-final-image-lifetime`: one durable
`COMPLETED` queue/history entry, one decoded 768x1024 PNG, checkpoint
`juggernautXL_ragnarokBy.safetensors [dd08fa32f9]`, and image SHA-256
`57a1b6f14ab483a3d981df3e35304ef9d26bbe0478b8abb7c3a12f4513eec76f`.
The repaired acceptance harness proved durable terminal state and queue-runner
idle before teardown; no duplicate or replay occurred.

The final native plain-SVD-XT job was `4df7d2a73ea04e42a09294a81dfe8897`.
It was submitted through the public SVD controller and queue-first NJR path,
reached durable `COMPLETED`, and produced one non-empty MP4. The source-aware
target was 576x1024 from the 768x1024 portrait source; preprocessing resized
and center-cropped without padding. FFprobe verified exactly 14 frames at 7
fps and 576x1024. The accepted profile was plain XT, 25 steps, motion bucket
48, noise 0.01, decode chunk 2, fp16, CPU offload ON, forward chunking ON,
local-only ON, and all optional postprocessing OFF.

The disposable Windows bootstrap/check-only evidence used Python 3.11.9,
CUDA-enabled Torch 2.14.0+cu130 (CUDA 13.0), Diffusers 0.40.0,
Transformers 5.17.0, Accelerate 1.15.0, imageio-ffmpeg 0.6.0, and an RTX
4070 Ti. The production plain-XT cache was complete and no model download
occurred. Embedded provenance read-back passed, including source image
SHA-256, source job identity, current NJR SHA-256, SVD configuration, actual
preprocess/postprocess facts, and media-content verification. The visual smoke
check showed portrait orientation with no obvious stretch, squash, or gross
corruption.

Required CI run 331 remains the source-SHA compatibility evidence; no source
validation was rerun for this docs-only closeout. The earlier 832x1216 pressure
rejection remains expected guardrail behavior, and the interpreter-shutdown
incident is closed as an acceptance-harness lifetime defect.

## Known non-blocking debt

- Informational Linux/Xvfb isolation failures remain outside the required CI verdict.
- Legacy stale tests still reflect superseded CLI, compatibility, migration, or
  stale constructor-fixture expectations.
- Local PR-gate execution can be unavailable when local `mypy` is missing;
  required GitHub mypy and smoke gates are the compatibility verdict.

Current exact collection and smoke counts are taken from the latest required CI
recorded here or in the applicable acceptance report. Run focused checks, then
`python tools/ci/run_pr_gate.py` when source changes require it. Do not repeat
GPU, WebUI, or SVD acceptance for docs-only changes.

Use Git history and the roadmap for historical detail. Update this file only
when repository direction, active work, or verified state materially changes.
