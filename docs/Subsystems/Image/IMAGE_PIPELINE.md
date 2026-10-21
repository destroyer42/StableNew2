# Still-image pipeline

Status: living document, edit in place
Owner area: still-image generation (`src/image_backends/`, the image stages of `src/pipeline/`, `src/assets/`, `src/prompting/`, `src/refinement/`, `src/conditioning/`)

How to keep this true:
- Change this file in the same PR that changes image behavior, ownership, a supported model profile or a safety rule. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.

## 1. Scope and the canonical path

This document covers still-image generation: txt2img, img2img, ADetailer, upscale, the SDXL refiner and hires fix inside txt2img, one OpenPose ControlNet unit, and the exact model profiles. Video (`src/video/`), training and Learning scoring are out of scope except where they touch image code.

The path is the repository-wide one (authority: `AGENTS.md`, `docs/ARCHITECTURE_v2.6.md` section 7). For an image job it resolves to:

| Step | Image-specific reality | Where |
|---|---|---|
| Intent | PromptPack slot, Pipeline-tab config, Review/reprocess item, CLI, replay source, Learning arm | `src/pipeline/prompt_pack_job_builder.py`, `src/pipeline/job_builder_v2.py`, `src/pipeline/reprocess_builder.py`, `src/pipeline/cli_njr_builder.py`, `src/pipeline/replay_njr_compiler.py`, `src/learning/model_comparison.py` |
| Compiler | Each builder merges config and calls `normalize_image_backend_options` (stamps `backend_options.image.backend_id` and, for an exact model, `model_profile`). `apply_model_compile_policy` (freezes exact-profile semantics) is called by the PromptPack, generic (`JobBuilderV2`) and CLI builders and by Learning (`src/learning/model_comparison.py`, `src/learning/model_policy_service.py`) [V]; `ReprocessJobBuilder` does not call it and relies on the stamped profile plus operation-compatibility and backend validation. | `src/image_backends/image_backend_types.py`, `src/image_backends/model_policy.py` |
| NJR | Immutable `NormalizedJobRecord` with an `ImageWorkloadSpec`, a tuple of `StageConfig`, frozen `backend_options` | `src/pipeline/njr_core_v26.py` |
| JobService | `JobService.submit_njrs` is the only fresh-submission boundary | `src/controller/job_service.py` |
| Queue/Repository | SQLite `JobRepository` owns the NJR snapshot and lifecycle; the queue and history are projections | `src/queue/job_queue.py`, `src/queue/job_repository.py` |
| Runner | `PipelineRunner.run_njr` builds a `RunPlan`, resolves one image backend for the whole NJR, then hands each stage to its handler in order | `src/pipeline/pipeline_runner.py`, `src/pipeline/run_stage_handlers.py`, `src/pipeline/run_plan.py` |
| Handler | `ImageBackendRegistry` -> backend `execute` -> `Pipeline.run_<stage>_stage` -> WebUI client | `src/image_backends/`, `src/pipeline/executor.py`, `src/api/client.py` |
| Artifacts/History | PNG with embedded provenance, per-image manifest JSON, run metadata, replay descriptor | section 8 |

Stage order is fixed: `txt2img -> optional img2img -> optional adetailer -> optional upscale` [V: `Pipeline` stage methods and the `run_njr` stage branches]. A backend that does not declare every requested stage refuses the whole NJR before any dispatch (`ImageBackendRegistry.validate_stage_chain`); there is no per-stage backend switching.

Replay and reprocess create a new NJR with lineage on the same path. Nothing in the GUI or a controller calls a backend or the executor.

## 2. Backends and layering

### 2.1 Identities

| Backend id | Class | Role |
|---|---|---|
| `forge_webui` | `ForgeWebUIImageBackend` (`src/image_backends/forge_webui_backend.py`) | Default for new work (`NEW_IMAGE_BACKEND_DEFAULT_ID`). Managed Forge Neo, pinned in `config/managed_forge_runtime.json`. Declares no Hypernetwork support and does declare OpenPose conditioning. |
| `a1111_webui` | `A1111WebUIImageBackend` (`src/image_backends/a1111_webui_backend.py`) | Rollback/compatibility. Selected only by explicit `webui_runtime_identity = a1111_webui` (or `STABLENEW_WEBUI_RUNTIME_IDENTITY`). |

Both are registered by `build_default_image_backend_registry` and both share ONE WebUI-family runtime slot (one endpoint, one `WebUIProcessManager`). Selection rules, all in `src/image_backends/image_backend_types.py` and `src/api/webui_runtime_identity.py`:

- New work: `configured_image_backend_id()` -> configured identity, default `forge_webui`. An unrecognized value raises `WebUIRuntimeConfigurationError`; nothing falls back to the other backend.
- Persisted record with no `backend_options.image.backend_id`: `resolve_image_backend_id` returns `a1111_webui` (`LEGACY_MISSING_IMAGE_BACKEND_ID`). This is deliberately not the new-work default, so old work is never reinterpreted.
- An explicit id in a replay/reprocess source is kept, never rewritten. Replaying A1111-created work while configured for Forge fails closed with `WebUIRuntimeIdentityMismatch` before dispatch (the message tells the operator to switch the setting) [V].
- Backend identity is configuration. It is never inferred from a model name or install folder.

### 2.2 Where things actually live

