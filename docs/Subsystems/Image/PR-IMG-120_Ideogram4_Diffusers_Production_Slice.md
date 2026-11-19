# PR-IMG-120 — Ideogram 4 NF4 Diffusers Production Slice

Status: **DESIGN ACCEPTED (owner decisions 2026-11-18, section 14); implementation on this branch.** Not qualified:
no physical run has been made.

| Item | Value |
|---|---|
| Execution class | Architectural (new image backend runtime, new GPU-runtime transition target, new contained child, new dependency) |
| Model recommendation | Claude Code: Opus 5.5, high effort (design and build in one session). Codex: GPT-5-class frontier model, high reasoning. No preferred host. |
| Task start | 2026-11-19T02:17:44Z (2026-11-18 local) |
| Sessions | `ed54169a-46b1-4837-84fe-e7527f4bd311` (this design/build session), started from `local_d31afe93-baab-47ac-8524-0eb1c639819f` |
| Base | `main` @ `2d179a38` (worktree `img-120-ideogram4-diffusers-ce4097`, branch `claude/img-120-ideogram4-diffusers-ce4097`) |

## 1. Owner authorization and licence

On 2026-11-18 the owner wrote: *"Bring Ideogram 4 in. The license works for me, this is all non-commercial work for
StableNew."*

- This authorizes PR-IMG-120, the production slice that STATUS open decision 7 and roadmap row P3 held as unauthorized.
- It accepts the **Ideogram 4 Non-Commercial licence** (`LICENSE.md` in the pinned weight snapshot) for StableNew's
  non-commercial use. Commercial use is not covered by this decision.
- It does **not** authorize a physical run, starting a backend, using the GPU or downloading weights. Physical
  qualification of this slice needs the owner's own later authorization of an exact plan (`docs/runbooks/qual_system_840.md`
  section 2).

## 2. Repository identity and evidence limits

- Repository `destroyer42/StableNew2`, `main` @ `2d179a38`, clean worktree, fast-forward to `origin/main` verified.
- Evidence read: `AGENTS.md`, `STATUS.md`, roadmap P3 and the PR-IMG-120 section, `docs/ARCHITECTURE_v2.6.md` (sections
  on the canonical path), PR-IMG-100, PR-IMG-110, PR-IMG-110R, `tools/qualification/img110r/`, `src/image_backends/`,
  `src/services/runtime_transition_service.py`, `src/utils/managed_process.py`, `src/conditioning/reference_map/`
  (the existing contained-model-child precedent), the pipeline runner's image dispatch and stage handlers, the model
  policy and exact-profile modules, the GUI model list, and ledger entry `IMG-Q4.ideogram4-diffusers`.
- Facts verified read-only on 2026-11-18:
  - The pinned Diffusers snapshot `ideogram-ai/ideogram-4-nf4-diffusers@1874bc70267ba2c823a7239e1d70dd308c8d64dc` is
    in the owner's Hugging Face cache, and `refs/main` equals the pin. It holds `text_encoder`, `transformer`,
    `unconditional_transformer`, `vae`, `tokenizer`, `scheduler` and `model_index.json`; it has no
    `prompt_enhancer_head`, so prompt upsampling is unavailable by construction. `ideogram-ai/ideogram-4-nf4` is also present.
  - Main venv: CPython 3.14.9, torch 2.14.0+cu130, diffusers 0.40.0 (contains `Ideogram4Pipeline`), transformers 5.17.0,
    accelerate 1.15.0, safetensors 0.8.0 — all already pinned in `constraints/windows-py314-cu130.txt`.
  - **`bitsandbytes` is not installed in the main venv and is not pinned anywhere.** Loading the NF4 weights requires it.
    110R used `bitsandbytes 0.50.2`, whose wheel is tagged `py3-none-win_amd64` (interpreter-independent), so it is
    expected to install on 3.14; that is not yet verified on the production interpreter.
- Limits: no model was run, no backend started, no GPU touched (by brief). 110R ran on Python 3.11 in disposable venvs;
  this slice runs on the production 3.14 interpreter, so the measured envelope transfers by code identity
  (same diffusers release, same weights, same residency policy) but is **not yet measured on 3.14**. On 3.12+ the
  release pipeline's `callback_on_step_end` (`locals()` inside a comprehension, `pipeline_ideogram4.py:717`) is
  expected to work (PEP 709), but this design does not depend on it (section 7.3).

