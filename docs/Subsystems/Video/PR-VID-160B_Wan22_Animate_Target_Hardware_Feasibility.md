# PR-VID-160B — Wan2.2-Animate Target-Hardware Feasibility Probe

Status: **`PR-VID-160B — PARTIAL EVIDENCE ACCEPTED / INTEGRATED — MOVE-MODE RESOURCE GATE STILL
OPEN`**. This is a qualification-only resource-feasibility probe. It adds no production `src/`
change, no backend, no queue/history authority, and no Wan production graph/settings change. Start
`main @ a203b831083caa334057d6e9f1b001e41937decb`.

## Outcome asked

Can one smallest-credible Wan2.2-Animate-14B GGUF **Move-mode** generation execute on this RTX 4070
Ti 12 GB / 32 GB RAM Windows machine without unsafe host-memory exhaustion, VRAM failure,
shared/pagefile collapse, GPU loss, or violation of StableNew runtime ownership?

**Not yet fully answered.** The one authorized physical generation completed cleanly and produced
valuable, accepted evidence, but it did **not** supply `pose_video` — the input that actually
exercises Move-mode motion transfer (`face_video` is a separate, optional expression-guidance
input). What was proven is the resource floor of the Animate-14B GGUF backbone
inference/decode path alone: no safety stop, no CUDA/GPU-loss, VRAM peaked at 11,396 MiB (886 MiB
below the 12,282 MiB ceiling), host RAM never dropped below 4.7 GB available, and a valid,
decodable 256×256/13-frame/8fps H.264 MP4 was produced in 30.4 s (see Phase H). This sub-finding is
recorded as **`ANIMATE_BACKBONE_RESOURCE_FLOOR_PASS`** (Phase I) — a descriptive result, not a new
production-governance classification, and not the same claim as "Move-mode is resource-feasible."
The true pose-driven Move-mode resource cost remains an open gate (see Gate C/D below and
PR-VID-160C).

## Phase A — dependency and environment discovery (read-only; nothing modified)

- Configured Comfy: `build_default_comfy_process_config()` resolves to base URL
  `http://127.0.0.1:8000`, working directory
  `E:\Users\rober\AppData\Local\Programs\ComfyUI\resources\ComfyUI`, base-directory
  `E:\Users\rober\ComfyUI` (a ComfyUI Desktop install; models/custom_nodes/input/output/user are
  redirected to the base directory).
- ComfyUI core version: `0.3.65` (`comfyui_version.py`). Torch `2.8.0+cu129` in the Comfy-owned venv
  `E:\Users\rober\ComfyUI\.venv-explicit` (a separate environment from StableNew's own Python
  environment; untouched by this probe).
- `WanAnimateToVideo` is a **native, stock** ComfyUI 0.3.65 node
  (`comfy_extras/nodes_wan.py`, `is_experimental=True`) — no Kijai wrapper, no `KJNodes`, and no
  `comfyui_controlnet_aux`/SAM2 are required for the core transformer/VAE/text-encoder/CLIP-vision
  load-and-sample path. Its `pose_video`, `face_video`, `background_video`, `character_mask`, and
  `continue_motion` inputs are all `optional`.
- Existing custom nodes (base-directory `custom_nodes/`): `StableNewLTXBridge` only. (The app
  resources' own `custom_nodes/` additionally has `ComfyUI-LTXVideo` and `ComfyUI-Manager`, but the
  base-directory redirect means the base-directory list is what actually loads.)
- Existing relevant model files (all reused, none re-downloaded):
  - `models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` — present.
  - `models/vae/wan_2.1_vae.safetensors` — present.
  - `models/diffusion_models/`: `wan2.1_vace_1.3B_fp16.safetensors`,
    `wan2.2_ti2v_5B_fp16.safetensors` — present, neither is Animate-14B.
  - `models/clip_vision/` — empty; `clip_vision_h.safetensors` absent (downloaded, see Phase D).
  - `models/unet/` — empty; no Animate GGUF present (downloaded, see Phase D).
