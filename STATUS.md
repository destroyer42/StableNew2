# StableNew current state

Updated: 2026-09-13

## Repository

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Default/release baseline: `main`
- Current remote `origin/main`: `4982e7672573927cc3bab0f5074123e5ba06207b`
- Active integration branch: `mvp/080-operator-readiness`
- Exact branch/head state must be verified from GitHub before planning or executing work.

`main` remains the release baseline until PR-MVP-080 integration is complete.
The canonical documentation order is `AGENTS.md`, `STATUS.md`,
`docs/CODEX_MAP.md`, the relevant architecture section, the relevant coding and
testing section, the roadmap for sequencing, and Git history only when current
evidence is insufficient or history is explicitly requested.

## Product state

StableNew has one queue-first NJR/runner spine, transactional SQLite lifecycle
state, versioned JSON PromptPack storage, and accepted image and native SVD XT
vertical slices. PR-MVP-060 is **COMPLETE / ACCEPTED**. PR-MVP-070 is
**COMPLETE / ACCEPTED**. PR-MVP-080 is **IN PROGRESS**. PR-MVP-090 is planned.

The runtime invariant remains:

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

Fresh work is queued, NJRs are immutable, lifecycle state belongs to queue and
history, replay creates a new NJR with lineage, and GUI/controllers do not
create an alternate runner path.

The current branch is an integration checkpoint, not a release declaration:
remaining 080 acceptance and the later 090 clean-machine proof are still
required before the release baseline can move.

## Approved post-v2.6 direction

After PR-MVP-080 and PR-MVP-090 are accepted and integrated, the first approved
post-v2.6 architecture PR is `PR-IMG-100 — Backend-Neutral Image Execution`.
The accepted course of action is **one typed image backend per image NJR**.
A1111/WebUI remains the default/current production image backend and its accepted
behavior must be preserved behind the new boundary. Newly compiled image NJRs
will explicitly persist image backend identity through the existing immutable
`backend_options` workload layer; historical v2.6 image NJRs that lack backend
identity will resolve deterministically to A1111 through one bounded compatibility
rule.

`PR-IMG-100` does not implement Ideogram, Diffusers image inference, ComfyUI
still-image execution, or per-stage backend composition. A later Diffusers
backend may be qualified against Ideogram 4 after PR-IMG-100 is accepted.
Per-stage backend composition (COA C) and ComfyUI-centric image execution (COA D)
remain possible future options, but neither may replace StableNew's compiler,
NJR, queue, runner, artifact, history, replay, cancellation, or process authorities.
The full approved acceptance contract and phased Codex prompts are in
`docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md`.

## Accepted PR-MVP-080 work

Accepted 080 work includes source-aware SVD target selection, readiness
projection/UI, truthful SVD preset state, explicit SVD geometry enforcement,
HARDEN-009 runtime timeout/watchdog corrections, canonical txt2img cancellation
deterministic proof, and a real A1111 operator-cancellation PASS. R1D managed /
external WebUI stall policy is integrated on the active PR-MVP-080 branch.

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

1. Complete queue/history action-state + no-op cleanup.
2. Finish PR-MVP-080 operator journey/docs/required CI/integration.
3. Return to the remaining PR-MVP-090 clean-machine/release-proof work.
4. After v2.6 release acceptance, begin PR-IMG-100 Phase A from the exact
   integrated post-v2.6 branch/SHA.

Next action: queue/history action-state + no-op cleanup.

PR-MVP-090 remains planned overall. Its Phase 0 runtime/bootstrap prerequisite
is complete and accepted, pulled forward only to unblock PR-MVP-080; the
remaining clean-machine and release-proof work stays after PR-MVP-080.

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
