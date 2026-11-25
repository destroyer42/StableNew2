# PR-IMG-COMFY-100: Comfy Still-Image Backend (Qwen-Image)

Status: DESIGN ACCEPTED, owner decisions recorded 2026-11-19 (section 12); implemented on the feature branch
Owner: Rob
Execution class: Architectural
Started: 2026-11-19T07:33:15-05:00
Ledger: `IMG-Q4.forge-vs-comfy-still`, `IMG-Q1.qwen-image` (no status changes in this package)

## 1. Decision and limits

The package adds **one typed Comfy still-image backend (`comfyui`) for one model family and one mode**:
Qwen-Image 2.1 `txt2img`. Per owner decision 1, it ships two exact variants side by side so they can be compared,
each with its own frozen graph: base int8 (`qwen_image_21_t2i` v1.0.0) and Turbo int8 (`qwen_image_21_turbo_t2i`
v1.0.0). Each NJR still runs one variant and makes one image. The backend sits below `PipelineRunner.run_njr`,
behind the PR-IMG-100 registry. It reuses the managed Comfy runtime and the PR-RUNTIME-100 GPU exclusivity
coordinator. It adds no second queue, runner, history store, compiler, process owner or GUI-to-backend path.

The owner brought the slice into scope on 2026-11-18 ("10. Bring it in." and "13. Tie it into the 10 work.",
`docs/Subsystems/Testing/QUAL-CAMPAIGN-920_Wave0_Capability_Campaign_Plan.md`, decision 4). This overrides the
"do not start production implementation yet" line in PR-IMG-BACKEND-QUAL-100. It does not override that report's
architecture conditions, which this design adopts in full (section 3).

This package runs no model, starts no backend, uses no GPU and downloads nothing. No Qwen-Image weights are
installed on the owner host (checked 2026-11-18/19), so the model is never offered in the GUI until the owner
installs them. Physical qualification is a later, separately authorized step. Per owner decision 3 it is not a
promotion gate: the profiles ship saying "not yet physically qualified", the same way PR-IMG-120 does for
Ideogram 4.

## 2. Verified evidence

| Fact | Source |
|---|---|
| Pinned managed Comfy is v0.38.0 `6b747c04`, custom-node policy `none`, launch flags `--disable-pinned-memory --disable-auto-launch` | `config/managed_comfy_runtime.json` |
| Pinned source natively supports Qwen-Image (`QwenImage`) and Qwen-Image 2.1 (`QwenImage21`): `comfy/supported_models.py`, `comfy/ldm/qwen_image21/`, `comfy_extras/nodes_qwen.py::TextEncodeQwenImage21`, `QwenImage21Cache`, `CLIPLoader` type `qwen_image` | installed source, `%LOCALAPPDATA%/StableNew/ManagedComfy/v0.38.0-py313/source` (read only) |
| Pinned source has native `float8_e4m3fn`, `int8_tensorwise`, `convrot_w4a4`, `asym_w4a8_int8` and `nvfp4` layouts (`comfy/quant_ops.py`) and dynamic VRAM on by default. It has **no GGUF loader**: GGUF needs the third-party ComfyUI-GGUF custom node, which policy `none` forbids | same |
| The pinned runtime ships the official `image_qwen_image_2_1_t2i.json` template: `UNETLoader qwen_image_2.1_int8_convrot` -> `QwenImage21Cache auto/default` -> `KSampler 25 steps, cfg 1, euler, simple, denoise 1`; `CLIPLoader qwen3vl_8b_int8_convrot (qwen_image)` -> `TextEncodeQwenImage21 (resolution 1024)`; `EmptyLatentImage 1024x1024x1`; `VAELoader qwen_image_2.1_vae_bf16`; prompt enhancer switched off | `venv/.../comfyui_workflow_templates_json/templates/image_qwen_image_2_1_t2i.json` (read only) |
| Workstation: RTX 4070 Ti 12 GB VRAM, 31.8 GiB host RAM | task brief; `Win32_ComputerSystem` |
| No Qwen-Image generation weights installed (ComfyUI `diffusion_models`/`text_encoders`/`vae`, HF cache) | task brief, 2026-11-18/19 |
| PR #360 (open) adds `model_backend_routing.py` with an explicit additive slot for "a Comfy still-image backend", `RUNTIME_FAMILY_*`, and a model-routed backend identity at construction | `gh pr view 360`; branch `claude/img-120-ideogram4-diffusers-ce4097` |

