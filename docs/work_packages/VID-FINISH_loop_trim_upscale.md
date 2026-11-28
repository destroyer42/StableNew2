# VID-FINISH: optional loop, trim and SeedVR2 upscale for finished clips

Status: built 2026-11-28 with deterministic tests. No GPU run, no download. Built on `origin/main` 841f9b49, then
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
- **Weights are not installed.** Needed, from `Comfy-Org/SeedVR2` on Hugging Face (apache-2.0):

  | File | Folder | Bytes |
  |---|---|---|
  | `seedvr2_3b_int8_convrot.safetensors` | `models/diffusion_models` | 3,458,259,704 |
  | `seedvr2_ema_vae_fp16.safetensors` | `models/vae` | 501,324,814 |

  Downloading them (3.96 GB) needs the owner's OK. Preflight checks presence and size; no SHA-256 is pinned because no
  copy has been verified.
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
- Nothing was run on a GPU. The graph's input names come from the installed node sources and have not been accepted by a
  running ComfyUI. The A14B Make Video default now runs Comfy Kitchen attention with dynamic VRAM (1.1.0); the
  upscale would run in that same process, which is also untested.
- The lossless clip uploaded for the upscale is H.264 RGB (`libx264rgb -qp 0`); ComfyUI decoding it pixel-exactly is
  unverified.
- The loop and trim tests that run real FFmpeg skip where FFmpeg is absent.

## 6. GPU timing and rating plan (draft; not authorized, not run)

Needs the owner's OK for the download and, separately, for the run.

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