| Concern | Location |
|---|---|
| Neutral contracts: `ImageBackendCapabilities`, `ImageExecutionRequest`, `ImageExecutionResult`, `ImageBackendInterface` | `src/image_backends/image_backend_types.py` |
| Shared stage translation for both identities: `WebUIFamilyImageBackend` (neutral request -> executor config; transition claim; identity guard; `execute`) | `src/image_backends/webui_family_backend.py` |
| Forge-only hooks: profile validation, module-baseline normalization, dependency gate, OpenPose admission, LoRA serving check, profile evidence | `src/image_backends/forge_webui_backend.py` |
| The executor: `Pipeline` with `run_txt2img_stage`, `run_img2img_stage`, `run_adetailer_stage`, `run_upscale_stage` (plus `run_adetailer`) | `src/pipeline/executor.py` |
| Runner entry and backend call: `PipelineRunner._resolve_image_backend_id`, `_execute_image_backend` | `src/pipeline/pipeline_runner.py` |
| Transport: `SDWebUIClient` (A1111 contract, retries, ambiguity classification), `ForgeWebUIClient` (module API) | `src/api/client.py`, `src/api/forge_client.py` |
| Client construction for the configured identity | `src/controller/ports/default_runtime_ports.py` |
| Runtime identity probe and same-session attestation of the managed Forge | `src/api/webui_runtime_identity.py`, `src/api/webui_identity_attestation.py` |
| Runtime transition (release the other StableNew-owned runtime before use) | `src/services/runtime_transition_service.py` |
| Presentation-side capability facts (UI must not advertise what the runtime cannot do) | `src/image_backends/backend_capabilities.py` |

`WebUIFamilyImageBackend.execute` order: `_validate_request` (pure refusal) -> `RuntimeTransitionCoordinator.prepare_for` -> `verify_backend_runtime_identity` -> `_before_dispatch` (Forge: dependency gate, module baseline, profile asset verification) -> `_finalize_config` -> `pipeline.run_<stage>_stage`. Unsupported work must be refused before the first generation POST.

### 2.3 Known layering debt (audit C1) [V/A]

The adapter boundary from PR-IMG-100 is real for backend selection and capability checks, but the executor is effectively the WebUI backend and is not behind it:

- `src/pipeline/executor.py` (6.8k lines) lives in generic `src/pipeline`. `WebUIFamilyImageBackend.execute` calls back into `Pipeline.run_*_stage` [V], and `PipelineRunner.__init__` constructs `Pipeline` and requires an `SDWebUIClient` [V].
- Family and feature branches inside the generic txt2img stage [V]: unconditional `project_zimage_wire_payload` and `verify_zimage_dispatch_state` calls (no-ops for other models, refusals for a Z-Image checkpoint without its profile); `zimage_*` manifest keys; the OpenPose `apply_openpose_wire_unit` / `classify_openpose_response` step; SDXL refiner fields; the `sdxl_guarded` launch-profile override in the admission/recovery path; hires fix.
- Family names are also spread through `src/pipeline/prompt_pack_job_builder.py`, `src/pipeline/reprocess_builder.py` (Klein edit items via `src/pipeline/klein_edit_reprocess.py`), `src/pipeline/job_builder_v2.py` and many `src` files that mention "klein" (36 files) or "zimage"/"z_image" (14 files) [V counts at time of writing].
- ARCHITECTURE section 12 forbids family branches in generic orchestration. The planned fix is an exact-profile plugin protocol plus moving the executor into a `webui` package under `src/image_backends/` (audit P4-4, P4-5) [A]. Until then, add model-specific code in `src/image_backends/` and keep new branches in the executor to the minimum the wire format forces.

## 3. Stages

All stages return a variant dict that `ImageExecutionResult.from_stage_result` canonicalizes (`src/pipeline/artifact_contract.py`) and the runner collects into `PipelineRunResult.variants`.

| Stage | Executor method | What it does | Notes |
|---|---|---|---|
| txt2img | `Pipeline.run_txt2img_stage` | Admission (`_assess_stage_pressure`, `_ensure_runtime_admissible`), global prompt terms, prompt optimizer, model/VAE/module sync (`_ensure_model_and_vae`), drift check, payload, `_generate_images_with_progress`, save each image with embedded metadata, per-image manifest | Hires fix (`enable_hr`, `hr_*`) and SDXL refiner (`use_refiner`, `refiner_checkpoint`, `refiner_switch_at` or `refiner_switch_steps`) are options of this stage, not stages. Refiner fields go at the top level of the payload; nothing in the repo checks that the pinned Forge Neo honors them [V]. |
| img2img | `Pipeline.run_img2img_stage` | Loads the previous stage image as base64, sends img2img through the shared progress and cancellation path (`_generate_images_with_progress`), writes a stage-prefixed output and manifest | Under the Klein profile it is the single-reference edit mode only (denoise 1.0). |
| adetailer | `Pipeline.run_adetailer_stage` -> `Pipeline.run_adetailer` | An img2img request carrying `alwayson_scripts.ADetailer.args` (face pass, optional hands pass), then effectiveness evidence; carries `stage_history` read from the input image's embedded metadata (`_extract_stage_history_from_input`) | Needs `adetailer_enabled` (the backend sets it). Contract of the pinned ADetailer-Neo arguments: `src/pipeline/adetailer_contract.py`; evidence: `src/pipeline/adetailer_effectiveness.py`. |
| upscale | `Pipeline.run_upscale_stage` | `upscale_mode` `single` (extras endpoint with `upscaler`, `upscaling_resize`) or `img2img` (denoised tiled upscale) | `_maybe_autodowngrade_upscale_for_pressure` can reduce the request under memory pressure. Supported-option defaults: `docs/Subsystems/Image/PR-IMG-FORGE-230_Supported_Option_Defaults_Integrity.md`. |
| ControlNet OpenPose | not a stage | One pre-rendered unit added to the base txt2img request (`alwayson_scripts.ControlNet.args`, `module="None"`) | Section 3.1. |

Common to every stage method [V/A]: runtime admission, model/VAE sync, drift check, manifest and metadata writing are re-implemented in each method (audit C3). A fix in one stage usually has siblings in the others.

### 3.1 OpenPose ControlNet (SDXL, Forge, base txt2img only)