## 3. Problem and decisions to make

Operator outcome: choose "Ideogram 4 NF4" as the model, write a prompt (plain text or a structured caption), queue it
like any other image job and get a reproducible PNG with full provenance in History, without StableNew ever running two
GPU-heavy runtimes at once.

Design uncertainty, each resolved below or put to the owner:

1. **Runtime ownership**: in-process, per-job contained child, or warm resident child — and how the GPU is leased
   exclusively against Forge/A1111, managed Comfy and native SVD.
2. **Residency policy**: 110R's harness becomes product code, with an allocator cap and fail-closed floors.
3. **Prompt mapping**: PromptPack/NJR prompt text to Ideogram's structured JSON caption with the official
   `CaptionVerifier` semantics.
4. **Model identity, policy and GUI exposure**, routed without a second backend selector.
5. **Dependency**: `bitsandbytes` must enter the production environment (stop condition: owner decision).

## 4. Invariants and ownership (unchanged by this slice)

- Canonical path `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler ->
  Artifacts/History`. The new backend is one `ImageBackendInterface` behind the existing `ImageBackendRegistry`,
  invoked by the existing `Txt2ImgHandler` through `PipelineRunner._execute_image_backend`. No second queue, runner,
  history, lifecycle, cancellation or compiler authority; no GUI-to-backend call.
- PR-IMG-100 COA B: one typed image backend per image NJR, persisted in `backend_options.image.backend_id`; an
  unsupported stage is refused before dispatch; no fallback between backends.
- PR-IMG-100 section 2: backend/runtime, model family and model identity stay separate; no model-named backend class
  as the public architecture. Hence the backend id is the runtime family **`diffusers`**, and Ideogram 4 is a
  model-family adapter inside it, selected by an exact immutable profile.
- `RuntimeTransitionCoordinator` (PR-RUNTIME-100) stays the only place that releases conflicting StableNew-owned GPU
  runtimes; each runtime's own owner keeps its lifecycle. External runtimes are never adopted, stopped or restarted.
- `src/utils/managed_process.py` stays the only child-process containment primitive.
- Same-process, single-node execution: the job still executes inside the single runner; the child is a contained
  model runtime owned by the backend for one job (the same shape as the reference-map model child), **not** a revival of
  the retired child runtime host (it owns no queue, NJR, history or job lifecycle and exits with its job).
- Required CI stays hermetic: no real model, GPU, network or runtime.

## 5. Where the backend sits

```text
GUI (model dropdown: "Ideogram 4 NF4 (Diffusers)")       captures intent only
  -> Compiler: apply_model_compile_policy -> Ideogram compile policy
       freezes profile ref, preset, geometry, seed, caption (mode + canonical JSON + sha256)
       stamps backend_options.image = {backend_id: "diffusers", model_profile: {id, version}}
  -> immutable NJR -> JobService.submit_njrs -> SQLite queue/repository
  -> PipelineRunner.run_njr
       _resolve_image_backend_id: validate_stage_chain("diffusers", ["txt2img"]) + validate_njr_intent
  -> Txt2ImgHandler -> _execute_image_backend -> ImageBackendRegistry.get("diffusers")
  -> DiffusersImageBackend.execute(pipeline, request)
       1. pure re-validation of the frozen intent (profile, caption, envelope)
       2. GPU lease: RuntimeTransitionCoordinator.prepare_for("diffusers")
       3. preflight floors: driver-visible free VRAM, host RAM, weights present at the pin, runtime packages present
       4. run_bounded(child, memory limit, timeout, cancel, record_ownership)  -- residency policy runs in the child
       5. teardown proof: child exited + container proves no survivor; post-exit VRAM observation recorded
       6. PNG + embedded metadata + per-image manifest written by the parent
  -> ImageExecutionResult -> existing artifact / History / replay
```

## 6. Process and runtime ownership (the GPU residency lease)

### 6.1 Alternatives

