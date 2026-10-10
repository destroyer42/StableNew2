# PR-IMG-MODELS-151 — Pinned Forge exact-model feasibility (FLUX.2 Klein Base 9B BF16)

Status: READ-ONLY FEASIBILITY PHASE COMPLETE; local implementation, hosted CI and review pending.

**Verdict: `NO_GO_RESOURCE_RISK`.** The package closes here: no model was loaded, no generation was run, Forge was not
launched, and no physical qualification is proposed for this candidate on this workstation.

Execution profile: Standard, qualification-only (no `src/` change). Claude Code Sonnet 5.5 High / Codex GPT-6.1 Sol High,
Windows Local/Desktop for the measurements. Controller Surface Assessment: no controller touched.

## Method

`tools/qualification/img151/feasibility.py` is a read-only evaluator. Its only subprocesses are an allow-list of four
read-only queries (`nvidia-smi --query-gpu`, two `Get-CimInstance`/`Get-Process` listings, one GPU-counter read); the only
network activity is a TCP connect (no HTTP) to the Forge ports; the only write is the report file the caller names; hashing
(`--hash`) only reads. It reuses the PR-IMG-MODELS-150 structural evidence and `read_host_memory`, and separates
**measured**, **documented**, **estimated** and **assumed** facts. Precedence: `MISSING_DEPENDENCY` > `NO_GO_PINNED_FORGE` >
`NO_GO_RESOURCE_RISK` > `INCONCLUSIVE` > `IDENTITY_PENDING` > `ELIGIBLE_FOR_OWNER_AUTHORIZATION`. Incomplete telemetry is
`INCONCLUSIVE`, never a guess; a definite resource failure is not hidden by other missing telemetry. Tests are synthetic
only (`tests/tools/test_img151_feasibility.py`).

## Candidate (measured, header + SHA-256; the weights were only read)

| Role | File | Bytes | Structure | SHA-256 |
| --- | --- | --- | --- | --- |
| Transformer | `flux-2-klein-base-9b.safetensors` | 18,157,185,200 | FLUX.2 DiT, hidden 4096, 8 double + 24 single blocks, BF16; needs a hidden-4096 encoder and 32-channel VAE | `9105af6c…41ca` |
| Text encoder | `qwen_3_8b.safetensors` | 16,381,517,176 | Qwen3, hidden 4096, 36 layers, plain **BF16** | `f0ff9239…f6c1` |
| VAE | `flux2-vae.safetensors` | 336,211,292 | 32 latent channels, native keys, F32 | `868fe7b3…e8f3` (identical to the VAE frozen for the qualified Klein 4B) |

Alternates kept distinct and never substituted: `model.safetensors` (Qwen3-8B structure, **F16**, SHA `2bb97dcc…c4ba`),
the fp8mixed/fp4mixed encoders (quantized), the 4B-class encoder (hidden 2560), the Diffusers-format 32-channel VAE copy.
Total candidate weights 34,874,913,668 bytes.

**Provenance.** The installed transformer is byte-identical (SHA-256) to the single file in the locally cached
`darknight9121/FLUX.2-klein-base-9B-bucket-uncensored` snapshot; the BF16 encoder and the VAE are byte-identical to the cached
`Comfy-Org/vae-text-encorder-for-flux-klein-9b` repack (base model `black-forest-labs/FLUX.2-klein-9B`); the F16 encoder is
byte-identical to that mirror's Diffusers `text_encoder/model.safetensors`. The mirror's README is the verbatim BFL card
(license `other`, `flux-non-commercial-license`) and does not state how its weights were produced; no official hash is
available offline. So equality with the **official** weights remains unverified (`OFFICIAL_IDENTITY_UNVERIFIED`); a name or
a matching size was never accepted as identity. Subtype: the repository card describes the undistilled 9B **Base**; the
structure cannot distinguish Base from distilled.

## Pinned Forge (measured, read-only source inspection)

Managed Forge Neo marker: revision `d70373eb…` status `verified`. The pinned source defines `Flux2K9B` (hidden 4096,
`memory_usage_factor` 19.5, BF16/FP16/FP32) and loads a Qwen3 8B encoder (`Qwen3_8B`); a 9B Klein model definition ships with
it. **Software support exists**; `NO_GO_PINNED_FORGE` does not apply. Official Base 9B reference settings are about 50 steps at
guidance 4.0, not the distilled Klein 4B profile (4 steps, CFG 1.0); that profile and its qualification do not transfer.

## Resource evidence (measured vs estimated)

| Item | Value | Kind |
| --- | --- | --- |
| Physical RAM | 34.1 GB total (18.9 GB available at measurement) | measured |
| Commit headroom / pagefile | 27.1 GB / 19.3 GB allocated | measured |
| GPU | RTX 4070 Ti, 12,282 MiB dedicated, 1.6 GiB in use, shared GPU memory ~0.05 GB, 38 C | measured |
| Competing processes | top working sets: chrome 1.1 GiB, explorer 0.6, ChatGPT 0.5, claude 0.4, Defender 0.4 (no Forge listening on 7860/7861) | measured |
| Best-case resident host footprint | 34.9 GB of weights vs 29.8 GB usable after a 4 GiB reserve | estimated |
| Scaled host peak | about 79 GB (PR-IMG-115 tree-peak / weights factor 2.27 x 34.9 GB) vs 27.1 GB commit headroom | estimated from the only physical baseline |
| Transformer vs VRAM | 18.2 GB BF16 vs 12.3 GB dedicated (10.2 GB resident limit after 2.5 GiB of activations) | estimated |
| Runtime cost vs the 4B distilled run | about 28x compute (steps x parameters), for scale only | estimated/assumed |

Reason codes: `HOST_RESIDENT_WEIGHTS_EXCEED_PHYSICAL` (even the best case, each file resident once with no process overhead,
exceeds usable physical RAM), `HOST_PEAK_EXCEEDS_COMMIT_HEADROOM`, `VRAM_TRANSFORMER_EXCEEDS_DEDICATED` (the BF16 transformer
cannot be resident, so it would need offload/swap outside the PR-IMG-115 envelope). The only physical baseline on this
machine class (Klein 4B FP8, 12.5 GB of weights) already drove available RAM to ~0.01 GB with a ~26 GiB Forge tree; this
candidate has 2.8x that weight. Precision, offload, sampler, Forge version and loading strategy were not altered to make a
test fit. Documented aggravating context (not an attribution): the unresolved hard-failure family recorded in
`docs/Subsystems/Runtime/DIAG-GPU-130_Post_5600_Black_Screen_Recurrence.md` (exit criterion not met).

## Disposition and next step

Close PR-IMG-MODELS-151 as a documented no-go for this workstation. Revisit only with materially larger VRAM/RAM, or an
owner-approved smaller exact candidate (for example a quantized-transformer 9B, not installed) that gets its own feasibility
evaluation first. The PR-IMG-MODELS-150 pre-dispatch gate continues to refuse this model before any module write or
generation POST; SDXL and the qualified Klein 4B profiles are unchanged.