| Phase | Owner |
|---|---|
| Authoring: slot declaration `controlnet_openpose` (`openpose.v1`) and the reference library under `<WebUI root>/models/OpenPose/` (`AssetKind.OPENPOSE_IMAGE`) | `src/conditioning/openpose.py`, `src/conditioning/openpose_library.py`, `src/conditioning/openpose_catalog.py` |
| Compile: target gate (SDXL checkpoint, Forge, base txt2img), validation, content-addressed job-owned snapshot, `FrozenOpenPose` in the NJR (never image bytes) | `src/pipeline/openpose_compile.py` (`OpenPoseCompiler`, called from `PromptPackNormalizedJobBuilder`), `src/conditioning/openpose_snapshot.py` |
| Capability projection | `src/image_backends/openpose_capability.py` (`assess_openpose_target`) |
| Pre-dispatch admission against what the running Forge advertises (`/controlnet/*`, read-only), SDXL header evidence of the weights | `src/image_backends/forge_controlnet.py` (`validate_openpose_intent`, `admit_openpose`), `src/assets/controlnet_structure.py` |
| Wire step (snapshot re-verified by SHA-256 immediately before POST) and output classification | `apply_openpose_wire_unit` in `forge_controlnet.py`; `classify_openpose_response` in `src/image_backends/openpose_output.py` |

Conditioning is refused, never silently dropped, on any other stage, model family or backend.

#### Ordered OpenPose, Canny and Depth units

`controlnet_units` is a separate optional slot declaration (`controlnet.v1`) containing an ordered list of at most two
`controlnet-unit.v1` units. Each unit names its modality (`openpose`, `canny`, `depth`), library-relative `asset`, model,
enabled flag, strength, guidance interval, control mode and resize mode. It cannot coexist with `controlnet_openpose`.
The published `openpose.v1` declaration and its replay behavior retain their original meaning and admission rules.

`src/conditioning/controlnet.py` owns the new declaration and frozen envelope. `src/pipeline/controlnet_compile.py` is an
adapter called only by the existing PromptPack builder: it requires registry-verified SDXL on Forge, reuses the existing
bounded image reader and content-addressed snapshot writer, and finishes all units before any NJR exists. Reference maps
share the existing `models/OpenPose` library and snapshot home; the directory name does not imply automatic pose detection.
Enabled units are frozen in authored order with independent settings, SHA-256, size, image facts and snapshot identity.
Provenance records `conditioning.controlnet_units`; image bytes never enter the NJR. Disabled units are not executed.

