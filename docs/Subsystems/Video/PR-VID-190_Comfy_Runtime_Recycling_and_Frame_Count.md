# PR-VID-190 — Owned-Comfy Recycling After Each Job & Selectable Frame Count (Wan2.2 TI2V-5B)

Status: **implemented and real-hardware accepted**; experimental workflow, per-job opt-in unchanged.
Part 1 of the owner-selected plan: fix the queue-recycling defect and the fixed ~2 s clip length on
the workflow the owner actually uses, then (separately) expose Wan-Animate-2 for real-world testing
on StableNew-managed ComfyUI.

## Why this package targets TI2V-5B, not Wan-Animate-2

The three owner-reviewed "high-quality, smooth, prompt-directed" clips that motivated this work were
produced by **`wan22_ti2v_5b_i2v_v1@1.0.0`** (Wan2.2 TI2V-5B: `wan2.2_ti2v_5B_fp16`, `wan2.2_vae`,
`umt5_xxl_fp8_e4m3fn_scaled`; stock `Wan22ImageToVideoLatent`, 49 frames at 24 fps) on the
StableNew-managed desktop ComfyUI — not by Wan-Animate-2 (`wan_animate_2_distill_int8_convrot`,
`Wan2_1_VAE_bf16`, `clip_vision_h`, `WanAnimateToVideo`), which has only ever run on the isolated
PR-VID-184R/S qualification ComfyUI. The durable job history showed each successful run preceded by
a ~1 s failure: `only 5.0 GB of system RAM is available (needs 16.0 GB for a cold Wan2.2 model
load)`. The owner-value verdict therefore belongs to TI2V-5B and is not recorded as an Animate-2 pass.

## Root cause

`ComfyWorkflowVideoBackend.execute()` started (or reused) the StableNew-owned Comfy, ran the job and
returned — with no per-job release. Comfy keeps the ~18 GB of loaded models in its own process, so
host RAM stayed consumed and the next job's (correct, unchanged) readiness check failed. The
qualification harnesses stopped the manager they owned; production never did.

## Changes

- **Declarative runtime policy.** A workflow may declare
  `backend_defaults["runtime_policy"] = {"release_owned_runtime_after_job": true}`. When it does,
  `execute()` releases the managed Comfy on every exit path — success, ordinary failure, a
  dependency/readiness/output failure after start, and interruption (`BaseException`, re-raised
  unchanged) — through `ComfyProcessManager.stop()`, the only release authority, and **only when
  the manager owns its process**. An external or unowned runtime is never asked to stop. The
  outcome (`ownership`, `pid`, `released`) is recorded in the result's backend metadata and
  diagnostics. Workflows without the policy keep their existing lifecycle.
- **One owner object across release/relaunch.** `stop()` unregisters the global manager; `start()`
  now re-registers it, and the backend keeps the manager it resolved. The next job therefore
  relaunches *the same* manager, so the app's exit cleanup and PR-RUNTIME-100 runtime transitions
  keep tracking the process StableNew owns (this also closes the same gap that already existed after
  a PR-RUNTIME-100 release).
- **Neutral frame-count contract** (`src/video/workflow_frame_count.py`). A workflow opts in with a
  `frame_count` input binding plus `backend_defaults["frame_count_policy"]`
  (`default, minimum, maximum, step, offset, fps`). A length is legal when
  `minimum <= n <= maximum` and `(n - offset) % step == 0` — Wan's `4n+1` rule. Illegal values are
  rejected with an operator-readable message, never rounded. The controller freezes the length (and
  the declared FPS) into the immutable stage config at admission, exactly like the seed; the backend
  re-validates before any runtime starts; the manifest, container metadata, result and replay
  fragment record `frame_count`, `fps` and `approximate_seconds`. No code branches on a workflow or
  model name.
- **Versioned workflow.** `wan22_ti2v_5b_i2v_v1@1.0.0` is byte-identical (spec fingerprint
  `2dd94ae2…` unchanged) so existing jobs replay against their exact pinned graph.
  `@1.1.0` is the same qualified graph and files with `Wan22ImageToVideoLatent.length` bound to the
  frozen frame count, the frame-count policy (default 49, legal 17–81, 24 fps) and the release
  policy. Readiness floors (10,000 MiB VRAM available to Comfy, 16 GB host RAM) are unchanged. The
  controller offers only the newest version per workflow; older versions stay registered.
- **UI.** The Video Workflow tab shows a **Frames** selector only for workflows that declare a
  frame-count policy, listing each legal length with its approximate duration
  (e.g. `81 frames (~3.4 s)`), preselecting the declared default. FPS is not an operator knob.

## Real-hardware acceptance

