# PR-COMFY-RUNTIME-100 — Reproducible managed ComfyUI runtime

Status: IMPLEMENTED / PHYSICALLY QUALIFIED / UNDER OWNER REVIEW; NOT MERGED TO `main`. Owner of the boundary: `config/managed_comfy_runtime.json`,
`constraints/comfy-windows-py313-cu130-v0.38.0.txt`, `scripts/bootstrap_managed_comfy_windows.ps1`,
`tools/runtime/verify_managed_comfy.py`. Operator procedure: `docs/runbooks/managed_comfy_runtime.md`.

## Objective and boundary

Replace the machine-local qualification ComfyUI (v0.37.0 on a Python 3.11 environment assembled by hand) with a
reproducible, StableNew-owned managed runtime: ComfyUI stable `v0.38.0` on an official standard-GIL CPython
3.13.x, CUDA 13.0, Torch `2.14.0+cu130` (retained), a clean Comfy core with no custom nodes, exact
repo-owned constraints, StableNew-owned input/output/temp/user folders, existing model libraries referenced and
never copied, and `--disable-pinned-memory` preserved.

Unchanged and not reopened: the canonical path
`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History`;
`ComfyProcessManager` as the only lifecycle authority (it launches only a free endpoint and stops only a
process it started; no process-name kill, no adoption); the StableNew application runtime (CPython 3.14,
`constraints/windows-py314-cu130.txt`, PR #33), which shares no venv, package, constraint or bootstrap with
this runtime; external Comfy (desktop app), A1111 and Forge, which are neither owned nor modified; the model
files and their sha256 identities; workflow graphs and operator controls; the readiness floors.

## Authorities

| Concern | Authority |
|---|---|
| Installation identity (release, commit, Python minor, Torch build, loopback + required flags, custom-node policy) | `config/managed_comfy_runtime.json` |
| Exact package versions (the complete installed set, 85 pins) | `constraints/comfy-windows-py313-cu130-v0.38.0.txt` |
| Build | `scripts/bootstrap_managed_comfy_windows.ps1` (own script; never the application bootstrap) |
| Read-only verification and launch command | `tools/runtime/verify_managed_comfy.py` |
| Lifecycle | `src/video/comfy_process_manager.py` (unchanged) |
| Workflow graphs, model hashes, controls, floors, qualification provenance | the workflow catalog |

The contract owns installation identity only; it contains no workflow fact. The bootstrap clones the exact tag,
requires `HEAD` to equal the pinned commit before installing, constrains every `pip install`, runs `pip check`
and the verifier, and refuses a drive-root/repository-root install, a non-3.13/free-threaded/JIT interpreter,
a reused wrong-interpreter venv, and a `-Recreate` of anything it did not create. It downloads no model,
installs no custom node, and starts, stops and touches no process. The verifier additionally treats an
installed-but-unpinned distribution as drift (this runtime carries exactly its constraints).

## Method

Two disposable candidates were built through the new bootstrap, so the interpreter change and the release
change were separated:

* **Candidate A** — ComfyUI v0.37.0 (`73c9bad4…`) on Python 3.13.16 with the *accepted* package set. Its 86
  installed packages are identical to the accepted v0.37.0/Python 3.11 qualification environment: only the
  interpreter moved.
* **Candidate B** — ComfyUI v0.38.0 (`6b747c04…`) on the same Python 3.13.16, Torch `2.14.0+cu130`, the same
  model libraries and the same graphs. This is the final runtime (85 packages).

### Dependency differences (A to B)

| Class | Packages |
|---|---|
| Required by v0.38.0's own `requirements.txt` | `comfy-kitchen` 0.2.35 to 0.2.36; `comfyui-frontend-package` 1.52.7 to 1.53.6; `comfyui-workflow-templates` 0.11.66 to 0.11.70 |
| Transitive of those pins | `comfyui-workflow-templates-core` 0.3.357 to 0.3.361; `-json` 0.1.92 to 0.1.96; `-media-assets-01` 0.1.47 to 0.1.48; `-media-assets-02` 0.1.3 to 0.1.6 |
| No longer required by v0.38.0 | `torchaudio` (not installed; nothing in the Comfy source imports it) |
| Unrelated drift | none — the other 77 packages, Torch/torchvision `+cu130`, `numpy`, `av`, `safetensors`, `aiohttp` and the resolver are identical |

### Node and API schema comparison

`/object_info` grows from 960 to 964 nodes. All 22 node classes used by the registered Wan workflow versions
(including `WanAnimate2ToVideo` with `positive_pose`, pose strength/window and reference strength,
`LoadVideo`, `GetVideoComponents`, `ResizeImageMaskNode`, `Wan22ImageToVideoLatent`, `SaveVideo`) have
identical input types, defaults, options and outputs. The only surface changes are 18 cloud-API provider
nodes (ByteDance, OpenAI, Claude, Quiver, `ImageColorSpace`), five added and one removed, none used. The
Animate-2 control ranges and defaults still match the real v0.38.0 `WanAnimate2ToVideo` source
(`tests/video/test_pr_vid_192_animate2_controls.py` with `STABLENEW_VID184_COMFY_SOURCE`). A source diff of the
Wan execution path shows why output is not bit-identical: the Wan attention call path moved to
`ComfyAttention`/`AttentionTensorContainer`, and AdaLN modulation uses the fused `comfy_kitchen` `adaln`
kernel for large CUDA tensors.

## Physical evidence

At most three deliberate generations ran, all through the canonical controller to NJR to `JobService` to
`run_njr` path with a StableNew-owned process, `--disable-pinned-memory`, per-job release and the unchanged
readiness floors. Same reference image (`source_fullbody.png`), same driving clip (sha256 `d761eb58…`),
seed `19103` for Animate-2 and `19001` for TI2V.

| Run | Runtime | Workflow | Frames / geometry | Wall | Peak VRAM (baseline) | Min host RAM | Peak temp / power | Result |
|---|---|---|---|---|---|---|---|---|
| A | v0.37.0, Python 3.13 | `wan_animate2_drive_i2v_v1@1.1.0` | 41 / 480x832 @ 24 fps | 176.8 s | 11,532 MiB (716) | 14.23 GB | 80 C / 253 W | generation completed; see note |
| B | v0.38.0, Python 3.13 | `wan_animate2_drive_i2v_v1@1.2.0` | 41 / 480x832 @ 24 fps | 190.8 s | 11,538 MiB (401) | 14.27 GB | 81 C / 255 W | COMPLETED |
| C | v0.38.0, Python 3.13 | `wan22_ti2v_5b_i2v_v1@1.2.0` | 49 / 480x832 @ 24 fps | 63.2 s | 11,386 MiB (386) | 16.91 GB | 76 C / 257 W | COMPLETED |

Accepted comparators (PR-VID-191, v0.37.0 on Python 3.11): Animate-2 driving, 41 frames, 167.5 s, 11,563 MiB,
15.4 GB; TI2V, 49 frames, 59.5 s, 11,820 MiB, 17.0 GB. Run A used `@1.1.0` and Run B `@1.2.0` because the two
graphs are hash-identical (pinned by test), so A/B differ only in the runtime; running both on `@1.0.0` would
not have exercised the shipped version. Runs B and C record the serving runtime in their manifest and
container metadata (`actual_runtime`: ComfyUI 0.38.0, Python 3.13.16, Torch 2.14.0+cu130, frontend 1.53.6).

**Run A note.** Comfy's history reported success, the clip is valid and was preserved from Comfy's own output
folder, and the owned runtime was released with the endpoint free and the GPU back to idle. StableNew then
failed to copy that file into the scratch run directory because my harness directory sat under a ~170
character path and the destination exceeded the Windows 260-character limit (a scratch-location defect, not a
product behavior); its scratch job row therefore reads `failed` and carries no `actual_runtime`. Runs B and C
used a short directory. The generation was not replayed. Candidate A's identity was recorded separately by the
ownership probe (ComfyUI 0.37.0, Python 3.13.16, Torch 2.14.0+cu130). Before the three runs, readiness refused
dispatch cleanly three times (available RAM 15.5 to 15.8 GB after Comfy loaded, against the unchanged 16 GB
cold-load floor) while the desktop held host RAM; nothing was queued, no GPU work occurred, and the floor was
not changed. Every run was clean: no GPU/display/CUDA event, owned release, endpoint free, no orphan process,
GPU memory back to ~0.4 GB. These are three more clean exposures, not evidence that the workstation's
black-screen history is resolved.

Model identity is runtime-independent and unchanged: all six pinned files (the TI2V UNet/VAE and the four
Animate-2 files, including the copies present in both model libraries) hash to their catalog sha256, checked
before the candidates ran and again after the runs. No model was downloaded, copied or upgraded.

### Output comparison (Run A vs Run B)

Same graph, models, source, driving clip, seed, controls, geometry and frame count.

* Container: both H.264 High, yuv420p, 480x832, 24 fps, 41 frames, 1.708 s. Hashes differ (not bit-identical).
* Pixel agreement: per-frame PSNR mean 17.8 dB (15.9 to 20.0), mean absolute difference 10.7/255. Not
  numerically negligible; expected from the changed attention and AdaLN kernels.
* Motion: motion-energy ratio B/A 0.95, per-frame motion curve correlation 0.90; StableNew's `clip_metrics`
  local motion 1.58 to 1.48 px, camera drift 0.002 to 0.002 px, motion-area fraction 0.233 to 0.233,
  temporal jitter 0.69 to 0.85 (a single sample each; no threshold exists for it).
* Visual inspection of the contact sheets: the same character, framing, background and high-knee drill
  progression, including the *same* known duplicate-subject artifact of the default-control graph
  (PR-VID-191/192) in both clips; differences are fine rendering and some limb positions.
* Classification: **not bit-identical; visually equivalent; no material quality-changing difference**
  attributable to the release. This is one sample per runtime. The clips and metrics are retained machine-local
  for owner inspection. Same-runtime reproducibility was already shown pixel-identical in PR-VID-184S, so the
  difference is the release, not run-to-run noise.

Run C (TI2V on v0.38.0) matches the accepted behavior: the subject turns her head and waves as prompted with
identity and framing preserved, 49 frames at 24 fps (valid H.264), VRAM within about 430 MiB below the accepted
peak and host RAM within 0.1 GB of it.

### Resource gate

Passed. Peak whole-GPU VRAM is 11.4 to 11.5 GB of 12.28 GB (A and B within 6 MiB of each other); minimum host
RAM is 14.2 GB for both Animate-2 runs, set by the desktop's baseline, with no new exhaustion pattern;
wall time varies by +8 % (B vs A) and +14 % (B vs the accepted run) for Animate-2 and +6 % for TI2V, within the
accepted run-to-run range. No readiness floor changed, pinned memory stays off, the owned runtime is released
after every job, and no orphan process or GPU residency remained. Starting Comfy costs about 1.9 GB of host
RAM before the readiness check, the same for v0.37.0 and v0.38.0, so a cold Wan load still needs about 18 GB
available at the moment of launch.

## Reproducibility

Candidate B was rebuilt from nothing with `-Recreate` under the final constraints and no overrides: the
installed set is identical to the first build, `pip check` is clean, the source tree is pristine at the pinned
commit, and `-CheckOnly` passes. Drift is detected in both directions on the real install (a stray
`six` package; `numpy` 2.4.5 against the pinned 2.4.6) and restored. The bootstrap needs an official
standard-GIL CPython 3.13 and network access only for the pinned tag and the pinned packages; nothing is
resolved from a mutable ref, and no hidden desktop-app dependency exists (models are referenced through
`extra_model_paths.yaml`).

## Workflow versioning

`wan22_ti2v_5b_i2v_v1`, `wan_animate2_prompt_i2v_v1` and `wan_animate2_drive_i2v_v1` gain `1.2.0`: the `1.1.0`
graph, model hashes, controls, frame policy, launch requirement and readiness floors, with only version
identity and qualification provenance changed (`comfyui_version` 0.38.0 and its commit). `1.0.0` and `1.1.0`
remain registered, byte-identical (spec and template hashes are pinned in
`tests/video/test_pr_comfy_runtime_100_workflow_versions.py`) and keep their historical provenance; the UI
offers the newest version and older jobs still resolve and replay. Governance stays `experimental` with
per-job opt-in.

## Machine-local production promotion

After Candidate B was accepted, only the machine-local managed-Comfy configuration was repointed: the
operator checkout's uncommitted `presets/settings.json` now carries the managed install's command and
`comfy_workdir`, with `--disable-pinned-memory` and the port matching `comfy_base_url`. The previous file is
kept beside it as `settings.json.before-pr-comfy-runtime-100`. It was launched once through the real
`ComfyProcessManager` (free endpoint, owned, 9.8 s start, healthy, ComfyUI 0.38.0 / Python 3.13.16 / Torch
2.14.0+cu130 / frontend 1.53.6, all nine registered workflow versions dependency-ready), stopped through the
manager, and the endpoint was free with no orphan. The v0.37.0 qualification install is untouched and remains the
rollback. Nothing owner-specific is committed; the repository default `presets/settings.json` is unchanged.

## Not changed

The StableNew application runtime and its constraints; any external/desktop Comfy, A1111 or Forge; model
files; graphs, controls, quality settings and readiness floors; the queue, runner, history, compiler and the
only lifecycle authority; still-image Comfy (PR-IMG-COMFY-100 and PR-IMG-FORGE-100 are not started).