| | A. Per-job contained child (recommended) | B. Warm resident child | C. In-process (like native SVD) |
|---|---|---|---|
| Shape | `run_bounded` child per job: load, encode, generate N images, exit | `ManagedProcess` server kept loaded between jobs; a new owned runtime | Diffusers pipeline inside the app process |
| VRAM release proof | Process exit; container proves no survivor; driver frees all memory | Must stop the server; needs a new process manager and coordinator release entry for every other target | Impossible to prove: CUDA context, caching allocator and bitsandbytes state stay in the app |
| Host RAM | ~30 GiB commit lives and dies with the child; job-object limit caps it | Held while idle (a 32 GB host cannot also run Forge comfortably) | ~30 GiB commit inside the GUI process |
| Fault blast radius | Child crash or device fault kills only the child | Same, plus stale-state recovery | A CUDA fault or OOM can take down the app and queue |
| Cancellation | Kill the contained tree (already proven by `run_bounded`) | IPC cancel plus kill fallback | Cooperative hook only |
| Latency | +~18-20 s component load per job (110R, Diffusers); generation 60-312 s | Load amortized | Load amortized |
| New lifecycle surface | None (reuses `run_bounded`) | New process manager, IPC protocol, health, idle policy | SVD-like cache plus release hook |
| Coordinator change | Add one target that releases the others; nothing to release later because nothing lingers | Add target and add "release Diffusers server" to every other target | Add target and add cache release to every other target |