- No Comfy Manager "update all", no Torch/CUDA change, no Python upgrade was performed.

## Phase B — frozen probe selection (before any installation)

### Quant selection

Inspected `QuantStack/Wan2.2-Animate-14B-GGUF` (HF repo `sha=33c51bb84d4e70ffc0d088aeb6068d40d9446fa3`,
base model `Wan-AI/Wan2.2-Animate-14B`, Apache 2.0). Available quants and on-disk sizes:

| Quant | Size |
|---|---|
| Q2_K | 6.46 GB |
| Q3_K_S | 7.97 GB |
| **Q3_K_M** | **8.63 GB** |
| Q4_K_S | 10.6 GB |
| Q4_0 | 10.4 GB |
| **Q4_K_M (task default)** | **11.5 GB** |
| Q5_0 / Q5_K_S / Q5_K_M | 12.5 / 12.3 / 13 GB |
| Q6_K | 14.6 GB |
| Q8_0 | 18.7 GB |

**Selected: `Wan2.2-Animate-14B-Q3_K_M.gguf` (8.63 GB)**, not the task's Q4_K_M default. Reason:
Q4_K_M's 11.5 GB on-disk size is materially larger than the ~10–12 GB VRAM community reports this
package's PR-VID-160A research summarized, and StableNew's own accepted telemetry already shows
the much smaller Wan2.2 TI2V-5B model peaking at ~11.6 GB VRAM on this exact 12 GB card — leaving
very little combined headroom for Q4_K_M plus the text encoder, VAE, and CLIP Vision resident in
the same session. Q2_K (6.46 GB) was rejected as not "credible enough that a PASS would justify
later motion characterization": 2-bit quantization on a 14B-class transformer commonly causes
coherence collapse, so a PASS there would be weak evidence. Q3_K_M is the largest quant tier below
Q4 that GGUF's ecosystem still treats as a balanced ("K_M") tier rather than an extreme low-bit
corner, materially reducing footprint versus the default while remaining a meaningful data point.

### Geometry / frame budget (a resource floor only — not a quality or 480×832 feasibility proof)

