# Model Profile Evidence Enrichment for StableNew

## Executive assessment

The existing architecture is already pointed in the right direction. The current `GenerationProfile` contract cleanly separates advisory generation recommendations from executable `ModelPolicy`; it supports Research, Custom, and Learning profiles, immutable revisions, verified model identities, per-setting evidence, and explicit `unavailable` fields instead of fabricated defaults. fileciteturn18file0L2-L2 PR #225 also demonstrates that a published Learning profile can survive selection, compilation, JobService admission, and SQLite persistence, while preserving ModelPolicy as the final execution authority. fileciteturn5file0L9-L17

The principal finding from this research is therefore:

> **Do not build another profile system. Build a richer evidence catalog behind the existing Research profile, keyed to exact asset identity, and distinguish authoritative recommendations from implementation defaults and hypotheses.**

There is substantially more source-backed information available than the current three Research profiles expose. In particular, SDXL can now be enriched beyond geometry: the official SDXL repository actually ships an `EulerDiscreteScheduler`, while Diffusers supplies concrete 50-step and CFG 5 defaults. Those latter values are implementation defaults rather than a Stability AI standalone-base recommendation, so they should be labeled accordingly rather than promoted to “official.” citeturn23search0turn20search0

There is also strong exact-profile evidence for several accelerated or distilled model types. SDXL-Turbo has an explicit 1–4-step, CFG-0, 512×512 recipe; SDXL-Lightning explicitly specifies Euler with trailing timesteps and, for ComfyUI, Euler + `sgm_uniform`; FLUX.2 Klein specifies 1024×1024, four steps and guidance 1.0; and Z-Image-Turbo specifies 1024×1024, nine scheduler steps corresponding to eight DiT forwards, with guidance disabled. citeturn26view0turn25view0turn27search0turn27search4

The important limitation is that I cannot directly enumerate the Windows host path `C:\Users\rob\stable-diffusion-webui\models` from this research environment. More importantly, StableNew's own prior asset-census package deliberately puts the machine-local inventory under ignored `data/asset_census/` and explicitly does **not** commit the local catalog, absolute paths, hashes, or third-party metadata. Consequently, the exact filenames of all 45 locally observed checkpoints cannot be reconstructed honestly from the public repository. fileciteturn10file0L2-L2

That does **not** prevent a useful deliverable. The repository already contains the mechanism needed to join this research to the exact local assets: `tools/asset_census.py` records SHA-256, display name, embedded safetensors metadata, `.civitai.info` sidecars, inferred family evidence, and—especially for LoRAs—model/version IDs, trained words and source metadata. fileciteturn23file0L2-L2 The missing piece is an evidence-enrichment pass over those records.

## What the local inventory evidence already establishes

The most recent repository-recorded machine census observed **45 file-backed checkpoints**, and the live A1111 API exposed the same count. It also found 10 VAEs plus two approximate VAEs, 46 LoRAs, 16 file-backed textual inversions, three ControlNet assets, and the restoration/upscaling assets listed below. This is historical repository evidence rather than a live October 27 re-enumeration. fileciteturn10file0L2-L2

| Asset class | Repository-recorded local inventory | Profile implication |
|---|---:|---|
| Checkpoints | 45 | Each should ultimately receive exact SHA-256 identity plus family/model-specific research evidence. fileciteturn10file0L2-L2 |
| VAEs | 10 standard + 2 approximate | Do **not** automatically pair one with every checkpoint; record compatibility and exact creator recommendations. fileciteturn10file0L2-L2 |
| LoRAs | 46 | Usually compatibility/trigger metadata rather than an independent generation profile; accelerator LoRAs are the important exception. fileciteturn10file0L2-L2 |
| Textual inversions | 16 file-backed; 15 loaded and one skipped in the observed runtime | Associate with compatible base family and trigger/token, not sampler/CFG defaults. fileciteturn10file0L2-L2 |
| ControlNet | 3 | Compatibility metadata belongs with family evidence; it should not alter basic generation defaults by itself. fileciteturn10file0L2-L2 |
| ESRGAN / RealESRGAN | 2 / 2 | Restoration metadata, not checkpoint-generation profiles. fileciteturn10file0L2-L2 |
| GFPGAN / CodeFormer | 3 / 1 | Restoration metadata, not checkpoint-generation profiles. fileciteturn10file0L2-L2 |