### 2.1 Public model facts (Hugging Face metadata only; nothing downloaded)

`Comfy-Org/Qwen-Image-2.1` at revision `aacf31a6d48e707f352ecba714cee0680da3479b` (2026-10-29), repackaged from
`Qwen/Qwen-Image-2.1`: a 7B single-stream DiT that does text-to-image and editing with up to 10 references, with
native 2048-class output. **Licence: Qwen Research License, non-commercial (research or evaluation) only.**

| Role | File (Comfy folder) | Bytes | SHA-256 |
|---|---|---:|---|
| diffusion model | `qwen_image_2.1_int8_convrot.safetensors` (`diffusion_models`) | 7,256,783,064 | `cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d` |
| text encoder | `qwen3vl_8b_int8_convrot.safetensors` (`text_encoders`) | 9,350,798,360 | `8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f` |
| VAE | `qwen_image_2.1_vae_bf16.safetensors` (`vae`) | 675,509,688 | `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9` |
| alt: Turbo model (8 steps, cfg 1) | `qwen_image_2.1_turbo_int8_convrot.safetensors` | 7,256,787,829 | `8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c` |
| alt: smaller encoder | `qwen3vl_8b_w4a8.safetensors` | 6,312,105,364 | `7754425e55e7bea2bfde4dde59a4cc236cb44e5ee9c215ea66ef8d47012824eb` |

The base set is the official template's set: 17,283,091,112 bytes (16.1 GiB). Each component fits in 12 GB VRAM
by itself, and Comfy loads them in turn. Host-RAM residency of about 16 GiB fits 31.8 GiB. The accepted pair
(decision 1) adds the Turbo model, which shares the encoder and VAE: 24,539,878,941 bytes (22.9 GiB) on disk for
both. Only one diffusion model is loaded per job.

The Turbo graph is taken from the official `image_qwen_image_2_1_turbo_t2i.json` (Comfy-Org/workflow_templates,
`main`, read 2026-11-19; not shipped in the pinned template package): `ManualSigmas "1.0, 0.978453, 0.95418,
0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"` (8 steps), `KSamplerSelect euler`, `CFGGuider cfg 1`,
`RandomNoise`, `SamplerCustomAdvanced`. All of these node classes are in pinned
`comfy_extras/nodes_custom_sampler.py`.

Qwen-Image (original, 20B MMDiT, Apache-2.0) and Qwen-Image-2512, in `Comfy-Org/Qwen-Image_ComfyUI`:

| File | Bytes |
|---|---:|
| `qwen_image_fp8_e4m3fn.safetensors` / `qwen_image_2512_fp8_e4m3fn.safetensors` | 20,430,635,136 / 20,430,679,144 |
| `qwen_image_nvfp4.safetensors` | 19,769,139,136 (FP4 tensor cores are Blackwell-only; the 4070 Ti is Ada) |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | 9,384,670,680 |
| `qwen_image_vae.safetensors` | 253,806,246 |

A subsequent header-only inventory found the original FP8 checkpoint and Qwen VAE under renamed files in
the shared WebUI library. The original inventory scoped its search to the Comfy paths and Hugging Face cache,
so it missed these copies. The Qwen2.5-VL-7B encoder was absent from the inspected model library.

That set is about 30 GB of weights. Through core Comfy on 12 GB VRAM it runs only by offloading the 20 GB model
to host RAM. On 31.8 GiB of host RAM that is the same kind of resource risk that made FLUX.2 Klein 9B BF16
`NO_GO_RESOURCE_RISK`. The usual 12 GB answer, GGUF Q4/Q5, needs a custom node that policy `none` forbids.

