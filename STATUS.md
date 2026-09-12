# StableNew status

Updated: 2026-09-12

## Repository

- Authoritative remote: `https://github.com/destroyer42/StableNew2.git`
- Product name: StableNew
- Default branch: `main`
- Current release line: v2.6 MVP recovery (converged baseline)
- Authoritative branch: `main`

`main` is the consolidated product baseline. It contains the reconciled
architecture, repository-completeness repair, trustworthy test harness,
immutable NJR core, typed compiler/submission cutover, repository simplification,
and the selected QOL PromptPack updates used by the verified image-generation
baseline. Superseded main/QOL deltas were dispositioned rather than merged into
the working tree wholesale.

## Product state

StableNew has a verified queue-first NJR/runner spine, trustworthy bounded CI
gates, one transactional SQLite authority for job lifecycle state, and one
versioned JSON authority for authored PromptPacks. Queue and history are
repository projections, and legacy persistence has offline backup-first
migration. PR-MVP-060 and PR-MVP-070 are **COMPLETE / ACCEPTED / INTEGRATED**.
 The image and native SVD XT vertical slices are accepted; operator readiness
 and clean-machine release proof remain future work.

## Runtime invariants

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`

- Fresh work is queue-first.
- NJR is immutable authorized work.
- Mutable lifecycle/result state belongs outside NJR.
- PromptPack identity is conditional on PromptPack source.
- Replay uses a new NJR with parent lineage.
- GUI/controllers do not create alternate runner paths.

## Current work

Repository convergence, simplification, transactional job persistence,
PR-MVP-045 PromptPack draft/preview/queue repair, and PR-MVP-050 one-file JSON
PromptPack convergence are complete. PR-MVP-060 Phase 1 and Phase 2A/2B/2C/2C1/2D
are verified on `main`. The final image implementation and acceptance are
integrated in the current main baseline. The
consolidated image journey composes live Pack Selector draft/preview, queue
persistence, manual dispatch, deterministic model synchronization, progress,
artifacts, history, and replay lineage. Do not revive recovery, hygiene, or
QOL branches as alternate sources of truth.

PR-MVP-060 — **COMPLETE / ACCEPTED**

Final R4 manual acceptance recorded:

- Real StableNew GUI exercised with native JSON PromptPack preview.
- Add to Queue worked without touching Override; SQLite-backed queue
  projections and counts remained correct with no first-item or leftover
  mismatch.
- Manual Send Job worked with Auto-run OFF; Auto-run ON drained continuously.
- Switching Auto-run OFF during active execution finished the current job and
  left subsequent jobs queued; pause/resume respected the active policy.
- External A1111 checkpoint mismatch, model switch, and verification succeeded.
- Real txt2img generated an image and produced artifact/history records.
- Replay created a new queued job and executed successfully.
- Responsive Width/Height acceptance passed.

PR-PACKS-001 Phase 1/1B converged the user library with a lossless backup and
quarantine before repository storage changed. Phase 2 is **COMPLETE / INTEGRATED**:
production PromptPack authority is `%LOCALAPPDATA%\StableNew\PromptPacks`, with
51 valid native JSON PromptPacks. The tracked runtime library and generated LoRA
cache are not source-controlled. Repository/worktree cleanup is **COMPLETE**;
the current main is `a107756f2d19475907015652d7a89a2c04bf30ac`.

PR-UI-RESOURCES-001 is **COMPLETE**: Base Generation Scheduler resources now
populate through the shared WebUI resource projection path.

PR-MVP-070 is **COMPLETE / ACCEPTED / INTEGRATED** on main
(`a107756f2d19475907015652d7a89a2c04bf30ac`). The accepted product path is:

`Intent -> Compiler / typed builder -> immutable NJR -> JobService -> SQLite
Queue/Repository -> PipelineRunner.run_njr -> SVDNativeVideoBackend -> native
SVD runner/service -> Canonical Artifact/History`

The validated conservative Windows/~12GB baseline uses the native
`stabilityai/stable-video-diffusion-img2vid-xt` model with 14 frames, 7 fps,
25 inference steps, 1024x576 center-crop output, motion bucket 48, noise
augmentation 0.01, decode chunk 2, fp16, CPU model offload ON, forward
chunking ON, and local-only model/cache policy. A real RTX 4070 Ti acceptance
completed the canonical queue-first job through COMPLETED in 77.7 seconds with
25/25 denoising and MP4, preview, manifest, history, and replay artifacts.
The manifest and ffprobe each report 14 frames. 25-frame XT remains an
explicit higher-memory capability, not the conservative default. The exact
sequence exporter now constrains MP4 output with `-frames:v len(temp_images)`;
slideshow semantics remain unchanged.

## Highest-value debt

1. Informational Linux/Xvfb full-suite isolation debt still causes known
   WindowsPath/platform-state failures outside the required integration gate.
2. Legacy CLI/compatibility and superseded JSON migration tests assert pre-cutover NJR
   fields and payload shapes; the broad suite is therefore not green.
3. Ruff still has a bounded legacy baseline; repository-wide mypy is not clean.
4. PromptPack visibility filtering can make packs appear missing without clearly
   indicating that SFW filtering is active.
5. Known stale legacy fixture debt remains outside the required gate.

## Now / next / later

**Now / Next**

- `PR-MVP-060`: **COMPLETE / ACCEPTED**; image create-to-replay vertical slice.
- `PR-PACKS-001`: **COMPLETE / INTEGRATED**; external PromptPack storage and
  repository/worktree cleanup are complete.
- `PR-MVP-070`: **COMPLETE / ACCEPTED / INTEGRATED**; native SVD XT admission,
  per-user Hugging Face cache policy, queue-first execution, target-GPU
  acceptance, exact artifacts/history, and replay lineage are complete.
- `PR-HARDEN-008`: **COMPLETE / INTEGRATED**; truthful runner-watchdog
  telemetry, bounded WebUI stall recovery, and safe ambiguous generation
  transport handling. Ambiguous txt2img/img2img response loss does not
  automatically re-POST, fails without fabricating an artifact, and later
  work waits for WebUI idle through the existing readiness authority.

**Later**

- `PR-MVP-080`: **NEXT** — operator UX, setup, diagnostics, and bounded lint cleanup.
- `PR-MVP-090`: clean-machine release proof and zero Ruff baseline.

## Verification state

Latest integrated-main verification for the converged product state:

- required GitHub CI run `34708650314`: Python 3.11 PASS and Python 3.12 PASS;
- informational full-suite jobs failed from known Linux/Xvfb
  WindowsPath/platform-state test debt and are not the integration verdict;
- bounded repository-wide Ruff and typing debt remains tracked separately.

Final R4 manual GUI acceptance passed on the real StableNew desktop GUI with
real A1111, including queue policy, model synchronization, txt2img,
artifact/history, replay, and responsive dimensions as recorded above.

The integrated PromptPack storage path resolved the default authority to
`%LOCALAPPDATA%\StableNew\PromptPacks` and discovered 51 valid native packs.
The generated LoRA cache was backed up, removed from tracking, and verified to
regenerate without dirty-tree noise.

Run focused tests, then `python tools/ci/run_pr_gate.py`. GitHub required CI on
Python 3.11 and 3.12 is the canonical integration verdict.

The focused repository, queue, history, and migration sweep passes 125 tests.
Superseded JSON/JSONL persistence and pre-NJR compatibility tests were removed
or rewritten against the current repository contract. A repository-wide test
run was not used as an acceptance gate for this bounded PR.

The local WebUI image path has completed a fixed-seed queue-to-runner smoke.
PR-HARDEN-008 resolved the false queue-runner stall diagnosis, bounded WebUI
stall recovery, and ambiguous generation transport replay risk.

Run the commands in `docs/StableNew_Coding_and_Testing_v2.6.md` rather than
copying these numbers elsewhere. Update this section only after a comparable
verified run.

## Update rule

Any change that materially alters repository direction, active work, roadmap
status, or verified baseline updates this file. Keep it current and concise;
use Git history and `CHANGELOG.md` for history.