One correction to the proposed scan scope is important: **the authoritative textual-inversion directory is the WebUI root-level `embeddings\`, not `models\embeddings\`**. The previous census found `models\embeddings` to be legacy/inactive: five files there were duplicate copies and its unique legacy `.pt` did not appear in the live A1111 embedding inventory. fileciteturn10file0L2-L2

The previous census also found usable metadata on only a subset of assets: embedded safetensors metadata existed on 16 checkpoints, 41 LoRAs, three VAEs and two embeddings. That means enrichment cannot depend only on embedded headers. SHA-256, sidecar metadata, structural classification and exact external-model identification must be combined. fileciteturn10file0L2-L2

That fits the architecture already developed after the original census. StableNew's compatibility layer treats embedded fields such as ModelSpec/base-model metadata and `.civitai.info` `baseModel` fields as separate pieces of provenance rather than blindly trusting one source. fileciteturn22file2L23-L33 This is much safer than filenames—particularly names containing `xl`, `turbo`, `pony`, `flux`, or `lightning`, which are useful search hints but are not identity evidence.

### Recommended local identity pipeline

For each installed checkpoint, the enrichment process should resolve evidence in this order:

**SHA-256 exact identity → embedded architecture/model metadata → exact sidecar model/version identity → structural checkpoint family → creator-authored model documentation → family-level fallback.**

Filename matching should only assist source discovery. It should never establish the final model identity or compatibility claim. That is consistent with the existing profile contract, where a model-level identity consists of verified family, a whole-name key and optionally SHA-256, and with `ModelPolicy`, which explicitly does not determine family from arbitrary filename substrings. fileciteturn18file0L2-L2 fileciteturn17file0L2-L2

For the next local census, the effective scope should therefore be equivalent to:

```text
checkpoint = C:\Users\rob\stable-diffusion-webui\models\Stable-diffusion
vae        = C:\Users\rob\stable-diffusion-webui\models\VAE
vae_approx = C:\Users\rob\stable-diffusion-webui\models\VAE-approx
lora       = C:\Users\rob\stable-diffusion-webui\models\Lora
lycoris    = C:\Users\rob\stable-diffusion-webui\models\LyCORIS
embedding  = C:\Users\rob\stable-diffusion-webui\embeddings
controlnet = C:\Users\rob\stable-diffusion-webui\models\ControlNet
```

Those are the discovery roots already established by the repository's census work; the existing tool recursively scans recognized model extensions, hashes files in a streaming fashion, reads only safetensors headers, and consumes adjacent CivitAI sidecars without loading model tensors. fileciteturn23file0L2-L2

## Research baseline recommendations

The table below separates **promotion-safe values** from **hypothesis values**. “Promotion-safe” means the source is strong enough to put into a Research recommendation with the stated provenance. It does **not** mean StableNew should execute that family when `ModelPolicy` currently refuses or leaves it unverified.

### Base and standard families

| Model/family | Recommended baseline | VAE | Text conditioning / CLIP | Evidence disposition |
|---|---|---|---|---|
| **Stable Diffusion 1.x** | **PLMS, 50 steps, CFG 7.5, 512×512.** The original CompVis reference script explicitly says these are its defaults. A WebUI scheduler value should remain unavailable rather than inventing how historical PLMS maps to Forge's newer sampler/scheduler split. citeturn20search1 | Model/checkpoint VAE unless the exact derivative's creator specifies an external VAE. | Frozen **CLIP ViT-L/14**. citeturn20search1 | **High** for sampler/steps/CFG/geometry on original SD1; derivative checkpoint documentation should supersede the family baseline. |
| **SD 2.1 base** | **512×512** family/subtype geometry. Do not manufacture sampler/step/CFG values from the name alone. | Model/default unless exact source says otherwise. | **OpenCLIP ViT-H**. Stability's SD2.1 card identifies that encoder. citeturn24search4 | **High** geometry/encoder; insufficient current evidence for a universally authoritative Forge recipe. |
| **SD 2.1 768** | **768×768** for the 768-v lineage. The model card identifies it as a finetune of the `768-v-ema` model. citeturn24search4 | Model/default. | **OpenCLIP ViT-H**. citeturn24search4 | Separate this subtype from 512-base; a single `sd2` geometry default would be wrong. |
| **SDXL base / ordinary SDXL finetune** | **1024×1024** square baseline. Native repository scheduler: `EulerDiscreteScheduler`. Best Forge hypothesis: **Euler / Automatic**, with **50 steps / CFG 5** as a Diffusers implementation baseline, not an official standalone-base recipe. citeturn23search0turn20search0 | **Checkpoint/model VAE** by default; do not globally force an external SDXL VAE. | Dual fixed encoders: **OpenCLIP-ViT/G + CLIP-ViT/L**. citeturn20search0 | 1024 is **high confidence**. Euler native scheduler is strong technical evidence. Forge `Automatic`, 50 and CFG 5 should be explicitly labeled inferred/implementation-baseline rather than official recommendation. |
| **SDXL base + refiner** | Stability's own example uses **40 total steps** and an **80/20 base/refiner split** (`high_noise_frac=0.8`). citeturn20search0 | Refiner example deliberately shares the base VAE. citeturn20search0 | SDXL dual encoder system. | This is a separate two-stage operation and should not silently become the ordinary txt2img default. |
| **SDXL-Turbo** | **512×512, CFG 0.0, 1–4 steps**. For a quality-oriented default, **4 steps** is defensible because Stability reports improvement at four steps; for latency-oriented use, one step is explicitly sufficient. citeturn26view0 | Model/default. | SDXL-derived. | **High** for geometry/steps/CFG. Keep Forge sampler/scheduler unavailable unless an exact runtime mapping is sourced/tested. |
| **SDXL-Lightning 2/4/8-step** | **Euler + SGM Uniform, CFG 0, exactly the number of steps encoded by the Lightning checkpoint/LoRA, 1024-class SDXL geometry.** ByteDance explicitly says Euler with `sgm_uniform` for ComfyUI and requires the checkpoint to match the inference-step count. citeturn25view0 | Base SDXL/model VAE. | SDXL conditioning. | **Very high** for sampler/scheduler/steps/CFG. This is an excellent candidate for an exact/variant-specific Research overlay. |
| **SDXL-Lightning 1-step** | Euler with trailing timesteps, **1 step, CFG 0**. ByteDance describes this variant as experimental and says the two-step version is substantially more stable. citeturn25view0 | Base/model VAE. | SDXL. | Do not make the one-step variant the generic Lightning default. |
| **LCM-SDXL / LCM adapter** | Treat `LCMScheduler` as an architectural requirement; few-step operation is intrinsic to LCM. Do not inherit ordinary SDXL sampling unchanged. | Base/model VAE. | SDXL. | Conditional accelerator overlay; only promote after an exact Forge sampler/scheduler mapping is verified. |
| **Hyper-SD accelerator variants** | Use **variant-specific** settings rather than a generic “Hyper-SD” default: different releases use DDIM/trailing, TCD or LCM-style scheduling and different step counts. | Inherit base checkpoint unless exact source states otherwise. | Inherit base model. | Adapter-specific profile overlay, not a checkpoint-family default. |

The SDXL finding is particularly useful for the current gap. The existing `research.py` deliberately exposes only SDXL's 1024 geometry and declares sampler, scheduler, steps and CFG unavailable. fileciteturn7file0L2-L2 The new primary-source evidence does **not** justify pretending that “Euler / Automatic / 50 / CFG 5” is an official Stability AI standalone recipe. It **does** justify an evidence-qualified best hypothesis:

```text
SDXL ordinary checkpoint
strict / official:
    width       = 1024
    height      = 1024
    native scheduler algorithm = EulerDiscreteScheduler

