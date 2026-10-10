# PR-IMG-MODELS-150 — Installed Model Readiness and Forge Module-State Preflight

Status: local implementation complete; hosted CI and independent review pending. No GPU, no generation, no model or Forge
configuration change, no new production profile.

Execution profile: Standard cross-cutting readiness/diagnostic change; Claude Code Sonnet 5.5 High / Codex GPT-6.1 Sol High,
Windows Local/Desktop (read-only inspection of the installed roots). Controller Surface Assessment: no controller or
coordinator file touched, no ceiling changed.

## Problem

An unqualified multi-component image checkpoint (a FLUX-style transformer that ships without its text encoder and VAE)
could be discovered, selected and submitted. Its job entered the ordinary Forge path, whose D110 baseline normalization
(`ForgeWebUIImageBackend._normalize_module_baseline`, correct for SDXL) replaces any persisted `forge_additional_modules`
with `[]`, stripping the very encoder and VAE the model needs before Forge loaded it. The executor has an independent
"switched model, no VAE -> Automatic" reset (`PipelineExecutor._ensure_model_and_vae`); both seams sit behind the backend
`_before_dispatch`.

## Contracts

**Header-only component evidence** (`src/assets/component_evidence.py`, parser `checkpoint_structure.read_tensor_table`):
a bounded safetensors header says whether a file is a dependency-bearing FLUX-style transformer (and then what it
requires: text-encoder hidden size = `txt_in` input / 3, VAE latent channels = transformer input channels / 4), a Qwen3 text
encoder (hidden size, layers, dtype, quantized or not, size label only for the exact known dimensions), a FLUX-family VAE
(latent channels, native vs Diffusers key format), or a self-contained bundle. Identification is by bytes, never by file
name. A structural match is not a load proof and F16, BF16, FP8/FP4 and quantized files are never interchangeable.
Malformed, truncated, duplicate-key or bad-offset headers yield an error and no evidence. Diagnostics carry no paths.

**Readiness projection** (`src/image_backends/model_readiness.py`, pure; evidence gathering in `model_readiness_probe.py`):
keeps file presence, structural identity, header-required dependencies, Forge's *catalog* (`/sd-modules`), Forge's *live
selection* (`/options` `forge_additional_modules`), exact-profile qualification and hardware qualification apart. Statuses:
`Qualified`, `No auxiliary dependencies identified`, `Discovered — dependencies incomplete`, `Discovered — dependencies
present but not selected`, `Discovered — selected but execution unqualified`, `Unknown/conflicting`, `Unavailable/stale`.
A failed or unreadable Forge read is unavailable, never an empty list or "ready"; duplicate catalog names are a conflict.
The durable record (`ModelReadiness.as_dict`) names the checkpoint, evidence type, architecture, requirements, listed and
selected module basenames, `qualification_status`, `reason_code`, `selection_source` and the epoch of the live read.

**Dependency gate** (`ForgeWebUIImageBackend._dependency_gate`, called first in `_before_dispatch` for work without an exact
profile): reads only (`GET /sd-models`, one bounded header, and — only when a refusal is certain — `/sd-modules` and
`/options`) and raises `ForgeUnqualifiedModelError` for a *positively identified* dependency-bearing, unqualified
checkpoint, before the baseline normalization, any `/options` write and any generation POST (every stage of a chain is
gated). The operator's live Forge selection is never adopted as an NJR dependency contract and never altered. Unknown,
unreadable, missing or ambiguous served-file evidence is "unverified": previously supported generic behavior is preserved
exactly (including the D110 SDXL clearing, explicit SDXL VAEs, the exact Klein 4B profile/LoRA paths and A1111). The exact
Klein 4B transformer name is exempt. The module-baseline log line and event now carry the job id, attributing any write
to StableNew at its real call site instead of inferring it from Forge's console.

**Operator diagnostic** (`src/gui/model_readiness_presenter.py`, mounted on the Base Generation panel): one read-only label
and a `Check readiness` button. Nothing runs at construction or on a model change (a change only marks the shown verdict
stale); the probe runs on a background worker, results are latest-request-wins and dropped for another model or a
destroyed widget. It never hashes, scans, writes to Forge or changes a control.

## Evidence classification (read-only inspection of the installed roots, header and size only; Forge was not running)

| Candidate | Evidence (header) | Class |
| --- | --- | --- |
| `flux-2-klein-base-9b.safetensors` (18.2 GB) | FLUX.2 DiT, native keys, 8 double + 24 single blocks, hidden 4096, BF16, no bundled encoder/VAE; needs a hidden-4096 text encoder (`txt_in` 12288 = 3 x 4096) and a 32-channel VAE | dependency-bearing, unqualified. Base vs distilled is not distinguishable from structure: unknown |
| `text_encoder/qwen_3_8b.safetensors` | Qwen3, hidden 4096, 36 layers, 399 tensors, **BF16** | structural match for the 9B; not load-qualified |
| `text_encoder/model.safetensors` | same structure, **F16** (the file measured earlier as 16.38 GB F16) | structural match; different dtype from `qwen_3_8b` |
| `text_encoder/qwen_3_8b_fp8mixed`, `_fp4mixed` | Qwen3 hidden 4096, quantized (scales, F8/U8) | not interchangeable with the plain encoder |
| `text_encoder/qwen3_4b_2964436.safetensors` | Qwen3 hidden 2560 (4B class) | mismatches the 9B (the profiled Klein 4B encoder class) |
| `VAE/flux2-vae.safetensors` | latent channels 32, native keys, F32, batch-norm stats | structural match |
| `VAE/diffusion_pytorch_model (2).safetensors` | latent channels 32, **Diffusers** key format, BF16 | structural match in shape; format differs from `flux2-vae`; unclassified for Forge loading |
| `VAE/flux1AE_v10`, `sdxl_vae` | 16 / 4 latent channels | mismatch |
| `juggernautZ_v10*_pruned_fp8.safetensors` | no recognized signature | unclassified (not gated, not claimed) |

SHA-256: none of the above is in the AssetRegistry cache (empty on this host) — byte identity is pending for all of them;
nothing in this package hashes large weights. The 9B's served path, catalog and live selection could not be read (Forge was
not running); the earlier `/options` observation with an empty selection stays unattributed.

## 151 feasibility (conservative ranking, not a qualification)

1. Full BF16 Klein 9B Base + BF16 Qwen3-8B (about 35 GB of weights) on a 12 GB GPU / ~34 GB host: likely `NO_GO_RESOURCE`
   unless qualified telemetry disproves it; the previously qualified 4B already nearly exhausted host RAM in some cases.
2. A 9B with a quantized transformer and the installed fp8/fp4 encoder would need its own exact evidence and is not installed.
3. Anything else installed stays unclassified until positively inspected. The owner chooses whether any candidate proceeds.

## Tests

`tests/integration/test_pr_img_models_150_readiness.py` (stateful fake Forge, synthetic tiny headers whose shapes carry the
signature) and `tests/gui_v2/test_model_readiness_presenter_150.py`. Before the repair, the eight refusal tests failed (the
generic path cleared `[qwen_3_8b, flux2-vae]` to `[]` and then Forge rejected the load); the reproduction of that mechanism is
kept as a test with the gate disabled. D110, Klein 4B and image-backend suites are unchanged and green.