### 2.2 Evidence limits

- The `int8_convrot` quantization layout is not proven to load on v0.38.0 with Ada int8 kernels. Comfy-Org
  published the files and the pinned runtime ships a template naming them, but only a physical run proves it.
- Speed, peak VRAM, RAM, cold load time and image quality on this workstation are unknown.
- The 2048-class native geometry is deferred; v1 offers the template's 1-megapixel class only.

## 3. Architecture invariants (unchanged)

`Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> image stage handler ->
ImageBackendRegistry -> ComfyImageBackend -> Artifacts/History`.

From PR-IMG-100 and PR-IMG-BACKEND-QUAL-100, this package keeps:

- One image backend per NJR (COA B). `comfyui` owns every image stage of its NJR and advertises only `txt2img`.
  `txt2img -> adetailer/img2img/upscale` fails in `validate_stage_chain` before dispatch. Forge and Comfy are
  never composed per stage, and nothing falls back to Forge.
- Backend identity is persisted in `backend_options.image.backend_id`. It is stamped at construction because the
  model requires it (the PR #360 `model_backend_routing` seam). It never becomes the new-work default.
- Comfy's queue and history are private to the backend. StableNew's SQLite queue and history remain the only
  lifecycle authority. One NJR makes one prompt and one image.
- The runtime is the existing `ComfyProcessManager`. External Comfy is never adopted, stopped or restarted.
  An ambiguous POST (`DispatchOutcomeUnknown`) is never replayed.
- The image and video registries stay separate. The image backend uses Comfy transport and runtime pieces; it
  does not join the video workflow registry or catalog.
- No `if qwen` in `PipelineRunner`. Model knowledge lives in the profile, policy and backend modules.

## 4. Alternatives considered

| Option | Verdict |
|---|---|
| **A. Typed adapter that reuses Comfy transport and runtime pieces by composition** (`ComfyApiClient`, `ComfyProcessManager`, `RuntimeTransitionCoordinator`, `workflow_asset_integrity.model_folders/verify_assets`, the pure prompt-observation predicates in `comfy_workflow_backend`), plus an image-owned frozen graph and profile | **Recommended.** No video file changes, so video behaviour cannot change. Same shape as PR #360. |
| B. Extract a shared Comfy prompt-session/lifecycle module used by both video and image | Rejected for this package: it edits the video dispatch path, which hits the "would change video behaviour" stop condition. Named follow-up once both callers exist and a video package can carry the regression. |
| C. Register still-image graphs in the video `WorkflowRegistry` and run them through `ComfyWorkflowVideoBackend` | Rejected: merges image and video registries (PR-IMG-100 item 29) and pulls video governance (frame counts, interpolation, controls) into images. |
| D. Run Qwen-Image through the PR #360 Diffusers child | Rejected for this item: the owner tied Qwen to the Comfy package. It would also need `QwenImage21Pipeline` from a newer Diffusers, which is a production dependency change. |
| E. GGUF through ComfyUI-GGUF | Rejected under node policy `none`. Widening it is a separate owner decision. |

### 4.1 Self-critique (one model; not an independent review)

- Weakest assumption: that `int8_convrot` plus dynamic VRAM really fits the 12 GB card on v0.38.0. Mitigations:
  (1) readiness requires the exact files by SHA-256 and the node classes and file names in Comfy's `object_info`
  before dispatch; (2) a pre-load free-VRAM and free-RAM floor from Comfy's own `system_stats`; (3) the owned
  runtime is released after every job; (4) physical qualification is still required before anyone calls it
  qualified. If the int8 layout fails at load time, the job fails with Comfy's error text and nothing is retried.
- Importing private (`_`-prefixed) pure helpers from the video module couples the two. It is read-only reuse
  of stateless predicates, imported lazily so the image path does not load the video module at import time. The
  coupling is named for the extraction follow-up instead of copying the logic.
- Hashing 16 GiB on every job would add minutes. Readiness hashes each file once per (path, size, mtime) per
  process and checks size on every job. That still proves the exact bytes before the first dispatch.

## 5. Placement and modules

All new production code is in `src/image_backends/`. No `src/video/` file changes.

| Module | Responsibility |
|---|---|
| `comfy_qwen_image_profile.py` | `QwenImage21Profile` v1, two frozen instances (base, Turbo): exact assets (repo, revision, file, folder, size, SHA-256), mode `txt2img`, fixed sampler/scheduler/steps/cfg, geometry list, one image, refusal rules. `validate_qwen_image_config`, `validate_qwen_image_njr`, `apply_qwen_image_compile_policy`, `is_qwen_image_model_name`. Pure. |
| `comfy_image_graphs.py` | Frozen graph catalog: `qwen_image_21_t2i` v1.0.0 builds the API-format prompt from a fixed template with typed substitutions (prompt, seed, width, height, filename prefix). Records its `template_sha256`, required node classes and required `CLIPLoader` type. Pure. |
| `comfy_image_readiness.py` | Offline installation check (`model_folders` + size; SHA-256 cached by path, size and mtime) for the GUI offer and dispatch. Live checks on a running owned Comfy: `object_info` node classes, file names and encoder type; `system_stats` VRAM and RAM floors. |
| `comfy_image_backend.py` | `ComfyImageBackend` (`backend_id="comfyui"`, `runtime_family="comfy"`, stages `("txt2img",)`): validate -> lease -> runtime -> probe -> floors -> dispatch once -> observe/cancel -> localize -> artifacts -> release. |

Small additive edits: `image_backend_types.py` (`COMFY_IMAGE_BACKEND_ID`, `RUNTIME_FAMILY_COMFY`),
`image_backend_registry.py` (register), `backend_capabilities.py` (map), `model_backend_routing.py` (one
resolver and one offer), `exact_model_profile.py` and `model_policy.py` (profile -> `FAMILY_QWEN_IMAGE` policy and
compile policy), `__init__.py` exports. `pipeline_runner.py` is unchanged: the PR #360 `runtime_family` check
already skips WebUI cleanup for non-WebUI backends.

## 6. Runtime and GPU exclusivity

1. `RuntimeTransitionCoordinator.prepare_for(RUNTIME_COMFY)` is the existing target the video backend uses. It
   releases the StableNew-owned WebUI-family runtime and the native SVD cache through their owners. An external
   WebUI occupant gives `ACTION_REQUIRED` and the job is refused. The PR #360 Diffusers child exists only inside
   its own job; one runner runs one job at a time, so no Diffusers child exists when a Comfy job starts.
2. The backend requires a **StableNew-owned** managed Comfy launched with the managed policy flags
   (`ComfyProcessManager.ensure_running(required_flags=...)`, then `owns_process`). An external Comfy at the
   configured URL is refused. StableNew cannot release it and cannot account for its VRAM. This is stricter than
   the video default, on purpose.
3. A pre-load floor reads Comfy's own `system_stats` (`devices[0].vram_free`, `ram_free`). Proposed: at least
   10 GiB free VRAM and 12 GiB free host RAM. These are proposals that qualification must confirm. Below the floor
   the job is refused with "another program is using the GPU/RAM; StableNew released its own runtimes".
4. Graph runtime policy `release_owned_runtime_after_job: true`. After every job, success or failure, the owned
   Comfy is stopped through `ComfyProcessManager.stop()` only, the same as the A14B policy. Warm reuse is a
   later optimisation once qualification has measured release behaviour.

Exclusivity is guaranteed against StableNew's own runtimes (Forge/A1111, Comfy video, Diffusers, native SVD).
For anything outside StableNew it is checked (floors, external refusal), not guaranteed. No stop condition is hit.

## 7. Graph catalog: `qwen_image_21_t2i` v1.0.0

API-format nodes, mirroring the official template with the prompt enhancer removed:

```text
1 UNETLoader            unet_name=qwen_image_2.1_int8_convrot.safetensors, weight_dtype=default
2 QwenImage21Cache      model=[1,0], device=auto, dtype=default
3 CLIPLoader            clip_name=qwen3vl_8b_int8_convrot.safetensors, type=qwen_image, device=default
4 VAELoader             vae_name=qwen_image_2.1_vae_bf16.safetensors
5 TextEncodeQwenImage21 clip=[3,0], prompt=<prompt>, negative_prompt="", resolution=1024
6 EmptyLatentImage      width=<w>, height=<h>, batch_size=1
7 KSampler              model=[2,0], positive=[5,0], negative=[5,1], latent_image=[6,0],
                        seed=<seed>, steps=25, cfg=1.0, sampler_name=euler, scheduler=simple, denoise=1.0
8 VAEDecode             samples=[7,0], vae=[4,0]
9 SaveImage             images=[8,0], filename_prefix=stablenew/<job>/<name>
```

Geometry v1 (multiples of 16, the template's 1-megapixel class, half of the official 4 MP aspect table):
1024x1024, 1200x896, 896x1200, 1264x848, 848x1264, 1376x768, 768x1376. Negative prompt: refused (at cfg 1 the
negative branch is not sampled; accepting text that has no effect would mislead). Steps, cfg, sampler and
scheduler are fixed. Seed `-1` is resolved by StableNew before dispatch and recorded. Batch is always 1.

### 7.1 `qwen_image_21_turbo_t2i` v1.0.0

The same loaders, cache, text encode, empty latent, decode and save nodes, with the Turbo diffusion model and the
official Turbo sampler chain in place of `KSampler`:

```text
1 UNETLoader            unet_name=qwen_image_2.1_turbo_int8_convrot.safetensors, weight_dtype=default
7 RandomNoise           noise_seed=<seed>
10 KSamplerSelect       sampler_name=euler
11 ManualSigmas         sigmas="1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"
12 CFGGuider            model=[2,0], positive=[5,0], negative=[5,1], cfg=1.0
13 SamplerCustomAdvanced noise=[7,0], guider=[12,0], sampler=[10,0], sigmas=[11,0], latent_image=[6,0]
8 VAEDecode             samples=[13,0], vae=[4,0]
```

It uses the same geometry list, one image per job and the same refusals. The 8 steps come from the frozen sigma
list. It does not offer a steps control.

The graphs are frozen by version. Any node, value or asset change is a new version. The catalog records
`template_sha256` over the canonical template, and the manifest records the hash of the prompt actually sent.

## 8. Model, policy and readiness

- Profile v1 matches the model by the exact diffusion-model filename (the GUI offers it under that identity,
  with display name "Qwen-Image 2.1 (Comfy)"). `model_backend_routing` maps it to `comfyui` for new work.
- `ModelPolicy`: family `qwen_image`, evidence `exact_profile`, `required_backend="comfyui"`, stages `txt2img`
  only. Sampler, scheduler, steps, cfg and VAE are fixed; geometry is a restricted choice. LoRA, embeddings,
  hypernetworks, ControlNet/OpenPose and every extra stage are unsupported. Prompt dialect is natural language.
  The note states the licence, "not yet physically qualified", and that each job loads the model again.
- Offline readiness (GUI offer, no I/O beyond `stat` and a cached hash): every pinned file is present in the
  configured Comfy model folders at its exact size. The GUI offers the model only then. Dispatch readiness also
  checks the SHA-256 (cached), then the live `object_info` and `system_stats` checks above. Nothing is ever
  downloaded or moved.

## 9. Execution: dispatch, observation, cancellation

`execute` runs a fixed, fail-closed sequence:

1. **Validate** (pure): stage `txt2img`, profile v1, exact model, no input image, empty negative prompt, frozen
   controls, listed geometry, one image. The same rules run in `validate_njr_intent` before any stage dispatch.
2. Cancel check. **Assets**: exact files by size and SHA-256.
3. **Lease**: `prepare_for(RUNTIME_COMFY)`; not ready -> `RuntimeTransitionError`.
4. **Runtime**: owned managed Comfy with required flags; external -> refused.
5. **Probe**: `object_info` has every node class, the three file names in the loader option lists, and
   `qwen_image` among the `CLIPLoader` types.
6. **Floors**: `system_stats` VRAM and RAM.
7. Cancel check, then **dispatch once**: `queue_prompt` with a caller-chosen UUID `prompt_id` and `client_id`.
   `DispatchOutcomeUnknown` fails the job and is never retried.
8. **Observe**: poll `/history/<prompt_id>` with the video module's pure predicates (ready, failed, failure
   detail, live-queue membership). Progress is liveness only ("Qwen-Image: executing (Ns)"); no invented
   percentages. Timeout cap 900 s (proposal). On timeout, the job cancels its own prompt and fails.
9. **Cancel**: the runner's cancel token is polled between steps and inside the wait. The backend interrupts its
   own prompt by id if running, deletes it if pending, and raises `CancellationError`. JobService and the
   repository stay the lifecycle authority.
10. **Release** the owned runtime on every exit path (`BaseException`), never masking the original error.

## 10. Outputs, provenance and refusals

- Comfy's `SaveImage` output is fetched with `download_view` into the StableNew run directory, which is the
  artifact authority. Exactly one generated PNG is required, at the requested size. It is re-saved with
  StableNew's embedded metadata contract (pixels unchanged) and gets a per-image manifest in the executor's
  result shape: `ImageExecutionResult.from_stage_result`, canonical artifact record, `image_backend_id=comfyui`.
- Provenance: model profile reference; asset identity (repo, revision, filenames, SHA-256); graph id, version,
  `template_sha256` and submitted-prompt SHA-256; prompt id; Comfy version and revision from `system_stats`;
  seed; geometry; lease, floor and release evidence; licence string.
- Refusals before dispatch: any non-`txt2img` stage; negative prompt; LoRA, embedding, hypernetwork, ControlNet,
  OpenPose, ADetailer; input image; batch above 1; unlisted geometry; steps, cfg, sampler or scheduler other than
  frozen; profile/backend mismatch; external Comfy; Comfy autostart off; missing or mismatched weights; missing
  node class, file or encoder type; VRAM or RAM floor not met; external WebUI occupant. After dispatch: Comfy
  execution error (its text kept), timeout, wrong output count or size, ambiguous dispatch. None is retried, and
  none falls back.

## 11. Test strategy (hermetic only)

No GPU, model, network, real Comfy or GUI display. A fake `ComfyApiClient`, a fake process manager and a fake
transition coordinator are injected (the `fake_comfy` helpers and PR #360 patterns).

- Profile and graph: frozen values, the geometry list, the refusal matrix, deterministic graph build and digest,
  every required node present, substitution only of typed slots.
- Readiness: synthetic files in temp model folders (size mismatch, SHA mismatch, missing, cached hash); probe
  with and without node, file or encoder type; floor pass and fail.
- Backend: happy path through dispatch -> history -> download -> PNG re-save -> manifest -> result; one POST
  only; `DispatchOutcomeUnknown` not retried; history failure detail kept; timeout cancels own prompt; cancel while
  running interrupts by id and while pending deletes; external Comfy refused; transition `ACTION_REQUIRED`
  refused; release on success, failure and cancel; wrong output count or size refused.
- Canonical path: a `txt2img` NJR for the profile goes through JobService -> SQLite -> `run_njr` -> `comfyui`
  with fakes, and `txt2img+adetailer` is refused before dispatch.
- Model policy and GUI projection: offered only when installed; policy controls; construction stamps
  `comfyui`; compile policy pins the frozen values.
- Coverage matrix: a `qwen-image-comfy-txt2img` row, `integration_only`, physical NOT RUN.

## 12. Owner decisions

Asked in this session with AskUserQuestion; answers recorded 2026-11-19.

| # | Decision | Recommendation given | Owner answer |
|---|---|---|---|
| 1 | Model, variant, quantization | Qwen-Image 2.1 base, `int8_convrot` model + `qwen3vl_8b_int8_convrot` encoder + bf16 VAE (official template set, 16.1 GiB, research licence) | "Do both 1 and 2, so we can compare." Both base int8 and Turbo int8 ship as two exact profiles with their own frozen graphs. They share the encoder and VAE (22.9 GiB on disk in all). The owner installs the weights, or approves a download, separately. |
| 2 | First slice scope | `txt2img` only | `txt2img` only. Reference edit is a follow-on package. |
| 3 | Matched Forge-vs-Comfy qualification before promotion | Gate on a Qwen-specific physical qualification only | **No gate.** Ship as "not yet physically qualified" (like Ideogram 4) and qualify later. The SDXL/Klein matched arm is not required. |
| 4 | Branch base (coordination with PR #360) | Stack on PR #360's branch | Stack on #360. Target `main`; merge `origin/main` once #360 merges. |

## 13. Implementation acceptance contract

1. A Qwen-Image `txt2img` NJR reaches `ComfyImageBackend` only through JobService -> SQLite -> `run_njr`.
2. Unsupported stages and features fail before any runtime start or dispatch.
3. Exactly one Comfy prompt is submitted per NJR; ambiguous dispatch is never replayed.
4. Only a StableNew-owned Comfy is used. It is leased through `prepare_for(RUNTIME_COMFY)` and released after
   the job.
5. Artifacts are in the StableNew run directory with embedded metadata, a manifest and provenance (section 10).
6. GUI offers the model only when its exact files are installed. Policy pins the frozen controls.
7. No video file changes and no new production dependency. Coverage matrix row added; ledger statuses unchanged.

Exclusions: physical runs, weight download, reference edit, 2048-class geometry, Turbo LoRAs, LoRA, prompt
enhancer, warm-runtime reuse, matched Forge comparison, default switch, shared Comfy-session extraction.

> Superseded in part by owner request (2026-11-22, PR-IMG-COMFY-381): the "default switch" and "matched Forge comparison"
> exclusions no longer apply. The operator can now choose ComfyUI as the default still-image backend (setting
> `image_backend_default`), SDXL txt2img runs there, and a Forge-vs-ComfyUI comparison package exists. Forge stays the shipped
> default; Qwen-Image behavior is unchanged.
>
> Warm reuse (PR-IMG-COMFY-382): the SDXL path now holds the owned ComfyUI after a successful job through the shared
> `runtime_warm_hold` slot (VID-WARM-373) instead of stopping it, for `comfy_image_keep_warm_seconds` of idle time (default 60,
> `0` restores release-after-every-job). Another job preparing any runtime, a failure, the idle grace or application exit ends it.
> Qwen-Image keeps its qualified release-after-every-job policy; the "warm-runtime reuse" exclusion above no longer applies to SDXL.

## 14. Stop conditions and authorization boundaries

Stop and ask the owner if: a second queue, runner, history store or GUI shortcut becomes necessary; GPU
exclusivity against StableNew's own runtimes cannot be guaranteed; a production dependency must be added or
upgraded; a custom node or managed-runtime change is needed; shared transport or lifecycle extraction would change
video behaviour. Weight download, any physical run, merging and ledger status changes each need separate owner
authorization.

## 15. Model recommendation

Claude Code: Opus 5.5, high effort (architectural, cross-boundary). Codex: GPT-6.1 Sol High. Local/Desktop host,
because readiness facts come from the owner's managed runtime. Controller surface: none touched; the GUI uses the
PR #360 model-list seam. Token-efficient validation: focused tests, then architecture ratchets, `pytest
tests/tools`, one PR gate and `git diff --check`.
