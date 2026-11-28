# VID-FINISH: optional loop, trim and SeedVR2 upscale for finished clips

Status: built 2026-11-28 with deterministic tests. GPU trial the same day in two runs: upscale pairs completed at 33 and 81
frames; the 121-frame upscale was stopped on low host RAM (sections 7 and 8). Built on `origin/main` 841f9b49, then
merged with 71e2a4a0; branch
`claude/vid-finish-eceb88`. Finishes slice (d) of the 2026-11-27 Value Assessment's VID-FRAME item (owner pick
2026-11-28).

Execution class: Standard (a finishing step inside the existing `video_workflow` stage; no new stage, runner, queue or
store). Model recommendation: Claude Code Sonnet 5.5 at high effort, or Codex equivalent. Controller surface: none
changed. Validation: focused tests, `tests/video`, `tests/pipeline`, `tests/system`, `tests/tools`, the ratchets, the
code map and `python tools/ci/run_pr_gate.py`.

## 1. What the operator gets

Under **Advanced** in the Video Workflow tab, all off by default:

- **Trim** from / to, in seconds. Positions on the clip's timeline; a blank "to" keeps the end.
- **Loop**: *Ping-pong* (forward, then back, without doubling the two turning frames: `2n-2` frames) or *Crossfade* (the
  last 0.5 s blends into the first 0.5 s, so the clip gets that much shorter).
- **Upscale 2x with SeedVR2** (experimental, unrated). Refused until its files are installed.

The choices are per job: they are not saved with the form, **Make Video** starts with them off, and Re-run with tweaks
restores what the finished job asked for. They are single-clip options; a sequence or Storyboard take that carries one
is refused, never silently ignored.

## 2. Contract

- Frozen on the NJR as `video_workflow.finishing` (stage config and provenance), with only the chosen keys:
  `loop_mode`, `crossfade_seconds`, `trim_start_seconds`, `trim_end_seconds`, `upscale{pass_id, pass_version, scale,
  seed, experimental_opt_in}`.
- Order inside the one stage: generate -> frames encoded (native clip) -> upscale -> RIFE smoothing -> trim -> loop.
  Upscaling first halves the SeedVR2 work compared with upscaling the smoothed frames.
- Each step writes a new file (`<stem>_upscaled`, `_smooth`, `_finished`). The last is the primary output. Every earlier
  clip, the native one first, is listed in `retained_paths` and tagged `retained_source`, which is the existing rule that
  keeps it out of Review, the phone gateway and Immich. The manifest also records `native_video_path`, `finishing` and
  `upscale`. The upscale's temporary folder is removed after the pass; if the app stops mid-pass, the publisher
  treats what is left in it as working files.
- Trim and loop are one FFmpeg pass over the previous step's clip, with StableNew's encoder (CRF 16, BT.709). That is a
  second encode of an already encoded clip; at CRF 16 it is expected to be invisible, which has not been rated.
- Trim and loop that the clip cannot satisfy are refused at Queue (and again before generation for stored jobs).

## 3. SeedVR2 on this PC

- The managed ComfyUI is 0.38.0 (`config/managed_comfy_runtime.json`), and its install has the stock SeedVR2 nodes
  (`comfy_extras/nodes_seedvr.py`; 0.37.0 has them too) and the blueprint *Upscale Video (SeedVR2 3B Int8)*. No custom
  node is needed.
- **Weights** (installed on the owner's PC 2026-11-28, section 7; not part of any installer), from `Comfy-Org/SeedVR2`
  on Hugging Face (apache-2.0):

  | File | Folder | Bytes |
  |---|---|---|
  | `seedvr2_3b_int8_convrot.safetensors` | `models/diffusion_models` | 3,458,259,704 |
  | `seedvr2_ema_vae_fp16.safetensors` | `models/vae` | 501,324,814 |

  Downloading them (3.96 GB) needs the owner's OK. Preflight checks presence and size; the code pins no SHA-256 (the
  verified values are in section 7).