`src/image_backends/forge_controlnet_units.py` admits the complete list against Forge's advertised models and modules,
requiring positive SDXL header evidence for every weight and a matching documented model identity. The initial identities
are `thibaud_xl_openpose`, `xinsir_openpose_sdxl`, `diffusers_xl_canny_full`, and `diffusers_xl_depth_full`. The full Canny/Depth
and Thibaud names are documented in the [upstream ControlNet release](https://github.com/Mikubill/sd-webui-controlnet/discussions/2039);
the Xinsir alias is the existing OpenPose contract's documented example. Names are compatibility evidence, not weight
integrity or physical quality qualification. Renamed/unknown weights, ambiguous resources and incompatible modalities
are explicitly refused. No filename substring inference, runtime installation or model substitution occurs.

Only pre-rendered maps with `preprocessor: "None"` are supported. Advertising an automatic module does not qualify its
detector resources or behavior, so automatic preprocessing is refused even if the module appears in Forge's list.
The Prompt tab's ordered-unit editor selects, edits and reorders units independently, displays each unit's local
availability, and refreshes references/weight evidence off Tk without changing saved selections. Preview remains the
compile authority; Add to Queue uses those frozen NJRs. Dispatch and replay re-verify every snapshot by hash.

The executor delegates generic conditioning projection to the adapter: exactly the admitted ordered units join the
existing ControlNet always-on script. Independently populated ControlNet scripts cause a refusal; unrelated scripts
remain intact. Output classification uses metadata plus every input map's decoded identity to reject maps in generation
slots and unknown trailing images before artifact writes. Unit evidence is recorded as `controlnet_units` and backend
evidence as `image_backend_metadata.controlnet_conditioning`.

Deterministic coverage: `tests/integration/test_pr_img_cnet_220.py`, `tests/gui_v2/test_controlnet_units_220.py` and the
existing OpenPose suites. This establishes plumbing and refusals, not physical two-unit fidelity, VRAM fit or performance.
The accepted Forge batch-directory override limitation in the OpenPose evidence record also applies to these units.
Missing Canny/Depth weights remain an executable-capability refusal; the feature never downloads them.

### 3.2 Frozen masked img2img from Review

Review's mask editor compiles one still image through the existing reprocess/image-edit builder and admission boundary.
The initial target is a registry-resolved SDXL base checkpoint on Forge (`src/image_backends/masked_inpaint.py`, projecting
ModelPolicy); exact profiles, other backends and unverified families are refused, never substituted or silently unmasked.

`src/pipeline/image_edit_inputs.py` reuses bounded image validation and the OpenPose snapshot writer under the existing
mutable state home, `state/image_edit_inputs`. `config.img2img.image_edit_inputs` (`stablenew.image_edit.inputs.v1`) records
the original path and source/mask snapshot paths, SHA-256, byte count, dimensions and format. The source input path and
`ImageEditSpec.mask_image_path` point at these job-owned snapshots; the NJR contains no image bytes. Masks are nonempty
grayscale PNGs matching source geometry, white changes / black preserves (`inpainting_mask_invert=False`, original fill).

Admission verifies original-source drift plus snapshot content; missing, corrupt or changed inputs refuse the whole request.
The img2img executor re-verifies snapshots and base64-encodes those same inspected bytes, avoiding a second mutable-file
read before the generation payload. Original working files may subsequently change without changing an admitted job's
inputs. Persisted replay/retry input checks include the mask digest. Queue, cancellation, backend identity, NJR schema,
repository ownership and output/history contracts are unchanged. CPU tests establish input/payload contracts; physical
masked-output acceptance remains a separate owner-authorized run. Outpainting is not implemented.

## 4. Model profiles, policy and adaptation

### 4.1 Exact profiles

An exact profile is an immutable, versioned contract. The NJR persists only `backend_options.image.model_profile = {"id", "version"}`; the code resolves that to the immutable expectations. A published version is never edited; a change is a new version. Persisted work keeps the version it froze.

| Profile | Id / version | Envelope (summary) | Code |
|---|---|---|---|
| FLUX.2 Klein 4B FP8 | `flux2_klein_4b_fp8` v1 and v2 (`latest_klein_profile()` is v2) | Forge only. Euler / Beta / 4 steps / CFG 1.0; 768x1024 or 1024x1024; modes txt2img and `single_reference_edit` (img2img, exactly one source, denoise 1.0); no negative prompt, no global terms, no optimizer, hires, refiner, ADetailer or upscale. v1 admits no LoRA; v2 admits exactly one explicitly Klein-4B-compatible LoRA on txt2img. Total host RAM at least 32e9 bytes. | `src/image_backends/forge_klein_profile.py` |
| Z-Image-Turbo FP8 (limited support) | `z_image_turbo_fp8_scaled` v1 | Forge only, txt2img only, 1024x1024, one image, Euler / Beta / 9 steps / CFG 1.0 / `distilled_cfg_scale` 9.0; natural-language positive prompt only (no weights, brackets, `<lora:>`, embeddings); no negative prompt; pinned Forge sampling options verified before dispatch. Physical qualification is inconclusive (STATUS.md Holds). | `src/image_backends/forge_zimage_profile.py` |
| Klein Base 9B | none | Refused. Verdict `NO_GO_RESOURCE_RISK`. Enforcement is generic, not a name check: the Forge dependency gate refuses any positively identified dependency-bearing, unqualified multi-component checkpoint (`ForgeUnqualifiedModelError`) before any module write or POST. | `src/image_backends/model_readiness.py`, `src/image_backends/model_readiness_probe.py`, `ForgeWebUIImageBackend._dependency_gate` |

Dispatch seam: `src/image_backends/exact_model_profile.py` (`ExactModelProfile`, `resolve_model_profile`, `validate_profile_intent`, `validate_profile_njr`, `profile_prompt_refusal`). A malformed, unknown or unknown-version reference fails closed (`KleinProfileError`, `ZImageProfileError`); it is never reinterpreted as SDXL. Model identity matching is whole-name (`is_klein_transformer_name`, `is_zimage_transformer_name`), never a substring heuristic.

Asset identity (size + SHA-256 of the exact files Forge will load) is verified before dispatch: `src/image_backends/forge_klein_assets.py` (`verify_klein_assets`, `verify_zimage_assets`), expected values in `config/forge_klein_assets.json`, install helper `scripts/install_forge_klein_assets.ps1`. Klein LoRA admission and served-LoRA binding: `src/image_backends/forge_klein_lora.py`, `src/image_backends/model_policy_lora.py`. Host-memory gate: `src/image_backends/forge_klein_readiness.py`.

### 4.2 Model policy and capability registry

`src/image_backends/model_policy.py` is the single capability/operator-policy answer: `resolve_model_policy(model_name, family_lookup=...)` returns a `ModelPolicy` (family, evidence level, allowed backends, stages, per-control `ControlPolicy` of configurable/fixed/unsupported, per-feature `FeaturePolicy`, prompt dialect). Resolution order: exact Klein name, exact Z-Image name, then `AssetRegistry` family evidence (`RegistryFamilyLookup`, persisted snapshot only, no scan), else unverified/unknown. Only SDXL (`QUALIFIED_REGISTRY_POLICY_IDS`) is a qualified registry policy; sd1, sd2, sd3 and flux are labelled but unqualified. Nothing unclassified is ever labelled SDXL.

Four concepts stay separate: backend identity (configuration), model family, exact profile, policy. The GUI, Learning and PromptPack editor project the policy and are advisory. The compiler and the backend are final.

Compile-time seams in `model_policy.py`:

- `apply_model_compile_policy(config)`: the one compile entry point; dispatches to the Klein or Z-Image compile policy; a no-op for every other model.
- `normalize_profile_owned_values(config, changes)` and `prepare_candidate_baseline(config)`: replace inherited values the exact profile itself owns (sampling, CLIP skip, VAE, optimizer, global prompt terms and flags) before validation. They never touch geometry, counts, seeds, stages, assets or optional features, so a genuine conflict is still refused.
- Generic builder: `prepare_effective_config` in `src/pipeline/exact_profile_effective_config.py` normalizes and composes global positive terms for an exact Z-Image selection; `JobBuilderV2` calls it before `apply_model_compile_policy`. The PromptPack builder does the equivalent inline for Z-Image and keeps source intent separate from the executable config.
- Global prompt policy: `src/pipeline/global_prompt_policy.py` (`has_frozen_global_prompt_policy`); the executor applies global terms only when not already composed by the compiler.

### 4.3 Cross-workflow compatibility preflight

`src/image_backends/operation_compatibility.py` answers "can this requested operation run on that resolved target?" from `ModelPolicy` alone (`assess_operation`, `assess_njr`, `require_njr_operation`; codes such as `backend_mismatch`, `stage_chain_unsupported`, `source_image_count`, `geometry_unsupported`). It is a projection, not an authority. Consumers: `src/controller/reprocess_admission.py`, `src/controller/review_batch_service.py`, `src/controller/batch_operations_service.py`, `src/gui/controllers/review_workflow_adapter.py`, `src/prompting/pack_target_readiness.py` (PromptPack editor readiness). A target without an exact profile (ordinary SDXL, unknown families) is never narrowed here.

### 4.4 Prompt compatibility and adaptation (`src/prompting/`)

| Module | Role |
|---|---|
| `prompt_compatibility.py` | `project_prompt_target`: describes what the target policy means for the current prompt (severity `info`/`advisory`/`action_required`). Never rewrites. |
| `prompt_adaptation.py` | `adapt_prompt_for_target` and `adapt_structured_prompt`: deterministic, policy-driven adaptation (flatten A1111 weighted attention, `BREAK` to paragraph boundary, omit channels/assets the target does not support). No family or model-name conditionals; plans carry operation codes, never prompt text. |
| `pack_target_readiness.py` | PromptPack editor readiness (structure vs target) from in-memory state. |
| `prompt_optimizer_*`, `stage_policy_engine.py`, `prompt_splitter.py` | The prompt optimizer used by the executor (`Pipeline._run_prompt_optimizer`). Disabled and refused under exact profiles. |

The PromptPack compiler calls `adapt_structured_prompt` on structured components before rendering the executable string (`src/pipeline/resolution_layer.py`, `src/pipeline/compile_evidence.py`), so Prompt-tab preview and execution share one rule. Compile-time adaptation is compile-safe: only definitive policy facts and definitive `incompatible` LoRA evidence delete an authored component; missing or conflicting evidence preserves it and the backend's fail-closed admission stays final. Adaptation evidence is frozen into the queued job.

## 5. Assets (`src/assets/`)

`AssetRegistry` (`src/assets/registry.py`) is the sole local-file identity authority: offline, streamed SHA-256, safetensors header reading only, duplicate paths grouped by content, hash cache at `state/asset_registry_v1.json` (`src/state/workspace_paths.py`, atomic writes, cross-process lock in `cache_lock.py`). Filename and path are aliases, never identity. It never contacts a WebUI; `WebUIResourceService` (`src/api/webui_resource_service.py`) is the separate read-only answer to what a running WebUI exposes.

| Module | Role |
|---|---|
| `registry.py` | `AssetKind` (checkpoint, vae, lora, embedding, upscaler, controlnet, adetailer, openpose_image, ...), `AssetRecord`, `refresh`, `cached_snapshot`, `locate_checkpoint` |
| `compatibility.py` | Conservative family evidence (`ModelFamily`, `CompatibilityStatus`); conflicting or absent evidence is preserved, never guessed |
| `checkpoint_structure.py`, `component_evidence.py`, `controlnet_structure.py`, `gguf.py` | Bounded header-only structural evidence (SDXL layout, dependency-bearing FLUX-style transformers, ControlNet family, GGUF container) |
| `observation.py`, `bundles.py`, `adapter_evidence.py`, `inventory_report.py` | Tier-1 observational inventory and advisory bundle/adapter evidence; never produce "ready" or "qualified" |
| `cache_diagnostics.py`, `cache_lock.py` | Path-free cache diagnostics; cache transaction lock |

`src/utils/lora_scanner.py` and `src/utils/embedding_scanner.py` are thin projections over the registry. The active embedding root is `<webui_root>/embeddings`.

PromptPack LoRA discovery uses `AssetRegistry.refresh(persist=False)` through the existing LoRA adapter: the same
identity and metadata readers, with a disposable snapshot and no cache-file write. A tracked worker performs discovery,
keyword/sidecar reads and local preview lookup. The local browser decodes only the current four-card page on a tracked
worker, with byte/pixel limits and at most four Tk images. Refresh requests coalesce and only the latest result is applied
through `GuiInvoker`; failed discovery visibly retains unverified inventory and all authored selections/strengths.
Unreadable metadata, conflicting evidence, ambiguous aliases and missing previews remain explicit unknown/unavailable facts.
`src/gui_v2/lora_browser.py` projects registry evidence and the existing ModelPolicy/LoRA assessment without admitting work.
Filename hints alone establish neither side of a pairing. Matching family evidence is only possibly compatible, never
physical checkpoint–LoRA qualification. Content visibility filters precede search/paging/decoding and redact retained
hidden selections, tooltips and annotations. Local browsing writes no source asset, model, PromptPack or user cache and
performs no network lookup or download.

## 6. Refinement, ADetailer and YuNet (`src/refinement/`)

- Adaptive refinement intent: `AdaptiveRefinementIntent` (`refinement_policy_models.py`), modes `disabled`, `observe`, `adetailer`, `full`, extracted from the NJR intent by `extract_adaptive_refinement_intent` (`src/pipeline/config_contract_v26.py`).
- `PipelineRunner.run_njr` resolves a `SubjectScalePolicyService` (`_resolve_refinement_policy_service`), assesses the stage input, and `_apply_adetailer_refinement_overrides` / `_apply_upscale_refinement_overrides` adjust the executable stage config; decisions land in `metadata["adaptive_refinement"]`. Prompt patches go through `apply_prompt_patch` (`prompt_patcher.py`) with provenance.
- Detectors implement `SubjectDetector`: `NullDetector` (default) and `OpenCvFaceDetector` (YuNet, CPU, `detector_id` `opencv_yunet`). The model is the repository asset `src/refinement/assets/face_detection_yunet_2026may.onnx`; the detector refuses native loading unless size and SHA-256 match exactly. No downloads, no scans.
- YuNet is StableNew's own CPU observation. It is not the Forge ADetailer detector and the two are never conflated.
- ADetailer control truth: the pinned ADetailer-Neo silently drops a pass whose arguments fail its schema, and exposes no machine-readable detection result. `schema_issues` / `detector_status` (`adetailer_contract.py`) define "supported"; `build_effectiveness` (`adetailer_effectiveness.py`, schema `stablenew.adetailer-effectiveness.v1`) keeps detection, execution, observable pixel change and visual improvement as four separate outcomes. Nothing may claim an anatomy fix succeeded.
- Under Forge only the managed runtime's accepted detector set is offered (`adetailer_detector_fallbacks` in `backend_capabilities.py`).

## 7. Photo Optimize touchpoint

`src/photo_optimize/submission.py` prepares intent and compiles only through the existing `ReprocessJobBuilder`; `src/controller/photo_optimize_submission.py` is the extracted controller preparation. It adds no executor, queue or compiler. Its jobs are ordinary img2img/ADetailer/upscale NJRs and are subject to the same backend and exact-profile admission (`reprocess_admission.require_njr_operation`). Settings, store and migration live in the rest of `src/photo_optimize/`.

## 8. Provenance, artifacts and metadata

| Artifact | Producer | Contract |
|---|---|---|
| Image file (PNG/JPEG) with embedded `stablenew:*` keys (schema, job id, run id, stage, payload SHA-256, NJR SHA-256, payload plain or gzip+base64, public `parameters` text) | `Pipeline._build_image_metadata_builder` -> `build_contract_kv` -> `save_image_from_base64` (`src/utils/file_io.py`) | `ImageMetadataContractV26` in `src/utils/image_metadata.py`. Soft limit 32 KiB inline, hard limit 256 KiB compressed, else payload omitted with a reason. |
| Per-image manifest `<run>/manifests/<image>.json` | `Pipeline._write_manifest_file` (plus prompt-optimizer sidecars) | Stage manifest incl. requested vs actual seeds, global-term accounting, pressure/admission, `artifact` record |
| Artifact record (`stablenew.artifact.v2.6`) | `artifact_manifest_payload`, `canonicalize_variant_entry` | `src/pipeline/artifact_contract.py` |
| Backend/profile evidence | `ImageExecutionResult.backend_metadata`: `klein_profile` / `zimage_profile` (asset size+SHA-256, host memory, observed Forge state, source image hash, LoRA binding), `openpose_conditioning`, `forge_module_baseline` | `ForgeWebUIImageBackend.execute` |
| Run metadata, replay and diagnostics descriptors | `write_run_metadata` (`src/learning/run_metadata.py`), `build_replay_descriptor` / `build_diagnostics_descriptor` | `src/pipeline/result_contract_v26.py` |
| Failure evidence | `build_failure_evidence` attached by the runner on failure (`dispatch_certainty`, category) | `src/api/webui_failure_evidence.py` |

Output folders are `output/<route>/<pack>-<model>-<vae>` (or the Learning experiment label), resolved by `PipelineRunner._resolve_run_dir` with `classify_njr_output_route`. Replay inputs are verified by SHA-256 (`src/pipeline/replay_input_verification.py`); `ReplayEngine` re-enters `run_njr`.

Provenance is best-effort but no longer silent (audit B9, fixed in P3-5) [V]: when the image metadata builder fails the PNG is still saved without embedded provenance, but the failure is logged at WARNING and recorded in `Pipeline._provenance_incomplete` (stage, image, reason, error); `PipelineRunner` copies the list into `result.metadata["provenance_incomplete"]` (absent when nothing was lost). An NJR identity failure and a `write_run_metadata` failure are logged the same way (the first is also recorded). The embedded `stablenew:njr_sha256` is the repository fingerprint (`jobs.njr_fingerprint`): both come from `src/utils/njr_identity.py` (the `{schema_version, job_id, normalized_job}` envelope, canonical ASCII-escaped JSON, SHA-256), so a PNG matches its SQLite row. Images written before P3-5 carry the older hash of the bare record and are not rewritten. `decode_payload` gunzips embedded payloads without a size bound (audit B11) [V]. Do not add code that depends on every image carrying a payload.

## 9. Invariants that must not be broken

1. Canonical path only. No second queue, runner, history or compiler authority. `PipelineRunner.run_njr` is the sole public runner entry. The GUI and controllers capture intent and render projections; they never build backend payloads or call a runner/backend.
2. Fresh work is queued; the NJR is immutable. Executors and backends must not mutate it; derive per-request copies (`thaw_json`).
3. Never replay an ambiguous dispatched generation POST. `SDWebUIClient` classifies an ambiguous transport failure (`_is_ambiguous_generation_transport_failure`, `WebUIGenerationOutcomeUnknownError`) and refuses automatic replay; a definite HTTP refusal is also not replayed. An unknown outcome is terminal/action-required. Do not add retries around `_generate_images*` that could re-send.
4. External A1111/Comfy/Forge processes are never adopted, restarted or killed. Lifecycle only for a process the manager launched. A Forge job needs a positively identified managed Forge endpoint (`verify_backend_runtime_identity`).
5. No backend fallback, no per-job runtime switching. Mismatch is refused before dispatch.
6. Refuse before dispatch, loudly. Unsupported features (Hypernetwork under Forge, OpenPose off-target, anything outside an exact profile envelope, unqualified multi-component checkpoint) raise before any module write or generation POST. Do not "drop and continue".
7. Exact profiles are immutable and are never inferred from a substring; a new envelope is a new version, validated by the compiler, the backend and operation compatibility independently.
8. Conditioning bytes (OpenPose) never enter the NJR, logs or manifests; the job-owned snapshot is hash-verified at the POST.
9. The registry never gains network or scan-at-import behavior; evidence modules stay header-only and path-free in reports.
10. Persisted state goes through `src/utils/atomic_io.py`.
11. The physical-GPU hold was lifted on 2026-10-18 (STATUS.md Holds); the device-loss quarantine remains. Tests must not contact a WebUI, model, GPU or display unless explicitly opt-in (`real_backend` marker).
12. Protected actions (push to `main`, merge, publish, secrets, material architecture changes) need explicit owner approval (`AGENTS.md` section 5).

## 10. How to test

Configuration is `pyproject.toml` only. Run `python tools/ci/run_pr_gate.py` for the required gate; run focused tests first.

| Area | Tests | Hermetic seam |
|---|---|---|
| Backend contract, registry, parity, Forge profile/ControlNet/LoRA/policy/prompt adaptation | `tests/image_backends/` | `tests/helpers/fake_webui_transport.py` (`FakeWebUITransport`, `flavor` forge or a1111; records every request so tests assert no generation POST preceded a refusal) |
| Executor stages, runner, ADetailer, refiner/hires, cancellation, NJR and PromptPack compile, OpenPose compile/wire | `tests/pipeline/` | `tests/helpers/pipeline_fakes.py`, `tests/helpers/fake_pipeline_runner.py`, `tests/helpers/njr_factory.py` |
| WebUI client, Forge client, readiness, identity, process manager | `tests/api/` | Fake transport; `tests/mocks/webui_mock_client.py` and `tests/mocks/webui_mock_server.py` for journey-style tests |
| Asset registry, header evidence, topology | `tests/assets/` | Header fixtures (`tests/assets/checkpoint_fixtures.py`, `tests/assets/topology_fixtures_152.py`); temp registry roots |
| OpenPose library, snapshot, catalog | `tests/conditioning/` | `tests/conditioning/openpose_fixtures_210.py` |
| Refinement, YuNet, prompt patcher | `tests/refinement/` | Synthetic images; no network |
| Photo Optimize | `tests/photo_optimize/` | Temp state roots |
| Image metadata and artifact contracts, replay | `tests/utils/test_image_metadata_contract.py`, `tests/pipeline/test_artifact_contract.py`, `tests/pipeline/test_replay_*` | In-memory payloads |
| Queue, repository, outage, GPU-loss | `tests/queue/`, `tests/controller/` | Stub runners |

Rules: use temporary state and artifact roots; never real WebUI, model or GPU. Operator-only qualification code lives in `tools/qualification/` and `tools/acceptance/` and is never part of the production path or CI. For a new refusal, assert both the error and that no generation POST was recorded.

## 11. Known debt and traps

- Executor monolith [V/A]: `src/pipeline/executor.py` has no size ratchet; the stage methods (`run_txt2img_stage`, `run_img2img_stage`, `run_adetailer`, `run_upscale_stage`, `run_adetailer_stage`) each repeat admission, model/VAE, drift, metadata and manifest steps (audit C3). `PipelineRunner.run_njr` is orchestration only (about 130 lines, guarded by `tests/pipeline/test_run_stage_handlers_p4_1.py`; audit P4-1): per-stage logic lives in `src/pipeline/run_stage_handlers.py` (`Txt2ImgHandler`, one `PerImageStageHandler` parameterized by `IMG2IMG_SPEC` / `ADETAILER_SPEC` / `UPSCALE_SPEC`, `VideoStageHandler`, resolved by `resolve_stage_handler`). A new image stage is a new spec or handler there; handlers reach `_execute_image_backend` through the runner, so it stays the only dispatch point.
- Dead code in the executor [V: zero callers in `src` and `tests`]: `Pipeline.run_pack_pipeline` (~450 lines, the only other caller of `run_adetailer`), `Pipeline.run_img2img` / `_run_img2img_impl`, `Pipeline.run_upscale` / `_run_upscale_impl`. The live stage methods are the `*_stage` ones. Do not fix bugs in the dead copies or mistake them for the production path.
- Dead code in the runner [V: no callers in `src`]: `PipelineRunner._call_stage`, `_build_stage_payload`, `_build_executor_config`, `_apply_stage_metadata`; `src/pipeline/payload_builder.py` (`build_sdxl_payload`) is reachable only through them. `_validate_stage_plan` is referenced only by a test. The executor comment that "flat payload format comes from `_build_stage_payload`" is stale.
- Untyped stage config [A]: dicts with spreading key aliases (executor ~570 `.get(` calls over ~195 keys; `StageConfig` types only 8 fields). `StageConfig.extra` is the real carrier and is flattened into the executor config by `WebUIFamilyImageBackend._stage_executor_config`.
- Alias keys [V]: model is `model` / `sd_model_checkpoint` / `base_model` / `model_name`; VAE is `vae` / `sd_vae` / `vae_name`; sampler is `sampler` / `sampler_name`; ADetailer values appear as `adetailer_cfg`, `adetailer_denoise`, `adetailer_confidence`, `adetailer_steps`, `adetailer_model`, `adetailer_checkpoint_model` and per-pass `adetailer_hands_*`, mapped to `ad_*` wire keys inside `run_adetailer` [A: up to 4 spellings per setting]. The normalizer (`src/pipeline/config_normalizer.py`) writes both spellings back. Profile validators therefore scan several keys per concept; a new validator must do the same.
- Divergent defaults [V]: `run_adetailer` hard-codes fallbacks in several places (face pass cfg 5.5 and denoise 0.32 through `get_with_fallback_warning`, but 7.0 and 0.4 in the outer img2img payload). Changing a default means finding every site.
- NJR construction sites [A]: `NormalizedJobRecord(` is built at eight sites with different policy subsets (audit C2). Anything you add to image compile must be applied in `JobBuilderV2`, `PromptPackNormalizedJobBuilder`, `ReprocessJobBuilder`, `cli_njr_builder.py` and checked against `src/learning/model_comparison.py`. `JobBuilderV2` stamps `SourceKind.CLI` on non-pack GUI runs [V]; audit C2 notes this mislabels provenance [A].
- Stale install hint [V]: the `src/image_backends/forge_klein_profile.py` module docstring places the Klein install script under `tools/`; the real file is `scripts/install_forge_klein_assets.ps1` (the backend's error text uses the right path).
- Swallowed stage exceptions: stage methods catch generic exceptions and return `None`, which the runner reports as "no images" (the backend raises `KleinProfileError` early for this reason, see `_assert_assets_listed`). Raise refusals from `validate_njr_intent` / `_validate_request` / `_before_dispatch`, not from inside a stage method.
- Layering [A]: `utils` imports upward and 23 packages form one import cycle (audit C6); `src/controller/prompt_pack_preflight.py` imports a GUI dialog (audit C1).
- Hypernetworks are refused under Forge but allowed under A1111; `requested_hypernetworks_for_njr` inspects config, stage `extra` and randomizer sweeps.
- `src/learning/model_profiles.py` (learning/style priors) is a different concept from `ModelPolicy`; do not merge them.

## 12. Adding or changing a model family today

There is no plugin protocol yet (audit P4-5). The honest file list for a new exact profile or a changed envelope:

1. Profile contract (new file or new immutable version): model it on `src/image_backends/forge_klein_profile.py` / `forge_zimage_profile.py` (frozen dataclass, `reference()`, `validate_*_config`, `apply_*_compile_policy`, `is_*_transformer_name`). Never edit a published version.
2. `src/image_backends/exact_model_profile.py`: extend `ExactModelProfile`, `model_profile_for_model`, `resolve_model_profile`, `validate_profile_intent`, `validate_profile_njr`, `profile_prompt_refusal`.
3. `src/image_backends/model_policy.py`: `policy_for_profile`, `resolve_model_policy`, `apply_model_compile_policy`, `normalize_profile_owned_values`, family constants. This is what the GUI, operation compatibility and prompt adaptation read.
4. `src/image_backends/forge_webui_backend.py`: `validate_njr_intent`, `_validate_request`, `_before_dispatch`, `_finalize_config`, `execute` evidence. `src/image_backends/forge_klein_assets.py` for asset identity and `config/forge_klein_assets.json`.
5. Wire format, only if the model needs it: a projection hook in `src/pipeline/executor.py` (`run_txt2img_stage`), as Z-Image does. Keep it a no-op for other models.
6. Compilers: `src/pipeline/prompt_pack_job_builder.py`, `src/pipeline/job_builder_v2.py` (via `src/pipeline/exact_profile_effective_config.py`), `src/pipeline/cli_njr_builder.py`, `src/pipeline/reprocess_builder.py`, `src/learning/model_comparison.py` and `src/learning/model_policy_service.py`.
7. Assets and readiness if the model is multi-component: `src/assets/component_evidence.py`, `src/image_backends/model_readiness.py`, `src/assets/compatibility.py` (new `ModelFamily` only with header evidence).
8. Prompt side: `src/prompting/prompt_adaptation.py` and `prompt_compatibility.py` normally need no change (policy-driven); the dialect lives in the `ModelPolicy`.
9. GUI projections that name the family: `src/gui/zimage_optional_control_projection.py` is an example of presentation-only control availability; `src/gui/prompt_target_presenter.py` for target labels.
10. Tests in `tests/image_backends/`, `tests/pipeline/`, `tests/assets/`, with the fake transport. Physical qualification is owner-gated (section 9).
11. This file, `STATUS.md` (supported capabilities) and a record under `docs/Subsystems/Image/` for the qualification evidence.

An ordinary checkpoint of an already-supported family (another SDXL model) needs none of this; it takes the generic path and the registry decides its label.

## 13. Evidence records

Per-PR records stay in `docs/Subsystems/Image/` as historical evidence. They may describe superseded behavior; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/Image/PR-IMG-100_Backend-Neutral_Image_Execution.md` | The one-backend-per-NJR contract and the A1111 compatibility rule |
| `docs/Subsystems/Image/PR-IMG-FORGE-100_Forge_Compatibility_Qualification.md` | Forge/A1111 differences, module baseline, identity guard (very long; grep it) |
| `docs/Subsystems/Image/PR-IMG-FORGE-120_Forge_Default_Production_Promotion.md` | Why Forge is the new-work default and how A1111 rollback works |
| `docs/Subsystems/Image/PR-IMG-116_FLUX2_Klein_Forge_Production_Slice.md` | Klein profile v1: envelope, evidence, refusals |
| `docs/Subsystems/Image/PR-IMG-117_FLUX2_Klein_LoRA_Qualification_and_Profile_v2.md` | Klein profile v2 and LoRA admission |
| `docs/Subsystems/Image/PR-IMG-130A_Model_Family_Capability_Registry.md` | `ModelPolicy` and the four-concept split |
| `docs/Subsystems/Image/PR-IMG-MODELS-155_ZImage_Turbo_FP8_Forge_Enablement.md` | Z-Image profile and its limited qualification |
| `docs/Subsystems/Image/PR-IMG-MODELS-158_Cross_Workflow_Model_Compatibility.md` | Operation compatibility preflight and reproduced failure boundaries |
| `docs/Subsystems/Image/PR-IMG-MODELS-159_ZImage_Effective_Configuration_Adaptation.md` | Effective-config normalization and global-positive composition |
| `docs/Subsystems/Image/PR-IMG-MODELS-151_Klein_Base_9B_Feasibility.md` | Why Klein Base 9B is refused (`NO_GO_RESOURCE_RISK`) |
| `docs/Subsystems/Image/PR-IMG-CNET-210_SDXL_OpenPose_ControlNet.md` | OpenPose conditioning end to end |
| `docs/Subsystems/Image/PR-REFINE-160_ADetailer_Control_Truth_and_Effectiveness_Evidence.md` | ADetailer argument truth and effectiveness evidence |
| `docs/Subsystems/Image/PR-ASSET-110_Local_Asset_Registry.md` | Registry identity boundary and cache |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit C1-C4, B9, B11 and the P4 plan referenced above |
