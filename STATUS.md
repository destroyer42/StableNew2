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

## Remaining sequence

1. Complete portable video provenance and parent artifact lineage.
2. Complete queue/history recovery UX and no-op cleanup.
3. Finish PR-MVP-080 operator journey/docs/required CI/integration.
4. Return to the remaining PR-MVP-090 clean-machine/release-proof work.

Next action: portable video provenance + parent artifact lineage.

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