- `width=256, height=256` (both divisible by 16; far smaller than PR-VID-150's 480×832).
- `length=13` (4 latent frames; far smaller than PR-VID-150's 49 frames).
- `steps=4` (enough to exercise the full `KSampler` denoise loop and `VAEDecode`; not enough for
  visual convergence — this probe does not evaluate output quality).
- `cfg=5.0`, `shift=8.0`, `sampler=uni_pc`, `scheduler=simple` — matching StableNew's already-
  accepted Wan2.2 production defaults for realism, rather than picking arbitrary values.
- `seed=1733123036` — the same frozen seed reused across PR-VID-140/150, for audit-trail
  consistency (not a specific requirement of this probe).
- Reference image: `reports/vid110/inputs/source_fullbody.png` (existing, already-approved
  full-body source; no new asset captured).
- **No `pose_video`, `face_video`, `background_video`, or `character_mask` input.** All four are
  optional on `WanAnimateToVideo`; omitting them avoids `comfyui_controlnet_aux`/`KJNodes`/SAM2
  entirely. This still forces the full 14B weight load, text encoder, CLIP Vision reference-image
  path, VAE encode/decode, and a complete `KSampler` denoise loop — the dominant memory/compute
  cost of a real run — but it does **not** exercise the motion/face-conditioning code path a true
  Move-mode run would use. A PASS under this reduced graph establishes a resource floor only; it
  does not prove Move-mode motion-transfer feasibility, 480×832 feasibility, 49-frame feasibility,
  quality, or identity retention.

## Phase C — environment mutation (minimized)

- **`ComfyUI-GGUF`** installed: `git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git`
  into `E:\Users\rober\ComfyUI\custom_nodes\ComfyUI-GGUF`, revision
  `6ea2651e7df66d7585f6ffee804b20e92fb38b8a`. Required because `UnetLoaderGGUF` is not a stock
  ComfyUI core node.
- Its only Python requirement, `gguf>=0.13.0`, was installed with `pip install --no-deps` into the
  Comfy-owned venv (resolved to `gguf==0.19.0`) specifically to avoid pulling any transitive
  dependency that could touch the existing `torch==2.8.0+cu129` / `numpy==2.2.6` stack. Verified
  `import gguf` and `import numpy` both succeed afterward with the pinned `numpy==2.2.6` unchanged.
  The requirement file's optional `sentencepiece`/`protobuf` tokenizer extras were **not**
  installed (not needed for this graph; StableNew's UMT5 text encoder path is already used
  unchanged by the accepted Wan2.2 workflow).
- No node replacing/downgrading PyTorch, CUDA packages, or requiring a new global Python
  environment, administrator privileges, or another standalone runtime was needed or installed.
- `comfyui_controlnet_aux`, `KJNodes`, SAM2, and VideoHelperSuite were **not** installed (avoided
  per Phase B's geometry/graph choice).

## Phase D — asset staging

| Asset | Source | Revision | Size | SHA-256 |
|---|---|---|---|---|
| `Wan2.2-Animate-14B-Q3_K_M.gguf` | `QuantStack/Wan2.2-Animate-14B-GGUF` | `33c51bb84d4e70ffc0d088aeb6068d40d9446fa3` | 8,630,769,472 bytes (8.63 GB) | `62cd6067c96599ade5bdde54a49a5ef1a7fd4de449eaae56ff4fd61ccbb16678` |
| `clip_vision_h.safetensors` | `Comfy-Org/Wan_2.1_ComfyUI_repackaged` | `617a7633e636506f850e043bc4605f290a466a8e` | 1,264,219,396 bytes | `64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | already present | n/a | reused | not recomputed |
| `wan_2.1_vae.safetensors` | already present | n/a | reused | not recomputed |

No BF16 Animate transformer, no second GGUF quant, no Mix-mode-only asset, and no relighting/
inpainting/interpolation model was downloaded. Model files were written under the existing Comfy
`models/unet` and `models/clip_vision` directories (runtime assets; not committed to Git).

## Phase E — qualification tooling

`tools/qualification/vid160b/`:

- `graph.py` — pure `build_probe_graph()`/`validate_graph()`; the frozen 15-node graph
  (`UnetLoaderGGUF`, `CLIPLoader`, `VAELoader`, `CLIPVisionLoader`, `CLIPTextEncode`×2, `LoadImage`,
  `CLIPVisionEncode`, `ModelSamplingSD3`, `WanAnimateToVideo`, `KSampler`, `TrimVideoLatent`,
  `VAEDecode`, `CreateVideo`, `SaveVideo`) — stock nodes plus the one required GGUF loader, no other
  custom node.
- `telemetry.py` — `ProbeResourceSampler`, extending the PR-VID-110/150 GPU-sampler concept with
  host RAM/swap observation every ~0.5 s, flushed per row. Frozen stop rule (documented before any
  physical run, not tuned afterward): available RAM < 1.0 GB for 2 consecutive samples, OR swap
  usage ≥ 90% while available RAM is also < 1.0 GB. `abort_reason()` plugs directly into the
  existing `tools.qualification.vid110.comfy_client.ComfyClient.wait(abort_reason=...)` hook, which
  already interrupts only the qualification tool's own prompt and never touches foreign work.
- `run.py` — orchestration: refuses to adopt an external healthy Comfy endpoint (`preflight()`),
  launches only through the existing `ComfyProcessManager` when the endpoint is free, verifies the
  frozen graph's node classes are advertised by `/object_info` before dispatch, submits exactly one
  prompt, always releases only the Comfy process its own manager owns (mirrors the accepted
  PR-VID-130/150 teardown pattern), and always writes `reports/vid160b/evidence.json` even on
  exception. No SQLite queue/history is created. No import from `src.controller`/`src.queue`.

`tests/tools/test_vid160b_qualification.py` — **16 passed**: graph freeze (frozen node classes,
pose/face/background/character-mask omission, dimension/length validation, dangling-link and
non-frozen-class detection), external-runtime refusal, dry-run non-submission, exactly-one-attempt
with no automatic retry, partial-evidence-preservation-and-teardown on exception, owned-vs-unowned
process cleanup (including a failing `stop()` not being swallowed), and safety-stop triggering
(low-RAM-for-two-consecutive-samples, and `ComfyClient.wait` actually interrupting and raising when
`abort_reason` fires). Ruff clean on all touched files. `git diff --check` clean.

## Phase F — telemetry (real run)

Captured every ~0.5 s for the full 30.4 s run (56 samples): GPU VRAM used, temperature, power,
utilization; host available RAM; swap used (GB and %). Flushed per sample to
`reports/vid160b/telemetry.csv`. Windows shared-GPU-memory counters and per-process RSS were
scoped out as optional/low-complexity per the package's own instruction; not needed to answer the
gate.

| Metric | Value |
|---|---|
| Samples | 56 |
| VRAM baseline / peak | 1,563 MiB / **11,396 MiB** (of 12,282 MiB total; 886 MiB headroom) |
| Host RAM available, minimum | **4.7 GB** (well above the 1.0 GB stop threshold) |
| Swap used, peak | 1.85 GB (5.4% of configured swap) |
| Temperature, peak | 59 °C |
| Power, peak | 209.06 W |
| Stop reason | none (empty) |
| Wall time | 30.4 s |

## Phase G — safety stop

**First check (deferred session):** GPU memory used was **8,642 MiB / 12,282 MiB**, static across
two checks a minute apart, with A1111 WebUI resident (`nvidia-smi --query-compute-apps`) and two
`python -m src.main` StableNew GUI processes also live. This failed the idle precondition and the
probe was deliberately not dispatched (see prior closeout).

**Retry (this run):** the operator reported the GPU was no longer blocked. Re-verified directly
before dispatch: GPU memory used **1,406 MiB / 12,282 MiB**, 0% utilization, `nvidia-smi
--query-compute-apps` showing only ordinary desktop/OS processes, and no Comfy/A1111/StableNew
Python process running. The idle precondition was met. Staged assets
(`Wan2.2-Animate-14B-Q3_K_M.gguf`, `clip_vision_h.safetensors`) and the `ComfyUI-GGUF` custom node
were reverified present and unchanged from Phase C/D before proceeding. No threshold, quant, or
environment change was made for this retry — it is the exact frozen probe from the deferred
session, run once the precondition it was waiting on was satisfied.

During the run itself: the frozen host-RAM/swap safety-stop rule never tripped (`stop_reason`
empty throughout); no CUDA OOM or Comfy allocation failure occurred; no GPU-lost/black-screen/
max-fan signature occurred.

## Phase H — one physical attempt

**Submitted, exactly once.** `prompt_id=2516c65b-9b81-49f2-9164-d687ad57c7a9`. The full frozen
graph (`UnetLoaderGGUF` → `CLIPLoader`/`VAELoader`/`CLIPVisionLoader` → `CLIPTextEncode`×2 →
`CLIPVisionEncode` → `ModelSamplingSD3` → `WanAnimateToVideo` → `KSampler` → `TrimVideoLatent` →
`VAEDecode` → `CreateVideo` → `SaveVideo`) executed end to end and returned a completed Comfy
history entry with one output file. Downloaded to `reports/vid160b/probe_output.mp4` (29,743
bytes). `ffprobe` confirms a valid, decodable H.264 stream: 256×256, 8 fps, exactly 13 frames —
matching the frozen spec exactly. A middle frame was extracted and visually inspected: a coherent
(if square-cropped, head-truncated) render of the reference image's torso/clothing, not noise or a
corrupted/black frame — no obvious graph or function failure. No fine-grained identity or
locomotion-quality evaluation was performed (out of scope for this probe; `pose_video`/`face_video`
were not supplied, so Move-mode motion conditioning was not exercised — see Phase B). The Comfy
process this run's own `ComfyProcessManager` launched was released in `finally`; `nvidia-smi`
afterward showed a clean return to idle (1,403 MiB, 0% utilization) and no lingering Comfy/Python
process. `managed_comfy_owned: true`, `teardown_errors: []`.

## Phase I — decision classification

**Package status: `PR-VID-160B — PARTIAL EVIDENCE ACCEPTED / MOVE-MODE RESOURCE GATE STILL OPEN`**

**Sub-finding: `ANIMATE_BACKBONE_RESOURCE_FLOOR_PASS`** (descriptive; not a production-governance
classification).

Every PASS-shaped condition was met for the graph actually run: generation completed; output is
decodable and matches the frozen spec; no CUDA/GPU loss; no safety stop; no severe commit/pagefile
collapse (swap peaked at 5.4%); the manager-owned runtime exited cleanly. But the original
acceptance contract for this package explicitly called for a bounded **Move-mode** generation with
a driving/control sequence, and the run that actually executed omitted both `pose_video` (the
motion-transfer input) and `face_video` (the optional expression input). The result therefore
proves only: **the Wan2.2-Animate-14B GGUF backbone (transformer load, text encoder, CLIP Vision
reference path, VAE, sampler, decode) is physically viable on this RTX 4070 Ti 12 GB / 32 GB RAM
machine at reduced geometry (Q3_K_M, 256×256, 13 frames, 4 steps)**. It does not establish that true
pose-driven Move mode is resource-feasible, does not authorize production integration, and does not
prove 480×832 feasibility, 49-frame feasibility, quality, or identity retention.

### Gate C — VRAM: materially de-risked, not fully closed

The Animate GGUF backbone completed at **11,396 MiB peak** on the 12,282 MiB GPU, leaving only
**~886 MiB margin**. That is real, positive evidence that the backbone alone fits with some room to
spare. But because the pose-guidance branch was absent from the executed graph, the true Move-mode
peak VRAM — with whatever additional conditioning tensors/cross-attention the pose branch adds —
remains **unmeasured**. Do not read 886 MiB as the actual Move-mode margin; it is the margin for a
strictly smaller graph than Move mode.

### Gate D — host RAM: strongly de-risked, not fully closed

The completed lower-bound run retained **4.7 GB available host RAM** and low swap pressure (5.4%
peak), substantially better than the accepted Wan2.2 TI2V-5B runs (which drove available RAM to
~0.01–0.02 GB on this same machine). That is a strong positive signal for the backbone alone. But
actual pose-guidance processing was absent from this run, so **do not extrapolate 4.7 GB minimum
directly to a full Move-mode workload** — pose/face conditioning may add its own host-RAM cost
(e.g., loading a driving-video tensor, any additional preprocessing) that this run did not exercise.

## Phase J — consequences (not implemented; recommendation only)

The Move-mode resource gate remains open. The next proposed package is
**`PR-VID-160C — Wan2.2-Animate True Move-Mode Resource Closure`** (see the contract boundary
below) — not a full motion-quality/identity characterization yet, and not authorized by this
package. That package should answer whether the same already-proven backbone configuration also
holds when a real `pose_video` is supplied, before any later package attempts identity-retention or
locomotion-quality evaluation or moves geometry toward PR-VID-150's 480×832/49-frame scale.

## Architecture effect

None. This probe dispatches directly to a manager-owned Comfy instance exactly as
`tools/qualification/vid110`/`vid130` already do; it never touches `VideoWorkflowController`, the
NJR contract, `JobService`, SQLite queue/history, or `VideoExecutionResolver`. Animate remains
unregistered as a StableNew workflow. No production `src/` file changed.

## DIAG-GPU-120

This run is recorded as **one additional clean high-load GPU exposure**: sustained VRAM residency
near the 12 GB ceiling (11,396 MiB peak) with clean completion, no GPU-lost/black-screen/max-fan
signature, and a clean return to idle afterward. This does **not** mark DIAG-GPU-120 PASS and makes
no hardware/root-cause conclusion; DIAG-GPU-120 remains observation-only.

## Validation

- 16 focused deterministic tests passed (`tests/tools/test_vid160b_qualification.py`).
- Ruff clean on `tools/qualification/vid160b/` and the new test file.
- `git diff --check` clean.
- No broader suite run (no source outside the new qualification tree changed).
- No GitHub CI obtained yet for this branch; not required to delay a docs/tooling-only closeout,
  and moot until this branch is pushed.
- Physical acceptance evidence: one real Comfy run, `ffprobe`-verified valid output, telemetry
  captured throughout, clean teardown verified by direct `nvidia-smi`/process re-check afterward.

## Remaining uncertainty

- Whether the same frozen graph holds VRAM/RAM margin at production-scale geometry (480×832,
  49 frames) rather than this probe's reduced 256×256/13-frame/4-step settings — not answered by
  this PASS.
- Whether supplying real `pose_video`/`face_video` Move-mode conditioning changes the resource
  profile materially (additional conditioning tensors/branches were not exercised here).
- Whether character-identity retention and locomotion-transfer quality are actually useful at any
  settings — entirely unaddressed by a resource-only probe.
- Whether Q3_K_M's quantization level (chosen for margin over the task's Q4_K_M default) preserves
  enough quality for a useful characterization, versus needing to move up a quant tier once more
  VRAM margin is confirmed available at reduced geometry.

## Recommended next package

**`PR-VID-160C — Wan2.2-Animate True Move-Mode Resource Closure`** (recorded here, not executed).
Its sole remaining question:

> Can the same already-proven Animate GGUF configuration complete one small pose-driven Move-mode
> generation when a real `pose_video` is supplied, without crossing RAM/VRAM/stability limits?

Contract boundary for that package:

- Reuse the already-installed `Wan2.2-Animate-14B-Q3_K_M.gguf` quant and existing model assets — do
  not redownload or switch quant.
- Reuse the existing `tools/qualification/vid160b/` harness and telemetry (safety-stop rule
  unchanged unless evidence from that run specifically warrants revisiting it).
- Reuse the same or a similarly minimal 256×256/short-frame workload — isolate the marginal cost of
  adding `pose_video`, not a jump to production-scale geometry.
- Supply `pose_video` only; a `face_video` is not required unless current `WanAnimateToVideo` graph
  semantics turn out to require it once inspected. Prefer `pose_video` alone to isolate the motion
  branch and minimize incremental resource cost.
- Do not install `comfyui_controlnet_aux`/`KJNodes`/DWPose solely to manufacture the control input
  if a valid preprocessed pose-video asset can be supplied directly (matching this package's own
  Phase B/C dependency-minimization precedent).
- One bounded physical attempt, same no-retry/safety-stop discipline as this package.

This is a distinct package from a full identity-retention/locomotion-quality characterization,
which remains a later, separately authorized step once the Move-mode resource gate itself closes.

## Explicit confirmations

No model was promoted to production. No `VideoWorkflowController`/NJR/`VideoExecutionResolver`
change occurred. No Torch/CUDA/Python replacement occurred. No GPU/BIOS/driver/XMP change occurred.
Exactly one generation was submitted this session (`prompt_id=2516c65b-9b81-49f2-9164-d687ad57c7a9`);
no second generation and no retry occurred, and no quant/threshold change was made after a failure,
because there was no failure. `src/controller/app_controller.py` and `presets/global_positive.txt`
(pre-existing unrelated local state) remained untouched and unstaged throughout.