best implementation hypothesis:
    sampler     = Euler
    scheduler   = Automatic
    steps       = 50
    cfg_scale   = 5.0
    vae         = checkpoint own / ""
```

That is exactly what the existing `SOURCE_INFERRED = "inferred_or_community"` evidence class is for. fileciteturn18file0L2-L2 The `scheduler="Automatic"` part deserves the lowest confidence because translating a Diffusers `EulerDiscreteScheduler` into Forge's two-dimensional **sampler + scheduler** vocabulary is not one-to-one. It should not be mislabeled as publisher provenance.

### Newer and multi-component families

| Model/family | Recommended source-backed baseline | Extra metadata | StableNew execution treatment |
|---|---|---|---|
| **FLUX.1 dev** | **1024×1024, 50 steps, guidance 3.5** from Black Forest Labs' own Diffusers example. citeturn25view2 | Reference example also sets `max_sequence_length=512`. citeturn25view2 | Record as research metadata, but do **not** auto-enable: current StableNew ordinary `flux` policy remains unverified rather than owner-qualified. fileciteturn17file0L2-L2 |
| **FLUX.1 Schnell** | Few-step model: official examples use the distilled low-step/no-guidance operating regime; keep the precise variant recipe tied to exact identity rather than applying it to all FLUX.1 assets. | Different prompt/token limits from dev should be metadata, not CLIP-skip guesses. | Metadata-only until executable policy exists. |
| **FLUX.2 Klein 4B FP8 — StableNew exact** | **Euler / Beta / 4 steps / CFG 1.0; 1024×1024 or 768×1024.** The BFL model card independently confirms 1024×1024, four inference steps and guidance 1.0. citeturn27search0 | StableNew's exact bundle owns its transformer, **Qwen 3 4B text encoder and `flux2-vae`**; ordinary negative-prompt behavior and optional features are constrained by its exact policy. fileciteturn17file0L2-L2 | **Already strong enough.** Keep Research values derived from the immutable executable profile as they are now. fileciteturn7file0L2-L2 |
| **Z-Image-Turbo FP8 — StableNew exact** | StableNew execution: **Euler / Beta / 9 steps / CFG 1.0 / distilled CFG 9 / 1024×1024 / CLIP skip 1**. The publisher independently specifies 1024 and `num_inference_steps=9`, representing eight DiT forwards. citeturn27search4 | Exact StableNew bundle includes Qwen text encoder and `flux1AE_v10` VAE; operator VAE selection is disallowed. fileciteturn17file0L2-L2 | Keep exact profile. Important provenance nuance: Tongyi's Diffusers recipe uses **guidance 0**, while the managed Forge profile uses CFG 1 plus distilled-scale handling; the latter is backend-specific, not publisher-equivalent. citeturn27search4 fileciteturn7file0L2-L2 |
| **Stable Diffusion 3 Medium** | **28 steps / CFG 7.0** from Stability AI's model-card example. citeturn25view3 | Three text encoders: **OpenCLIP-ViT/G, CLIP-ViT/L, T5-XXL**. citeturn25view3 | Research metadata only until StableNew's executable policy explicitly qualifies SD3. |
| **Stable Diffusion 3.5 Medium** | **40 steps / CFG 4.5** from Stability AI's example. citeturn25view4 | It is an MMDiT-X model, not an SDXL checkpoint despite superficial `.safetensors` similarities. citeturn25view4 | Research metadata only until executable policy qualifies it. |

The last point matters architecturally: StableNew's existing `ModelPolicy` resolves verified SDXL as its only owner-qualified ordinary checkpoint family; resolved SD1, SD2, SD3 and ordinary FLUX are identified but remain generic/unverified. fileciteturn17file0L2-L2 **Researching a good setting does not imply authorization to execute that family.** That boundary should remain untouched.

## VAE, CLIP, LoRA and embedding enrichment rules

The research strongly argues against treating every asset in the model tree as the same sort of “profile.”

### VAE selection

The safe default rule should be:

> **Use the checkpoint/model's own VAE unless there is exact-model evidence that a particular external VAE is required or recommended.**

That is particularly important for mixed local libraries. An external VAE that happens to be excellent for one SD1.5 derivative is not evidence that it belongs with another SD1.5 checkpoint, and an SDXL VAE must never be automatically carried into an unrelated model family. The current Research implementation already takes the conservative approach for SDXL, stating that fine-tuned checkpoints differ in their VAE requirements and therefore leaving the checkpoint's own VAE in place. fileciteturn7file0L2-L2

For exact multi-component profiles such as Klein and Z-Image, the apparent generation-profile value `vae=""` must not be interpreted as “there is no VAE.” It means **there is no operator-selectable external VAE**; the exact backend profile owns the required VAE module. fileciteturn17file0L2-L2

A VAE enrichment record should therefore contain something closer to:

```json
{
  "asset_kind": "vae",
  "sha256": "<exact bytes>",
  "compatible_families": ["sdxl"],
  "recommended_for": [],
  "recommendation_scope": "compatibility_only",
  "source_class": "embedded_metadata",
  "auto_select": false
}
```

Only a creator-authored exact checkpoint recommendation should populate `recommended_for`.

### “CLIP size” should be technical metadata, not another generation knob

The useful information is **which text encoder architecture is present/required, its tokenizer/context characteristics where known, and whether the serving stack requires auxiliary encoder modules**. A generic `clip_skip` default should not be guessed from family.

Examples from primary/model sources are:

| Family | Conditioning architecture worth recording |
|---|---|
| SD1.x | CLIP ViT-L/14. citeturn20search1 |
| SD2.x | OpenCLIP ViT-H. citeturn24search4 |
| SDXL | OpenCLIP-ViT/G + CLIP-ViT/L. citeturn20search0 |
| SD3 Medium | OpenCLIP-ViT/G + CLIP-ViT/L + T5-XXL. citeturn25view3 |
| FLUX.2 Klein exact | StableNew's exact bundle uses Qwen 3 4B. fileciteturn17file0L2-L2 |
| Z-Image exact | StableNew's exact bundle uses the pinned Qwen text encoder and fixes CLIP-skip-equivalent execution policy at 1. fileciteturn17file0L2-L2 |

This information belongs in asset/research metadata even though the current `GenerationProfile.SETTING_KEYS` deliberately contains only sampler, scheduler, steps, CFG, width, height and VAE. fileciteturn18file0L2-L2 That distinction is valuable: there is no reason to enlarge the user-facing profile contract merely to record technical facts useful for compatibility and research.

### Ordinary LoRAs should inherit; accelerator LoRAs should overlay

For the 46 locally observed LoRAs, the default behavior should be **inherit the selected checkpoint profile**. A normal style, character or concept LoRA does not have its own sampler/steps/CFG just because it is a `.safetensors` file.

The useful LoRA metadata is:

```text
exact SHA-256
creator/model/version identity
verified base family
training/base-model version
trigger words
recommended strength, when creator-sourced
compatible checkpoint families
known incompatibilities
source / reviewed date
```

The existing census already extracts base-model fields, creator, model ID, model name, source metadata, trained words and version ID from LoRA sidecars where present. fileciteturn23file0L2-L2 It also previously joined 13 local LoRAs exactly to the optional keyword-cache evidence. fileciteturn10file0L2-L2

**Accelerator LoRAs are the exception.** SDXL-Lightning, LCM and Hyper-SD can fundamentally alter the required scheduler, step count and CFG. ByteDance's Lightning documentation, for example, requires the step-specific checkpoint/LoRA to be used at that exact step count with CFG 0 and trailing Euler scheduling; its ComfyUI instructions explicitly prescribe Euler + `sgm_uniform`. citeturn25view0 Those should be represented as a profile **overlay attached to the LoRA identity**, not as an ordinary LoRA recommendation and not as a new profile framework.

A useful distinction is therefore:

```json
{
  "lora_behavior": "inherit_base_profile"
}
```

versus:

```json
{
  "lora_behavior": "generation_profile_overlay",
  "overlay": {
    "sampler_name": "Euler",
    "scheduler": "SGM Uniform",
    "steps": 4,
    "cfg_scale": 0.0
  }
}
```

### Embeddings should carry compatibility, not sampling recipes

Textual inversions should similarly record exact bytes, compatible text-encoder/model family, trigger token/name and loading availability. They normally have **no independent sampler, scheduler, step, CFG, geometry or VAE recommendation**.

This also highlights why keeping the live-runtime projection separate from the local byte catalog is correct. The previous census found 16 embedding files but only 15 loaded by A1111; local presence and runtime usability are different facts. fileciteturn10file0L2-L2

## PR-ingest data contract

The cleanest implementation is **not** a fourth profile type. It is an evidence-enrichment document that feeds the existing `research_profiles()` builder and the Asset Registry.

I would use a record shaped approximately as follows:

```json
{
  "contract": "model_research_enrichment/1",
  "record_id": "sha256:<checkpoint-sha256>",

  "identity": {
    "asset_kind": "checkpoint",
    "sha256": "<64 lowercase hex>",
    "model_key": "<normalized whole-name key>",
    "family": "sdxl",
    "subtype": "base",
    "identity_confidence": "verified",
    "identity_evidence": [
      "safetensors_metadata",
      "checkpoint_structure",
      "creator_sidecar"
    ]
  },

  "generation": {
    "recommended": {
      "width": 1024,
      "height": 1024
    },

    "hypothesis": {
      "sampler_name": "Euler",
      "scheduler": "Automatic",
      "steps": 50,
      "cfg_scale": 5.0,
      "vae": ""
    },

    "unavailable": {},

    "evidence": [
      {
        "fields": ["width", "height"],
        "source_class": "official_model_recommendation",
        "citation": "SDXL model/report geometry",
        "confidence": "high"
      },
      {
        "fields": ["sampler_name"],
        "source_class": "inferred_or_community",
        "citation": "official repository ships EulerDiscreteScheduler",
        "confidence": "medium",
        "qualification": "Forge mapping is an inference"
      },
      {
        "fields": ["steps", "cfg_scale"],
        "source_class": "inferred_or_community",
        "citation": "Diffusers implementation defaults",
        "confidence": "medium",
        "qualification": "implementation defaults, not publisher recipe"
      },
      {
        "fields": ["scheduler"],
        "source_class": "inferred_or_community",
        "citation": "Forge Automatic chosen to avoid inventing a sigma schedule",
        "confidence": "low"
      }
    ]
  },

  "technical_metadata": {
    "native_scheduler": "EulerDiscreteScheduler",
    "training_geometry": "approximately one-megapixel aspect-ratio buckets",
    "text_encoders": [
      "OpenCLIP-ViT/G",
      "CLIP-ViT/L"
    ],
    "external_vae_required": false,
    "clip_skip_recommendation": null
  },

  "execution": {
    "auto_apply_eligible": true,
    "model_policy_remains_final": true,
    "policy_family_required": "sdxl"
  },

  "research": {
    "reviewed_on": "2026-10-27",
    "status": "candidate"
  }
}
```

This structure intentionally keeps `technical_metadata` separate from the current `GenerationProfile` fields. The current contract already defines exactly seven recommendable Base Generation keys and refuses unknown ones, which is a useful invariant rather than a deficiency. fileciteturn18file0L2-L2

For family-wide evidence, the same record can omit SHA-256 and use:

```json
{
  "record_id": "family:sd1",
  "identity": {
    "asset_kind": "checkpoint",
    "family": "sd1",
    "identity_kind": "family",
    "requires_registry_verified_family": true
  }
}
```

For a creator-specific derivative, it should become model-level:

```json
{
  "record_id": "model:sdxl:<normalized-model-key>",
  "identity": {
    "identity_kind": "model",
    "family": "sdxl",
    "model_key": "<whole-name-key>",
    "sha256": "<checkpoint-sha256>"
  }
}
```

That maps naturally onto the exact/family/model identity scheme the current `GenerationProfile` contract already defines. fileciteturn18file0L2-L2

### Candidate baseline catalog for ingestion

The following is the concise machine-oriented baseline I would seed before exact checkpoint-specific creator research:

```json
{
  "contract": "model_research_baselines/1",
  "reviewed_on": "2026-10-27",
  "records": [
    {
      "id": "family:sd1",
      "policy_status": "metadata_and_research_only_until_policy_allows",
      "settings": {
        "sampler_name": "PLMS",
        "steps": 50,
        "cfg_scale": 7.5,
        "width": 512,
        "height": 512,
        "vae": ""
      },
      "unavailable": {
        "scheduler": "Original reference recipe predates Forge sampler/scheduler separation."
      },
      "metadata": {
        "text_encoders": ["CLIP ViT-L/14"]
      }
    },

    {
      "id": "family:sd2_base_512",
      "policy_status": "metadata_only",
      "settings": {
        "width": 512,
        "height": 512,
        "vae": ""
      },
      "metadata": {
        "text_encoders": ["OpenCLIP ViT-H"]
      }
    },

    {
      "id": "family:sd2_768",
      "policy_status": "metadata_only",
      "settings": {
        "width": 768,
        "height": 768,
        "vae": ""
      },
      "metadata": {
        "text_encoders": ["OpenCLIP ViT-H"]
      }
    },

    {
      "id": "family:sdxl",
      "policy_status": "qualified_family",
      "strict_settings": {
        "width": 1024,
        "height": 1024
      },
      "hypothesis_settings": {
        "sampler_name": "Euler",
        "scheduler": "Automatic",
        "steps": 50,
        "cfg_scale": 5.0,
        "vae": ""
      },
      "metadata": {
        "native_scheduler": "EulerDiscreteScheduler",
        "text_encoders": ["OpenCLIP-ViT/G", "CLIP-ViT/L"]
      }
    },

    {
      "id": "variant:sdxl_turbo",
      "settings": {
        "steps": 4,
        "cfg_scale": 0.0,
        "width": 512,
        "height": 512,
        "vae": ""
      },
      "unavailable": {
        "sampler_name": "No exact Forge mapping promoted from current evidence.",
        "scheduler": "No exact Forge mapping promoted from current evidence."
      },
      "metadata": {
        "supported_step_range": [1, 4],
        "negative_prompt": "not_used"
      }
    },

    {
      "id": "variant:sdxl_lightning_Nstep",
      "settings": {
        "sampler_name": "Euler",
        "scheduler": "SGM Uniform",
        "steps": "<derive from exact 2/4/8-step variant>",
        "cfg_scale": 0.0,
        "width": 1024,
        "height": 1024,
        "vae": ""
      }
    },

    {
      "id": "family:flux1_dev",
      "policy_status": "metadata_only",
      "settings": {
        "steps": 50,
        "cfg_scale": 3.5,
        "width": 1024,
        "height": 1024,
        "vae": ""
      },
      "metadata": {
        "max_sequence_length": 512
      }
    },

    {
      "id": "exact:flux2_klein_4b_fp8",
      "policy_status": "exact_profile",
      "settings": {
        "sampler_name": "Euler",
        "scheduler": "Beta",
        "steps": 4,
        "cfg_scale": 1.0,
        "width": 1024,
        "height": 1024,
        "vae": ""
      },
      "metadata": {
        "alternate_geometry": [768, 1024],
        "text_encoder": "Qwen 3 4B",
        "vae_selection": "profile_owned"
      }
    },

    {
      "id": "exact:z_image_turbo_fp8_scaled",
      "policy_status": "exact_profile_limited",
      "settings": {
        "sampler_name": "Euler",
        "scheduler": "Beta",
        "steps": 9,
        "cfg_scale": 1.0,
        "width": 1024,
        "height": 1024,
        "vae": ""
      },
      "metadata": {
        "publisher_guidance": 0.0,
        "forge_distilled_cfg_scale": 9.0,
        "clip_skip": 1,
        "vae_selection": "profile_owned"
      }
    },

    {
      "id": "family:sd3_medium",
      "policy_status": "metadata_only",
      "settings": {
        "steps": 28,
        "cfg_scale": 7.0,
        "vae": ""
      },
      "metadata": {
        "text_encoders": [
          "OpenCLIP-ViT/G",
          "CLIP-ViT/L",
          "T5-XXL"
        ]
      }
    },

    {
      "id": "family:sd35_medium",
      "policy_status": "metadata_only",
      "settings": {
        "steps": 40,
        "cfg_scale": 4.5,
        "vae": ""
      }
    }
  ]
}
```

The evidence underlying those records is not uniform, which is why the production record should retain evidence per field rather than treating the JSON object itself as authority. SD1's 512/PLMS/50/7.5 recipe comes directly from CompVis. citeturn20search1 SDXL's native Euler scheduler comes from the shipped scheduler config while its complete Forge recipe remains partly inferred. citeturn23search0turn20search0 Turbo's 512/CFG-0/few-step behavior is publisher-prescribed. citeturn26view0 Lightning's Euler/SGM-Uniform/exact-step/CFG-0 recipe is unusually explicit. citeturn25view0 FLUX.1 dev's 1024/50/3.5 values come from BFL's model card. citeturn25view2 Klein and Z-Image have both publisher evidence and StableNew-owned exact profiles. citeturn27search0turn27search4 fileciteturn17file0L2-L2 SD3 and SD3.5 have explicit Stability AI inference examples but do not yet have StableNew-qualified execution policies. citeturn25view3turn25view4

## Selected profile versus compiled versus executed settings

This is the highest-value GUI enhancement after enrichment because it answers the operational question that a richer Research catalog otherwise leaves unresolved:

> **Did the settings I selected actually become the settings that executed?**

PR #225 explicitly states that the current system preserves the canonical path from intent through compiler, immutable NJR, JobService/SQLite and runner, but also acknowledges that full historical per-field compiled provenance is not recorded and must not be invented. fileciteturn5file0L9-L17

The GUI should therefore show three factual columns:

| Field | Selected profile | Compiled effective | Recorded execution |
|---|---|---|---|
| Model identity | Research/Learning/Custom exact or family identity | NJR model + exact profile reference | Backend-recorded checkpoint identity where available |
| VAE | Profile recommendation | Effective NJR/module configuration | Actually selected module/VAE if recorded |
| Sampler | Selected value | Post-ModelPolicy/compiler value | Dispatch payload / execution metadata |
| Scheduler | Selected value | Post-compiler value | Dispatch payload / execution metadata |
| Steps | Selected value | Effective NJR value | Executed/requested steps |
| CFG | Selected value | Effective NJR value | Backend-requested CFG/distilled CFG |
| Geometry | Selected width × height | Effective NJR dimensions | Recorded output/request dimensions |
| CLIP/text modules | Technical metadata or “not applicable” | Profile-owned module configuration where relevant | Backend-recorded modules where available |

Each cell should have one of four statuses:

**same**, **changed by compilation/policy**, **not recorded**, or **unavailable**.

It should **not** synthesize a reason when none was persisted. For an old historical job, “compiled source unavailable” is preferable to “Research profile” if the latter cannot be proved. That follows the exact principle already embedded in `GenerationProfile`: missing evidence is declared unavailable rather than filled in. fileciteturn18file0L2-L2

Z-Image is an excellent test case for this UI. A Research profile can truthfully show StableNew's selected CFG 1.0, while the evidence panel notes that Tongyi's native Diffusers recipe uses guidance 0; the compiled/execution view can separately show StableNew's profile-owned `distilled_cfg_scale=9`. citeturn27search4 fileciteturn17file0L2-L2 Without that separation, “CFG 1” can incorrectly appear to be a publisher recommendation rather than a Forge execution adaptation.

Likewise, SDXL is a useful ordinary-model case:

```text
Selected Research
    geometry       1024×1024
    sampler        Euler             [inferred from native scheduler]
    scheduler      Automatic         [Forge hypothesis]
    steps          50                [Diffusers implementation baseline]
    CFG            5.0               [Diffusers implementation baseline]

