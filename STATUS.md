# StableNew current state

Updated: 2026-09-12

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

## Current acceptance blocker

Phase 0R1 established that the StableNew runtime is healthy under the proven
local execution scope. StableNew's production default Hugging Face cache is
the per-user Hugging Face hub cache, and it already contains a complete
`stabilityai/stable-video-diffusion-img2vid-xt`. No XT download is required.

A fresh `SVDController` default using the accepted plain-XT profile passes
production local-only preflight:

- Model is supported and cached.
- Torch is available.
- Diffusers and `StableVideoDiffusionPipeline` are available.
- CUDA is available on the RTX 4070 Ti.
- The portrait source is valid.
- Blocking reasons and warnings are empty.

The remaining operator blocker is stale persisted GUI state in more than one
SVD field:

- `model_id` is `stabilityai/stable-video-diffusion-img2vid` (base).
- `cache_dir` points to the obsolete repository-local `cache` directory, where
  plain XT is incomplete.

The base model is supported historical/user state, but it is not the
authoritative Recommended-profile baseline for this acceptance. Correcting
`cache_dir` alone would therefore not establish the accepted
operator-effective profile. Historical base-model and XT 1.1 records do not
supersede the canonical accepted plain-XT baseline. No user-state mutation,
NJR submission, model load, or inference occurred during Phase 0.

XT 1.1 remains a distinct supported model and must not be substituted for the
accepted plain-XT baseline merely because it is cached.

## Remaining sequence

1. Complete the remaining PR-MVP-090 Phase 0 operator prerequisite: reconcile
   the full persisted SVD effective state against the `Recommended 12GB / XT
   14f` preset, apply that preset through the existing operator/UI-state
   authority while preserving unrelated settings, restore the canonical cache
   authority, and prove the operator-effective local-only preflight; then
   complete the reproducibility/bootstrap helper gap.
2. Resume the real portrait source-aware SVD geometry acceptance.
3. Decide/repair RIFE interpolation semantics if required.
4. Complete queue/history recovery UX and no-op cleanup.
5. Finish PR-MVP-080 operator journey/docs/required CI/integration.
6. Return to the remaining PR-MVP-090 clean-machine/release-proof work.

Next action: reconcile the full persisted SVD effective state against the
`Recommended 12GB / XT 14f` preset, apply that preset through the existing
operator/UI-state authority while preserving unrelated settings, restore the
canonical cache authority, and rerun production preflight; then complete the
reproducibility/bootstrap helper gap.

PR-MVP-090 remains planned overall. Its Phase 0 runtime/bootstrap prerequisite
is pulled forward only to unblock PR-MVP-080; the remaining clean-machine and
release-proof work stays after PR-MVP-080.

## Known non-blocking debt

- Informational Linux/Xvfb isolation failures remain outside the required CI verdict.
- Legacy stale tests still reflect superseded CLI, compatibility, migration, or
  stale constructor-fixture expectations.
- Bounded Ruff and mypy debt remains tracked; local environment/bootstrap normalization belongs to PR-MVP-090.

Current exact collection and smoke counts are taken from the latest required CI
recorded here or in the applicable acceptance report. Run focused checks, then
`python tools/ci/run_pr_gate.py` when source changes require it. Do not repeat
GPU, WebUI, or SVD acceptance for docs-only changes.

Use Git history and the roadmap for historical detail. Update this file only
when repository direction, active work, or verified state materially changes.
