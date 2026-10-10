# PR-IMG-MODELS-153 — Pinned Forge and hardware feasibility: Z-Image-Turbo FP8-scaled

Status: READ-ONLY FEASIBILITY PHASE COMPLETE (local); hosted CI and review pending.

**Verdict: `ELIGIBLE_FOR_OWNER_AUTHORIZATION` — conditional eligibility only.** It means no source-level, identity or
hard-resource *disproof* was found for the exact stack below, so a separate explicit owner decision may consider one controlled
physical qualification. It is **not** confirmation that the stack fits this hardware: the host-memory and VRAM risks below
remain open. No model was loaded, no image generated, Forge was not launched, and no profile, admission, NJR, queue, runner,
compiler or GUI change was made.

Execution profile: Standard, qualification-only (`tools/qualification/img153/`, no production `src/` change). Claude Code Sonnet 5.5
High / Codex GPT-6.1 Sol High, Windows Local/Desktop. Controller Surface Assessment: no controller touched.

## Exact candidate (no substitutions)

| Role | File | Bytes |
| --- | --- | --- |
| Transformer | `zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors` | 6,158,115,074 |
| Text encoder | `qwen3_4b_2964436.safetensors` | 8,044,982,048 |
| VAE | `flux1AE_v10.safetensors` | 335,304,388 |

Complete verified SHA-256 digests (computed by the explicit read-only `--hash` option for these three files only):

| Role | SHA-256 |
| --- | --- |
| Transformer | `59610861d46ae8d5d1d371ab7b2532ce64c0835052b395551a8550fa0e3eb3cf` |
| Text encoder | `6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a` |
| VAE | `afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38` |

Header-only structure: Z-Image DiT (dim 3840, 30 layers, caption width 2560; 208 FP8-E4M3 weights, 453 F32 tensors); Qwen3
(hidden 2560, 36 layers, plain BF16); FLUX.1-style AE (16 latent channels, native keys, F32).