Compiled effective
    whatever ModelPolicy + compiler actually accepted/froze

Recorded execution
    values actually submitted/recorded
```

A difference between those three layers is not necessarily an error. **An unexplained difference is the error.**

## Recommended implementation posture

The most economical next PR should have a narrow objective: **turn the existing local asset census and Research profile framework into an evidence-enriched catalog without changing execution authority.**

The first slice should ingest the local census by exact SHA-256 and attach technical/research metadata. The existing census already produces almost all the required identity substrate—path, hash, embedded metadata, sidecars, duplicate relationships and LoRA enrichment—and intentionally performs no model loading or GPU work. fileciteturn23file0L2-L2 There is no reason to create another scanner.

The second slice should enrich only models for which evidence can be resolved confidently. For an exact derivative with a sidecar model/version ID, research the **creator's exact version**, not merely its base family. A hypothetical local checkpoint such as an SDXL photorealism merge should inherit SDXL geometry only until its exact creator documentation supplies a sampler, CFG, VAE or step recommendation. Conversely, an exact Lightning-derived checkpoint must not inherit ordinary SDXL's 50-step hypothesis when ByteDance's accelerated recipe is identifiable. citeturn25view0

The precedence should be:

```text
exact checkpoint creator recommendation
    >
exact StableNew tested/executable profile
    >
