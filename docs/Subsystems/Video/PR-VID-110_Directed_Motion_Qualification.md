# PR-VID-110 — Directed-Motion Local Backend Qualification

Status: qualification evidence; **not an integration**. Lane A (Wan2.2 TI2V-5B) and the
reference-only half of Lane B (Wan2.1 VACE-1.3B) were physically qualified, and Lane A
was repeated on operator-supplied media. The Lane B control-video (motion-transfer)
comparison is **on HOLD**: the GPU was lost mid-run (section 9) and it needs a reboot.
Nothing here registers a production backend, workflow, catalog entry, GUI field, NJR
schema change, or runner/queue change.

## 1. Question and bar

What local/open technology should follow native SVD for materially directed human/body
motion on the supported machine? A candidate must (a) complete on the hardware, (b) show
materially more real body motion than the accepted native-SVD baseline (>= 1.5x by the
metric below), (c) score >= 3/5 on identity, face, limb anatomy, temporal coherence and
prompt/action adherence, and (d) have a reasonable footprint (<= 20 min for a ~2 s clip,
VRAM headroom >= 300 MiB). Executing is not enough. The rule is coded in
`tools/qualification/vid110/evidence.py::decide` and unit-tested.

## 2. Host and runtime

| Item | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 4070 Ti, 12,282 MiB, driver 616.92 |
| CPU / RAM | Intel i9-13900K, 31.8 GB (operator apps resident: ~22-24 GB free at run start) |
| OS | Windows 11 Home 10.0.26100 |
| ComfyUI | 0.3.65, PyTorch 2.8.0+cu129, Python 3.10.6, stock nodes only |
| Free disk (models volume) | 164 GB before, ~143 GB after (22.7 GB of weights added) |

Runtime ownership: the operator's external ComfyUI (port 8000) was inventoried through its
public API. It could not sample: its stderr handle appears broken (the process that launched it
no longer exists), so every `KSampler` node raised `OSError [Errno 22]` from the progress-bar flush
(reproduced with both `uni_pc` and `euler`). It was not touched (no restart or
reconfiguration; one `POST /free` released the model memory this work had loaded). Runs
therefore used a **qualification-owned** ComfyUI on port 8199 launched from the same
install/venv with `--disable-all-custom-nodes` and scratch input/output/temp/user
directories (`tools/qualification/vid110/owned_comfy.py`); only that spawned process was
ever stopped. The operator's A1111/StableNew were closed by the operator beforehand so the
GPU was dedicated (idle baseline ~0.8 GB).

## 3. Candidate facts and pinned files (stock-Comfy evidence class)

| File | Repo @ revision | SHA-256 | Bytes |
|---|---|---|---|
| wan2.2_ti2v_5B_fp16.safetensors | Comfy-Org/Wan_2.2_ComfyUI_Repackaged @ c4f60d30c55a624e35427060fdd217579a6c1d77 (Apache-2.0) | 456f901338bd9ead...fcaeca1e | 9,999,658,848 |
| wan2.2_vae.safetensors | same | e40321bd36b97099...ed156 | 1,409,400,960 |
| umt5_xxl_fp8_e4m3fn_scaled.safetensors | same | c3355d30191f1f06...4f68 | 6,735,906,897 |
| wan2.1_vace_1.3B_fp16.safetensors | Comfy-Org/Wan_2.1_ComfyUI_repackaged @ 617a7633e636506f850e043bc4605f290a466a8e (Apache-2.0) | 640ccc0577e6a5d4...84f2 | 4,309,519,800 |
| wan_2.1_vae.safetensors | same | 2fc39d31359a4b0a...976b | 253,815,318 |

All hashes were verified against the Hugging Face LFS object IDs before installation into
`E:\Users\rober\ComfyUI\models\{diffusion_models,text_encoders,vae}`. Total added:
22.7 GB. To remove them: delete those five files. Full 64-hex digests are in the local
`reports/vid110/model_manifest.json` and the per-run JSON.

Workflows use only stock nodes (`Wan22ImageToVideoLatent`, `WanVaceToVideo`,
`TrimVideoLatent`, `KSampler`, `CreateVideo`, `SaveVideo`, ...); no community node, GGUF or
quantised path was used, so all numbers below are stock-Comfy evidence.

## 4. Test inputs

- **Source still**: a neutral full-body still made locally by Wan2.2 TI2V-5B text-to-video
  (seed 110110, 480x832, first frame; prompt in `session_a.py`). No independent full-body
  image was available (the operator's A1111 was closed and the operator's existing outputs
  are not suitable). It carries Wan-typical background artifacts and gives the Wan2.2 lane a
  home-field identity advantage; treat identity scores accordingly.
