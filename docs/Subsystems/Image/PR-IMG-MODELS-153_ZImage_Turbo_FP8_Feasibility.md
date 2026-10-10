# PR-IMG-MODELS-153 — Pinned Forge and hardware feasibility: Z-Image-Turbo FP8-scaled

Status: READ-ONLY FEASIBILITY PHASE COMPLETE (local); publication, hosted CI and review pending.

**Verdict: `ELIGIBLE_FOR_OWNER_AUTHORIZATION`** for *one* controlled physical qualification of the exact stack below, under the
stated preconditions. This is not qualification: no model was loaded, no image generated, Forge was not launched, and no
profile, admission, NJR, queue, runner, compiler or GUI change was made. Physical qualification needs a separate explicit owner
decision.

Execution profile: Standard, qualification-only (`tools/qualification/img153/`, no production `src/` change). Claude Code Sonnet 5.5
High / Codex GPT-6.1 Sol High, Windows Local/Desktop. Controller Surface Assessment: no controller touched.

## Exact candidate (no substitutions)

| Role | File | Bytes | Header-only structure | SHA-256 |
| --- | --- | --- | --- | --- |
| Transformer | `zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors` | 6,158,115,074 | Z-Image DiT, dim 3840, 30 layers, caption width 2560; 208 FP8-E4M3 weights, 453 F32 tensors | `59610861…b3cf` |
| Text encoder | `qwen3_4b_2964436.safetensors` | 8,044,982,048 | Qwen3, hidden 2560, 36 layers, plain BF16 | `6c671498…fc5a` |
| VAE | `flux1AE_v10.safetensors` | 335,304,388 | FLUX.1-style AE, 16 latent channels, native keys, F32 | `afc8e282…9e38` |

Verified byte identity (SHA-256 of the installed files, computed by the explicit read-only `--hash` option for these three files
only) is kept separate from provenance. **The text encoder is byte-identical to the Qwen3 4B encoder PR-IMG-115 ran on this
machine class**, which gives a same-bytes load baseline for 8.04 of the 14.5 GB. Official-source provenance of all three files is
unverified (no official hash offline; the transformer is a third-party FP8-scaled conversion; the VAE's modelspec hash is a
claim). The decision uses installed bytes; a qualification would freeze these digests.

## FP8-scale convention (header-measured, not guessed)

A `scaled_fp8` marker tensor (2 elements, F8_E4M3) plus one per-layer `*.scale_weight` (F32, 1 element) for every one of the 208
FP8 weights; none orphaned, no other quantized dtypes, no embedded `_quantization_metadata`, no `comfy_quant`. The evaluator
labels any other combination (missing or orphaned scales, U8/E5M2 mixes, partial coverage) `unknown` and returns `INCONCLUSIVE`
rather than inferring a convention.

## Pinned Forge (source-level, revision `d70373eb…`, marker `verified`)