C is rejected: VRAM release cannot be proven in-process and a 30 GiB load inside the GUI process is unsafe on the
target host. B is a later optimization (it can reuse A's worker protocol) once real use shows the per-job load matters.

### 6.2 Lease sequence (recommended A)

1. **Claim**: `RuntimeTransitionCoordinator.prepare_for(RUNTIME_DIFFUSERS)` (new target `"diffusers"`). Conflicts:
   whichever WebUI-family runtime StableNew owns, owned Comfy, and the SVD cache — the same release set and the same
   owner-delegated release boundaries the `comfy` and `svd_native` targets already use. An external or ambiguous
   occupant yields `ACTION_REQUIRED` and the job is refused before any load; an owned release that fails yields
   `RELEASE_FAILED`. No target needs to release Diffusers, because the child never outlives its job.
2. **Exclusivity against everything else**: jobs are serialized by the single runner, so no other StableNew GPU job can
   start during the child's life. Non-StableNew GPU use is caught by the floors in section 7.2 (refusal, not a wait).
   Residual risk: an operator who manually starts a WebUI from the GUI during an Ideogram job can still contend; the
   allocator cap turns real exhaustion into an explicit OOM failure instead of a silent spill, and the job timeout
   bounds a slow spill. This is the same guarantee the Comfy and SVD targets rely on today.
3. **Release and proof**: the child exits after its last image (or is killed on cancel/timeout). `run_bounded(...,
   record_ownership=True)` terminates any survivor and proves from the job object that no process of the tree remains
   before the container is released; the Windows driver then reclaims the child's whole CUDA context. The backend
   records the ownership evidence and a post-exit driver-visible VRAM reading (`nvidia-smi`, observational) in the
   image manifest. The parent never initializes CUDA.

## 7. Residency policy as product code

### 7.1 Envelope (measured in 110R; nothing outside it is offered or accepted)

- Presets (official registry values, asserted in tests): `V4_TURBO_12` (12 steps, mu 0.5, std 1.75),
  `V4_DEFAULT_20` (20, 0.0, 1.75), `V4_QUALITY_48` (48, 0.0, 1.5), with the official guidance schedules passed to
  Diffusers first-step-first (the reversed official order).
- Geometry: 1024x1024 (default), 768x1024, 1024x768, 768x768, 512x512. No side above 1024 (2048 was never tested).
- 1-4 images per job, seeds `seed + i`; a requested seed of -1 is resolved by the backend before launch and recorded.
- No negative prompt (the model's unconditional branch carries no text), no LoRA, embeddings, hires, refiner,
  ADetailer, upscale, img2img, ControlNet or prompt optimizer; txt2img only.

### 7.2 Floors and caps (fail closed, before any load)

| Check | Where | Value | Basis |
|---|---|---|---|
| Driver-visible free VRAM | parent, `nvidia-smi` | >= 10,700 MiB | Diffusers swap peak reserved 10.2 GiB (10,445 MiB) plus CUDA context margin |
| Allocator cap | child, after CUDA init | `min(11,200, free_after_context - 256)` MiB via `torch.cuda.set_per_process_memory_fraction`; refuse if below 10,445 MiB | 110R cap 11,200 MiB; real exhaustion becomes an explicit OOM instead of spill |
| Host RAM available | parent, `psutil` | >= 16 GiB | 110R: Diffusers component load near 30 GiB commit with 8.9 GB free minimum from 20-27 GB free |
| Child commit limit | job object | 36,864 MB | ~30 GiB measured plus 20 %; a runaway is stopped by the OS, not the host |
| Weights | parent | snapshot dir at the exact pin, every component file present | no download path exists (`HF_HUB_OFFLINE=1`, `local_files_only=True`) |
| Runtime packages | parent | `torch`, `diffusers` with `Ideogram4Pipeline`, `transformers`, `bitsandbytes` importable specs | absence means the model is not offered and queued work is refused |
| Wall-clock timeout | parent | 300 s + images x steps x 20 s | measured ~6.5 s/step at 1024x1024; 3x headroom; a spill (~60 s/step) times out |

### 7.3 Child sequence (`diffusers_worker`, run as `python -I <worker> <job dir>`)

The child is the 110R `staged_swap` path, restructured as testable classes with torch and Diffusers injected:

1. Environment forced by the parent: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, an
   env allowlist, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False` left at default (not changed).
2. Init CUDA, read `mem_get_info`, apply the allocator cap (refusal code if too low).
3. Load `text_encoder` (`Qwen3VLModel`), `transformer` and `unconditional_transformer` (`Ideogram4Transformer2DModel`)
   **one at a time**, each with `revision=<pin>`, `torch_dtype=bfloat16`, `local_files_only=True`, parked on the CPU
   before the next; then `Ideogram4Pipeline.from_pretrained(..., **parts)`. The default `from_pretrained` puts all 15 GiB
   on the GPU and OOMs under the cap (110R).
4. Tokenize the caption with the pipeline's chat template; `max_sequence_length` = exact token count (refuse above
   2048). Text encoder to GPU, `encode_prompt` once, encoder back to CPU, `empty_cache`.
5. VAE to GPU; transformers stay on the CPU; the execution device is pinned to CUDA.
6. Forward pre-hooks swap the conditional and unconditional transformers (`park.to("cpu")`, `bring.to(cuda)`), so
   exactly one ~4.9 GiB transformer is resident at a time. The same pre-hook on the conditional transformer is the
   step boundary: it writes progress and checks a cancel file. Progress and cancel do not use `callback_on_step_end`.
7. Call the pipeline with the cached embeddings (encode_prompt replaced by the cached value), the preset's steps,
   schedule, mu, std and `torch.Generator("cuda").manual_seed(seed)`; write each PNG to the job dir; write `result.json`
   with seeds, timings, peak allocated/reserved and the applied cap.
8. Exit. Nothing is cached between jobs.

## 8. Prompt handling

### 8.1 Caption verification (official semantics, independent implementation)

`src/image_backends/ideogram4_caption.py` re-implements the rules of the official `CaptionVerifier`
(`ideogram4/caption_verifier.py`, ideogram-oss/ideogram4 @ `990fe1c4`), read in the 110R reference venv; the
code is written independently, not copied. Rules: root must be an object with only `high_level_description`,
`style_description`, `compositional_deconstruction`; `compositional_deconstruction` required with string
`background` and list `elements`, in that key order; `style_description` has exactly one of `photo` / `art_style`, with
the photo order `aesthetics, lighting, photo, medium[, color_palette]` or the non-photo order `aesthetics, lighting,
medium, art_style[, color_palette]`; elements are `obj` (`type, [bbox], desc[, color_palette]`) or `text` (`type,
[bbox], text, desc[, color_palette]`); bbox is four ints in [0, 1000] with ymin <= ymax and xmin <= xmax; palettes are
uppercase `#RRGGBB`, at most 16 (style) or 5 (element); raw text that escapes non-ASCII as `\uXXXX` with no literal
non-ASCII is flagged. **StableNew treats every verifier warning as a refusal** (the official pipeline's
`raise_on_caption_issues=True` default). Serialization is compact (`separators=(",", ":")`, `ensure_ascii=False`),
exactly as the official guide and 110R.

### 8.2 Mapping (owner decision 2)

Recommended: **both**, decided by the prompt text itself, frozen at compile time:

- **Authored**: a positive prompt that parses as a JSON object is the operator's caption. It must pass the verifier;
  otherwise the job is refused with the verifier's findings (never silently rewritten).
- **Automatic**: any other prompt becomes the minimal valid caption
  `{"high_level_description": <text>, "compositional_deconstruction": {"background": "", "elements": []}}`, after the
  shared model-aware adaptation (`src/prompting/prompt_adaptation.py`, natural-language dialect) flattens weighted
  attention and BREAK. LoRA and embedding tokens are refused. Automatic captions are valid but off the model's preferred
  distribution; quality is unqualified and the GUI note says so.
- As built: the NJR freezes the adapted positive prompt; the caption is derived from it **deterministically** under
  `CAPTION_MAPPING_VERSION = 1` (same prompt, same caption bytes, same SHA-256) at admission, in the backend and in the
  child, and `caption_mode`, the canonical caption JSON, its SHA-256 and the mapping version are recorded in every image
  manifest. The child re-verifies the caption and its SHA-256 before inference. A replay re-derives the identical caption
  from the identical frozen prompt; any future change to the mapping must bump the version and keep v1 derivation for
  replay. No extra NJR field is added, so the NJR schema is unchanged.
- Negative prompt, global positive/negative terms and the prompt optimizer: PromptPack and generic compilation clear
  them and record the adaptation (the Klein/Z-Image precedent); a manual non-empty negative prompt is refused.
- No prompt upsampling (no `prompt_enhancer_head` in the pin; it would also be a second model).

## 9. Model policy, profile, routing and GUI

- **Exact profile** `src/image_backends/diffusers_ideogram4_profile.py`: `Ideogram4Profile` v1 (`ideogram4_nf4_diffusers`,
  version 1, backend `diffusers`, repo + pinned revision, component subfolders, presets, geometries, image limit,
  residency constants). Model identity name: `ideogram-4-nf4-diffusers@1874bc70` (whole-name match only).
- **Exact-profile dispatch** (`exact_model_profile.py`): additive branch for the new profile id in
  `resolve_model_profile`, `model_profile_for_model`, `validate_profile_njr`.
- **Model policy** (`model_policy.py`): `policy_for_profile` gains the Ideogram policy — family `ideogram4`,
  `required_backend="diffusers"`, stage txt2img only, sampler/scheduler/CFG/VAE fixed, steps restricted to 12/20/48
  (the preset), geometry restricted to the envelope, every optional feature unsupported, prompt dialect
  `ideogram4_caption`, and an operator note. `resolve_model_policy` recognizes the identity; `apply_model_compile_policy`
  and `ModelPolicyResult.project_flat` gain the Ideogram compile policy.
- **Routing** (small, additive, shared with the coming Comfy/FLUX packages): `normalize_image_backend_options` asks one
  function, `required_backend_for_model(model_name)`, for a model that requires a non-WebUI backend; for new work with no
  explicit identity it stamps that backend instead of the configured WebUI identity. An explicit conflicting identity is
  kept and then refused by the profile (never switched).
- **Registry**: `build_default_image_backend_registry` registers `DiffusersImageBackend` (lazy: nothing heavy imports).
  `ImageBackendCapabilities` gains `runtime_family` (default `"webui"`); the runner skips the WebUI pre-job memory
  cleanup for non-WebUI families (it would POST to a WebUI that the lease just stopped).
- **GUI** (owner decision 4): recommended — one entry "Ideogram 4 NF4 (Diffusers)" appended to the Base Generation
  model list only when the offline readiness check passes (packages importable, pinned snapshot complete); selecting it
  projects the policy through the existing model-policy panel projection (fixed controls shown read-only, steps as the
  preset choice, geometry choices, the note). Prompts are typed in the existing prompt box (plain text or JSON caption).
  No new tab, no backend selector, no controller growth (`app_controller.py` is at its 5,010-line ceiling).

## 10. Failure and refusal behaviour

All refusals happen before the child launches unless marked; none falls back to another backend or retries.

| Condition | When | Behaviour |
|---|---|---|
| Stage other than txt2img, LoRA/embeddings/input images, negative prompt, geometry/steps outside envelope | compile, admission (`validate_njr_intent`), execute | typed `Ideogram4ProfileError`, job refused |
| Caption fails verification | compile, execute, child | refused with the verifier findings |
| Runtime packages or pinned weights missing | readiness (GUI hides the model), execute | refused: "Ideogram 4 is not installed" with the missing item |
| Coordinator `ACTION_REQUIRED` / `RELEASE_FAILED` | execute | `RuntimeTransitionError` (existing) |
| Free VRAM or host RAM below floor | execute (parent) | refused naming the measured and required values |
| Allocator cap below required | child | `vram_insufficient` result, job failed |
| CUDA OOM under the cap | child | `out_of_memory` result, job failed; teardown still proven |
| Token count above 2048 | child | `caption_too_long`, job failed |
| Cancel | any time | contained tree killed, job cancelled (existing `CancellationError`), no partial images registered |
| Timeout | parent | tree killed, job failed `timeout` |
| Child crash / non-zero exit / unreadable result | parent | job failed with bounded stderr tail; no replay |
| Containment or memory limit cannot be established | parent | not run (`run_bounded` launch_error) |

## 11. Artifacts, provenance and replay

The parent saves each PNG into the run directory with StableNew's embedded metadata contract (`build_contract_kv`) and
writes `manifests/<stem>.json` with: profile ref, repo + revision, preset, geometry, requested and actual seeds, caption
mode, caption JSON and SHA-256, token count, backend id, applied allocator cap, peak allocated/reserved, load/encode/
generate timings, lease result (`RuntimeTransitionResult.to_dict()`), floors observed, ownership evidence and post-exit
VRAM. The result dict has the executor's shape (`path`, `all_paths`, `manifest_path`, `artifact`) so History, Review and
replay need no change. Replay builds a new NJR from the frozen record on the same path.

## 12. Test strategy (hermetic)

- Profile and policy: envelope, presets equal the official values (guidance reversed), identity matching, policy
  projection, compile policy freezing and refusals, flat projection, routing for new and explicit identities.
- Caption: every verifier rule, serialization, both mapping modes, adaptation refusals; a cross-check against 110R's
  fixed caption.
- Residency (child classes with fake torch/Diffusers modules): components loaded one at a time and parked on CPU,
  encoder released before transformers, exactly one transformer resident at every forward, cap computed and refused
  correctly, cancel file raises at a step boundary, OOM classified, result document shape.
- Backend: refusal ordering (validate -> lease -> floors -> launch), coordinator fake (READY / ACTION_REQUIRED /
  RELEASE_FAILED), floor fakes, fake process runner returning success / cancel / timeout / crash / launch error,
  artifact and manifest writing, ownership evidence recorded, no CUDA import in the parent.
- Coordinator: the new target's release set, unchanged behaviour of existing targets.
- Runner: `validate_stage_chain` refusals, pre-job WebUI cleanup skipped for `diffusers`, end-to-end
  `run_njr` with a fake child runner producing an artifact.
- GUI: the model list gains the entry only when readiness passes; policy projection for the identity.
- Architecture: import-time side effects (no torch/diffusers import from `src.image_backends` at import), ratchets.

## 13. Self-critique (single model; not an independent review)

- **Weakest assumption: 3.14 parity.** 110R ran on 3.11. Same diffusers, transformers, torch and weights, but
  bitsandbytes 0.50.2 on 3.14 and the full staged path are unmeasured. Mitigation: nothing claims qualification; the
  ledger next test (section 17) is the first 3.14 canary.
- **Per-job load cost** (~18-20 s plus ~30 GiB commit churn per job) may feel slow for batches. Mitigation: up to 4
  images per job share one load; B (warm child) stays an evidence-driven follow-up.
- **Exclusivity is cooperative against manual operator actions** (section 6.2). A hard GPU fence across GUI actions would be
  a new lifecycle authority; not proposed.
- **Floors are derived, not measured as product code.** They come from 110R numbers; the canary must confirm them.
- **Automatic captions are minimal.** They pass the verifier but under-use the model; authored captions remain the
  quality path.
- **Licence**: verifier semantics are re-implemented; no official code is vendored.

## 14. Owner decisions

Asked in this session on 2026-11-18 (each with a recommendation); the owner accepted every recommendation:

1. **GPU residency lease: per-job contained child** (section 6, alternative A). Not a warm resident child, not
   in-process.
2. **JSON-caption mapping: both, by prompt content** (section 8.2). A JSON-object prompt is the operator's caption and
   must pass verification; any other prompt is wrapped automatically.
3. **`bitsandbytes`: optional pinned extra.** `bitsandbytes==0.50.2` (the 110R-qualified version) is pinned in a separate
   optional requirements file and the Windows constraints; the owner installs it explicitly; CI never installs it;
   without it the model is hidden and queued work is refused with a reason.
4. **GUI: one Base Generation model-list entry**, shown only when the offline readiness check passes (section 9).

## 15. Implementation acceptance contract

In scope: profile, policy and routing entries; caption module; residency classes and the child worker;
`DiffusersImageBackend`; coordinator target; runner pre-job cleanup guard; GUI model-list entry; the dependency pin per
decision 3; deterministic tests; `coverage_matrix.v1.json` row; living-doc and STATUS updates for changed truth.

Exclusions: any physical run, backend start, GPU use or weight download; ledger status changes (owner-accepted separate
edit); per-stage composition (COA C); img2img/inpaint/ADetailer/upscale on Ideogram; prompt upsampling; a warm
resident child; Comfy or FLUX backends; Learning/Model Comparison support for Ideogram (refused there by the existing
`explicit_capabilities`/qualified-policy gates until a later package).

Acceptance: hermetic tests above pass; `python tools/ci/run_architecture_ratchets.py`, `pytest tests/tools`,
`python tools/ci/run_pr_gate.py` and `git diff --check` pass; no controller ceiling rises; import-time side effects
unchanged.

## 16. Controller surface and validation plan

- Controller Surface Assessment: no change to `app_controller.py` (at ceiling), `pipeline_controller.py`,
  `job_service.py` or `job_history_service.py` is needed. The GUI change is in `src/gui/base_generation_panel_v2.py`;
  the runner change is a few lines in `pipeline_runner.py` (not a ratcheted controller).
- Token-efficient validation: focused new test modules first, then the touched existing suites (runtime transition,
  image backend registry, model policy, runner image dispatch, base generation panel), then the ratchets, `pytest
  tests/tools`, one `run_pr_gate.py`, `git diff --check`.

## 17. Coordination, ledger next test and stop conditions

- The Comfy still-image (Qwen) and generic FLUX packages start after this PR opens. Shared touch points are kept to
  additive one-liners: one `register(...)` line in the registry, one `required_backend_for_model` resolver tuple, one
  branch each in `exact_model_profile` / `model_policy`, one `KNOWN_TRANSITION_TARGETS` entry. `runtime_family` on
  capabilities is the seam they reuse.
- Ledger next test for `IMG-Q4.ideogram4-diffusers` (to be written by the owner-accepted ledger edit; this PR does not
  touch the ledger): a gated **canary** of the integrated slice on the production 3.14 interpreter after the
  bitsandbytes install — one 768x1024 `V4_TURBO_12` job and one 1024x1024 `V4_DEFAULT_20` job queued from the GUI with an
  authored caption, a repeat for bit-identical output, a cancel mid-denoise, and a Forge job immediately after, recording
  peak VRAM, host commit, teardown evidence and the coordinator results. Needs owner authorization of the exact plan.
- Stop conditions honoured: no second queue/runner/history or GUI shortcut is needed; exclusivity is guaranteed to the
  same standard as the existing GPU targets (section 6.2); the dependency addition is put to the owner (decision 3).
