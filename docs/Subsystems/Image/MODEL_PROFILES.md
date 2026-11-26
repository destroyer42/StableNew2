# Exact model profiles and model policy

Status: living document, edit in place
Owner area: exact image-model profiles and the model policy projection (`src/image_backends/forge_klein_*.py`, `forge_zimage_profile.py`, `exact_model_profile.py`, `model_policy*.py`, `operation_compatibility.py`, `model_readiness*.py`, `src/pipeline/exact_profile_effective_config.py`, `src/learning/model_comparison.py`)

How to keep this true:
- Change this file in the same PR that changes a profile envelope, adds a profile version, moves a rule between compiler/backend/GUI, or changes a refusal. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.
- Stage, backend, executor and artifact context is in `docs/Subsystems/Image/IMAGE_PIPELINE.md` (sections 1 to 4, 9, 12). This file goes deeper on profiles and does not repeat it.

## 1. Scope and the four concepts

Covered: exact profiles and structural family profiles for Forge, Diffusers and Comfy still-image work, the refusal of Klein Base 9B, `ModelPolicy`, operation compatibility, effective-config adaptation and global-positive ownership, local asset evidence as it gates dispatch, readiness, and Model Comparison where it touches profiles. Not covered: SDXL ordinary work (generic path), OpenPose (IMAGE_PIPELINE 3.1), video.

SDXL backend row (PR-IMG-COMFY-381): a registry-classified SDXL checkpoint (`_sdxl_policy`) is allowed on `forge_webui`, `a1111_webui` (every feature as before) and `comfyui` (txt2img only: sampler/scheduler mapped by `comfy_sdxl_mapping`, `<lora:>` tags turned into `LoraLoader` nodes resolved by registry SHA, negative prompt and CLIP skip supported; hires, refiner, ADetailer, img2img, upscale and ControlNet refused at Preview). The ComfyUI leg is offline-tested only and not physically qualified; the Forge-vs-ComfyUI comparison is a separate owner-gated run.

Four concepts stay separate (a fifth, advisory recommended generation profiles, is in section 17); most bugs here come from mixing them (`model_policy.py` module docstring):

| Concept | Authority | Never |
|---|---|---|
| Backend identity (`forge_webui`/`a1111_webui`) | Configuration, resolved by `resolve_image_backend_id` / `configured_image_backend_id` | inferred from a model name |
| Model family (`sdxl`, `flux2_klein`, `z_image`, `unknown`, sd1/sd2/sd3/flux) | Exact profile first, else `AssetRegistry` evidence via `RegistryFamilyLookup` | guessed; nothing unclassified is labelled SDXL |
| Exact profile (`{"id","version"}`) | Immutable dataclasses in `forge_klein_profile.py` / `forge_zimage_profile.py`, dispatched by `exact_model_profile.py` | edited after publication |
| Policy (`ModelPolicy`) | `src/image_backends/model_policy.py`, a read-only projection of the profile | an executor, compiler or hash authority |

The GUI, PromptPack editor readiness, Learning and operation compatibility project the policy and are advisory. The compiler and the Forge backend validate every job independently and are final.

## 2. Profiles and envelopes

All three exact-profile dataclasses reuse `KleinAsset` (role, filename, size, SHA-256, models subdir, repo, revision). Both profiles require the Forge backend (`backend_id = forge_webui`) and the 32e9-byte total-RAM floor (decimal, not GiB; available RAM is recorded only) [V].

### 2.1 FLUX.2 Klein 4B FP8 (`flux2_klein_4b_fp8`)

| Field | v1 | v2 |
|---|---|---|
| Constructed by | `KLEIN_PROFILE_V1` | `replace(V1, version=2, max_loras=1)` (`KLEIN_PROFILE_V2`) |
| Assets | transformer `flux-2-klein-4b-fp8.safetensors` (4,070,624,520 bytes), text encoder `qwen_3_4b.safetensors`, VAE `flux2-vae.safetensors`; sizes and SHA-256 are in the dataclass | identical |
| Sampling | Euler / Beta / 4 steps / CFG 1.0 (fixed) | identical |
| Geometry | 768x1024 or 1024x1024 | identical |
| Modes | `txt2img` (stage chain exactly `["txt2img"]`, 0 source images); `single_reference_edit` (chain exactly `["img2img"]`, exactly 1 source, denoise 1.0) | identical |
| LoRA | none (`max_loras = 0`) | at most one, txt2img only, only if registry metadata explicitly names Klein 4B (section 7); never with the edit mode |
| Always off | negative prompt, global prompt terms, prompt optimizer, hires, refiner, aesthetic, ControlNet, hypernetwork, ADetailer, upscale, image count other than 1 | identical |

Enforced where:

- Compiler: `apply_klein_compile_policy` (reached through `apply_model_compile_policy` when `klein_selected(config)`) fixes sampler/scheduler/steps/CFG, clears negative and global terms, sets `global_prompt_policy_source = frozen_njr`, disables the optimizer and the global flags, and stamps `backend_options.image.model_profile = latest_klein_profile().reference()`. It deliberately does not touch geometry, hires, LoRA or stages, so a real conflict reaches the validators and is refused, never rewritten [V].
- Review edit intent: `prepare_klein_edit_item` (`src/pipeline/klein_edit_reprocess.py`) runs `validate_klein_intent`, freezes the source image SHA-256 into `ReprocessSourceItem.metadata[KLEIN_EDIT_METADATA_KEY]`, and `klein_edit_config` builds the whole frozen config. The edit is explicit, never inferred from an image.
- Backend, once per NJR before any stage: `ForgeWebUIImageBackend.validate_njr_intent` (called by `PipelineRunner._resolve_image_backend_id`). Per stage, before any side effect: `_validate_request`. Both use `validate_profile_intent` -> `validate_klein_intent` plus `detect_unsupported_features`, `_vae_conflict`, `_global_term_conflicts` and the LoRA checks. `validate_klein_intent` raises one `KleinProfileError` listing every conflict [V].
- Backend, immediately before the first POST (`_before_dispatch`): host RAM (`check_klein_host_memory`), asset bytes (`verify_klein_assets`), served listing (`_assert_assets_listed`), served LoRA binding when a LoRA is present, and for the edit the source file SHA-256 (`_verify_frozen_source`).
- Projection: `_finalize_config` overwrites model, sampling, modules (`additional_modules` = text encoder + VAE) and, for edits, `denoising_strength` and drops mask keys. Edit denoise is forced here, not validated [V].

### 2.2 Z-Image-Turbo FP8 (`z_image_turbo_fp8_scaled` v1, limited support)