- The pass is `seedvr2_3b_int8_upscale_2x` 1.0.0 (`src/video/seedvr2_upscale.py`), pinned by a digest of its graph and
  file list. It is not a catalog workflow, so the picker never offers it. It follows the blueprint with two changes:
  fixed temporal chunks (5 frames, 1 latent frame of overlap) instead of `auto`, which sizes chunks from whatever
  memory is free and so is not reproducible; and `lab` colour correction (the node's default) instead of `none`.
- Governance: **experimental**. The request called it "an approved workflow, off by default and labelled
  experimental/unrated"; marking an unrun, unrated pass `approved` would contradict `AGENTS.md` section 2, so it is a
  pinned pass that warns beside Queue (`video_upscale_experimental`) and records the job's opt-in. Promotion is an owner
  decision after section 6.
- Preflight refusals, all naming what is missing and that a download needs the owner's OK: at Queue (node file, model
  files, sizes), again before generation, and the serving ComfyUI's node list before the first prompt. A job without the
  recorded opt-in is refused by `JobService` admission.

## 4. Memory estimate (not a measurement)

ComfyUI publishes no VRAM figure for this model (`docs.comfy.org/tutorials/utility/seedvr2` gives none). The estimate
uses the constants ComfyUI's own chunking code carries (`comfy/ldm/seedvr/constants.py`, measured on the **3B fp16**
model on an RTX 5090):

- free memory needed for sampling = `8.5 + 0.55 x megapixels x latent_frames` GiB, plus a `4 x 0.55` GiB safety margin;
- the int8 weights are 3.22 GiB against 6.32 GiB for fp16, so the fixed part is taken as 5.4 GiB (a subtraction, not a
  measurement);
- the largest input is 399,360 pixels, so the output is at most 1.60 MP; 5 frames are 2 latent frames.

That gives **about 7.2 GiB** at the peak, about 9.4 GiB with ComfyUI's margin. Tiled VAE encode and decode (512 px) are
expected to stay below that. The gate is the existing VRAM stop rule (`WorkflowResourceReadiness`) with a floor of
**10,000 MiB available to ComfyUI**, checked again after generation, just before the upscale is queued. Under ComfyUI's
own fp16 law this PC would only fit 1-frame chunks, so the first GPU run must treat out-of-memory as likely until shown
otherwise.

The video workflow's models are still loaded when the pass starts, and ComfyUI counts almost none of them as
PyTorch's memory (V1-6 / VID-WARM-373), so the check would read them as another program's. The owned ComfyUI is
therefore asked to unload (`POST /free`) before the check, which waits up to 30 s for the memory to appear, and
again after the pass so the next job's check is not misled. A ComfyUI StableNew does not own is never asked, so
after a generation its check will usually refuse. Whether unloading returns enough memory on this card is part of
section 6.

Host RAM: the same constants put about 9.9 GB of caches on the host at 1.6 MP, on top of the decoded frames. The 16 GB
advisory is a warning only.

Limits, refused at Queue: input at most 399,360 pixels per frame (the A14B and TI2V-5B 480p-class sizes, not 720p), at
most 121 frames, and a workflow that saves its frames.

A job that upscaled releases the owned ComfyUI instead of keeping it warm. If the upscale fails after generation, the
job fails; the native clip and frames stay on disk.

## 5. Known limits

- **Continue this clip** and Storyboard continuation use the native generated frames, so they continue from the end of
  the clip as generated, not from a trimmed end or a loop point, and not at the upscaled size.
- **Send to Movie Clips** prefers a clip's frames, so it assembles the native frames. Smoothed clips already behave
  this way.
- On a GPU (sections 7 and 8) the pass completed for A14B clips of 33 and 81 frames, in the same ComfyUI process as the
  CK default. At 121 frames it ran out of the 3 GiB host RAM margin before finishing. TI2V-5B input is unmeasured.
