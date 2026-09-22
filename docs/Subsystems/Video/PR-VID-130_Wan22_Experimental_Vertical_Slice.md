# PR-VID-130 — Wan2.2 Experimental Prompt-Directed I2V Vertical Slice

Status: **implemented and physically accepted on branch `video/130-wan22-experimental`; awaiting
product-owner acceptance/integration.** One real Wan2.2 TI2V-5B job ran through the production path
on the RTX 4070 Ti 12 GB. Native SVD remains the accepted, default production video backend and is
unchanged. Wan2.2 is **experimental and opt-in**: it is never approved, never a default, and makes
no identity-preservation or performance-transfer claim. VACE-1.3B stays NO-GO and unregistered.

## 1. What changed (before -> after)

**Before.** `VideoWorkflowController` emitted no neutral intent, always demanded an end anchor, and
`WorkflowRegistry` executed only `approved` workflows. Model files and stock nodes could not be
verified exactly, and there was no per-workflow resource check.

**After.** Video Workflow UI/controller -> immutable NJR with an explicit `video_execution` block ->
`JobService` -> SQLite -> `PipelineRunner.run_njr` -> `VideoExecutionResolver` ->
`ComfyWorkflowVideoBackend` -> pinned stock-node Wan graph -> canonical artifact/history/replay.

## 2. Workflow identity and governance

| Field | Value |
|---|---|
| Workflow | `wan22_ti2v_5b_i2v_v1` v`1.0.0`, `backend_id=comfy` |
| Governance | `experimental`, pinned revision `catalog:wan22_ti2v_5b_i2v_v1@1.0.0` |
| Task / controls | `image_to_video`; accepts `source_image`, `prompt_text`, `negative_prompt` only |
| Required inputs | `source_image`, `prompt`, `seed` (no end anchor, no mid anchors, no control/pose video) |
| Model files (exact names) | `wan2.2_ti2v_5B_fp16.safetensors` (sha256 `456f9013...`), `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (`c3355d30...`), `wan2.2_vae.safetensors` (`e40321bd...`) |
| Upstream | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` @ `c4f60d30c55a624e35427060fdd217579a6c1d77`, Apache-2.0, ComfyUI 0.3.65 (PR-VID-110 manifest; full digests in the catalog) |
| Stock nodes | `UNETLoader`, `CLIPLoader`, `VAELoader`, `ModelSamplingSD3`, `CLIPTextEncode`, `LoadImage`, `Wan22ImageToVideoLatent`, `KSampler`, `VAEDecode`, `CreateVideo`, `SaveVideo` |

The graph is the PR-VID-110 Lane A graph promoted unchanged (480x832, 49 frames, 24 fps, 20 steps, cfg 5.0,
shift 8, `uni_pc`/`simple`); a test renders it and requires it to equal the qualification builder's output node
for node. The raw graph lives only in the catalog `backend_defaults` (adapter-private), never in the NJR.
A landscape source is centre-cropped to 480x832 by `Wan22ImageToVideoLatent` (a documented limitation).

## 3. Experimental execution policy

- `WorkflowRegistry.get(..., allow_experimental=False)`: approved runs; experimental runs **only** when
  the job passes `allow_experimental=True`; disabled never runs, opt-in or not. There is no global switch.
- The authorization is `video_execution.experimental_opt_in` (true only for an experimental spec whose form
  ticked the box), stored in the immutable stage config, carried through `VideoExecutionIntent` ->
  `VideoExecutionRequest.experimental_opt_in`, checked by the resolver's workflow validation *before
  dispatch*, and again by the backend before any runtime is started. Replays copy the stage config, so the
  original authorization (and seed) is preserved with a new job identity and parent lineage.
- `list_specs_for_backend` (approved only) is unchanged; producers use `list_offerable_specs`
  (approved + experimental, never disabled), so listing is not authorization.

## 4. Producer, capability-driven validation, UI

`VideoWorkflowController` now emits a complete neutral block for **every** submission (LTX included):
`{backend_id, task, controls, workflow_id, workflow_version, experimental_opt_in}`. Controls, required inputs
and unsupported inputs are derived from the spec's bindings/tags in `src/video/video_workflow_intent.py`
(pure functions; no workflow-name branching): LTX still requires its end anchor, Wan requires source image and
prompt only, and end/mid anchors, camera intent or depth supplied to Wan are rejected with a readable reason
before queue admission. The qualified default negative prompt is applied when the field is empty; a random
sampler seed is recorded in the job.

The existing Video Workflow tab shows Wan as **EXPERIMENTAL (per-job opt-in required)**, disables the
anchor/motion/conditioning inputs it does not honour, and shows an unchecked "Enable experimental workflow for
this job" box that resets whenever the selection changes, is submitted per job only, and is never saved or
restored from state. Verified in a real Tk session (Wan: end/mid/motion disabled, box visible; LTX: enabled,
box hidden).

## 5. Dependency and resource readiness

- Dependency probe kinds `model_file` (exact pinned file must appear in the loader's advertised choices,
  e.g. `UNETLoader.unet_name`) and `stock_node` (exact class name); missing files/nodes are named and an
  unlistable file is missing, never assumed present. Runs before any queue dispatch.