- Assets: transformer `zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors`, text encoder `qwen3_4b_2964436.safetensors`, VAE `flux1AE_v10.safetensors`; pinned to managed Forge revision `forge_revision` (`config/managed_forge_runtime.json`). The text encoder is byte-identical (same size and SHA-256) to Klein's under a different filename [V].
- Envelope: Forge only; txt2img only; 1024x1024; one image (`batch_size`, `n_iter`, `images_per_prompt` all 1); Euler / Beta / 9 steps / CFG 1.0 / `distilled_cfg_scale` 9.0; CLIP skip 1; no VAE selection; no negative or global prompt text; global flags off; no hires, refiner, ADetailer, upscale, img2img, LoRA, embeddings, ControlNet, hypernetwork, styles, `alwayson_scripts`, `override_settings`; seed integer in -1..4294967295; prompt non-empty, at most 10,000 characters, natural language only (the regex in `validate_zimage_config` rejects `<`, `>`, `(x:1.2)` weights, `[`, `]`, `embedding:`) [V].
- Compiler: `apply_zimage_compile_policy` first runs `validate_zimage_config` (so inherited values must already be normalized, section 5), then `normalize_image_backend_options`, requires Forge and exactly `ZIMAGE_PROFILE_V1`, and fills defaults.
- Backend: `validate_njr_intent` -> `validate_zimage_njr` (which also re-validates every enabled stage's `extra` and the NJR scalar fields); `_validate_request` re-validates `execution_config`, stage config, `extra`, seed, image count, VAE; `_before_dispatch` runs host RAM and `verify_zimage_assets`, which requires the StableNew-owned managed Forge, checks `verify_pinned_launch` against the revision, and hashes the exact served paths from `get_models` / `get_module_catalog` (ambiguity refuses).
- Executor wire seam: `Pipeline.run_txt2img_stage` preserves the exact profile's admitted positive prompt through empty refinement. `project_zimage_wire_payload` keeps only an allow-list of payload keys plus `distilled_cfg_scale`, `send_images`, `save_images=False`, and refuses a `shift` field or a changed prompt. `verify_zimage_dispatch_state` reads `/options` immediately before the POST and refuses unless the 20 pinned sampling options (`SAMPLING_OPTIONS`), the checkpoint and the module set match. Both calls are no-ops for other models. The projection refuses a Z-Image checkpoint that lacks its profile (IMAGE_PIPELINE 2.3).
- Evidence: `backend_metadata["zimage_profile"]` carries `qualification_status = "one_generation_observed; INSTRUMENTATION_GAP"`. Physical qualification is inconclusive and no repeat attempt is authorized (STATUS.md Holds); do not describe the profile as qualified [V].

### 2.2a Ideogram 4 NF4 (`ideogram4_nf4_diffusers` v1, Diffusers, not physically qualified)

- Identity: model name `ideogram-4-nf4-diffusers@1874bc70` (whole-name match), snapshot `ideogram-ai/ideogram-4-nf4-diffusers` @ `1874bc70`, read offline from the local Hugging Face cache; offered in Base Generation only when `diffusers_readiness.check_installation` is ready (packages incl. the optional pinned `bitsandbytes==0.50.2` extra, and every pinned file).
- Envelope: `diffusers` backend only; txt2img only; steps choose the official preset (12 Turbo, 20 Default, 48 Quality; guidance reversed for Diffusers); sizes 1024x1024, 768x1024, 1024x768, 768x768, 512x512; 1-4 images per job; no negative prompt, LoRA, embeddings, VAE choice or other stages. Plain prompts map to a minimal caption, JSON prompts must pass the official caption rules (`ideogram4_caption.py`, mapping v1).
- Runtime: 110R staged-swap residency in a per-job contained child with an allocator cap, VRAM/RAM floors and teardown proof. Non-commercial licence accepted by the owner on 2026-11-18. Record: `docs/Subsystems/Image/PR-IMG-120_Ideogram4_Diffusers_Production_Slice.md`.

### 2.2b FLUX.1 [dev] family profile (`flux1_dev_gguf` v1, Forge, not physically qualified)

- Record: `docs/Subsystems/Image/PR-IMG-FLUX-130_Generic_FLUX_Families.md` (owner decisions Q1-Q4, 2026-11-20). Module: `src/image_backends/forge_flux1_profile.py`.
- A **family** profile: the transformer is admitted by its structural layout, not by name or bytes. Any transformer-only file whose bounded header (safetensors table or GGUF tensor table) classifies as `flux1_dev` (`src/assets/flux_variant.py`) in an admitted precision (GGUF Q4_K_S/Q5_K_S/Q6_K/Q8_0, FP8-scaled safetensors) runs under it; its SHA-256 is recorded (`recommended_download` when it equals the pinned `city96/FLUX.1-dev-gguf` Q4_K_S digest, else `derivative_or_other_conversion`), never required. CLIP-L, T5-XXL FP8 and the FLUX.1 AE are pinned by size and SHA-256 and verified on the served paths (`verify_flux1_assets`).
- Envelope: managed Forge `d70373eb` only; txt2img only; Euler / Simple / 20 steps / CFG 1.0 / distilled guidance 3.5 / CLIP skip 1, all fixed; sizes 1024x1024, 896x1152, 1152x896, 832x1216, 1216x832; one image; no negative prompt, global terms, prompt optimizer, LoRA, embeddings, VAE choice, input image or other stages. Same 32e9-byte host-RAM floor as Klein.
- Selection: the compiler stamps the reference only when the registry snapshot records a transformer-only `flux1_dev` layout for the selected checkpoint (the installable lookup `install_variant_lookup`, installed by `src/main.py`); a frozen reference is never upgraded or swapped. The backend re-derives the layout from the served file at dispatch.
- Evidence: `backend_metadata["flux1_profile"]` (`flux1_provenance` + `asset_identity`), `qualification_status = "not physically qualified"`. Policy evidence is `structural_profile`, so `exact_identity_authority` is false and Model Comparison refuses it.

### 2.2c FLUX.1 [schnell] family profile (`flux1_schnell` v1, Forge)

The standalone schnell layout is identified by the absence of the FLUX.1 guidance embedding. It uses the same
verified CLIP-L, T5-XXL FP8 and FLUX.1 AE modules as dev. The profile freezes four Euler/Simple steps, CFG 1,
and omits distilled guidance from the Forge payload. Physical qualification is pending.

### 2.2d Qwen-Image on managed ComfyUI

- The Qwen-Image 2.1 int8 and 2.1 Turbo int8 profiles retain their exact pinned assets and graphs.
- `qwen_image_20b_fp8` v1 admits the standalone 60-block, unscaled E4M3 Qwen-Image DiT layout. The NJR freezes
  the selected checkpoint name and profile reference. Comfy readiness checks the selected file and dependencies
  at Preview. Dispatch verifies the file's header again and records its SHA-256 alongside the pinned encoder and VAE.
- The core-node graph uses Euler/Simple, 20 steps, CFG 4 and shift 3.1. It generates one image from a positive
  text prompt. The profile needs the 9.38 GB Qwen2.5-VL-7B FP8 scaled encoder in `models/text_encoders` and
  the pinned Qwen-Image VAE. A uniquely identifiable renamed VAE with the pinned bytes is accepted.
- A shared checkpoint library must be visible to Comfy's `diffusion_models` loader. See the
  [managed Comfy runtime runbook](../../runbooks/managed_comfy_runtime.md). The pre-dispatch floors are 11 GiB
  free VRAM and 28 GiB free RAM. Physical qualification is pending and requires owner authorization.

### 2.3 Klein Base 9B and other FLUX layouts (refused, no profile)

There is no profile for Klein 9B. `NO_GO_RESOURCE_RISK` is the decision recorded in `PR-IMG-MODELS-151`. The refusal is generic: `ForgeWebUIImageBackend._dependency_gate` (run from `_before_dispatch` only when there is no exact profile and the name is not the Klein 4B transformer) calls `probe_model_readiness`; `ModelReadiness.blocks_dispatch` is true for a not-qualified checkpoint whose safetensors header positively identifies a dependency-bearing transformer; since owner decision N1 (warn, don't block, 2026-11-25) the gate no longer refuses it: it returns a `PolicyWarning` (why, which file is missing and the Forge folder it goes in, or which listed module to select), records it on the result as `policy_warning` and skips the module baseline so Forge's own module selection is used (N1 option a). Only a file that is positively a text encoder or VAE still raises `ForgeUnqualifiedModelError`. Queue from the Pipeline tab freezes the warning the picker showed in the job's `provenance.metadata.accepted_warnings`. Unreadable, ambiguous or unrecognized evidence is "unverified" and preserves the old generic behavior [V]. Any other FLUX-style multi-component checkpoint is handled the same way.

PR-IMG-FLUX-130 names the layout: a FLUX transformer is classified into `flux1_dev`, `flux1_schnell`, `flux2_klein_4b`, `flux2_klein_9b` or `flux_unrecognized` (plus a `_bundled` form) from safetensors headers **and GGUF tensor tables**, so the GGUF 9B files that used to bypass the gate as "unsupported format" are refused too. Each refused layout has its own sentence (`FLUX_VARIANT_REFUSALS`): 9B is NO-GO in every precision; a Klein 4B-class file outside the exact profile and unrecognised FLUX layouts have no profile. `ModelPolicy.refusal` carries the same sentence to the GUI. A transformer-only DiT of no known layout (`unrecognized_dit`, the installed `flux3Klein_*` transformer) is refused, and a text encoder or VAE selected as a checkpoint is `NOT_A_CHECKPOINT`.

## 3. Versioning and frozen work

- The NJR persists only `backend_options.image.model_profile = {"id", "version"}`; the code owns the expectations. A published version is never edited; a change is a new `replace(...)` version registered in `_PROFILES` (Klein) [V].
- Resolution is `resolve_model_profile` (`exact_model_profile.py`): a Z-Image id must equal `ZIMAGE_PROFILE_V1.reference()` exactly (int version, no extra keys); otherwise Klein resolution runs, which accepts only `(id, version)` pairs in `_PROFILES`. A malformed, unknown or unknown-version reference raises `KleinProfileError` / `ZImageProfileError`; it is never read as SDXL [V].
- "Latest" is used only when constructing new work: `latest_klein_profile()` feeds `apply_klein_compile_policy`, `model_profile_for_model` (which `normalize_image_backend_options` uses when `model_name` is given and no profile is present), `klein_edit_config`, `prepare_klein_edit_item`, the Review readiness adapter and `resolve_model_policy(model_name)`. `_LATEST_PROFILE` is v2. Per its comment it moves to a newer version only after that version's physical qualification succeeds [V].
- Persisted work resolves its own version everywhere that matters: backend `_profile_for(backend_options)`, `policy_for_njr` / `policy_for_model_profile_reference` in operation compatibility, and Learning's frozen `policy_context`. So a v1 NJR still refuses LoRA after v2 exists.
- Replay and reprocess keep an explicit `model_profile` untouched (`normalize_image_backend_options` never overwrites it). Replaying a profile NJR on the A1111 backend is refused by `WebUIFamilyImageBackend._reject_foreign_model_profile` (`KleinProfileError`, also for Z-Image).
- The reprocess path only builds Klein edits through `prepare_klein_edit_item`; Z-Image has no reprocess mode, so operation compatibility refuses any non-txt2img chain for it.

## 4. ModelPolicy and the capability registry

`resolve_model_policy(model_name, family_lookup=None)` resolution order [V]:

1. `is_klein_transformer_name` -> `policy_for_profile(latest_klein_profile())`.
2. `is_zimage_transformer_name` -> `policy_for_profile(ZIMAGE_PROFILE_V1)`.
3. Ideogram 4 and the two Qwen-Image 2.1 profiles match their pinned model names.
4. A resolved checkpoint layout can select the FLUX.1 dev or schnell family profile, the Qwen-Image 20B Comfy
   profile, or a precise FLUX or Z-Image refusal. The Z-Image tensor layout leaves the Turbo variant unresolved.
5. Resolved ordinary SDXL uses the SDXL policy. Conflicting, unreadable and unsupported evidence produces an
   unverified policy.

Name matching is whole-name after stripping directory, a ` [hash]` suffix and a weights extension (`_model_key`), never a substring. Three copies of that normalizer exist (`forge_klein_profile._model_key`, `model_policy._model_key`, `model_readiness_probe.checkpoint_key`); keep them equivalent [V].

`ModelPolicy` content: `controls` (`ControlMode` configurable/fixed/unsupported for sampler, scheduler, steps, cfg_scale, vae, geometry; geometry with `allowed` is a restricted choice), `features` (`Support` supported/unsupported/unverified for negative_prompt, prompt_optimizer, embeddings, lora, hires, refiner, adetailer, controlnet, upscale, with `limit`, `compatibility_policy`, `stages`), `stage_controls` (Klein img2img denoise fixed), `allowed_backends` / `required_backend`, `stages`, `modes`, `prompt_dialect`, `profile_ref`, `note`. Derived properties used as gates: `qualified` (a profile exists), `exact_identity_authority` (profile evidence), `explicit_capabilities` (no `UNVERIFIED` feature), `constrained`, `learning_variables()`.

- `QUALIFIED_REGISTRY_POLICY_IDS = {"sdxl"}` is the only owner-qualified ordinary-checkpoint policy. Qualifying another family means authoring its `ModelPolicy` and adding its id there, with owner approval.
- `policy_for_profile` builds Klein and Z-Image policies from the profile fields (so a profile change flows to the GUI automatically). It is an `isinstance(ZImageProfile)` branch with Klein as the implicit else (audit E2) [V/A]. The Z-Image family string `"z_image"` is a bare literal; Klein has `FAMILY_FLUX2_KLEIN`.
- Compile seams: `apply_model_compile_policy` (one entry point; Z-Image branch, a frozen Z-Image reference without the Z-Image checkpoint raises `ValueError`, Klein through `_COMPILE_POLICIES`, no-op otherwise), `normalize_profile_owned_values` and `prepare_candidate_baseline` (only Z-Image acts; section 5). The PromptPack route evaluates the policy once per prepared prompt through `compile_model_policy`; the returned `ModelPolicyResult` projects onto the nested configuration (`project_nested`, the evaluated mapping) and onto each record's flat payload (`project_flat`, which restores the profile-owned keys the flattening drops and re-checks the payload against the Z-Image profile), so a new family adds its evaluation and its projection in `model_policy.py` (P4-2G) [V].
- GUI projections of the same policy: `src/gui_v2/model_policy_projection.py` (pure) and `src/gui/model_policy_panel_projection.py` (Tk glue: fixed values shown disabled, draft restore), `src/gui/zimage_optional_control_projection.py` (disables Z-Image-unsupported controls, never removes stored intent), `src/gui/model_readiness_presenter.py` (explicit "Check readiness" button, worker thread).
- `src/learning/model_profiles.py` (style priors for Learning) is a different concept; do not merge it with `ModelPolicy`.

The Base Generation panel resolves displayed checkpoint labels to internal resource names before projecting policy. Resource
publication and READY sidebar refresh share validated AppState catalogs. Empty/missing catalogs remain empty in AppState and
notify consumers, including Learning cancellation. The Pipeline panel preserves its working selections and menu presentation;
its last displayed scheduler choices can restore the widget on saved-config load and never establish resource availability.
The transport cannot distinguish failed refresh from a successful empty catalog, so retained choices are presentation only;
consumers must use the published catalog to assess availability. Non-empty model replacements reconcile aliases and preserve
the selected checkpoint; an absent selection is shown as unavailable instead of selecting the first checkpoint.
Resource refresh and saved-recipe restoration reapply the
existing fixed controls. Add to Queue submits the frozen Preview NJRs and clears successful drafts without resetting working
generation settings; no resource projection recompiles or substitutes those records.

## 5. Effective-config adaptation and global-positive policy

The rule: values an exact profile owns are replaced with the profile's own, with a content-free change record; values the operator owns (geometry, counts, seed, stages, assets, optional features) are never touched, so a real conflict is refused. Source intent and the executable config stay separate.

| Profile | Who normalizes inherited values | Global positive terms |
|---|---|---|
| Klein | `apply_klein_compile_policy` clears them (it is a compile policy, not an adaptation) | Cleared and disabled; the backend refuses non-empty `global_positive_prompt` / `global_negative_prompt` |
| Z-Image | `normalize_profile_owned_values` -> `project_shared_baseline` (sampling, CLIP skip, VAE, optimizer, prompt channels, global flags) | Composed into the prompt by the compiler, because the Z-Image executor config cannot apply them; flags then forced off |

Call sites that must normalize before `apply_model_compile_policy` for Z-Image [V]:

- PromptPack: `PromptPackNormalizedJobBuilder._prepare_entry` normalizes the executable copy only, keeps `source_config` for adaptation evidence, and composes global positive in the resolution layer (`resolution_layer.compose_global_positive`).
- Generic/matrix builder: `JobBuilderV2` calls `prepare_effective_config` (`src/pipeline/exact_profile_effective_config.py`, contract `effective_configuration/1`): normalize, then compose enabled stored terms in front of the prompt with `merge_global_positive` after `adapt_prompt_for_target`. `EffectiveProfileConfig.evidence()` is the frozen provenance (`normalized`, `global_positive` = `composed`/`not_applied`, `global_negative` = `omitted`, `operations`). The manual prompt is validated, not adapted.
- Model Comparison: `prepare_candidate_baseline` per arm (section 9).
- CLI (`build_cli_njr`) and Learning single-variable `compile_variant` call only `apply_model_compile_policy`; there is no normalization step, so for Z-Image inherited non-profile values are refused by `validate_zimage_config` rather than adapted [V by reading, not run].

Frozen global-prompt policy (`src/pipeline/global_prompt_policy.py`): a config is "frozen" when `global_prompt_policy_source == "frozen_njr"`, both term keys exist, and all five stage flags are present (`has_frozen_global_prompt_policy`). The executor reads terms from the NJR when frozen and falls back to the mutable prompt files (`LEGACY_POLICY_SOURCE`) otherwise (`Pipeline._global_prompt_terms`). `frozen_global_positive_policy` is the read-only `(terms, enabled)` projection after a compile policy has run; the effective ownership of a target is derived from it, never tabulated by family. Prompt-level adaptation (weights, BREAK, LoRA/embedding omission) is IMAGE_PIPELINE 4.4.

## 6. Where each rule lives

| Rule | GUI projection (advisory) | Operation compat (preflight) | Compiler | Runner/backend (final) |
|---|---|---|---|---|
| Backend must be Forge | `ModelPolicy.required_backend`, panel note | `backend_mismatch` | `apply_zimage_compile_policy` (Z-Image) | `validate_profile_intent`; `_reject_foreign_model_profile` |
| Stage chain / mode | `policy.modes`, Review edit checkbox | `stage_unsupported`, `stage_chain_unsupported`, `mode_not_requested` | Klein edit builder; Model Comparison `_require_envelope` | `validate_klein_intent`, `validate_zimage_njr`; `validate_stage_chain` |
| Source image count | n/a | `source_image_count` | `prepare_klein_edit_item` | `validate_njr_intent` (Klein 0/1), `_validate_request` |
| Geometry | `ControlPolicy.allowed` presets | `geometry_unsupported` (only when width/height known) | Model Comparison shared-geometry check | `validate_klein_intent`, `validate_zimage_config`, `_finalize_config` (Z-Image forces 1024) |
| Sampler/scheduler/steps/CFG/VAE | `ControlMode.FIXED` | not assessed | Klein/Z-Image compile policies | Both validators; `_finalize_config` overwrites |
| Negative / global terms | `features.negative_prompt` | not assessed | cleared (Klein), cleared/composed (Z-Image) | `_global_term_conflicts`, `validate_*` |
| Optional features (hires, refiner, ...) | `features.*` | not assessed | not rewritten | `detect_unsupported_features` / `validate_zimage_config` |
| LoRA count and compatibility | `assess_lora_selection` (cache-only resolver) | not assessed | PromptPack LoRA selection manifest | `evaluate_klein_loras` with a refreshing resolver |
| Asset bytes, host RAM, served state | readiness button (names only) | never | never | `_before_dispatch` |

Rule of thumb: the GUI and operation compatibility may say "this will be refused"; only the backend may say "this is allowed". An ordinary SDXL or unverified target is never narrowed by operation compatibility (`assess_operation` returns ready when `policy.qualified` is false).

## 7. Klein v2 LoRA admission

Owner module `src/image_backends/forge_klein_lora.py`; the policy points to it through `LORA_POLICY_KLEIN_4B_EXPLICIT`, and `model_policy_lora.assess_lora_selection` runs the same `evaluate_klein_loras` for the GUI/Learning (so the projection cannot drift from admission) [V].

- Evidence comes only from the `AssetRegistry` record (SHA-256, embedded metadata, CivitAI-style sidecar) via `classify_klein_lora`. Exact whole-value match against `KLEIN_4B_BASE_MODEL_VALUES` -> `compatible`; an anchored other-FLUX identifier or a resolved SD/SDXL/SD3 family -> `incompatible`; Klein evidence plus contradicting evidence or a registry conflict -> `conflicting`; generic FLUX, unknown or no evidence -> `unverified`. Only `compatible` is runnable. Never a filename, Forge listing or operator choice.
- Limits: at most `max_loras` tags (1), weight in (0, 2.0], well-formed `<lora:name:weight>` tags, every NJR-declared LoRA must be in the rendered prompt, `lora_strengths` overrides refused.
- `RegistryLoraResolver(cache_only=True)` is the UI/compile projection (snapshot only, can only make the UI more cautious); the backend resolver refreshes the LoRA kind.
- The local PromptPack LoRA browser projects a worker-returned read-only registry snapshot. It calls the same
  `assess_lora_selection`/`classify_klein_lora` authorities and displays the profile's selection limit without changing
  authored choices. Explicit Klein metadata is labeled possibly compatible, with no physical pairing claim. Ordinary
  family matches require non-filename evidence for both target and adapter; absent or conflicting evidence stays unknown.
  This browser evidence does not refresh the persisted compile snapshot or replace Preview/dispatch admission.
- At dispatch: `_assert_lora_served` requires Forge to list the adapter and (when the registry locations are known) to serve the same file path; after generation `observe_lora_consumption` parses Forge's own `[LORA] Loaded` / mismatch log lines, and an explicit mismatch fails the job (`consumed is False`); `None` (silence) is accepted because Forge caches identical adapter sets.
- PromptPack selection: `src/prompting/pack_lora_selection.py` (contract `klein_lora_selection/1`) freezes the chosen adapter into `NJR.extra_metadata["klein_lora_selection"]` and config metadata; `frozen_selection_problems` re-checks it against refreshed evidence at both `validate_njr_intent` and `_validate_request`. A selection without an exact profile is refused (`ForgeUnsupportedIntentError`).

## 8. Asset identity, readiness and dependency gating

Three different questions, three modules; none implies the next:

| Question | Module | Reads | Result |
|---|---|---|---|
| Are the exact bytes of the profile files installed in the managed Forge? | `forge_klein_assets.py` (`verify_klein_assets`, `verify_zimage_assets`) | Files under the owned Forge `--data-dir` (taken from the manager's launch-session command) | Size + SHA-256, cached by stat identity; mismatch raises `KleinProfileError`. An external or unowned Forge is refused for profile work (`resolve_owned_forge_data_dir`). |
| Is the host big enough? | `forge_klein_readiness.py` (`check_klein_host_memory`) | `psutil`, Windows commit headroom | Hard fail below `min_total_ram_bytes`; availability and commit are evidence only |
| Does an unprofiled checkpoint need parts StableNew cannot qualify? | `model_readiness.py` (pure) + `model_readiness_probe.py` (I/O) | `GET /sd-models`, a bounded safetensors header, then (only if the header says multi-component) `GET /sd-modules` and `/options`; header reads of catalog files via `src/assets/component_evidence.py` | `ReadinessStatus`; `blocks_dispatch` only for a positively identified dependency-bearing, unqualified checkpoint |

- `config/forge_klein_assets.json` mirrors the Klein v1 asset table for the installer (`scripts/install_forge_klein_assets.ps1`); a test pins equality with the dataclass. It has no Z-Image entry; the Python profile is the authority [V].
- `ReadinessStatus.QUALIFIED` needs `profile_verified=True`; no production code passes it, so the GUI shows at most `PROFILE_AVAILABLE` ("assets and runtime not verified here") and the real verification happens at dispatch [V: grep of `src` and `tools`].
- Tri-state reads: `get_module_catalog` and `get_additional_modules` return `None` on failure and `[]` for "Forge answered with nothing"; the legacy `get_vae_models` cannot tell them apart and is treated as unreadable by the probe. Keep that distinction in any new reader.
- Ordinary (non-profile) Forge stages also run `_normalize_module_baseline` after the gate: a non-empty persisted `forge_additional_modules` that differs from what the work needs is replaced through the verified module write, so a previous Klein/Z-Image job's encoder never leaks into an SDXL job. Profile stages skip it (the profile sets its own modules).
- If module cleanup occupies the local options-write slot, the Forge checkpoint write waits within the shared bounded throttle budget and rechecks readiness and write permission. An exhausted wait fails locally before sending the checkpoint write. A sent switch still requires checkpoint readback before generation.
- Asset-compat evidence layers: `src/assets/compatibility.py` (coarse family, conflicts preserved), `checkpoint_structure.py`/`component_evidence.py` (header-only structure), `adapter_evidence.py` (advisory LoRA/embedding family claims; never admits). Only the Klein LoRA module turns evidence into admission.
- `src/image_backends/model_inventory_reconcile.py` is an operator-invoked GET-only comparison of the offline inventory with one running endpoint; it is not on the job path.

## 9. Operation compatibility and Model Comparison

### 9.1 Operation compatibility

`operation_compatibility.py` (`assess_operation`, `assess_njr`, `require_njr_operation`, `OperationNotSupportedError`) answers from `ModelPolicy` alone. Codes: `backend_mismatch`, `stage_unsupported`, `stage_chain_unsupported`, `mode_not_requested`, `source_image_count`, `geometry_unsupported`. `policy_for_njr` prefers the frozen profile reference, else `resolve_model_policy(base_model)` (latest Klein): an old NJR with a Klein name and no reference is therefore projected as the latest profile while the backend still runs it as an unprofiled checkpoint [V]. Consumers: `src/controller/reprocess_admission.py`, `review_batch_service.py`, `batch_operations_service.py`, `src/review/workflow_adapter.py` (`assess_readiness`), `src/prompting/pack_target_readiness.py`. The edit request must be explicit (`explicit_single_reference_edit` checks that every source item froze `KLEIN_EDIT_METADATA_KEY` with mode `single_reference_edit`).

### 9.2 Model Comparison (`src/learning/model_comparison.py`)

A txt2img-only, PromptPack-row, target-envelope study (`COMPARISON_CLAIM = target_envelope_preference`, `causal_one_variable = False`). `build_comparison_snapshot` is pure and deferred-imports the compiler:

1. Per candidate: `evidence.policy_for(model)` (`CompileEvidence`, registry snapshot only) -> `candidate_ineligibility` (needs `exact_identity_authority` or `registry_evidence`; registry candidates must be in `QUALIFIED_REGISTRY_POLICY_IDS` and `explicit_capabilities`; must support txt2img) -> `_require_envelope` (required/allowed backend, shared geometry in the policy's allowed set, txt2img-only stage flags, hires/refiner/controlnet only if the policy supports them, no aesthetic/hypernetwork for a qualified policy).
2. The arm config is a deep copy of the shared baseline with `model_profile` popped; then `prepare_candidate_baseline` -> `apply_model_compile_policy` (the same compiler seams as section 5) -> `global_positive_ownership`.
3. Shared geometry, counts, seed policy, stages and optional features are never normalized to make an arm qualify; any `ValueError` fails the whole study naming the arm (`_arm_failure`). `verify_arms_admissible` materializes every arm at Preview.
4. Global positive parity (`learning_model_comparison_global_positive/1`): modes `not_requested`, `executor_applied` (the compiled arm still carries executor-applied terms; they must equal the shared text), `compiler_composed` (exactly one `global_positive_composed` adaptation operation). The mode is derived from what the canonical policy left in the arm via `frozen_global_positive_policy`, not from the family. A study without the shared record is a pre-parity study and keeps its old meaning (`_verify_global_positive`; fixture `tests/learning_v2/fixtures/model_comparison_legacy_global_positive_159.json`).
5. `frozen_arm` re-validates a persisted arm without live lookups: arm SHA-256, source-intent digest, `policy_from_context` (a reconstructed policy), `policy_for_model_profile_reference(options)` against the frozen `policy_context`, fixed controls against the frozen config, prompt/embedding/LoRA/global evidence. `materialize_njr` builds the NJR and ends with `validate_profile_njr`, which currently validates Z-Image only (Klein's NJR validation needs live backend evidence and stays in the backend).

Learning's single-variable path uses `src/learning/model_policy_service.py` (`validate_experiment`, `compile_variant`, frozen `policy_context` equality, recommendation preflight). `compile_variant` rejects an experiment whose tested value is overwritten by the compile policy. The Learning recommendation Apply path is not reachable from the UI (STATUS.md).

## 10. Refusal catalogue

Refusals are exceptions raised before any generation POST; there is no shared code namespace.

| Where | Type | Meaning |
|---|---|---|
| Profile intent, host RAM, assets, served listing, LoRA, source hash | `KleinProfileError` (`ValueError`) | Outside the Klein envelope or unverifiable |
| Z-Image intent, wire seam, dispatch state, assets | `ZImageProfileError` (subclass of `KleinProfileError`) | Outside the Z-Image envelope; one `except KleinProfileError` catches both |
| Hypernetworks, frozen Klein selection without a profile | `ForgeUnsupportedIntentError` | Forge cannot do it |
| Encoder/VAE as checkpoint | `ForgeUnqualifiedModelError` (carries `ModelReadiness`) | Dependency gate |
| Unqualified multi-component checkpoint, unprofiled FLUX layout, unrecognised DiT (N1: runs) | none: `policy_warning` on the result, modules left as they are | Dependency gate |
| FLUX.1 [dev] family envelope, served layout/precision, auxiliary bytes | `Flux1ProfileError` (subclass of `KleinProfileError`) / `KleinProfileError` | Outside `flux1_dev_gguf` or unverifiable |
| Module baseline unverifiable | `ForgeVAEError` | Could not read or set Forge modules |
| OpenPose or ordered ControlNet units on a profile model | `OpenPoseDispatchError` with `CODE_BACKEND` (`backend_unsupported`) | Conditioning refused for exact profiles; ordered units require registry-verified SDXL on Forge (IMAGE_PIPELINE 3.1) |
| Preflight | `OperationNotSupportedError` (codes in 9.1) | Nothing was queued |
| Learning/Model Comparison | `ValueError` with an operator sentence | Whole study refused; rebuild preview |

`ModelReadiness.reason_code` values (`exact_profile_name_match`, `exact_profile_verified`, `checkpoint_evidence_unavailable`, `checkpoint_header_unreadable`, `no_auxiliary_dependency_identified`, `forge_state_unavailable`, `duplicate_module_names`, `dependency_not_listed`, `selected_but_unqualified`, `dependencies_listed_not_selected`, `served_file_ambiguous`, `component_not_checkpoint`) are stable diagnostics in path-free `as_dict()` records.

Stage methods swallow generic exceptions (IMAGE_PIPELINE 11). Raise a refusal from `validate_njr_intent`, `_validate_request` or `_before_dispatch`, never from inside a stage method.

## 11. Evidence a profile run records

`ImageExecutionResult.backend_metadata["klein_profile"]` (built by `klein_provenance` plus `host_memory_before_dispatch`, `observed` Forge modules/checkpoint, `asset_identity`, `source_image`, and a `lora` block with name, weight, SHA-256, compatibility decision, served binding and log observation) or `["zimage_profile"]`. Z-Image also writes `zimage_effective_request`, `zimage_selection` and `zimage_profile` into the txt2img variant metadata (and so the per-image manifest) from the executor. Evidence is path-free and the admission decision is a snapshot of that dispatch, not a standing qualification claim.

## 12. Invariants

1. A profile version is immutable; new semantics are a new version. Never "upgrade" persisted work (`apply_zimage_compile_policy` explicitly refuses a profile upgrade).
2. Exact identity is whole-name plus byte verification at dispatch; never a substring, a filename guess, or a Forge listing alone. Amended for **family profiles only** (`flux1_dev_gguf`, owner decision Q4 on 2026-11-20): the transformer is admitted by the structural layout of the served file's header, its SHA-256 recorded; every auxiliary stays byte-pinned. A family profile is never an exact-identity authority.
3. The GUI and operation compatibility never authorize; the backend validates every NJR and every stage request independently of how it was built.
4. Conflicting immutable intent is refused, never silently rewritten. Only values the profile owns are replaced, and only at compile time, with recorded evidence.
5. No backend switching and no profile fallback; a missing or unknown profile reference fails closed.
6. Profile work requires the StableNew-owned managed Forge at the pinned runtime; external processes are not adopted (AGENTS.md).
7. Physical qualification is unauthorized for Z-Image (STATUS.md Holds): a new version may be added in code and tests, but `_LATEST_PROFILE` must not move, and nothing here may claim hardware qualification, without owner authorization.
8. Tests never contact a WebUI, model or GPU; assert both the error and that no generation POST was recorded.

## 13. How to test

| Area | Tests |
|---|---|
| Klein profile, assets, LoRA | `tests/image_backends/test_forge_klein_profile.py`, `test_forge_klein_assets.py`, `test_forge_klein_lora.py` |
| Qwen-Image profiles, Preview, and fake Comfy dispatch | `tests/image_backends/test_comfy_qwen_image_profile_comfy100.py`, `test_comfy_image_readiness_comfy100.py`, `test_comfy_image_backend_comfy100.py` |
| Z-Image profile | `tests/image_backends/test_forge_zimage_profile.py` |
| FLUX layouts, GGUF tables, FLUX.1 family profile | `tests/assets/test_flux_variant_130.py`, `tests/image_backends/test_forge_flux1_profile_130.py`, `tests/integration/test_pr_img_flux_130_canonical_path.py` (fixtures `tests/assets/flux_fixtures_130.py`) |
| Backend validation and dispatch ordering | `tests/image_backends/test_forge_webui_backend.py` (with `tests/helpers/fake_webui_transport.py`) |
| Policy and operation compatibility | `tests/image_backends/test_model_policy_130a.py`, `test_operation_compatibility_158.py` |
| Compile policies and effective config | `tests/pipeline/test_klein_compile_policy.py`, `test_zimage_compile_policy.py`, `test_exact_profile_effective_config_159.py`, `test_zimage_effective_config_159.py`, `test_global_prompt_policy.py`, `test_klein_pack_selection_143.py` |
| Readiness and dependency gate | `tests/integration/test_pr_img_models_150_readiness.py`, `tests/gui_v2/test_model_readiness_presenter_150.py` |
| Canonical-path proofs | `tests/integration/test_pr_img_116_klein_canonical_path.py`, `test_pr_img_117_klein_lora_canonical_path.py`, `test_pr_img_155_zimage_canonical_path.py`, `test_pr_img_159_zimage_effective_config.py` |
| GUI projections | `tests/gui_v2/test_model_policy_panel_130a.py`, `test_zimage_policy_projection.py` |
| Learning and Model Comparison | `tests/learning_v2/test_model_comparison_140.py`, `test_model_comparison_compat_158.py`, `test_model_comparison_evidence_145.py`, `test_model_comparison_global_positive_160.py`, `test_model_capabilities_130d.py`, `tests/gui_v2/test_learning_model_policy_130d.py` |

Inject `memory_probe`, `lora_resolver` and a fake client into `ForgeWebUIImageBackend`; use `verify_klein_assets(..., data_dir=...)` as the byte-verification seam; use `clear_verified_cache()` between tests.

## 14. Known debt and traps

- Family branching [A/V]: `policy_for_profile`, `apply_model_compile_policy`, `resolve_model_profile`, `validate_profile_intent`, `ForgeWebUIImageBackend` (17 lines reference `ZImageProfile`, `KleinProfile` or the Z-Image name check) and the executor wire seam are if/isinstance chains (audit C1, E2). The planned `ExactProfilePlugin` protocol (audit P4-5) does not exist; use section 15.
- Misleading names [V]: `forge_klein_profile.py` defines `KleinAsset`, `KleinProfileError` and `_model_key` that Z-Image imports (including a private helper); `check_klein_host_memory`, `KleinReadiness` and `verify_zimage_assets` live in `forge_klein_*` modules; `ExactModelProfile` is `KleinProfile | ZImageProfile`. `KLEIN_PROFILE_VERSION = 1` is exported but unused and is not the latest version.
- Inconsistent version parsing [V]: Klein accepts any int-coercible `version` and ignores extra keys; Z-Image requires an exact `{"id","version"}` dict with an int.
- Normalization is the caller's job [V]: `apply_zimage_compile_policy` validates before it defaults, so a new builder that skips `normalize_profile_owned_values` / `prepare_effective_config` makes Z-Image jobs fail on inherited values. CLI and `compile_variant` are such builders today. Audit C2 lists eight NJR construction sites with uneven policy application [A].
- Stale text [V]: `klein_edit_reprocess.py` module docstring says "frozen to Klein profile v1" but the code freezes `latest_klein_profile()` (v2); `normalize_image_backend_options` docstring says it stamps Klein only, but `model_profile_for_model` stamps Z-Image too; `forge_klein_profile.py` still places the installer script under `tools/` (the file is `scripts/install_forge_klein_assets.ps1`) and says "no generic profile registry here" although `model_policy.py` now exists.
- No unqualified-dependency gate for profile names: `_dependency_gate` only runs when there is no profile, and exempts the Klein 4B name; a Klein-4B-named checkpoint without a profile reference follows the generic path [V].
- `Pipeline` global-term fallback: a config that is not frozen reads the mutable global prompt files at run time (`LEGACY_POLICY_SOURCE`); all new builders must freeze (`apply_global_prompt_policy`).
- `_vae_conflict` and `validate_zimage_config` accept different VAE spellings (`""`, `none`, `automatic`, ...); a new profile must scan every alias key (`vae`, `sd_vae`, `vae_name`) like both do (IMAGE_PIPELINE 11).
- Klein edit denoise and Z-Image width/height/CLIP skip are overwritten in `_finalize_config` rather than validated; a changed value in the NJR is silently normalized at the wire for these keys [V].
- The Klein LoRA hard-codes the Klein 4B identifier set; extending it needs a proven metadata form, not a pattern (comment in `forge_klein_lora.py`).

## 15. Changing a profile today

New envelope for an existing model (for example a Klein v3):

1. `forge_klein_profile.py`: add `KLEIN_PROFILE_V3 = replace(KLEIN_PROFILE_V2, version=3, ...)` (add a field to `KleinProfile` only if needed, with a default that keeps v1/v2 meaning), register it in `_PROFILES`. Leave `_LATEST_PROFILE` alone until physical qualification is authorized.
2. Teach every consumer of the changed field: `validate_klein_intent` / `detect_unsupported_features`, `policy_for_profile`, `_finalize_config`, `klein_provenance`, and the backend checks that read `profile.max_loras`.
3. If assets change: `config/forge_klein_assets.json` and its equality test, `verify_klein_assets`, the install script.
4. Tests for old versions must keep passing unchanged (a v1/v2 NJR must behave as before). Add version-pair tests, then update this file.

New exact profile for another model: follow IMAGE_PIPELINE section 12 (profile file, `exact_model_profile.py`, `model_policy.py`, `forge_webui_backend.py`, builders, readiness, tests). Additions specific to this file: a `normalize_profile_owned_values` branch if it owns inherited values, the global-positive decision (cleared like Klein or composed like Z-Image), an operation-compatibility mode in `ModelPolicy.modes`, a Model Comparison eligibility check (it will need `exact_identity_authority` and an explicit position on every feature), and `QUALIFIED_REGISTRY_POLICY_IDS` only for ordinary registry-evidenced families.

## 17. Recommended generation profiles (advisory, `src/generation_profiles/`)

A recommended generation profile is a typed, versioned set of **partial** Base Generation recommendations (`sampler_name`, `scheduler`, `steps`, `cfg_scale`, `width`, `height`, `vae`) for one model identity, with per-setting evidence. It is a fifth concept, separate from the four above: it never owns execution, never enables a stage, and the executable policy stays final. `application.plan_application` skips a value `ModelPolicy` owns and says so; the compiler and backend validate the job regardless.

- Kinds: **research** (code-owned, read-only, `research.py`), **learning** (explicitly confirmed controlled txt2img findings from Learning's Recommendations area, qualified per setting by `src/learning/profile_publication.py` and published only through `GenerationProfileStore.publish_learning_profile`), **custom** (operator saved, editable by writing the next revision). Learning publication accepts only the next immutable revision of the same model lineage; duplicate findings and competing writes cannot overwrite revisions. Missing or malformed profile files give an explicit fallback status and are skipped; the last valid revision keeps being used.
- Identity (`identity.py`): from the exact profile (whole-name plus recorded SHA-256 evidence) or the `AssetRegistry` family via `RegistryFamilyLookup`; never a filename substring. An unverified model gets no profile and a stated reason. A renamed file with the same bytes matches; a same-name file with different bytes conflicts and nothing is applied.
- Built-in executable Research coverage remains SDXL geometry, FLUX.2 Klein and Z-Image (derived from immutable executable profiles). The Model Evidence Catalog (`evidence_catalog.py`, `evidence_baseline.py`) adds per-field sources, scope, reviewed date, confidence, contradictions and backend caveats, including metadata-only unsupported lineages and labeled SDXL implementation hypotheses. Reviewed exact-checkpoint claims extend the existing Research kind only with fingerprint-verified SHA-256 and compatible registry family; exact recommendations precede family starting points, while favorites retain precedence. Low-confidence, contradictory and translation-dependent claims never become executable defaults. Technical metadata stays separate from the seven Base Generation settings. See `PR-IMG-MODEL-EVIDENCE-760.md`.
- The SDXL Turbo Research recommendation uses the compatibility probe's shared recipe (Euler a, SGM Uniform, 4 steps, CFG 1, 512 × 512). It requires a fingerprint-current registry SHA-256, the SDXL base tensor layout and coherent embedded Turbo metadata. The recommendation follows verified byte identity across renames. Where a served file is known, its path must resolve to that verified record. Startup waits for the served model catalog before applying a saved Turbo profile. Favorites retain priority.
- Base Generation resource refresh classifies catalog candidates using bounded headers and registry sidecar provenance. The model menu omits positive non-checkpoints, labels unverified files, and shows existing policy or readiness refusals for unsupported transformers. The VAE menu omits non-VAEs, preview decoders, sidecars and known incompatible families. Four latent channels leave SD 1.x versus SDXL unverified without corroborating family evidence. Unverified entries are selectable by the operator and retain their exact backend names. Executable profiles own locked controls and pinned modules.
- Proposed Experiments uses the same catalog and policy to derive offline v2 qualification drafts (`src/learning/evidence_autopilot.py`; Learning section 3.15). Save/Queue only create Library drafts; Preview compiles without admission. Catalog candidates are hypotheses, never automatic Research/Learning profile publication, application, favorites or startup defaults. Exact Klein/Z-Image ownership and all existing publication thresholds remain final.
- Store: per-user data directory (`LOCALAPPDATA`, else `XDG_DATA_HOME`; `STABLENEW_GENERATION_PROFILE_DIR` overrides it, and tests isolate it): `profiles/custom|learning/<id>/rNNNN.json` (one immutable file per revision), `favorites.json`, `startup_defaults.json`. Mutable files use `atomic_write_json`; Learning revisions use `atomic_publish_json` (complete-file publication that atomically refuses replacement). It is not `presets/`, not a PromptPack and not `settings.json`.
- Learning scope/provenance: each published setting carries `learning_evidence`, actual counts and an evidence digest, with compact scalar publication provenance. Raw prompts, artifact paths and full rating records stay in Learning. Untested settings are unavailable, not copied from the baseline. Registry checkpoint hashes must remain fingerprint-verified; exact executable ID **and version** must match. Incompatible Learning profiles remain readable but cannot apply (including a startup reference to an incompatible Learning profile). Research/Custom matching semantics remain unchanged. Publication refreshes the catalog without selection, application, favoriting or startup-default writes.
- Application: choosing a checkpoint in the Base Generation panel applies the favorite (else the Research) profile to the editable working settings only. Prompt text, stage flags and stage intent are untouched; a known incompatible or unavailable explicit VAE resets to model default with an explanation, while compatible choices carry forward; a sampler or scheduler the runtime does not offer is reported, not rewritten. PromptPacks, the Job Draft, queued jobs and Preview records are never rewritten. Override OFF keeps each pack's own saved settings; Override ON compiles from the working stage snapshot.
- Startup defaults (`startup.py`, button "Save Current Settings as Startup Defaults" in the Pipeline sidebar): the model identity and name, the selected profile reference, the Base Generation values, the stage flags and the stage settings. Never saved: input or source image paths, masks and anchors, Learning/experiment working state, active or historical jobs, result paths, model assets (`sanitize_stage_settings` drops them by key and by file extension). The save reports its real outcome. Restore runs once after the last-run restore, so it wins; it never scans or launches a runtime and reports a model or value the runtime does not offer instead of substituting one. Stage settings load before the final validated Base Generation overlay, so shared card variables cannot overwrite the restored model or reinstate a rejected value; rejected values retain their pre-restore working value. An explicit saved VAE waits for a usable catalog if startup precedes refresh, and unavailable, incompatible or policy-owned values are disclosed. Pending model validation survives partial/empty resource updates and checks the supplied model inventory when it first becomes usable, independent of delayed AppState projection. Validation notifications use the existing GUI dispatcher.
- Layering: domain in `src/generation_profiles/` (no Tk, no controller), controller adapter `src/controller/generation_profile_controller.py`, text in `src/gui_v2/generation_profile_projection.py`, widget `src/gui/generation_profile_strip.py`.

## 16. Evidence records

Per-PR records stay in `docs/Subsystems/Image/` as historical evidence. They may describe superseded behavior; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md` | Physical evidence behind the Klein envelope and the host-RAM rule |
| `docs/Subsystems/Image/PR-IMG-116_FLUX2_Klein_Forge_Production_Slice.md` | Klein v1: envelope, asset verification, refusals |
| `docs/Subsystems/Image/PR-IMG-117_FLUX2_Klein_LoRA_Qualification_and_Profile_v2.md` | v2 and the LoRA evidence rules |
| `docs/Subsystems/Image/PR-IMG-130A_Model_Family_Capability_Registry.md` | `ModelPolicy` and the four-concept split |
| `docs/Subsystems/Image/PR-IMG-MODELS-150_Installed_Model_Readiness.md` | Readiness statuses and the dependency gate |
| `docs/Subsystems/Image/PR-IMG-MODELS-151_Klein_Base_9B_Feasibility.md` | Why Klein Base 9B is refused |
| `docs/Subsystems/Image/PR-IMG-MODELS-155_ZImage_Turbo_FP8_Forge_Enablement.md` | Z-Image profile and its limited qualification |
| `docs/Subsystems/Image/PR-IMG-MODELS-154B_ZImage_Turbo_Controlled_Physical_Qualification.md` | The one observed generation and the open instrumentation gap |
| `docs/Subsystems/Image/PR-IMG-MODELS-158_Cross_Workflow_Model_Compatibility.md` | Operation compatibility and reproduced failure boundaries |
| `docs/Subsystems/Image/PR-IMG-MODELS-159_ZImage_Effective_Configuration_Adaptation.md` | Effective-config normalization and global-positive composition |
| `docs/Subsystems/Image/PR-IMG-MODELS-160_Model_Comparison_Global_Positive_Parity.md` | Model Comparison global-positive ownership modes |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit C1, C2, E2 and the P4-5 plugin plan referenced above |