Verified byte identity is kept separate from provenance. **The text encoder is byte-identical to the Qwen3 4B encoder PR-IMG-115
ran on this machine class** (same digest), a same-bytes load baseline for 8.04 of the 14.5 GB. Official-source provenance of all
three files is unverified (no official hash offline; the transformer is a third-party FP8-scaled conversion; the VAE's modelspec
hash is a claim). The evaluator records the digests but compares only the encoder (to PR-IMG-115's digest); a qualification
would have to freeze and re-verify all three.

## FP8-scale convention (header-measured, fail-closed)

The recognized convention mirrors the pinned converter (`backend/state_dict.convert_quantization`): exactly one `*scaled_fp8`
marker of two elements whose key prefix every converted layer shares, and one scalar F32 `<layer>.scale_weight` for each FP8
2-D `<layer>.weight`, with nothing else quantized. The candidate has a 2-element F8_E4M3 `scaled_fp8` marker (empty prefix) and
208 scalar F32 `scale_weight` tensors matching all 208 FP8 weights, with none orphaned and no `scale_input`, `comfy_quant` or
`_quantization_metadata`. Every other placement is `unknown` and yields `INCONCLUSIVE`: a missing marker, partial coverage, an
orphan scale, a non-F32 or non-scalar scale, a marker prefix the layers do not carry, several markers, a marker with other than
two elements, FP8 tensors that are not 2-D weights, `scale_input`, mixed U8/E5M2 dtypes. A per-layer `comfy_quant` layout is
accepted only when every FP8 weight has a U8 `comfy_quant` record and a scalar F32 `weight_scale`; a lone `comfy_quant` key is
`unknown`.

## Pinned Forge (source-level, revision `d70373eb…`, marker `verified`)

* `model_list.ZImage(Lumina2)`: `dim` 3840, `memory_usage_factor` 2.8 (Klein 4B: 14.6), clip target `qwen3_4b.transformer`; bf16/fp32 (fp16 only conditionally via `allow_fp16`).
* `detection.detect_unet_config` selects Z-Image from `cap_embedder.1.weight` (+ `noise_refiner.0.attention.k_norm.weight`) with `dim == 3840`; the candidate has both.
* `loader` builds `ZImageTransformer2DModel`; `replace_state_dict` routes a Qwen3 file with `post_attention_layernorm` width 2560 to `qwen3_4b`; a `decoder.conv_in.weight` VAE is placed under the model's `vae.` prefix.
* `state_dict.convert_quantization` turns the marker + `.scale_weight` into `weight_scale` + `comfy_quant` records (`float8_e4m3fn`). A 2-element marker sets `full_precision_matrix_mult`, which in `operations_mixed_precision` makes `_use_quantized` false: for this exact file FP8 tensor-core compute is not expected, and the GPU's compute capability does not select the execution path. This is a source reading, not an observed behavior.
* Module discovery: files under `models/VAE` and `models/text_encoder` are the selectable modules (`/sd-modules`, `forge_additional_modules`).
* Pinned Z-Image-Turbo UI preset: Euler / Beta, 9 steps, CFG 1.0, shift 9.0 (the model definition's own sampling shift is 3.0).

Software support exists in source. It has **never been exercised by a load on this workstation** (an evidence gap).

## Official Turbo guidance (documented, not applied)

Tongyi-MAI/Z-Image-Turbo card: distilled 6B, `num_inference_steps` 9 (= 8 DiT forwards), `guidance_scale` 0.0, 1024x1024 example,
bfloat16; a vendor claim of fitting 16 GB consumer GPUs (this host has 12 GB). The foundation Z-Image is a different variant
(50 steps with CFG); Turbo settings do not transfer to it. The installed file *declares* `model_type z-image-turbo`, a claim;
structure cannot distinguish Turbo from foundation.

## Resources — terms kept apart

| Term | Value | Kind |
| --- | --- | --- |
| Physical RAM / allocated pagefile | 31.8 GiB / 18.0 GiB | measured |
| Principal weight residency (each file once) | 13.5 GiB (1.17x the PR-IMG-115 baseline's weights) | measured sizes |
| Usable physical RAM (RAM − 4 GiB reserve) | 27.8 GiB | estimated; the 4 GiB reserve is an **assumed policy number**, not a measured quiesced state |
| Process-private commit analogues (Forge tree) | 28.2 GiB (additive) to 30.7 GiB (ratio), from PR-IMG-115's 26.3 GiB | estimated; one baseline, a range, not a prediction |
| System commit limit (RAM + allocated pagefile) | 49.8 GiB | estimated from measured terms |
| Policy-adjusted commit limit (that − 4 GiB assumed reserve) | 45.8 GiB | estimated; a theoretical ceiling |
| Momentary commit headroom / available RAM | 16.1 GiB / 12.5 GiB, with the development session running | measured, workload-dependent |
| Projected paging pressure (analogue − usable physical) | about 0.5–2.9 GiB against 18 GiB of pagefile | estimated |

**Both private-commit analogues exceed usable physical RAM** (`HOST_PEAK_PROJECTION_EXCEEDS_USABLE_PHYSICAL`): paging is the
expected case, not an edge case. PR-IMG-115 at 26.3 GiB already drove available RAM down to 0.01 GB before recovering, and this
stack is heavier. `HOST_PEAK_PROJECTIONS_WITHIN_POLICY_COMMIT_LIMIT` says only that both analogues sit below the policy-adjusted
commit limit; it is neither measured free headroom nor a demonstration that the stack fits. The unresolved `DIAG-GPU-130`
hard-failure family remains aggravating context (no attribution).

VRAM, with measured, documented, derived and future items separated:

| Term | Value | Kind |
| --- | --- | --- |
| Dedicated VRAM / in use now | 12.0 GiB / 2.3 GiB (desktop and other processes), 36 C | measured |
| PR-IMG-115 recorded dedicated-VRAM peak | 9.47 GiB (9,696 MiB); **no phase attribution and no recorded desktop share** | documented |
| Derived additive bound | 11.4 GiB = documented peak + 1.9 GiB larger FP8 transformer | derived, conservative (may stack an encoder-phase peak on a denoise-phase delta) |
| FP8 transformer residency | 5.7 GiB vs 9.5 GiB resident limit (card − 2.5 GiB activation reserve) | estimated |
| Launch-time VRAM in use | to be measured by a future package | future |

The additive bound is above 95% of the card (`VRAM_MARGIN_THIN_IN_ADDITIVE_BOUND`; the fraction is a declared assumption); it is
a flagged risk, not a disproof. Hard no-gos require disproof: weights beyond usable RAM, the optimistic analogue beyond the policy
commit limit, a transformer that cannot be VRAM-resident, or a documented peak above the card. None applies.

## Safety gate for any physical test — not defined here

PR-IMG-MODELS-153 defines **no** executable preflight gate, abort threshold, process termination or GPU telemetry. A separate
physical-qualification package, under a new explicit owner authorization, must define before any dispatch: measurable
preflight conditions measured at launch; instrumentation and phase markers; abort criteria split into **operator stop
conditions** and **automatic thresholds that are reliably enforceable** (only the latter may be called enforced, and only after
that package implements and tests them); fault-event checks (WHEA, Kernel-Power, LiveKernel); and safe lifecycle ownership through
the managed process manager (single case, no retry, replay or tuning). A black-screen, driver-level hang or hard restart cannot
be guaranteed recoverable by a software watchdog; accepting that residual risk is the owner's decision. The report lists these
requirements and a few measured values as inputs, explicitly not gates.

## Evidence gaps

Pinned loading is source-only; official provenance is unverified; resource figures are analogues from one baseline whose VRAM
peak is unattributed; the Turbo subtype is a claim; output quality is untested.

## Method and tests

`tools/qualification/img153/feasibility.py` reuses the PR-152 header evidence and the PR-151 allow-listed telemetry and SHA
helper; its only subprocesses are the PR-151 read-only queries, with no off-host network (the PR-151 probe makes a loopback TCP
connect to the Forge ports), and the only write is the report file the caller names. The report is deterministic, bounded and
carries no local path. Precedence: `MISSING_DEPENDENCY` > `NO_GO_PINNED_FORGE` > `NO_GO_RESOURCE_RISK` > `INCONCLUSIVE` >
`IDENTITY_PENDING` > `ELIGIBLE_FOR_OWNER_AUTHORIZATION`. Tests are synthetic only (`tests/tools/test_img153_feasibility.py`,
`tests/tools/test_img153_repair.py`).

## Disposition

Stop here. Whether to commission a physical-qualification package is a separate owner decision. Nothing in this package makes
the model executable.