exact accelerator/adapter recommendation
    >
verified family recommendation
    >
implementation baseline / best hypothesis
    >
unavailable
```

For Klein and Z-Image, the immutable executable profiles remain the primary StableNew execution truth, exactly as `research.py` already does. fileciteturn7file0L2-L2 For SDXL, family Research can become richer while retaining clear source classes. For SD1/SD2/SD3/ordinary FLUX, research data can be stored immediately even though ModelPolicy continues to prevent that metadata from making unsupported execution claims. fileciteturn17file0L2-L2

The Learning relationship should remain equally simple:

```text
Research
    source-backed starting point

        ↓ operator actually generates and rates

Learning
    controlled empirical evidence for that exact verified model identity

        ↓ explicit evidence-qualified publication

immutable Learning profile revision

Custom
    operator-authored deliberate settings
```

Learning should not overwrite the underlying Research provenance. It should record that, for example, an exact SHA-256 checkpoint consistently scored better at 32 steps / CFG 4.5 than its Research baseline of 50 / 5.0 under controlled comparisons. That distinction is precisely what makes Learning useful rather than turning it into a mutable preference store.

The present architecture already supports that direction: Learning publication is explicit and evidence-qualified, immutable revisions are stored separately, and PR #225 proved that a published profile can be reselected and make the normal compiler/SQLite round trip without changing the architectural authority chain. fileciteturn5file0L9-L17

## Conclusions and remaining limitations

The current profile framework is **not** the gap. The gap is evidence density and execution observability.

The strongest immediate additions to the Research catalog are:

1. **SDXL:** preserve 1024×1024 as authoritative, add its native `EulerDiscreteScheduler` as technical evidence, and optionally expose Euler / Automatic / 50 / CFG 5 as an explicitly **inferred implementation baseline**, not a Stability AI official recipe. citeturn23search0turn20search0
2. **SD1.x:** add the original publisher recipe—PLMS / 50 / CFG 7.5 / 512×512 / CLIP ViT-L/14—when the Asset Registry verifies the family. citeturn20search1
3. **SD2.x:** distinguish 512-base from 768-v instead of assigning one geometry to the whole family, and record OpenCLIP ViT-H. citeturn24search4
4. **SDXL-Turbo:** add an exact/distilled variant record: 512×512, CFG 0, 1–4 steps; four is the quality-oriented default, one the speed-oriented default. citeturn26view0
5. **SDXL-Lightning:** add exact N-step records or accelerator overlays with Euler / SGM Uniform / exact N / CFG 0. This is among the clearest authoritative sampler/scheduler recipes found. citeturn25view0
6. **FLUX.1 dev, SD3, SD3.5:** store their publisher-recommended generation metadata now but keep it metadata-only until their ModelPolicy/execution support is actually qualified. citeturn25view2turn25view3turn25view4
7. **Klein and Z-Image:** keep the existing exact profiles as the canonical executable recommendations; their evidence is already substantially stronger than the generic SDXL recipe. fileciteturn7file0L2-L2

The main unresolved limitation is the **exact current 45-checkpoint name/hash inventory**. The repository proves such a census was performed, but deliberately excludes the machine-local output from source control. fileciteturn10file0L2-L2 Without direct access to the Windows host's current `data/asset_census` or model folders, it would be misleading to fabricate a checkpoint-by-checkpoint list. Once that exact census is consumed, the research strategy above can turn each of those 45 hashes into one of four outcomes: **exact creator profile, exact accelerator profile, verified-family fallback, or explicitly unavailable evidence**.

That is also the right standard for the LoRAs, VAEs and embeddings: enrich aggressively, infer conservatively, and execute only through existing policy.

Most importantly, the next operator-facing capability should expose:

> **Selected recommendation → compiled effective settings → recorded execution settings**

with source class and “not recorded/unavailable” states visible per field. That closes the real trust gap without weakening `ModelPolicy`, inventing historical provenance, or adding another profile framework.