- `src/video/workflow_readiness.py` is an **observe-only** guard, not a scheduler or lease: it never stops,
  adopts or restarts any process, never retries or replays. Floors (from PR-VID-110): **10,000 MiB** of GPU memory
  available to Comfy (measured footprint 9,570 MiB in the operator-media run, 11,690 MiB whole-GPU peak with 2,120
  MiB used outside; the studio runs peaked 11.1-11.6 GiB) and **16 GB** available host RAM (18.1 GB of models,
  mmap-loaded; qualification started at 20.8-27 GB free and still dipped to 0.01-0.05 GB). Headroom is narrow by
  measurement, not comfortable.
- GPU memory is the **driver-reported** free VRAM plus what Comfy's own allocator holds (so a warm Wan state is
  not rejected). Comfy's own `/system_stats` `vram_free` is *not* trusted: live on this machine it reported
  11,056 MiB free while A1111 held 7,259 MiB and the driver reported 3,298 MiB free. If the driver figure is
  unreadable the guard fails closed. Live check with A1111 running: blocked on both VRAM (3,329 MiB available)
  and RAM (9.8 GB), naming A1111 without touching it.
- Ownership is unchanged: managed Comfy is the process StableNew launched; an external Comfy is never adopted,
  stopped or replaced (the existing manager still refuses to start over a healthy external endpoint).
  VID-130 adds **no** production process-termination or restart authority. The only code that stops a process is
  the local acceptance harness (`tools/acceptance/vid130_wan_acceptance.py`), and it may stop only the managed
  Comfy process that its own run launched and still owns (`ComfyProcessManager.owns_process`); external runtimes
  are never asked to stop.

## 6. Evidence

Deterministic (fake Comfy, no GPU): `tests/video/test_wan22_experimental_workflow.py` (identity/pins, exact graph
equivalence, governance, dependency probe, readiness incl. the live discrepancy, resolver, failures before
`queue_prompt`, relative-path artifact regression) and `tests/integration/test_pr_vid_130_wan_experimental_queue.py`
(real controller -> NJR -> JobService -> SQLite -> run_njr -> Comfy adapter: LTX neutral block, Wan admission,
opt-in survives SQLite reload and replay with parent lineage, missing opt-in / disabled / resource / dependency
failures never reach `queue_prompt`, no VACE/model branching in the runner).

Real operator acceptance (`python -m tools.acceptance.vid130_wan_acceptance`, isolated scratch queue, production
registry, StableNew-managed Comfy on the configured endpoint after the operator closed A1111 and their own Comfy):

| | Run 1 | Run 2 (after fix) |
|---|---|---|
| Result | completed; valid 480x832 / 49 frames / 24 fps MP4 | completed; same, 1,599,707 bytes |
| Wall (includes managed Comfy start + cold model load) | ~88 s | 83.4 s |
| Peak VRAM (whole GPU) | 11,586 MiB | 11,630 MiB (baseline 1,144) |
| Min free host RAM | 0.94 GB (cold-load transient) | 1.45 GB |
| GPU | 71 C, 241 W | 72 C, 241 W, clock >= 2,610 MHz, throttle `0x405` |
| Faults | none | none (no GPU loss, no reset) |

The harness's first version orphaned the StableNew-launched Comfy when an exception occurred during closeout after
the job had run (cleanup then covered only `run_once`). It is repaired: from the moment the runtime stack starts
being built until `run_acceptance` returns, one `finally` runs `_teardown`, which stops the owned Comfy (never an
unowned one), then the job runner, then closes the repository, each step guarded, never masking the run's own
exception or turning a failed run into success, and preserving partial evidence. Covered by
`tests/tools/test_vid130_acceptance_cleanup.py` (including the real controller->queue->`run_njr` path with a fake
backend that fails in post-run evidence processing). The accepted real-GPU evidence below was produced before
this repair and was not rerun.

Run 1 exposed one real defect: a relative run directory made the artifact path join onto itself (and broke the
container-metadata step). Fixed (`Path(...).resolve()`) with a regression test; run 2 shows correct artifact paths.
Run 2 recorded job `9445ce93...`, backend `comfy`, task `image_to_video`, workflow `wan22_ti2v_5b_i2v_v1` `1.0.0`,
`experimental_opt_in=true`, controls `negative_prompt, prompt_text, source_image`, seed 1450782625, and replay
eligibility (a queued replay with `parent_job_id` set and an identical `video_execution` block). Visual review of
an operator-owned still: the same child and clothing are kept and run 2 shows crouch, reach and lift as prompted;
run 1 moved less. Faces soften and motion blur appears mid-clip, consistent with the PR-VID-110 CONDITIONAL result
(inconsistent quality). Media stays in git-ignored `reports/vid130/`.

## 7. Bridge status and boundaries

Producers still relying on the historical stage-owned bridge (unchanged by design): the SVD producer
(`SVDController` -> `svd_native` stage), AnimateDiff and stage-config `video_workflow` produced by the prompt-pack
and reprocess builders, and every historical replayed NJR. Only `VideoWorkflowController` is migrated. Retirement
still needs all producers neutral plus proven replay normalization.

Not in this diff: VACE, SCAIL/Wan Animate, alternate Wan quantizations, custom Comfy nodes, a GPU scheduler/lease,
any production process termination/restart authority (the acceptance harness releases only the managed Comfy it
launched), a new NJR field, or SVD changes.
