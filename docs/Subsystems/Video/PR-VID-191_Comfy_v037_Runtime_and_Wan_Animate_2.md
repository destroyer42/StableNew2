# PR-VID-191 — Managed ComfyUI v0.37.0 Runtime & Experimental Wan-Animate-2

Status: **implemented; pending PR review/merge; real-hardware results below**. Part 2 of the
owner-selected PR-VID-190 plan
(stacked on PR-VID-190's owned-runtime release and frame-count contract). Experimental, explicit
per-job opt-in; native SVD remains the default production video backend.

## Why the runtime had to change

Wan-Animate-2 had only ever run on the isolated PR-VID-184R/S qualification ComfyUI
(`v0.37.0`, revision `73c9bad4`, torch `2.14.0+cu130`, comfy-kitchen `0.2.35`, comfy-aimdo `0.5.5`).
StableNew's managed runtime was the desktop ComfyUI app, **v0.3.65**, which has none of what
Animate-2 needs: no `model_animate2` architecture (its `WanAnimateToVideo` is the original Wan2.2
Animate), no int8 "convrot" quantized-weight loader for `wan_animate_2_distill_int8_convrot`, and no
`--disable-pinned-memory` flag. Two of the four model files also existed only in the qualification
environment. Owner decision: point StableNew's managed Comfy at the proven v0.37.0 install now, and
upgrade the desktop app to the newest ComfyUI later, once this setup is stable.

## Runtime switch (configuration, owner-authorized)

`presets/settings.json` `comfy_command` now launches the v0.37.0 install on the same endpoint
(`127.0.0.1:8000`) through the unchanged `ComfyProcessManager`:

- interpreter/entry: `qual\vid184\env\venv\Scripts\python.exe` `qual\vid184\env\comfyui_source\main.py`
- `--input-directory/--output-directory/--temp-directory/--user-directory` under
  `%LOCALAPPDATA%\StableNew\ComfyRuntime\` — StableNew-owned runtime folders, so staging and outputs
  never touch the qualification evidence folders;
- `--extra-model-paths-config %LOCALAPPDATA%\StableNew\ComfyRuntime\extra_model_paths.yaml` — adds the
  desktop model library (`E:\Users\rober\ComfyUI\models`) and the A1111 folders; the install's own
  `extra_model_paths.yaml` (qualification models, incl. Animate-2) is loaded automatically and is not
  modified. Duplicate filenames across the two libraries (`umt5_xxl_fp8_e4m3fn_scaled`,
  `clip_vision_h`) were verified byte-identical (sha256 `c3355d30…`, `64a7ef76…`).
- `--disable-pinned-memory` — the PR-VID-184R/S preferred launch policy, now for every managed job.
- `comfy_health_total_timeout_seconds` 30 → 90 (v0.37.0 took 22 s to become healthy; margin for
  cold boots).

Smoke test through `ComfyProcessManager`: healthy in 22.0 s; `Wan22ImageToVideoLatent` and
`WanAnimate2ToVideo` present; all six TI2V-5B/Animate-2 files visible to their loaders. The venv
launcher shim parents the real interpreter; `stop()` on the shim ended both (no interpreter left,
endpoint free) — the same behavior PR-VID-190's per-job release relies on. The desktop app's custom
nodes (`ComfyUI-GGUF`, `StableNewLTXBridge`) are not loaded by this runtime; they only serve the
LTX specs, which remain disabled.

**TI2V-5B re-verified on v0.37.0** (`wan22_ti2v_5b_i2v_v1@1.1.0`, three queued jobs, no manual kill,
`reports/vid191_ti2v_on_v037/`):

| Job | Frames | Result | Owned PID | Released | Wall | Min free RAM | VRAM peak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 49 | COMPLETED 49 f / 2.04 s | 48004 | yes | 59.5 s | 17.0 GB | 11,820 MiB |
| B | 81 | COMPLETED 81 f / 3.375 s | 31188 | yes | 81.8 s | 16.6 GB | 11,228 MiB |
| C | 49 | COMPLETED 49 f / 2.04 s | 46068 | yes | 63.8 s | 16.6 GB | 11,765 MiB |

Versus the v0.3.65 run in PR-VID-190 (108/122/84 s, cold-load RAM dipping to 0.01 GB), the new
runtime is faster and removes the host-memory pressure. Replay lineage, frozen frame count and seed
unchanged; GPU idle and endpoint free after every job.

## Wan-Animate-2 workflows

`src/video/workflow_catalog_wan_animate2.py` registers two experimental `backend_id=comfy` specs,
built node-for-node from the qualified flat graph (`run5_flat_graph.json`, sha256 `9ef8dae4…`):
the same four pinned files (`wan_animate_2_distill_int8_convrot` `d2e566ec…`, `umt5_xxl_fp8`
`c3355d30…`, `Wan2_1_VAE_bf16` `1ab9a32c…`, `clip_vision_h` `64a7ef76…`), `WanAnimate2ToVideo`,
lcm/simple, 10 steps, shift 5, cfg 1, sigmas from the unshifted model as qualified, the stock Wan
negative prompt verbatim, and `WanAnimate2Cache`/context windows off as qualified. StableNew binds
the reference image, prompt, seed, frozen geometry (portrait 480×832 / landscape 832×480, prepared
before admission) and frozen frame count; output uses stock `CreateVideo`/`SaveVideo` (mp4).

- **`wan_animate2_prompt_i2v_v1` — Prompt Motion:** reference image + prompt; the node's optional
  `pose_video` is left unconnected. This mode was **not** part of the PR-VID-184 qualification; it is
  exposed so the owner can evaluate it.
- **`wan_animate2_drive_i2v_v1` — Driving Video Motion:** adds a required driving video (neutral
  `CONTROL_POSE_VIDEO` / `WORKFLOW_CAP_POSE_VIDEO`). Verified from the v0.37.0 node source,
  `WanAnimate2ToVideo.pose_video` takes **raw video frames** (VAE-encoded directly; a shorter clip's
  last frame is held) — no pose extraction exists or is needed, so the UI labels it honestly as
  "Driving Video". This is the qualified mode.

Two declarative specs rather than one conditional graph: the generic compiler never gains
workflow-specific logic. Both declare: frame count default 41 (qualified), legal `4n+1` 17–81,
24 fps; `release_owned_runtime_after_job`; `required_launch_flags: ["--disable-pinned-memory"]`;
readiness floors 10,000 MiB VRAM available to Comfy and 16 GB host RAM (PR-VID-184S pinned-OFF:
~11.8 GB peak whole-GPU from a ~1.1 GB baseline, ~12–14 GB host-memory rise); and a 1,200 s
generation wait.

## Backend/controller/UI changes

- **Required launch flags.** Before anything starts, the backend checks that the command StableNew
  itself launches (the resolved manager's, or the default managed configuration) contains every
  declared flag. Missing → the job fails with an operator-readable message; no managed configuration
  (an external runtime whose flags cannot be verified) → refused. StableNew never rewrites the
  command.
- **Driving-video staging.** `LoadVideo.file` is uploaded as a copy through Comfy's `/upload/image`
  (verified in v0.37.0 `server.py` to store any file type into the input folder, where `LoadVideo`
  lists video files) exactly like `LoadImage.image`; the source file is only read. Because the
  launch-flag requirement refuses unverifiable runtimes, staging only ever targets the
  StableNew-managed runtime, whose input folder is the StableNew-owned `ComfyRuntime\input`.
- **Provenance.** The controller freezes `pose_video_path` + `pose_video_sha256` at admission; the
  manifest, container metadata, result and replay record them. Prompt-only jobs carry none.
- **Declared generation wait.** `backend_defaults.history_timeout_seconds` extends the default 120 s
  history wait for long generations (Animate-2 1,200 s; TI2V-5B 1.1.0 600 s — its 81-frame run used
  ~100 s of the 120 s default on the old runtime). `@1.0.0` stays byte-identical.
- **UI.** A **Driving Video** field with Browse appears only for workflows that accept one; the
  Frames selector (PR-VID-190) shows each workflow's own legal lengths.

## Real Wan-Animate-2 acceptance

Three jobs queued before the first dispatch through the canonical controller → NJR → JobService →
SQLite → `run_njr` path on the managed v0.37.0 runtime, run back to back, **no manual kill**; same
neutral full-body reference image; the driving clip is the exact qualified
`B_locomotion_driving_39f_candidate.mp4` (sha256 `d761eb58…`, frozen and recorded at admission).

| Job | Workflow | Frames | Result | Owned PID | Released | Wall | Min free RAM | VRAM peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | prompt motion | 41 | COMPLETED 41 f / 1.71 s | 9120 | yes | 96.7 s | 15.6 GB | 11,606 MiB |
| B | prompt motion | 81 | COMPLETED 81 f / 3.375 s | 42004 | yes | 213.3 s | 15.4 GB | 11,531 MiB |
| C | driving video | 41 | COMPLETED 41 f / 1.71 s | 31260 | yes | 167.5 s | 15.4 GB | 11,563 MiB |

Outputs verified with `ffprobe` (480×832, 24 fps, exact frame counts). GPU idle and endpoint free
after every job; no retry, no device-loss sign; replay of A kept lineage, frame count and seed.
81 frames therefore fits; the accepted envelope stays 17–81.

**Defect found and fixed during acceptance.** Job C's recorded primary artifact was the *driving
clip*: ComfyUI v0.37.0's `LoadVideo` reports a preview of its input as a history output with
`type: "input"`, and the backend treated every non-`temp` descriptor as a generated result. The
backend now accepts only `type: "output"` descriptors (regression test added). A single real re-run
of job C (`reports/vid191_animate2_drive_fix/`, PID 43176 released) recorded only the generated
clip and no longer copied the driving clip into the run folder.

**Post-run workstation events (2026-09-29 ET).** The final driving-video rerun finished at about
08:33 with a generated 41-frame MP4, the owned Comfy process released, and the endpoint free.
Windows later recorded display watchdog `LiveKernelEvent 141` and `1b8` reports at about 08:42,
followed by an unexpected shutdown at 08:49; a separate `141` report occurred at 15:02. No
StableNew/Comfy generation is evidenced at either event. These events do not turn the completed jobs
into failures or establish a Comfy cause; they also do not establish workstation display stability.
The desktop ComfyUI upgrade remains gated on the owner's stability decision.

**Visual observations (agent, not the owner's verdict):**

- **A (prompt, 41 f):** clean prompt-directed motion — she raises her right hand, waves and lowers
  it; identity, anatomy and background stable; single figure.
- **B (prompt, 81 f):** a clear raise-and-lower of both arms during roughly the first 2 s, then
  mostly standing; the prompted turn-and-walk did not occur. No temporal collapse. Motion here is
  concentrated early rather than continuing through the longer clip.
- **C (driving video, 41 f): duplicate-figure artifact.** A second, near-identical figure appears in
  every frame: one performs the driving clip's high-knee drill while another stands beside it. The
  qualified PR-VID-184R/S runs had zero ghost frames. The most likely cause is a deviation from the
  qualified graph made in this package: the qualified graph fed `positive_pose` a separate
  motion-only description (node 612), whereas this spec leaves `positive_pose` unconnected so it
  defaults to the main (appearance/scene) prompt. Other differences are geometry (480×832 here versus
  the qualified 480×848 derived from the driving clip) and seed. This is one sample; driving-video
  mode is exposed as experimental with this known issue, and restoring the qualified separate
  motion prompt is the recommended next step.

## Validation

- `tests/video/test_pr_vid_190_wan_animate2.py` (23, including input previews never treated as
  artifacts): experimental specs with the accepted model set
  and policies; opt-in required; qualified sampling settings; node-level parity with the real
  qualified flat graph (when present); 41-frame default and legal envelope; prompt mode takes no
  driving video and hides the field; driving mode declares the neutral pose-video control; other
  workflows hide it; prompt admission records no driving video; driving mode requires one; supplied
  video frozen with its hash and never modified; invalid path/extension rejected before admission;
  prompt-only workflow refuses a driving video; missing `--disable-pinned-memory` refused before any
  start; unverifiable external runtime refused with nothing staged; prompt job releases the runtime
  and records no driving video; driving video staged as a copy with provenance; a source changed
  after queue admission is refused before upload or dispatch; compiled length and geometry; three
  queued Animate-2 jobs through the real queue; declared generation waits.
- Focused PR review repair (no GPU): 60 tests passed across the Animate-2 and PR-VID-190 lifecycle
  modules on Python 3.12.14; controller/registry checks had 10 passed and 8 GUI skips because local
  Tcl is unavailable. Ruff on the changed Python files (`--no-cache`) and `git diff --check` passed.
  The local PR gate reported the known tooling blocker: mypy and the Ruff executable are absent
  from this environment; required Python 3.11/3.12 CI remains pending. The repair checks the
  admission-frozen driving-video SHA-256 immediately before any Comfy upload and leaves the
  qualified graph, runtime command, model paths, and existing hardware results unchanged.
- GUI: Driving Video field shown/hidden per workflow, state round-trip.
- Regression vs clean `origin/main`: no new failures in video/controller/services/queue and the video
  queue integration tests.

## Next steps (owner decisions)

1. Owner real-world evaluation of both Animate-2 modes through the Video Workflow tab.
2. Driving-video mode: restore the qualified separate motion prompt (`positive_pose`) and re-check
   for the duplicate-figure artifact with one run.
3. Once this runtime has proven stable in real use: upgrade the desktop ComfyUI app to the newest
   release (the owner does not use it outside StableNew), then re-point and re-verify the managed
   runtime on it, keeping `--disable-pinned-memory` and the StableNew-owned runtime folders.
4. The qualification install now doubles as the production runtime; it must not be deleted until
   step 3 replaces it.

## Execution profile and validation plan

**Execution Profile + Model/Reasoning Recommendation:** Standard, bounded video-backend and
controller work with file provenance and managed-process boundaries. Use a frontier-capable coding
model (GPT-6 Astra) at medium reasoning for implementation and focused verification; raise reasoning
for security or architecture review if evidence exposes a boundary change. The extra review capacity
reduces expected retries and costly hardware re-verification compared with selecting solely by
nominal model cost.

**Token-Efficient Validation Plan:** Check the exact stacked SHA and scoped diff; run the focused
Animate-2, PR-VID-190 lifecycle, and GUI/controller tests after relevant source edits, then Ruff,
mypy on changed modules, and `git diff --check`. Reuse the completed seven-clip v0.37.0 hardware
evidence while the graph, runtime configuration, and model files remain unchanged. Required Python
3.11/3.12 CI and the triggered security review remain PR gates; no additional GPU job is needed for
the admission-hash repair.

## Architecture boundaries

`ComfyProcessManager` remains the sole managed-Comfy lifecycle authority; the runtime change is
configuration only. No second queue, runner, history, compiler or process authority; no external
runtime adopted, stopped or rewritten; no readiness threshold lowered; no job auto-replayed; no
model downloaded or moved. **Controller Surface Assessment:** the Video Workflow controller gains
only driving-video validation and path/hash freezing (mirroring seed/frame count); it acquires no
process lifecycle.