`tools/acceptance/vid190_queue_recycling_acceptance.py`, on the owner's workstation (RTX 4070 Ti
12 GB) and managed ComfyUI (port 8000), isolated scratch queue/output. Three jobs were queued before
the first dispatch through the real `VideoWorkflowController → NJR → JobService → SQLite →
PipelineRunner.run_njr → backend` path and run in queue order; **no process was stopped or killed
between jobs** (the harness only observes). Neutral full-body reference image
(`qual/vid184/env/inputs/source_fullbody.png`), neutral prompts.

| Job | Frames | Result | Managed Comfy PID | Released | Host RAM before | VRAM peak | Wall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 49 | COMPLETED, 49 f / 2.04 s | 34656 (owned) | yes | 18.3 GB | 11,617 MiB | 108.1 s |
| B | 81 | COMPLETED, 81 f / 3.375 s | 26548 (owned) | yes | 24.8 GB | 11,737 MiB | 122.2 s |
| C | 49 | COMPLETED, 49 f / 2.04 s | 47036 (owned) | yes | 24.5 GB | 11,572 MiB | 84.4 s |

- Every job started a fresh managed runtime (three distinct owned PIDs) and released it; after
  each job the endpoint was free, the manager was not running, and the GPU was idle (0 %
  utilization, ~1.1–1.3 GB driver-used). Readiness passed for every job on fresh state; the
  unchanged 16 GB floor was never lowered.
- 81 frames fits: peak VRAM only ~120 MiB above the 49-frame run; minimum host RAM during the run
  2.66 GB (the cold 49-frame load on job A dipped to 0.01 GB, matching the PR-VID-130 baseline).
  No retry was needed; the accepted envelope stays 17–81 frames.
- Outputs verified with `ffprobe`: 480×832, 24 fps, exactly the requested frame counts.
- Replay of job A created a new identity with `parent_job_id` = A and the same frozen frame count,
  seed and video-execution intent (cancelled undispatched; lineage evidence only).
- Final teardown found no owned process to stop (the policy had already released it).

**Longer-clip usefulness (agent observation, not the owner verdict):** in the 81-frame clip the
subject is nearly static for roughly the first 2 s and then clearly turns to her left into profile
during ~2.0–3.2 s, with identity, anatomy and background holding and no catastrophic temporal
degradation; the prompted arm raise did not visibly occur. Motion therefore continues usefully past
the old ~2 s window in this sample. The owner's visual review of the clips is the product verdict.

## Validation

- `tests/video/test_pr_vid_190_comfy_lifecycle_frame_count.py` (37): 1.0.0 byte-identity; 1.1.0
  graph/files/readiness parity; legal `4n+1` envelope and rejection (never rounding); frame count
  offered only by declaring workflows; frozen length compiled into the graph; illegal length fails
  before any runtime start; admission freezes default/selected lengths and duration metadata;
  per-job experimental opt-in still required; only the newest revision offered while 1.0.0 still
  resolves; the controller acquires no process lifecycle; release after success, after dependency /
  readiness / output failures once started, and on interruption; unowned and external runtimes never
  stopped; non-policy workflows stay resident; the next job relaunches; one owner object reused after
  the global is cleared; `start()` re-registers the global owner; three jobs through the real
  queue/SQLite/runner complete serially with readiness evaluated per job — and the unchanged 1.0.0
  revision reproduces the owner's defect (job 2 fails readiness against the resident runtime).
- GUI: Frames selector shows exactly the declared lengths with durations, defaults, hides for a
  workflow without a policy, round-trips saved state.
- Existing Wan/registry/controller/PR-VID-130 integration tests updated only where they pinned the
  1.0.0 graph (now named explicitly) or the old fixed-49 projection.
- Regression: `tests/video`, `tests/controller`, `tests/pipeline`, `tests/services`, `tests/queue`,
  `tests/integration` show no new failure versus clean `origin/main`; the pre-existing failures
  (SVD/ffmpeg, dependency-probe, LTX compiler, controller/pipeline suites, a stale NJR-constructor
  golden-path test, and an intermittent `tests/integration` hang) reproduce identically on
  `origin/main`.

## Architecture boundaries

No second queue, runner, history, compiler or process authority. `PipelineRunner.run_njr` remains
the only runner entry; `ComfyProcessManager` remains the sole managed-Comfy lifecycle authority and
`stop()` its only release. External Comfy/A1111 are never adopted, stopped or restarted. No
readiness threshold was changed, no job is auto-replayed, no GPU scheduler or lease system was
added. Native SVD defaults are unchanged. **Controller Surface Assessment:** the Video Workflow
controller gained only spec-driven frame-count validation/freezing (mirroring the seed) and a
newest-version-per-workflow listing; it acquires no process lifecycle (tested).