* `model_list.ZImage(Lumina2)`: `dim` 3840, `memory_usage_factor` 2.8 (Klein 4B: 14.6), dtypes bf16/fp32, clip target `qwen3_4b.transformer`.
* `detection.detect_unet_config` selects Z-Image from `cap_embedder.1.weight` (+ `noise_refiner.0.attention.k_norm.weight`) with `dim == 3840`; the candidate has both.
* `loader` builds `ZImageTransformer2DModel` via `NextDiT`; `replace_state_dict` routes a Qwen3 file with `post_attention_layernorm` width 2560 to `qwen3_4b`; a `decoder.conv_in.weight` VAE is placed under the model's `vae.` prefix (Diffusers-key AEs are converted, native keys are used as-is).
* `state_dict.convert_quantization` turns the `scaled_fp8` marker + `.scale_weight` into `weight_scale` + `comfy_quant` (`float8_e4m3fn`; a 2-element marker sets `full_precision_matrix_mult`); `quant_ops` implements the layer. FP8 compute needs compute capability 8.9 or higher (RTX 4070 Ti = Ada 8.9, documented); without it the layer uses full-precision matmul.
* Module discovery: files under `models/VAE` and `models/text_encoder` are the selectable modules (`/sd-modules`, `forge_additional_modules`).
* Pinned Z-Image-Turbo UI preset: Euler / Beta, 9 steps, CFG 1.0, shift 9.0 (the model definition's own sampling shift is 3.0).

Software support therefore exists in source. It has **never been exercised by a load on this workstation** (an evidence gap).

## Official Turbo guidance (documented, not applied)

Tongyi-MAI/Z-Image-Turbo card: distilled 6B, `num_inference_steps` 9 (= 8 DiT forwards), `guidance_scale` 0.0 ("should be 0 for the
Turbo models"), 1024x1024 example, bfloat16; a vendor claim of fitting 16 GB consumer GPUs (this host has 12 GB). The foundation
Z-Image is a different variant (50 steps with CFG); Turbo settings do not transfer to it. The installed file *declares*
`model_type z-image-turbo`, which is a claim; structure cannot distinguish Turbo from foundation.

## Resources (measured vs documented vs estimated)

| Item | Value | Kind |
| --- | --- | --- |
| Physical RAM / pagefile | 31.8 GiB / 18.0 GiB allocated | measured |
| Commit headroom, available RAM (momentary) | 16.1 GiB, 12.5 GiB — with the development session running | measured |
| GPU | RTX 4070 Ti, 12.0 GiB dedicated, 2.3 GiB in use (desktop), shared GPU memory 0.2 GiB, 36 C; no Forge listening | measured |
| Weights | 13.5 GiB (1.17x the PR-IMG-115 baseline's 12.45 GB) | measured |
| Best-case resident host footprint | 13.5 GiB vs 27.8 GiB usable physical | estimated |
| Host Forge-tree peak analogue | 28.2 GiB (additive) to 30.7 GiB (ratio) from the PR-IMG-115 26.3 GiB peak | estimated; one baseline, a range not a prediction |
| Quiesced commit capacity | 45.8 GiB (RAM + pagefile − 4 GiB reserve) | estimated |
| Dedicated VRAM analogue | 9.5 GiB (text-encoder phase, identical encoder) to 11.4 GiB (denoise phase, larger FP8 transformer) of 12.0 GiB | estimated |
| Transformer residency | 5.7 GiB FP8 vs 9.5 GiB resident limit | estimated |

Reason codes: `HOST_PEAK_PROJECTIONS_FIT_QUIESCED_CAPACITY`, `VRAM_MARGIN_THIN_IN_UPPER_PROJECTION`,
`CURRENT_COMMIT_HEADROOM_BELOW_PROJECTION` (a momentary, workload-dependent reading: a launch precondition, not a verdict
input), `ENCODER_BYTES_MATCH_IMG115_QUALIFIED_ENCODER`, `OFFICIAL_PROVENANCE_UNVERIFIED`, `KNOWN_GPU_RISK_CONTEXT`.
Hard no-gos require disproof: weights beyond usable RAM, even the optimistic projection beyond commit capacity, or a transformer
that cannot be VRAM-resident. None applies. Unlike PR-IMG-MODELS-151 (34.9 GB of weights, a no-go on the weights alone), this
candidate's weights fit with margin; the open risks are thin VRAM headroom in the upper analogue and host memory pressure like
PR-IMG-115's (available RAM fell to 0.01 GB there).

## Evidence gaps and preconditions for any future qualification

Gaps: pinned loading is source-only; official provenance unverified; resource figures are analogues from one baseline; the Turbo
subtype is a claim; output quality is untested. Preconditions: a quiesced host with commit headroom at launch of at least the high
projection (about 30.7 GiB; 16.1 GiB with the development session running), desktop VRAM use at about the PR-IMG-115 level, no
other Forge/WebUI endpoint, one managed lifecycle, a single case, and no parameter or precision tuning to make it fit. The
unresolved hard-failure family in `DIAG-GPU-130` remains aggravating context (no attribution).

## Method and tests

`tools/qualification/img153/feasibility.py` reuses the PR-152 header evidence and the PR-151 allow-listed telemetry and SHA helper;
its only subprocesses are the PR-151 read-only queries, there is no network, and the only write is the report file the caller
names. The report is deterministic, bounded and carries no local path. Precedence: `MISSING_DEPENDENCY` > `NO_GO_PINNED_FORGE` >
`NO_GO_RESOURCE_RISK` > `INCONCLUSIVE` > `IDENTITY_PENDING` > `ELIGIBLE_FOR_OWNER_AUTHORIZATION`. Tests are synthetic only
(`tests/tools/test_img153_feasibility.py`): dependency mismatches, scale-key ambiguity, wrong key layouts, unverifiable identity,
unsupported pinned loading, insufficient resources, missing telemetry, precedence, determinism and forbidden side effects.

## Disposition

Stop here. If the owner wants it, the next step is one separately authorized, single-case physical qualification on a quiesced host
(PR-IMG-115-style harness, frozen to the exact digests above). Nothing in this package makes the model executable.