- **Directed-action prompts** (2 s, 49 frames, seed 12345, 480x832): *walk_wave* ("walks toward
  the camera ... then stops and waves the right hand") and *turn_raise_arms* ("turns to face
  left, then raises both arms above the head and lowers them"), static camera.
- **SVD baseline**: metrics only, from the six most recent accepted native-SVD clips
  (`output/SVD`, 56 frames @ 28 fps, 576x1024). They were not viewed and are not the same
  source image, so this is a per-pixel-motion reference, not a paired comparison.
- **Operator-supplied media (session C)**: one owned still of a person standing outdoors
  and one owned barbell-lift clip. The still was upright-corrected and centre-cropped to
  480x832; the clip was cut to 49 frames at 24 fps, 480x832 (start 5.2 s). The
  prompt was "bends at the hips and knees, grips a barbell on the ground with both hands, and
  lifts it while standing up straight". These files and their outputs stay in the
  git-ignored `reports/vid110/` and are not committed or described further. An earlier
  candidate folder of prior SVD outputs was declined as source/driving media.

## 5. Measured results

`local_motion_px` = mean per-frame optical-flow residual (Farneback at 256 px width, global
camera translation removed). SVD baseline = **0.1225**.

| Run | Wall | Peak VRAM (whole GPU) | Min free RAM | local_motion | vs SVD | identity (hist) |
|---|---|---|---|---|---|---|
| Wan2.2 TI2V-5B T2V source (5 frames, cold load) | 42 s | 11,275 MiB | 2.4 GB | - | - | - |
| Wan2.2 I2V walk_wave | 60 s | 11,577 MiB | 5.7 GB | 0.567 | 4.6x | 0.955 |
| Wan2.2 I2V turn_raise_arms | 56 s | 11,548 MiB | 6.4 GB | 0.484 | 3.9x | 0.919 |
| VACE-1.3B reference-only walk_wave | 217 s | 11,562 MiB | 10.4 GB | 0.390 | 3.2x | 0.014 |
| VACE-1.3B reference-only turn_raise_arms | 205 s | 11,086 MiB | 13.2 GB | 0.352 | 2.9x | 0.006 |
| Wan2.2 I2V operator still, barbell prompt (session C) | 147 s | 11,690 MiB | 0.05 GB (cold load) | 3.98 | 32x (inflated, see below) | 0.644 |

Peak VRAM includes models cached from the previous run in the same process, so it is a
ceiling, not a minimum. The first (cold) load of the 10 GB UNet + text encoder drove system
RAM to ~0.01 GB free once (Windows mmap paging; the machine stayed up). The first attempt
was aborted by an over-strict 0.4 GB guard and repeated with a sustained-low-RAM guard
(<0.25 GB for 30 s); the repeat completed. Camera drift was negligible in all runs
(< 0.5 px/frame). The optical-flow metric under-reads large, coherent motion (VACE walks
toward the camera visibly more than Wan2.2), so the visual scores decide direction and
the metric only screens for "any real body motion".

Visual scorecard (0-5; recorded in `tools/qualification/vid110/scorecard.py`):

| Run | identity | face | limbs | temporal | prompt/action | computed verdict |
|---|---|---|---|---|---|---|
| Wan2.2 walk_wave | 4 | 4 | 2 | 3 | 2 | NO-GO (limbs, prompt) |
| Wan2.2 turn_raise_arms | 4 | 4 | 3 | 3 | 3 | PASS |
| VACE walk_wave | 1 | 4 | 4 | 4 | 5 | NO-GO (identity) |
| VACE turn_raise_arms | 1 | 3 | 3 | 3 | 4 | NO-GO (identity) |
| Wan2.2 operator still, barbell prompt | 4 | 3 | 3 | 3 | 4 | PASS (motion ratio inflated) |

Observations. Wan2.2: the wave and the arms-overhead motion happen with the source person,
clothing and framing preserved; the requested walk and turn do not happen (the body stays
put), and the waving hand renders with a red colour cast. VACE reference-only: it follows the
action prompts strongly (a clear walk toward the camera plus a wave; a profile-to-front turn
plus an arm raise) with cleaner rendering, but it generates a different person (face, skin,
hair, shoes), i.e. the reference image is only weakly bound, and one clip changes sleeves
mid-way. Both ran on stock nodes with no crash.

Session C (operator media, Wan2.2 only): the person bends, grips a barbell and stands up lifting
it, as prompted, with the same person and clothing throughout (identity histogram 0.64,
lower than the studio still because the outdoor scene is far busier). The face is soft
and blotchy mid-clip, saturation rises with a pink cast late, the camera tilts up in the last
third so the background changes (drift 3.6 px/frame, motion-area fraction 0.96), and the
barbell has a plate on one end only. Because that tilt is scene motion, the 32x
ratio over SVD overstates body motion; the visual score, not the ratio, carries this
result. The clip's motion curve correlates at r = -0.20 with the driving clip, which is expected:
Wan2.2 I2V only sees the text prompt, not the driving video, so this run measures prompt-directed
motion, not motion transfer. Cold-load free RAM again dipped to ~0.05 GB and the machine stayed up.

## 6. Verdicts

| Candidate | Result | Reason |
|---|---|---|
| **Wan2.2 TI2V-5B** (stock Comfy, fp16) | **CONDITIONAL** | Completes in ~1 min per 2 s clip on the 12-GB card; materially more body motion than SVD and keeps the source identity; gesture-level prompts work, locomotion/turn prompts did not; VRAM peaks at ~11.6 of 12.3 GiB (little headroom); RAM-tight cold load; artifacts at 480x832. |
| **Wan2.1 VACE-1.3B** reference-only | **NO-GO** as identity-preserving I2V; **motion-transfer HOLD** | Strong prompt direction and clean output but the reference identity is not preserved. Its real value (control-video motion transfer) is still untested: the one control-video run (Canny of the operator's clip) was cut short by the GPU loss in section 9. This is not a NO-GO for the control lane. |
| SCAIL-2 / Wan Animate 2 | **Not qualified (deferred)** | Official Comfy repacks are 14B: smallest weights 16.65 GB (int8_convrot) / 17.7 GB (fp8), and the 11 GB nvfp4-mix targets Blackwell FP4, which Ada lacks. With 12 GB VRAM and ~32 GB RAM shared with the operator's applications there is no credible stock path; community GGUF would be a separate, pinned evidence class, and both need a driving clip anyway. |
| HunyuanVideo-1.5, LTX-2.5, Wan 3.0/2.6/2.7, MiniMax H3, CogVideoX | **Deferred per brief** | Official runtime/VRAM floors, hosted-only, licensing/territory, or no evidence of an advantage over the Wan candidates; no new evidence changed that. |
| Native SVD | Reference baseline | Accepted; per-pixel motion 0.1225 on the sampled clips. |

## 7. Architecture implications and recommended follow-on

- The generic `ComfyWorkflowVideoBackend` seam is sufficient: both Wan lanes ran as plain
  stock-node API graphs. No new production Comfy node is required for these two candidates.
- Nothing in the qualification touched the NJR schema, JobService, queue, runner or catalogs;
  `tests/tools/test_vid110_qualification.py` guards that none of these models/workflows
  appears in `src/`.
- Any integration needs product-owner decisions this package does not make: whether gesture-level
  directed motion from a still (Wan2.2 TI2V-5B) is worth an opt-in experimental workflow given
  the VRAM/RAM tightness; whether identity-preserving directed motion requires the motion-transfer
  lane (VACE with a control video, or a 14B Animate/SCAIL path that this hardware may not run);
  and how a queued job should surface a RAM-hungry cold load and an external-Comfy readiness
  problem (the broken-stderr failure above is an operational hazard for any Comfy-backed video job).
- Recommended next step: reboot, confirm `nvidia-smi` sees the GPU, then re-run the VACE
  control-video comparison only (`python -m tools.qualification.vid110.session_c`; the finished
  Wan2.2 run is cached and will not repeat). Stock `Canny` control first; a pose
  preprocessor would be a separate pinned custom-node class. Then decide between "Wan2.2
  experimental workflow" and "wait for a motion-transfer path".

## 8. Reproduction and evidence

Local only, GPU-bound, never in CI: `python -m tools.qualification.vid110.session_a`, then
`session_b`, then `session_c` (which needs operator media at the paths named in the module;
all need the GPU free and the five model files above). Deterministic tests
cover inventory, workflow structure, evidence serialization, scoring inputs, the verdict
rule and the no-production-registration guarantee. Raw evidence (per-run JSON, videos,
contact sheets, model manifest, owned-Comfy log) is under the git-ignored
`reports/vid110/`.

## 9. Incident: GPU lost during the VACE control-video run

While the owned Comfy was sampling the VACE-1.3B Canny-control run (25 steps at 5-7 s/it), the
client got `ConnectionResetError 10054` and the owned process disappeared. Afterwards
`nvidia-smi` reported "Unable to determine the device handle for GPU0: 0000:01:00.0: GPU is lost.
Reboot the system to recover this GPU". The operator's external Comfy on port 8000 began
returning HTTP 500. RAM was healthy (about 22 GB free), the System event log showed no
nvlddmkm/TDR entry (only an unrelated DCOM 10016), and the Wan2.2 run immediately before it had
finished cleanly. The cause is **unproven** (a driver/device fault under sustained 12-GB load is
one candidate; no other has been ruled in or out). Per the brief, all GPU work stopped without an
automatic retry, and nothing on the machine was restarted or reconfigured. The control-video
comparison remains incomplete and produces no verdict.
