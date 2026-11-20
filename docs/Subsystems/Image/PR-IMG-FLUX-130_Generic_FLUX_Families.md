# PR-IMG-FLUX-130 — Generic FLUX families in the model policy

Status: IMPLEMENTED (hermetic) — owner decisions recorded in section 10; as-built differences in section 12. Not physically qualified: no model was run, no backend started and nothing downloaded.

Execution class: **Architectural** (a new family-identity rule and a new profile kind on the Forge image path).
Model recommendation: Claude Code Opus 5.5 High / Codex GPT-6.1 Sol High for design and build; Sonnet 5.5 Medium is enough for
the test-only follow-ups. Controller Surface Assessment: no controller is touched (policy, assets, backend and GUI projection
only). Token-Efficient Validation Plan: focused tests of the new modules and the touched backend/policy tests, then the
architecture ratchets, `pytest tests/tools`, one `run_pr_gate.py`, `git diff --check`.

Started 2026-11-20T06:22:45-05:00. Sessions: `8f05b9ec-86de-4af7-bfda-33233930c99a` (this package, child of
`local_d31afe93-baab-47ac-8524-0eb1c639819f`). Base: `main` at `fefc7aae` (PR #360, Ideogram 4 on Diffusers, merged).

No model was loaded, no backend started, no GPU used and nothing downloaded. Every file fact below comes from a bounded
header read with the repository's own parsers (`read_tensor_table`, `inspect_component_file`, `inspect_gguf`) or from a
read-only `grep` of the pinned Forge and Comfy sources. Hugging Face sizes and licences are repository metadata only.

## 1. Owner outcome and the decision to make

Ledger entry `IMG-Q1.other-generic-families` (status `UNSUPPORTED`): on 2026-11-18 the owner said "I would like to bring in
generic FLUX families"; SD1, SD2 and SD3 stay out (`QUAL-CAMPAIGN-920` decision 4). The same decision list keeps
`IMG-Q1.klein-base-9b` **NO-GO**.

The operator outcome: when a FLUX-family checkpoint is selected, StableNew says exactly what it is (generation, size,
quantization, fine-tune or not), runs it through the canonical image path with fixed, versioned settings when a profile
covers it, and refuses it with a precise reason when nothing does. Today every FLUX file is either the one exact Klein 4B
profile or the coarse label `flux` (`unverified_generic:flux`), and transformer-only files are refused by the dependency gate
with a generic message.

Decisions this package needs: which FLUX models get an executable profile first (and whether that needs a download), how a
"generic" family profile establishes identity (exact bytes, or structure plus pinned auxiliaries), whether Klein 9B is
revisited, and how the `flux3Klein_*` files are classified.

## 2. Evidence

### 2.1 Current code (read on `fefc7aae`)

| Concern | Owner | What it does today |
|---|---|---|
| Family label | `src/assets/compatibility.py` | One coarse `ModelFamily.FLUX`, only from embedded/sidecar metadata or a whole-token filename hint (`flux-2-...` matches; `flux3Klein...` does not, because `flux` is followed by a letter-digit run). No structural FLUX evidence feeds the registry family (`registry._build_record` maps only SD1/SD2/SDXL structures). |
| Structure | `src/assets/component_evidence.py` | `_flux_transformer` recognises native and Diffusers FLUX DiT keys; reports `flux2_dit` vs `flux_dit`, hidden size, double/single block counts, required encoder hidden size (FLUX.2 only) and VAE latent channels, plus precision facts. Safetensors only. |
| GGUF | `src/assets/gguf.py` | Reads the container's key/value block only (`general.architecture`, `general.file_type`); the tensor table is skipped. |
| Policy | `src/image_backends/model_policy.py` | `sdxl` is the only qualified registry policy; any other resolved family is `unverified_generic:<family>` with every feature `UNVERIFIED`. Exact profiles: `flux2_klein_4b_fp8@v1/v2`, `z_image_turbo_fp8_scaled@v1`, `ideogram4_nf4_diffusers@v1`. |
| Dependency gate | `forge_webui_backend._dependency_gate` + `model_readiness.py` | Refuses before any module write or POST a checkpoint whose **safetensors** header positively identifies a dependency-bearing, unqualified transformer (`ForgeUnqualifiedModelError`). Unreadable, unrecognised or non-safetensors evidence is "unverified" and keeps the old generic behavior. |

### 2.2 Installed FLUX-related files (WebUI root `C:\Users\rob\stable-diffusion-webui`, header-only)

The managed Forge (`%LOCALAPPDATA%\StableNew\Forge\neo-d70373eb`) holds the qualified `flux-2-klein-4b-fp8.safetensors` in its
own data dir and references the WebUI root's models, so Forge lists every file below.

| File (folder) | Bytes | Header evidence | What it is |
|---|---|---|---|
| `flux-2-klein-base-9b-fp8.safetensors` (Stable-diffusion) | 9,567,278,472 | `flux2_dit`, native keys, hidden 4096, 8 double + 24 single, needs a hidden-4096 encoder and a 32-channel VAE; FP8 E4M3 by bytes with 216 scale keys (`mixed_scaled`) | FLUX.2 Klein **9B**, FP8-quantized; base vs distilled is not structurally distinguishable |
| `flux-2-klein-base-9b-Q8_0.gguf` (Stable-diffusion) | 9,978,304,800 | GGUF v3, `general.architecture = flux`, file type Q8_0, 201 tensors; tensor table (header bytes 0..14,617) shows `img_in [4096,128]`, `txt_in [4096,12288]`, `double_stream_modulation_img`, 8 double + 24 single | FLUX.2 Klein 9B, Q8_0 |
| `flux-2-klein-base-9b-Q6_K.gguf` (Stable-diffusion) | 7,865,424,160 | same structure, file type Q6_K | FLUX.2 Klein 9B, Q6_K |
| `flux3Klein_klein_pruned_int8.safetensors` (Stable-diffusion) | 5,827,874,779 | **unrecognized**: keys `content_mode_blocks.image/.image_cond`, `txt_mode_blocks`, 28 `single_blocks`, `emb_in.image_cond`, `ref_time_in`, `comfy_attention.config`; `txt_in [3072, 20480]`; INT8 weights with Comfy `comfy_quant` scales; metadata `model = f3-image-small` | a transformer-only DiT of a layout that **neither the pinned Forge (`d70373eb`) nor the pinned Comfy (0.38.0) source contains** (read-only grep); not the FLUX.2 Klein layout |
| `flux3Klein_kleinBase_txt_3299228.safetensors` (**Stable-diffusion**) | 4,858,559,240 | `model.language_model.*` (hidden 2560, 36 layers) plus `model.visual.*` with `deepstack_merger_list`; INT8 `comfy_quant` | a Qwen3-VL-4B-class **text encoder** sitting in the checkpoint folder; same size as the next file |
| `flux3Klein_klein_txt_3299383.safetensors` (text_encoder) | 4,858,559,240 | same layout, INT8 | Qwen3-VL-4B-class encoder |
| `flux3Klein_klein_txt_bf16.safetensors` (text_encoder) | 8,875,719,408 | same layout, plain BF16 | Qwen3-VL-4B-class encoder |
| `qwen_3_8b.safetensors`, `qwen_3_8b_fp8mixed.safetensors`, `qwen_3_8b_fp4mixed.safetensors` (text_encoder) | 16,381,517,176 / 8,664,848,742 / 6,802,593,327 | Qwen3 8B, hidden 4096 (BF16 / quantized / quantized) | Klein 9B encoders |
| `flux1AE_v10.safetensors` (VAE) | 335,304,388 | `flux1_ae`, 16 latent channels; metadata `Flux.1 Autoencoder`, Black Forest Labs, Apache-2.0 | the FLUX.1 VAE (also the Z-Image VAE) |
| `flux2-vae.safetensors` (VAE) | 336,211,292 | `flux2_vae`, 32 channels | the FLUX.2 VAE (Klein) |

No FLUX.1 [dev] or [schnell] transformer, and no CLIP-L or T5-XXL encoder, is installed.

**Gap found.** The three new Klein 9B files do not all meet the NO-GO refusal. The FP8 safetensors is refused by the gate. The
two GGUF files are not: `inspect_component_file` returns "unsupported format" for `.gguf`, readiness becomes
`UNKNOWN_OR_CONFLICTING` with architecture `unrecognized`, `blocks_dispatch` is false, and a selected 9B GGUF would be sent to
Forge on the generic path. The `flux3Klein_kleinBase_txt` encoder in the checkpoint folder is also sent on the generic path
(an encoder is "not dependency-bearing").

### 2.3 Pinned runtimes (read-only source inspection)

- Forge Neo `d70373eb`: `backend/diffusion_engine/flux.py` builds FLUX.1 from CLIP-L + T5-XXL + the 16-channel AE;
  `use_distilled_cfg_scale` is off only for schnell; `processing.py` defaults `distilled_cfg_scale = 3.5`; Hugging Face
  configs ship for `FLUX.1-dev`, `FLUX.1-schnell`, `FLUX.2-klein-4B` and `FLUX.2-klein-9B`; `loader_gguf.py` and
  `operations_gguf.py` load GGUF transformers; `state_dict.py` understands `comfy_quant` scales. So FLUX.1 dev/schnell, Klein
  4B/9B and GGUF are software-supported. Software support is not qualification.
- Comfy 0.38.0: no `content_mode_blocks` / `txt_mode_blocks` layout either.

### 2.4 Download candidates (Hugging Face metadata, 2026-11-20; nothing downloaded)

| Role | Repository / file | Bytes | Licence |
|---|---|---|---|
| FLUX.1 [dev] transformer, GGUF Q4_K_S | `city96/FLUX.1-dev-gguf` / `flux1-dev-Q4_K_S.gguf` | 6,805,988,640 | FLUX.1 [dev] Non-Commercial (`license: other`) |
| FLUX.1 [dev] transformer, GGUF Q5_K_S | same / `flux1-dev-Q5_K_S.gguf` | 8,285,267,232 | same |
| FLUX.1 [dev] transformer, GGUF Q6_K | same / `flux1-dev-Q6_K.gguf` | 9,857,000,736 | same |
| FLUX.1 [dev] transformer, FP8 | `Kijai/flux-fp8` / `flux1-dev-fp8.safetensors` | 11,901,525,888 | same |
| FLUX.1 [schnell] transformer, GGUF Q5_K_S | `city96/FLUX.1-schnell-gguf` / `flux1-schnell-Q5_K_S.gguf` | 8,263,222,304 | Apache-2.0 |
| FLUX.1 [schnell] transformer, FP8 | `Kijai/flux-fp8` / `flux1-schnell-fp8-e4m3fn.safetensors` | 11,891,329,784 | Apache-2.0 |
| T5-XXL encoder, FP8 | `comfyanonymous/flux_text_encoders` / `t5xxl_fp8_e4m3fn.safetensors` | 4,893,934,904 | Apache-2.0 |
| T5-XXL encoder, FP16 | same / `t5xxl_fp16.safetensors` | 9,787,841,024 | Apache-2.0 |
| CLIP-L encoder | same / `clip_l.safetensors` | 246,144,152 | Apache-2.0 |
| FLUX.1 VAE | installed (`flux1AE_v10.safetensors`) | 335,304,388 | Apache-2.0 |

The official `black-forest-labs/FLUX.1-dev` and `-schnell` repositories are gated (access denied without an accepted licence and
a token), so their hashes could not be read. The city96 GGUF and Kijai FP8 files are community conversions, not BFL artefacts.
Hugging Face exposes no SHA-256 through the metadata used here, so an exact pin is taken from the local file after it is
installed. Getting any weights is an owner action or a separately approved download.

## 3. FLUX taxonomy StableNew recognises

One pure classifier, `src/assets/flux_variant.py`, turns the existing header evidence into a `FluxVariant`. It reads nothing
itself: it takes a `ComponentEvidence` (safetensors) or the extended `GgufEvidence` (section 3.2). Names, sizes and Forge
listings are never evidence of a variant.

| Variant id | Structural signature (all must hold) | Notes |
|---|---|---|
| `flux1_dev` | `flux_dit` (no FLUX.2 modulation keys), hidden 3072, 19 double + 38 single, `img_in` input 64 (16-channel VAE), `txt_in` input 4096 (T5-XXL), `vector_in` input 768 (CLIP-L), **`guidance_in.*` present** | guidance-distilled; uses Forge's distilled CFG |
| `flux1_schnell` | as `flux1_dev` but **no `guidance_in.*`** | timestep-distilled, 1-4 steps |
| `flux2_klein_4b` | `flux2_dit`, hidden 3072, 5 double + 20 single, encoder hidden 2560, VAE 32 channels | the only qualified file is the exact `flux2_klein_4b_fp8` profile |
| `flux2_klein_9b` | `flux2_dit`, hidden 4096, 8 double + 24 single, encoder hidden 4096, VAE 32 channels | NO-GO (section 6) |
| `flux_unrecognized` | a FLUX DiT whose counts match none of the above | labelled, never executable |

Orthogonal facts recorded with every variant: `container` (`safetensors` / `gguf`), `precision` (`bf16`, `fp16`, `fp8_scaled`,
`int8_scaled`, or the GGUF quantization named by the container's declared file type), `bundled` (encoders/VAE inside the file)
and `key_format`.

**Base vs fine-tune.** Structure cannot tell an official checkpoint from a fine-tune or a merge with the same layout. The
variant is therefore a *layout class*, and every file in it is a potential derivative unless its SHA-256 equals a pinned
official identity. The operator label says so ("FLUX.1 [dev]-class, identity not pinned").

**Klein base vs distilled.** Not distinguishable from structure (PR-IMG-MODELS-151); a `base` filename token is a claim, shown as
such, never evidence.

### 3.1 Registry family

`ModelFamily.FLUX` stays the coarse registry family (no change to `compatibility.py`'s tokens or tiers, so existing
filename/metadata outcomes and conflicts are unchanged). The variant is a second, finer answer from structure, joined in
`model_policy.resolve_model_policy`: a structural variant can refine `flux` but never overrides a conflicting or non-FLUX
registry family, and a structural FLUX variant on a file the registry calls SDXL/SD1/SD2/SD3 is a conflict (unknown).

### 3.2 GGUF structure

`gguf.inspect_gguf` gains a bounded read of the tensor-info table that follows the key/value block (names, dims, types; never
tensor data). The 9B files' tables end at byte 14,617, well inside the existing 1 MiB bound; a table that does not fit is
"structure unknown", never guessed. GGUF dims are stored fastest-first and are reversed to the safetensors order before the
same FLUX signature is applied. A GGUF whose container says `general.architecture = flux` but whose table cannot be read is a
**FLUX transformer of unknown variant**, which is enough to refuse it at the gate (the city96 convention stores the
transformer alone).

## 4. Profiles and policies

### 4.1 Which families get an executable profile

Recommendation (owner decision Q1, Q2): one new executable family, **FLUX.1 [dev]**, as profile `flux1_dev_gguf@v1`, built
now in code and tests and dormant until its files are installed. Everything else in the taxonomy gets an explicit, labelled
policy that refuses with a reason.

| Variant | Policy | Executable |
|---|---|---|
| `flux1_dev` | `flux1_dev_gguf@v1` profile (section 4.2) | yes, once installed and the auxiliaries verify; not physically qualified |
| `flux1_schnell` | labelled `flux1_schnell (unqualified)`, refused | no (a later `flux1_schnell@v1` is a one-file addition if the owner wants it) |
| `flux2_klein_4b`, exact Klein file | existing `flux2_klein_4b_fp8@v2`, **unchanged** | yes (as today) |
| `flux2_klein_4b`, any other file | labelled `FLUX.2 Klein 4B-class (unqualified)`, refused | no |
| `flux2_klein_9b` (FP8, Q8_0, Q6_K, BF16) | labelled `FLUX.2 Klein 9B — NO-GO (PR-IMG-MODELS-151)`, refused | no |
| `flux_unrecognized`, `flux3Klein_*` | unknown, refused when positively a transformer-only DiT (section 7) | no |

### 4.2 `flux1_dev_gguf@v1` settings

Identity (owner decision Q4, recommended "structure plus pinned auxiliaries"):

- **Transformer:** any file whose header classifies as `flux1_dev`, transformer-only (not bundled), GGUF Q4_K_S/Q5_K_S/Q6_K/Q8_0
  or FP8-scaled safetensors. Its SHA-256 is computed at dispatch (cached by stat identity, like `verify_klein_assets`) and
  recorded in the stage provenance and the image manifest; it is evidence, not an admission rule, so fine-tunes of the same
  layout run under the same profile and are labelled as derivatives.
- **Auxiliaries, pinned by bytes:** CLIP-L, T5-XXL FP8 and the FLUX.1 AE. The AE is installed (335,304,388 bytes) and is
  byte-identical to the asset the Z-Image profile already pins. The two encoders are pinned to the sizes and SHA-256 values the
  Hugging Face file pages publish for `comfyanonymous/flux_text_encoders` (read 2026-11-20; nothing downloaded), with the
  repository revision that last changed each file (section 12). A copy with other bytes refuses at dispatch.

Settings (the published Forge FLUX.1 [dev] defaults; StableNew has no physical evidence for them yet):

| Field | Value |
|---|---|
| Backend | `forge_webui` only (managed Forge `d70373eb`); A1111 refused |
| Sampler / scheduler | Euler / Simple (fixed) |
| Steps | 20 (fixed; see section 12) |
| CFG | 1.0 (fixed; true CFG would double the cost and turns negative text on) |
| Distilled guidance | `distilled_cfg_scale` 3.5 (fixed) |
| Geometry | 1024x1024, 896x1152, 1152x896, 832x1216, 1216x832 (restricted choice, first is default) |
| Images per job | 1 |
| Modules (`forge_additional_modules`) | CLIP-L, T5-XXL FP8, FLUX.1 AE, in that order |
| VAE control | fixed (the module set owns it) |
| CLIP skip | 1 |
| Prompt dialect | natural language; no negative prompt, no global terms, prompt optimizer off |
| LoRA, embeddings | unsupported in v1 (a FLUX.1 LoRA rule is its own later version, like Klein v2) |
| Host RAM | the existing 32e9-byte total-RAM floor (`check_klein_host_memory`); available RAM is evidence only |

Compile policy: a new `apply_flux1_dev_compile_policy`, dispatched from `apply_model_compile_policy` / `project_flat`
exactly like Klein (fixes the owned values, clears negative and global text, stamps `model_profile`), never touching geometry,
counts, stages or features so a conflict is refused. The family is selected by the checkpoint's structural variant, which the
compiler reads through the registry snapshot (`CompileEvidence`, no scan, no hashing); the backend re-derives it from the
served file's header at dispatch and refuses if it differs.

### 4.3 Stage support and refusals

| Stage / feature | `flux1_dev_gguf@v1` | Other FLUX variants |
|---|---|---|
| txt2img | supported | refused |
| img2img (free-form) | refused in v1 (denoise semantics not qualified) | refused |
| ADetailer | refused (its inner passes would reuse SDXL-shaped defaults) | refused |
| Upscale | refused in v1 (an upscale-only stage after a FLUX txt2img is a later, separately tested version) | refused |
| Hires fix, refiner | refused | refused |
| ControlNet / OpenPose | refused (ordered units require registry-verified SDXL, IMAGE_PIPELINE 3.1) | refused |
| Negative prompt | refused | refused |

Refusals use the existing types: `KleinProfileError`-family `Flux1ProfileError` for envelope conflicts,
`ForgeUnqualifiedModelError` for the gate, `OperationNotSupportedError` for preflight.

## 5. VRAM and resource readiness (RTX 4070 Ti, 12,282 MiB; 34.1 GB RAM)

Estimates use the only physical baseline on this machine class (Klein 4B FP8: 12.45 GB of weights, Forge tree peak about
26 GiB, available RAM driven to about 0; factor 2.27) and the PR-IMG-MODELS-151 VRAM rule (about 10.2 GB resident after
2.5 GiB of activations). Nothing here is measured for FLUX.1.

| Candidate set | Weights (GB) | Transformer vs 10.2 GB VRAM | Scaled host peak vs 27.1 GB commit headroom |
|---|---|---|---|
| Klein 4B FP8 (qualified baseline) | 12.45 | 4.07 fits | ~28 (measured envelope) |
| FLUX.1 dev Q4_K_S + T5 FP8 + CLIP-L + AE | 12.28 | 6.81 fits | ~28 (inside the measured envelope) |
| FLUX.1 dev Q5_K_S + same | 13.76 | 8.29 fits | ~31 (above it) |
| FLUX.1 dev Q6_K + same | 15.33 | 9.86 at the limit | ~35 |
| FLUX.1 dev FP8 + same | 17.38 | 11.90 exceeds; offload | ~39 |
| Klein 9B Q6_K + Qwen3-8B fp8mixed + VAE | 16.87 | 7.87 fits | ~38 |
| Klein 9B Q8_0 / FP8 + Qwen3-8B fp8mixed + VAE | 18.98 / 18.57 | 9.98 / 9.57 at the limit | ~43 / ~42 |
| Klein 9B BF16 (the 151 verdict) | 34.87 | 18.16 exceeds | ~79 |

FLUX.1 [dev] Q4_K_S is the only new set inside the measured envelope, which is why it is the recommended first file. Compute:
20 steps of a 12B transformer is roughly 15x the qualified 4-step 4B run (steps x parameters), so a 1024x1024 image is expected
to take minutes, not seconds; that is for scale only.

**Klein 9B.** The quantized files cut the 9B weight total roughly in half, but every 9B set still estimates above the measured
host envelope, the files' provenance is unknown, and the owner reaffirmed NO-GO on 2026-11-18. This package keeps NO-GO and
does not edit the 151 verdict or the ledger. It closes the GGUF gap so the gate refuses all four 9B forms. Revisiting needs an
owner decision and its own read-only feasibility package with the `img151` evaluator.

## 6. GUI exposure

Projection only; nothing new authorises.

- Base Generation (`model_policy_projection` / `model_policy_panel_projection`): the selected FLUX checkpoint shows its variant
  label and precision ("FLUX.1 [dev]-class, GGUF Q4_K_S, identity not pinned"), the fixed controls of `flux1_dev_gguf@v1`
  disabled at their values, the restricted size choices, and the policy note. Refused variants show the refusal
  sentence as `blocking` (for example "FLUX.2 Klein 9B is NO-GO on this workstation (PR-IMG-MODELS-151)").
- Model readiness button: the existing `probe_model_readiness` gains the variant and, for the profile, the auxiliary pin state.
- Checkpoint lists are unchanged: StableNew shows what Forge lists; it hides nothing and renames nothing.
- Learning / Model Comparison: `flux1_dev_gguf@v1` is not added to `QUALIFIED_REGISTRY_POLICY_IDS` and its identity is
  structural, so `exact_identity_authority` is false and Model Comparison keeps refusing it until physical qualification and an
  owner decision.

## 7. The `flux3Klein_*` files

Recommendation (owner decision Q3): **unrecognised, not FLUX.** The transformer's layout matches no FLUX variant and no pinned
runtime, and its metadata names a different model (`f3-image-small`). It gets no family label. Because it is positively a
transformer-only DiT (it carries `txt_in`, `time_in`, `single_blocks`, bundles no encoder or VAE), the gate refuses it with
"unrecognised multi-component transformer; no runtime StableNew pins recognises this layout". The Qwen3-VL encoder in the
checkpoint folder (`flux3Klein_kleinBase_txt_3299228`) is refused as "a text encoder, not a checkpoint". The two encoders in
`text_encoder` stay plain modules. Nothing is moved, renamed or deleted.

## 8. Alternatives considered

1. **Minimal: labels and refusals only.** Taxonomy, GGUF structure, variant labels and the gate fixes; no new executable
   profile. Cheapest and fully hermetic; gives the operator truth but no new capability. It is the fallback if the owner wants
   no download (Q1 option C).
2. **Per-file exact profiles (Klein pattern).** One immutable profile per transformer file, pinned by SHA-256. Strongest
   identity; does not deliver "generic families" (every fine-tune needs a code change) and needs the bytes before the profile
   can exist.
3. **Family profile with structural transformer identity and byte-pinned auxiliaries (recommended).** Delivers fine-tune
   coverage with one versioned settings envelope; the transformer hash is recorded, not required. Cost: it relaxes invariant 2
   of `MODEL_PROFILES.md` section 12 ("exact identity is whole-name plus byte verification") for this profile kind, which is
   why it is an owner decision (Q4).
4. **Comfy backend for FLUX.** Rejected for now: PR-IMG-COMFY-100 owns the Comfy still-image path and is unmerged; Forge already
   supports every recognised FLUX variant.

## 9. Self-critique (one model; not an independent review)

- *Weakest assumption:* that a FLUX.1 [dev]-class layout plus the pinned encoders runs correctly in pinned Forge for any
  fine-tune. Structure proves shape, not training: a merge with a different guidance distillation would run with the wrong
  settings. Mitigation: the derivative label, recorded SHA-256 and "not physically qualified" note; the owner may choose
  alternative 2 instead.
- *Settings are untested here.* Euler/Simple/20/3.5 are Forge and BFL defaults, not StableNew evidence. The profile says so and
  stays out of Model Comparison.
- *The 2.27 host factor comes from one Klein run.* FLUX.1's T5-XXL is a different encoder; the envelope may be worse. That is
  exactly what the later physical qualification measures.
- *Dormant code risk.* A profile that cannot run until a download happens is untested end to end. Hermetic tests cover the
  canonical path with fake headers and a fake Forge; physical work is the owner's later authorization.
- *Gate tightening is a behavior change* for GGUF FLUX files and for encoders in the checkpoint folder: both went to Forge
  before. No installed file loses a working path (none of them is qualified, and the 9B ones are NO-GO).

## 10. Owner decisions

Asked in this session on 2026-11-20 with the recommendations above; the owner answered the same day, before any code was
written.

| # | Question | Recommendation | Owner answer (2026-11-20) |
|---|---|---|---|
| Q1 | Which FLUX family and file first | FLUX.1 [dev] GGUF Q4_K_S + T5-XXL FP8 + CLIP-L (owner download 11.95 GB; AE installed) | **FLUX.1 dev Q4_K_S** (as recommended). The download is the owner's action; the profile is built now and stays dormant until the files are installed and the auxiliaries are pinned. |
| Q2 | Klein 9B | Keep NO-GO; close the GGUF gap so all four 9B forms are refused | **NO-GO + later feasibility**: the verdict and the ledger are unchanged, the gap is closed here, and a separate read-only `img151` feasibility package for Klein 9B Q6_K + Qwen3-8B fp8mixed goes on the backlog (no physical run). |
| Q3 | `flux3Klein_*` | Unrecognised, not FLUX; refuse the transformer and the misplaced encoder at the gate | **Unrecognised, refuse** (as recommended). |
| Q4 | Identity of a family profile | Structure plus byte-pinned auxiliaries; transformer SHA-256 recorded | **Structure + pinned auxiliaries** (as recommended). Invariant 2 of `MODEL_PROFILES.md` section 12 is amended for this profile kind only. |

## 11. Implementation contract (after the answers)

In scope: `src/assets/flux_variant.py` (new, pure); bounded GGUF tensor table in `src/assets/gguf.py`; FLUX family ids and
variant-aware policies in `model_policy.py` (additive); `src/image_backends/forge_flux1_profile.py` (new: profile, validator,
compile policy, provenance); `exact_model_profile.py` dispatch; dependency-gate and readiness additions (GGUF FLUX, misplaced
encoder/VAE, unrecognised transformer-only DiT, variant labels); Forge backend profile handling for module selection and
distilled CFG; GUI projection text; deterministic tests; `MODEL_PROFILES.md`, `IMAGE_PIPELINE.md` section 12 pointers and the
`coverage_matrix.v1.json` rows.

Excluded: any change to `flux2_klein_4b_fp8@v1/v2`, Z-Image, Ideogram or SDXL behavior; the Klein 9B verdict and every ledger
status; downloads, hashing of large files in CI, model loads, Forge launches; Comfy; Model Comparison eligibility; LoRA.

Acceptance: a FLUX.1 [dev]-class header reaches an NJR stamped `flux1_dev_gguf@v1` through the canonical path with fixed
settings, the Forge payload carries the pinned module set and `distilled_cfg_scale`, and an unpinned auxiliary refuses before
any POST; a served auxiliary with other bytes refuses before any POST; each refused variant is refused before any module
write or POST with its own reason; GGUF and safetensors 9B files
are refused; existing Klein, Z-Image, Ideogram and SDXL tests pass unchanged.

Stop conditions: a second queue, runner, history or compiler, or a GUI-to-backend shortcut; a new production dependency; any
change to an existing qualified profile; any change to the Klein 9B NO-GO without an owner decision.

## 12. As built (2026-11-20)

Differences from sections 3 to 7, each smaller than or equal to the accepted design:

- **Steps are fixed at 20.** The restricted 20/28 choice would need a second settings envelope the GUI and the validator both
  carry; with no physical evidence for either value, v1 fixes the Forge default. A 28-step version is a later profile version.
- **Encoder pins come from the published Hugging Face SHA-256** (CLIP-L `660c6f5b…6cdd`, 246,144,152 bytes, revision
  `168aff54…`; T5-XXL FP8 `7d330da4…4f09`, 4,893,934,904 bytes, revision `2f74b39c…`). The recommended transformer
  (`city96/FLUX.1-dev-gguf` `flux1-dev-Q4_K_S.gguf`, `75bb1945…f62b`, 6,805,988,640 bytes, revision `7e7853bc…`) is recorded as
  guidance and derivative labelling only: a structurally matching transformer with other bytes runs and is labelled
  `derivative_or_other_conversion`.
- **The asset registry now indexes `.gguf` checkpoints** (checkpoint kind only; LoRA, embedding and other kinds are unchanged).
  Without it the compiler could never see the recommended GGUF's structure, so the profile could not be stamped. A full
  inventory refresh therefore hashes GGUF checkpoints like any other checkpoint (the two installed Klein 9B GGUF files add
  about 17.8 GB of hashing to the next full refresh). The structure contract is `checkpoint_structure/2`, so cached entries
  re-read their bounded header once without rehashing.
- **Selection seam.** The compiler reads the structural variant through one installable lookup
  (`forge_flux1_profile.install_variant_lookup`), installed only by `src/main.py` over the registry snapshot. Without it nothing
  is stamped and the dependency gate refuses a FLUX.1 [dev]-class transformer with a "refresh the model inventory" hint, so
  tests stay hermetic and no path guesses.
- **Readiness** gains `NOT_A_CHECKPOINT` (a text encoder or VAE selected as a checkpoint; refused before dispatch), names the
  FLUX layout class in every FLUX message, and reports `gguf_tensor_table` evidence for GGUF files.
- **GUI**: `ModelPolicy.refusal` carries the refusal sentence; the Base Generation projection shows it as `blocking` even on the
  right backend. `refusal` is not part of a frozen Learning policy context.

Not done here (owner-gated): the FLUX.1 [dev] downloads, the first physical run and its qualification, any Model Comparison
eligibility, and the backlog `img151` read-only feasibility package for Klein 9B Q6_K + Qwen3-8B fp8mixed (owner answer Q2).