- The Queue warning still says the pass has never been run on this PC; changing that text is a code change.
- The lossless clip uploaded for the upscale is H.264 RGB (`libx264rgb -qp 0`); ComfyUI decoding it pixel-exactly is
  unverified.
- The loop and trim tests that run real FFmpeg skip where FFmpeg is absent.

## 6. GPU timing and rating plan (run in part 2026-11-28, section 7)

The owner approved the trial and, separately, the download. The text below is the plan as written before the run.

**Before the GPU.** Download the two files, record their SHA-256, confirm their sizes. Close other GPU programs and the
StableNew app (or run the clips through the app and queue nothing else). Check free VRAM and host RAM.

**Clips.** Three non-explicit test sources (stock frames or the subject test images, not the output library), A14B full
picture unless stated, one fixed seed per case, smoothing on in both arms:

| Case | Size, frames | Why |
|---|---|---|
| U1 | 624x624, 33 | smallest useful check; first OOM signal |
| U2 | 480x832 (TI2V-5B 1.3.0), 81 | the common length |
| U3 | 544x720, 121 | the declared maximum; the host RAM case |

Each case runs twice: without the upscale ("before") and with it ("after"). Because generation is seeded, the pair
differs only by the upscale; check the two native clips look the same before rating.

**Order and stop rules.** U1, then U2, then U3, each only if the one before passed. Stop on: any out-of-memory, a
failed VRAM readiness check, host RAM free below 3 GiB, an upscale stage longer than 20 minutes, or any `nvlddmkm`
event (the device-loss quarantine applies). On out-of-memory the next step is a new pass version with 1-frame chunks,
not a retry.

