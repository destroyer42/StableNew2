# PR-VID-160B — Wan2.2-Animate Target-Hardware Feasibility Probe

Status: **PHASES A-G COMPLETE / PHYSICAL DISPATCH DEFERRED**. This is a qualification-only
resource-feasibility probe. It adds no production `src/` change, no backend, no queue/history
authority, and no Wan production graph/settings change. Start
`main @ a203b831083caa334057d6e9f1b001e41937decb`.

## Outcome asked

Can one smallest-credible Wan2.2-Animate-14B GGUF Move-mode generation execute on this RTX 4070 Ti
12 GB / 32 GB RAM Windows machine without unsafe host-memory exhaustion, VRAM failure,
shared/pagefile collapse, GPU loss, or violation of StableNew runtime ownership?

**This session did not obtain a physical answer.** Discovery, dependency minimization, asset
staging, and qualification tooling (built and deterministically tested) are complete and frozen.
The one authorized physical generation was deliberately **not** submitted because Phase G's own
precondition — "GPU must be idle enough that unrelated workloads do not contaminate the result" —
was not met: the operator's own A1111 WebUI and the StableNew GUI application were both observed
live and resident on this machine during this session (see Phase G below). This is not a defect in
Wan2.2-Animate, the GGUF path, or this tooling; it is an environmental precondition that must be
re-checked before the next attempt.

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

## Phase F — telemetry (ready, not yet exercised by a real run)

Captured every ~0.5 s once a probe runs: GPU VRAM used, temperature, power, utilization; host
available RAM; swap used (GB and %). Flushed per sample to `reports/vid160b/telemetry.csv` so a
hard failure still leaves a trail. Windows shared-GPU-memory counters and per-process RSS were
scoped out as optional/low-complexity per the package's own instruction; their absence would not
have blocked the probe.

## Phase G — safety stop: **precondition failed, dispatch deferred**

Before dispatch, this session checked GPU idleness twice, about a minute apart:

| Check | Result |
|---|---|
| GPU memory used | **8,642 MiB / 12,282 MiB** (both checks identical) |
| GPU utilization | 0–1% |
| `nvidia-smi --query-compute-apps` | A1111 WebUI (`stable-diffusion-webui\venv\...\python.exe launch.py`) resident |
| Other live processes observed | Two `python -m src.main` StableNew GUI processes also running |

A static, non-fluctuating 8.6 GB VRAM residency with 0–1% utilization is consistent with the
operator's own A1111 session having a checkpoint loaded (idle but resident), not a transient spike.
Combined with StableNew's own GUI running live, this is real, current use of the machine, not
leftover process debris. Phase G's own precondition — "GPU must be idle enough that unrelated
workloads do not contaminate the result" — was not met, and with only ~3.6 GB of the 12 GB card
free, the probe would not have had enough VRAM margin for the ~8.63 GB transformer plus text
encoder/VAE/CLIP-Vision residency regardless.

**Decision: do not dispatch.** Forcing the probe through now would either fail immediately on VRAM
pressure (contaminating the resource-feasibility answer with an unrelated cause) or contend with
the operator's active A1111/StableNew session. Per the package's own hard-stop instruction not to
"lower the threshold" or push through a failing precondition, this session stopped before Phase H.

## Phase H — one physical attempt

**Not submitted.** Zero Comfy prompts were queued this session. The frozen graph, assets, and
tooling are staged and ready; `python -m tools.qualification.vid160b.run <reference_image> --dry`
can be used to re-verify the endpoint/preflight state at any time without submitting anything.

## Phase I — decision classification

**`RESOURCE_FEASIBILITY_INCONCLUSIVE`**

Per the package's own definition: "Use only when a separable non-resource defect prevents testing
the intended gate." The GPU being contended by the operator's own concurrent, live A1111/StableNew
usage is exactly that — a separable environmental condition unrelated to Wan2.2-Animate's actual
resource footprint — not a resource failure of the candidate itself. This is not a reinterpreted
OOM: no generation was attempted, so no OOM or any other failure signature occurred.

## Phase J — consequences (not implemented; recommendation only)

Retry this exact frozen probe (same branch, same tooling, same quant/graph/thresholds — no
environment or quant change needed) once the operator confirms the GPU is idle: A1111 (or any other
GPU consumer) closed, and ideally the StableNew GUI's own generation activity idle too. This is a
resumption of PR-VID-160B, not a new package. If the retry then produces `RESOURCE_FEASIBILITY_PASS`
or `_CONSTRAINED`, PR-VID-160A's Phase J consequences apply as written (PASS → bounded Move-mode
motion-transfer characterization with real identity/locomotion evaluation; CONSTRAINED →
product-owner review of the resource margin). A NO-GO outcome returns to PR-VID-160A's candidate
research per its own consequence table.

## Architecture effect

None. This probe dispatches directly to a manager-owned Comfy instance exactly as
`tools/qualification/vid110`/`vid130` already do; it never touches `VideoWorkflowController`, the
NJR contract, `JobService`, SQLite queue/history, or `VideoExecutionResolver`. Animate remains
unregistered as a StableNew workflow. No production `src/` file changed.

## Validation

- 16 focused deterministic tests passed (`tests/tools/test_vid160b_qualification.py`).
- Ruff clean on `tools/qualification/vid160b/` and the new test file.
- `git diff --check` clean.
- No broader suite run (no source outside the new qualification tree changed).
- No GitHub CI obtained yet for this branch; not required to delay a docs/tooling-only closeout,
  and moot until this branch is pushed.

## Remaining uncertainty

Everything Phase H would have answered: whether the frozen Q3_K_M/256×256/13-frame/4-step graph
actually completes on this machine within VRAM, and whether host RAM/swap stay within the frozen
safety thresholds. None of that is known yet.

## Recommended next package

Resume PR-VID-160B on this same branch once the GPU-idle precondition is met; do not open a new
package number for the retry.

## Explicit confirmations

No model was promoted to production. No `VideoWorkflowController`/NJR/`VideoExecutionResolver`
change occurred. No Torch/CUDA/Python replacement occurred. No GPU/BIOS/driver/XMP change occurred.
No second generation, no retry, and no quant/threshold change were made after a failure, because no
generation was attempted. `src/controller/app_controller.py` and `presets/global_positive.txt`
(pre-existing unrelated local state) remained untouched and unstaged throughout.
