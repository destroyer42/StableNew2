# PR-VID-110 — Directed-Motion Local Backend Qualification

Status: qualification evidence; **not an integration**. Lane A (Wan2.2 TI2V-5B) and both
halves of Lane B (Wan2.1 VACE-1.3B: reference-only and Canny control-video motion
transfer) were physically qualified, the pair on operator-supplied media. A GPU loss
interrupted the first control-video attempt; the repeat after a reboot completed
(section 9 records the incident and the investigation). Outcome: Wan2.2 CONDITIONAL,
VACE NO-GO on identity in both modes, motion-transfer fidelity itself good.
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
  (a young child) and one owned barbell-lift clip (a side-on adult deadlift in a gym), so
  the driving body and the source body differ in size and proportions. The still was upright-corrected and centre-cropped to
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
| VACE-1.3B Canny control from the operator clip (session C) | 221 s | 11,749 MiB | 6.05 GB | 0.644 | 5.3x | -0.069 |

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
| VACE Canny control, operator clip | 1 | 2 | 3 | 3 | 3 (+ driving fidelity 4) | NO-GO (identity, face) |

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

VACE control-video (session C, repeated after the reboot): the output follows the driving lift
(hinge, grip, pull; motion-curve correlation with the driving clip r = 0.82, camera static,
drift 0.004 px/frame), so motion transfer itself works on stock nodes at 480x832 in 221 s.
It does not carry the source identity: Canny edges of the whole driving frame bring the gym,
the framing and an adult silhouette, so a different, older-looking person in the driving
clip's red top appears instead of the source child (identity score 1; the histogram proxy is
-0.07). A pink toy-face object shows up under a kettlebell-like weight and turns into
barbell plates in the last frames, and the person is still bent at the end of the 2 s
window. The two runs had a single seed, one control strength (1.0) and one source/driving
pair; a lower control strength, a body-only mask or a pose (skeleton) control would be the
levers to try, but those are tuning or a separate pinned custom-node evidence class, so they
are recorded as follow-on rather than run here. Peak GPU temperature was 84 C at up to 260 W;
the driver reported a power-cap throttle bit (0x4) and an unnamed 0x400 bit, with the
graphics clock never below 2,775 MHz while busy (`*_telemetry.csv` beside each run).

## 6. Verdicts