**Measured per run:** upscale stage wall time (the job's log lines), total job time, peak VRAM and minimum free host RAM
(1 s `nvidia-smi` and memory sampling), output size and frame count.

**To rate sitting.** Author the six clips as a video eval suite (two arms, `finishing: {"upscale": true}` in the "after"
arm), register it with `tools/review_gateway_rating.py`, and rate on the phone's **To rate** tab or the desktop
Evaluate view. Ratings: source fidelity, subject stability, continuity (watch for flicker between chunks), and which of
the pair is better and whether it is worth the time. Whether an eval suite accepts the `finishing` key end to end is
untested; if it does not, rate a blind pair folder as VID-FRAME's attention sitting did.

**Decision after rating:** promote, keep experimental, or remove.

## 7. First GPU trial (2026-11-28): one pair, then a VRAM stop

**Download.** `Comfy-Org/SeedVR2` at `df48879708206a403d2a61acd55578c2e80fd233`; sizes and SHA-256 verified:
`seedvr2_3b_int8_convrot.safetensors` `c3dec8bcc5916843a8a858572970597462e1f2dc598d6dfd818f6cd40f53a157`,
`seedvr2_ema_vae_fp16.safetensors` `20678548f420d98d26f11442d3528f8b8c94e57ee046ef93dbb7633da8612ca1`.

**Run.** Eval harness at `85a59f91`, StableNew closed, seed 374, smoothing on in both arms, SFW subject pictures. Four
cases were planned (the three of section 6 plus 720x544, 81 frames); 3 of 8 jobs ran. Stop line: 11,500 MiB.

| Case | Arm | Result | Wall s | Upscale pass s | Smoothing s | Peak VRAM MiB (of 12,282) | Free RAM low GiB |
|---|---|---|---:|---:|---:|---:|---:|
| U1 A14B 1.1.0, 624x624, 33 f | before | completed | 142.9 | - | 6.7 | 11,189 | 6.38 |
| U1 | after | completed, 1248x1248 | 207.6 | 180.6 | 21.1 | 6,773 (6,111 during the pass) | 5.71 |
| U2 TI2V-5B 1.3.0, 480x832, 81 f | before | stopped and cancelled | 57.2 | - | - | 11,740 | 14.07 |
| U2 after, U3, U4 | | not run | | | | | |

- The upscale pass took about 5.5 s per source frame at 624x624. Longer clips are unmeasured.
- Its readiness check passed with 10,406 MiB available after unload, 406 MiB above the 10,000 floor.
- U1's "after" job reused ComfyUI's cached generation, so its wall time excludes generation. The two native clips are
  frame-for-frame identical, so the pair differs only by the upscale.
- The stop was U2's **plain TI2V-5B generation, with no upscale**, at its first sampling step. Earlier clean TI2V-5B
  runs on this card peaked at 11,386 to 11,820 MiB, so the 11,500 line was below its normal peak; the case should not
  have been run under it. It says nothing about SeedVR2.
- An `nvlddmkm` event 153 was logged in the same second as the interrupt and ComfyUI stop. Its cause is not established
  (a 153 on forced termination has been seen before). `nvidia-smi` and device status were normal afterwards; no further
  GPU work tested it. Nothing was retried.
- **Not measured in this run:** 81 and 121 frames, 544x720 and 720x544 (see section 8).
- **Rating:** sitting `vid-finish-seedvr2-upscale` has the one completed pair, blind; not rated when recorded. The pass
  stays experimental.

Evidence: `%USERPROFILE%\Videos\StableNewAcceptance\GPU-CHECKS\seedvr2\`.

## 8. Second run (2026-11-28): the two A14B cases, TI2V-5B dropped

Owner decision: finish with A14B only. Eval harness at `e15f3e4d`, StableNew and Forge closed, A14B 1.1.0, seed 374,
smoothing on in both arms. Stop rules as in section 7 plus the 3 GiB host RAM floor and a 20-minute limit on the pass.

| Case | Arm | Result | Wall s | Upscale pass s | Smoothing s | Peak VRAM MiB | Free RAM low GiB |
|---|---|---|---:|---:|---:|---:|---:|
| U4 720x544, 81 f | before | completed | 230.4 | - | 22.2 | 11,065 | 4.78 |
| U4 | after | completed, 1440x1088 | 683.3 | 594.4 | 75.5 | 6,634 | 5.22 |
| U3 544x720, 121 f | before | completed | 245.1 | - | 28.2 | 8,851 | 11.14 |
| U3 | after | **stopped**: host RAM 2.96 GiB | 905.1 | 889.7 (unfinished) | - | 6,747 | 2.96 |

- **81 frames:** the upscale added about 11 minutes (594 s for the pass, 53 s more smoothing), about 7.3 s per source
  frame. The two native clips are frame-for-frame identical, so the pair differs only by the upscale.
- **121 frames:** all sampling chunks finished with free host RAM near 12 GiB. As ComfyUI moved to decoding the whole
  1088x1440 clip, free RAM fell to 2.96 GiB within 8 s, under the floor, and the job was cancelled. No upscaled clip was
  made. Whether it would have finished is unknown; it was not retried.
- No out-of-memory error, device loss, `nvlddmkm` event or retry in this run. The pass peaked under 6.8 GiB of VRAM at
  81 and 121 frames.
- The "before" VRAM peaks are single one-second samples during the final decode, so measured peaks vary between runs.
- **Rating:** the 81-frame pair is sitting `vid-finish-seedvr2-upscale-2`, blind; not rated when recorded. Its upscaled
  clip is shown on the phone at 1280 px on the long edge. The 33-frame pair stays in `vid-finish-seedvr2-upscale`.
- Before the pass is offered for long clips, its host RAM at the final decode needs a fix or a limit: a lower frame cap,
  a chunked decode, or a re-measurement after a RAM upgrade.

Evidence: `%USERPROFILE%\Videos\StableNewAcceptance\GPU-CHECKS\seedvr2\runs\20261128T152316Z\`.
