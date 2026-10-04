# PR-IMG-115 - FLUX.2 Klein 4B FP8 target-hardware qualification

Result class: **MODEL/RUNTIME QUALIFICATION** on the pinned managed Forge. It is not StableNew production
integration: there is no new backend, queue, runner or compiler, and `src/` is unchanged.

**Technical verdict: `FLUX2_KLEIN_4B_FP8_PASS_CONSTRAINED`.** Product value: `PRODUCT_VALUE_PENDING_OWNER_REVIEW`.

## Question and answers (RTX 4070 Ti 12 GB, Windows)

| # | Question | Answer |
|---|---|---|
| 1 | Does the pinned managed Forge load and run Klein 4B FP8 reliably? | Yes. Three clean generations; no OOM, no GPU/system event, clean owned lifecycle. |
| 2 | Useful 1024-class text-to-image without OOM or pathological spill? | Yes. 1024x1024 in 18.9 s; dedicated VRAM peak 9.4 GiB of 12; shared-GPU-memory spill about 0.12 GiB (baseline-level). |
| 3 | Useful single-reference editing? | Yes. A selective jacket edit preserved identity, pose, hands, motorcycle, sign and street. |
| 4 | Useful two-reference editing? | **Not determined.** Forge's built-in reference mechanism (`ImageStitch Integrated`) is rejected by the pinned Forge API before any generation. A runtime/API gap, not evidence about the model. |

## Pins and assets

| Item | Identity |
|---|---|
| Runtime | managed Forge Neo `d70373eb...` (unchanged; `-CheckOnly` passes before and after), Python 3.13.16, torch 2.13.0+cu130, torchvision 0.28.0+cu130 |
| Transformer | `black-forest-labs/FLUX.2-klein-4b-fp8` @ `5b4408e5...` `flux-2-klein-4b-fp8.safetensors`, 4,070,624,520 B, sha256 `97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6` |
| Text encoder | `Comfy-Org/vae-text-encorder-for-flux-klein-4b` @ `5f526678...` `split_files/text_encoders/qwen_3_4b.safetensors`, 8,044,982,048 B, sha256 `6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a` |
| VAE | same repo/revision `split_files/vae/flux2-vae.safetensors`, 336,211,292 B, sha256 `868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3` |
| Downloaded | 12,451,817,860 B in total; nothing else |

Provenance of the two modules. Forge loads single-file modules, and the official FLUX.2-klein-4B repo ships its
Qwen3 text encoder as two shards. The single-file Comfy-Org repackaging declares the BFL model as its base; a
safetensors-header comparison shows the same 398 tensor names, dtypes and shapes as the official shards. The
official VAE is in diffusers key layout while Forge's `AutoencoderKLFlux2` uses the LDM layout of the Comfy-Org
file, which is the one used. Weight equality with the official files was not verified tensor by tensor.

## Method

Qualification-only harness `tools/qualification/img115/` (fakes-only tests in `tests/tools/test_img115_harness.py`):
exact asset verification, an isolated root outside the repository/managed install/A1111/application envs
(`%LOCALAPPDATA%\\StableNew\\Qualification\\IMG115_FLUX2_KLEIN_4B_FP8`, models hard-linked into a qualification
`--data-dir`), the managed Forge launched only through `WebUIProcessManager` on a qualification port (7885), model and
modules selected through Forge's supported `/options`, and a dispatch ledger that never retries or replays. Frozen
parameters (pinned Forge Klein preset): steps 4, CFG 1.0, sampler Euler, scheduler Beta, empty negative prompt, no
optimizer, no tuning flags, "Diffusion in Low Bits" Automatic. Seeds 424242-424245.

## Results

| Case | Result | Generation | Dedicated VRAM peak | Min host RAM avail. | Forge tree private peak | Peak temp |
|---|---|---|---|---|---|---|
| A portrait 768x1024 | passed (seed 424242 returned) | 19.0 s (includes first model load) | 9,420 MiB | 0.01 GB | 26.3 GiB | 57 C |
| B product 1024x1024 | passed (424243) | 18.9 s | 9,430 MiB | 0.08 GB | 26.3 GiB | 59 C |
| C single-reference edit 768x1024 | passed (424244) | 17.4 s | 9,696 MiB | 1.02 GB | 26.3 GiB | 60 C |
| D two-reference edit | API-rejected, no generation | 0.3 s | n/a | n/a | n/a | n/a |

Artifact sha256: A `8a722fdc...`, B `1bd41893...`, C `62f0fe3a...`. Runtime ready in 12-36 s (first launch 35.6 s, later 12-13 s). The
model loads lazily on the first request, which is where host memory is stressed: available RAM fell to 0.01 GB (A) and
0.08 GB (B) on a 34 GB host with an active pagefile before recovering, and the Forge process tree's private memory
peaked around 26 GiB. Denoising itself runs at about 7 GiB VRAM. No sustained shared-memory spill was observed.

## Case D and the Forge API gap

Every request carrying `alwayson_scripts: {"ImageStitch Integrated": ...}` returned HTTP 500 `IndexError: list
assignment index out of range` from `modules/api/api.py::init_script_args`, in 0.2-0.3 s with no GPU work. The script is
listed by `/script-info` for both tabs (3 args). Case C's first attempt used txt2img with one reference and was rejected the
same way; one bounded harness repair moved edit to `/sdapi/v1/img2img` (reference 1 = init image, which Forge feeds to
Klein as a reference latent), after which single-reference editing passed without any script argument. Two-reference
editing needs the second reference through `ImageStitch`, which is rejected; a second repair class would have
violated the package's stop rule and production/Forge changes were out of scope. Classification of D:
`FORGE_API_INTEGRATION_GAP`. The ledger records the repair, and the harness counted five generation POSTs in total (three
completed generations and two rejected by the API layer before any work).

## Safety and cleanliness

No GPU, display, WHEA, kernel-power or LiveKernel/WER event across the whole package window, no OOM marker, no reboot, no
retry or replay, no external-runtime mutation, no package or environment change, no Forge/A1111 production setting
touched, and no Forge process left after any case.

## Observations (factual; the owner decides product value)

- **A:** a coherent rain-wet street at dusk with a blue vintage motorcycle, natural skin texture and a dark green hooded
  jacket; both hands are visible; the neon sign reads "NOR'H" (letter damage, observational only); framing reaches the
  thighs rather than the knees.
- **B:** a clean studio motorcycle with a white tank stripe, brass headlamp, black seat and neutral gray background; mechanical
  detail is plausible, small tank lettering is garbled, and a small watermark-like glyph appears bottom left.
- **C:** only the jacket changed, to deep red leather with plausible creasing and reflections; the face, pose, hands, motorcycle, sign
  and street are preserved with no visible composition drift.
- **D:** no output.

## Constraint and not proven

Constraint: two-reference editing is unreachable through the pinned Forge API. Host memory is tight while the 8 GB BF16
text encoder and FP8 transformer load. Not proven: multi-reference model quality, behaviour on a different Forge revision,
tensor-level equality of the Comfy-Org single files with the official shards, production integration (model management, UI,
job-level reference handling) and any ADetailer interaction.