| Candidate | Result | Reason |
|---|---|---|
| **Wan2.2 TI2V-5B** (stock Comfy, fp16) | **CONDITIONAL** | Completes in ~1 min per 2 s clip on the 12-GB card; materially more body motion than SVD and keeps the source identity; gesture-level prompts work, locomotion/turn prompts did not; VRAM peaks at ~11.6 of 12.3 GiB (little headroom); RAM-tight cold load; artifacts at 480x832. |
| **Wan2.1 VACE-1.3B** (reference-only and Canny control) | **NO-GO** as identity-preserving I2V and as stock-Canny motion transfer; motion fidelity itself is good | Strong prompt direction and clean output but the reference identity is not preserved. Control-video motion transfer (Canny of the operator's clip) follows the driving motion well (r = 0.82, 4/5) but also replaces the source person and scene (identity 1/5), so it is a NO-GO as identity-preserving directed motion with stock Canny control. Pose-only control, control-strength tuning and masking were not tried. |
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
- Recommended next step (product-owner decision): choose between (a) an opt-in experimental
  Wan2.2 TI2V-5B prompt-directed workflow (identity kept, gesture-level motion, ~1-2.5 min per
  2 s clip, near the 12-GB ceiling) and (b) waiting for a motion-transfer path that keeps
  identity. For (b) the untried levers are a pose-skeleton control (a separate pinned
  custom-node evidence class), a lower control strength or a person mask on VACE, and the
  14B Animate/SCAIL family on hardware with more memory. Stabilising the workstation
  (section 9) should come first for either choice.

## 8. Reproduction and evidence

Local only, GPU-bound, never in CI: `python -m tools.qualification.vid110.session_a`, then
`session_b`, then `session_c` (which needs operator media at the paths named in the module;
all need the GPU free and the five model files above). Deterministic tests
cover inventory, workflow structure, evidence serialization, scoring inputs, the verdict
rule and the no-production-registration guarantee. Raw evidence (per-run JSON, videos,
contact sheets, model manifest, owned-Comfy log) is under the git-ignored
`reports/vid110/`.

## 9. Incident: GPU lost during the VACE control-video run, and investigation

What happened. While the owned Comfy was sampling the first VACE Canny-control attempt (25 steps
at 5-7 s/it, straight after a 147 s Wan2.2 run), the client got `ConnectionResetError 10054` and
the owned process disappeared. `nvidia-smi` then reported "GPU is lost. Reboot the system to
recover this GPU"; the operator's Comfy on port 8000 returned HTTP 500. Windows itself stayed up
and there was no bugcheck, TDR, `nvlddmkm` or WHEA entry for the moment; the operator had to
reset the machine (Kernel-Power 41 at boot, previous shutdown 08:19). A WPF app
(`MicrosoftSecurityApp.exe`) crashed at 08:10:34, when the GPU dropped. The identical graph and
settings then completed after the reboot (221 s, 84 C peak), so the graph is not a deterministic
trigger.

What the machine's own logs show (read-only inspection; nothing was changed):

- **It predates this work.** Kernel-Power 41 (unexpected reboot) events: 2026-07-23 and 07-30 (one
  each), then 15 between 2026-09-07 and 2026-09-21 (on nine separate days). The qualification's
  first GPU run was at 07:09 on 9/21, so 14 of those 15 reboots (all but this incident's) predate it.
- **Two DPC_WATCHDOG_VIOLATION bugchecks** (0x133, argument 1, timeout 0x1e00) on 9/9 05:51 and
  9/14 07:46 with the same argument signature.
- **17 `nvlddmkm` event-153 errors ("Error occurred on GPUID: 100")** between 9/7 and 9/15, and
  `WATCHDOG` live-kernel dumps on 9/16 06:20 and 08:07 that coincide with two of the unexpected
  power-offs (those dumps hold session/`csrss`/`dwm` state, not a driver stack).
- **`MicrosoftSecurityApp.exe` crashes cluster with the failures** (within about a minute or two of
  the unexpected shutdowns on 9/16 x2, 9/18 and 9/19, and at the moment of this GPU loss). It
  is a symptom of the display stack failing, not a cause.
- **Not implicated by the evidence:** system RAM (about 22 GB free at failure), system drive
  health (all NVMe/SSD Healthy), or VRAM overcommit alone (the successful runs used the same
  11.7 of 12.3 GiB). Volume F: (external USB) is flagged "Full Repair Needed" by NTFS after the
  hard resets; that is a consequence, and `chkdsk F: /f` is the operator's call.
- **Configuration worth knowing:** i9-13900K on an ASRock Z690-C/D5 (BIOS 16.01, 2025-10-22), two
  Micron DDR5 modules rated 5600 MT/s **configured at 6000 MT/s** (XMP/EXPO, 1.35 V), NVIDIA driver
  32.0.16.1692 (dated 2026-09-03; installed 8/30 and again 9/17), High-performance power plan.
  PSU model and 12VHPWR seating cannot be read from software.

Assessment (not proven). The failure class (silent whole-GPU loss, 0x133 with identical
arguments, no driver TDR record, many unrelated live-kernel watchdog reports, a cadence of several a week)
points at platform or power stability under sustained GPU load more than at the qualification
graph or at a single bad kernel. In rough order of suspicion: (1) memory/CPU-memory-controller
stability at DDR5-6000 on a 13th-gen part; (2) GPU power delivery or the PSU/connector (the card
peaked at 84 C and about 260 W in the successful run); (3) the NVIDIA driver 616.92 WDDM path.
Cheap discriminating steps for the operator: drop memory to its 5600 MT/s JEDEC rating (or lower)
for a few days and watch Kernel-Power 41; run a memory test; confirm the PSU rating and reseat the
GPU power connector; try the previous NVIDIA driver with a clean install. None of these was
attempted because they change the machine's configuration.

What changed in the tooling because of it: every run now writes a per-row, flushed telemetry
trail (`*_telemetry.csv`: VRAM, temperature, power, clocks, utilisation, throttle bits, free RAM)
so a hard failure leaves evidence, and `session_c` skips runs that already completed so a repeat
does not redo them.
