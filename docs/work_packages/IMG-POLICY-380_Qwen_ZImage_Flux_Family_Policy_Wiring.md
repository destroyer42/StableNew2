# IMG-POLICY-380 — Make the installed Qwen-Image, Z-Image and FLUX-family checkpoints runnable: structural family policies and wiring

Hand-off prompt for a fresh Claude Code or Codex session. Discovery is done (including a read-only header scan of the owner's
model folder); read only the files named here.

## Objective

- **Owner complaint (2026-11-22):** "We made Qwen, Generic Flux model policies/profiles, but they aren't wired up. Multiple
  downloaded models don't run because we don't have a valid policy for them; finish the wiring that makes those functional."
- **Key finding (read this first):** the existing profiles *are* wired compiler → backend, but they match **exact file names**
  of files the owner does not have. The files the owner *does* have are covered by no profile:

| Installed file (`C:\Users\rob\stable-diffusion-webui\models\…`) | Header class (repo reader) | Today |
|---|---|---|
| `Stable-diffusion\qwenImage_qwenImageFp8E4m3fn.safetensors` (20,430,635,136 B) | `qwen_image_dit`: hidden 3072, 60 layers → original **Qwen-Image 20B fp8** (renamed); needs a **Qwen2.5-VL-7B text encoder (hidden 3584)** and the 16-ch Qwen VAE | No profile → refused at the Forge gate. **No Qwen2.5-VL encoder is installed anywhere.** |
| `VAE\qwenImage_qwenImageVAE.safetensors` | `qwen_image_vae` | Unused |
| `Stable-diffusion\zImageTurbo_turbo.safetensors` (bf16), `juggernautZ_v10*_pruned_fp8.safetensors` ×2 | `z_image_dit` | Z-Image profile matches only its exact FP8 file name → refused |
| `flux-2-klein-base-9b-*` (fp8 + GGUF) | FLUX.2 Klein 9B | Refused by owner decision (`NO_GO_RESOURCE_RISK`) — **stays refused** |
| `flux3Klein_klein_pruned_int8` | `unrecognized_dit` | Refused by owner decision Q3 — **stays refused** |
| FLUX.1 dev/schnell | — | Profile `flux1_dev_gguf@v1` exists but is dormant: no FLUX.1 transformer, `clip_l`, or `t5xxl` installed |

- **Outcome:** structural (header-evidence) family identity for Qwen-Image and Z-Image DiTs flows registry → policy → routing →
  backend, so (1) the Z-Image Turbo bf16 and juggernautZ fp8 checkpoints run on Forge through a Z-Image **family** profile,
  (2) the original Qwen-Image 20B fp8 has a profile on the `comfyui` backend that runs once its encoder is present (or refuses
  with a precise "missing Qwen2.5-VL-7B text encoder" readiness reason), (3) FLUX.1 schnell gets its one-file profile, and
  (4) every remaining refusal in the model picker says exactly *why* and *what to install*, instead of a generic "(unsupported)".
- **Explicit exclusions:** Klein 9B and `flux3Klein` stay refused (owner decisions). No model downloads or physical runs by the
  agent. No LoRA/img2img/hires for Qwen (COMFY-100 exclusions stand). No Forge Qwen path (COMFY-100 chose Comfy; Forge Neo has
  Qwen support per PR-IMG-BACKEND-QUAL-100 L87 — mention as an alternative only).

## Execution class and model recommendation

- Execution class: **Standard-high** (cross-file, known architecture: assets → policy → routing → backend; no new runtime owner).
- Model recommendation: Claude Code **Sonnet 5.5 XHigh** (or Opus 5.5 High if the structural-identity design feels ambiguous);
  Codex **GPT-6.1 Sol XHigh**.
- Expected usage: about 20M cache-read, 150k output.

## Exact start state and sequencing

- `origin/main` at hand-off `d8ea1c86`; isolated worktree (live app runs from the main checkout); main's `.venv` interpreter.
  Branch `image/img-policy-380-family-wiring`. Record task-start timestamp and session ID.
- **Land before `IMG-COMFY-381`** (SDXL on ComfyUI + backend toggle) — both edit `model_policy.py` and `model_backend_routing.py`.

## Research already done

### How policy resolves today
- `src/image_backends/model_policy.py::resolve_model_policy` (L518-563): exact names first — Klein `is_klein_transformer_name`,
  Z-Image `is_zimage_transformer_name`, Ideogram `is_ideogram4_model_name`, Qwen `qwen_image_profile_for_model`; then registry
  family via `RegistryFamilyLookup` (L577-629; cached snapshot, matched by file name `_model_key` L566); SDXL → `_sdxl_policy`;
  FLUX with transformer-only layout → `FLUX1_DEV_PROFILE_V1` or `_flux_refused_policy` (L418-438); else `_unverified_policy`
  (`unverified_generic[:family]`, L479-491). `policy_for_profile` (L288-365). Compile: `apply_model_compile_policy` (L686-706),
  `compile_model_policy` (L757) → `ModelPolicyResult` (L710-754; `project_flat` mirrors dispatch).
- `src/image_backends/exact_model_profile.py`: `model_profile_for_model` (L57-63, exact names), `resolve_model_profile` (L66-82),
  `validate_profile_intent` (L119-161), `validate_profile_njr` (L85-93).
- Matching: Qwen by name (`comfy_qwen_image_profile.py` L197-203) then size + SHA-256 at dispatch; Klein/Z-Image name + byte
  verification; FLUX.1 by structural layout in the registry snapshot (`forge_flux1_profile.flux1_selected` L239-242) via the lookup
  installed in `src/main.py` L589-600, 631. **FLUX.1 is the precedent for structural identity — copy its pattern.**
- Routing `src/image_backends/model_backend_routing.py`: `_RESOLVERS` (L36), `_qwen_image` (L29-33, exact-name),
  `_qwen_image_offers` (L48-59, 2.1 profiles only), `required_backend_for_model` (L89) ← `image_backend_types.normalize_image_backend_options` (L88-93).
- Refusal: `src/image_backends/forge_webui_backend.py::_dependency_gate` (L715-744) from `_before_dispatch` (L746-757) raises
  `ForgeUnqualifiedModelError` (L160), fed by `model_readiness.assess_model_readiness` (L204+, `blocks_dispatch` L133-138); message
  L300-304 or `FLUX_VARIANT_REFUSALS` (`forge_flux1_profile.py` L151-166). Picker suffix " (unsupported)":
  `src/api/webui_resource_service.py::_classify_pickers` (L114-140) → `src/gui/base_generation_panel_v2.py` L605-620.

### The missing links (verified)
1. `src/assets/compatibility.py` `ModelFamily` (L17-22) has no `qwen_image` / `z_image`.
2. `src/assets/checkpoint_structure.py::checkpoint_header_evidence` (L208-241) records only SD/SDXL/FLUX layouts → Qwen and Z-Image
   DiTs come out "unrecognized" even though `src/assets/component_evidence.py` already detects `ARCH_QWEN_IMAGE_DIT` (L233-255) and
   `src/assets/bundles.py` L59-71 documents the `qwen2_5_vl` encoder need. Wire that evidence through.
3. `src/assets/registry.py::_build_record` (L996-1051) — family mapping (FLUX mapping L1015-1020 is the model).
4. `resolve_model_policy` has no Qwen / Z-Image structural branch; routing `_qwen_image` is exact-name only.
5. Comfy readiness cannot see the A1111 `checkpoints` folder: `comfy_image_readiness.comfy_model_folders` (L49-65) →
   `src/video/workflow_asset_integrity.model_folders` (L14+, reads only `diffusion_models`/`unet`, `text_encoders`/`clip`, `vae`, L37-41);
   `%LOCALAPPDATA%\StableNew\ComfyRuntime\extra_model_paths.yaml` maps A1111 folders only as `checkpoints`/`vae`. A Qwen DiT in
   `models\Stable-diffusion` must be visible to ComfyUI's `UNETLoader` (`diffusion_models`) — add the A1111 `Stable-diffusion` folder
   to the generated extra-paths `diffusion_models` entry (find the generator; grep `extra_model_paths`) **or** have readiness tell the
   owner to place it under `diffusion_models`. Prefer the generator change; never move or copy the owner's files.
6. Qwen: `ComfyImageBackend._require_profile` (L152-167) typed to `QwenImageProfile`; graphs only for 2.1 (`comfy_image_graphs._GRAPHS` L203).

### Profiles and docs
- Qwen: `src/image_backends/comfy_qwen_image_profile.py` (`QWEN_IMAGE_21_PROFILE_V1` / `_TURBO_` L118-153, validators, compile policy
  L354-415), `comfy_image_graphs.py` (`_qwen_image_21_t2i` L88), `comfy_image_backend.py`, `comfy_image_readiness.py`,
  `model_policy._qwen_image_policy` (L441-461). Qwen hard-requires `comfyui`; comfyui NJR = txt2img only.
- Z-Image: exact profile in `docs/Subsystems/Image/PR-IMG-MODELS-155_ZImage_Turbo_FP8_Forge_Enablement.md`; code
  `src/image_backends/forge_zimage_profile.py` (grep `is_zimage_transformer_name`); Holds: Z-Image clean shutdown/repeat stability
  unresolved, back in scope 2026-11-18, QUAL-927 bounded teardown landed — family profile inherits the same runtime behavior.
- FLUX: `src/image_backends/forge_flux1_profile.py` (`flux1_dev_gguf@v1` L91-145; schnell refusal L160-162), `src/assets/flux_variant.py`;
  `docs/Subsystems/Image/PR-IMG-FLUX-130_Generic_FLUX_Families.md` §4.1 ("a later `flux1_schnell@v1` is a one-file addition"), §10 Q1, §12.
- `docs/Subsystems/Image/PR-IMG-COMFY-100_Comfy_Still_Image_Backend.md` §2.1 (L66-77): original Qwen-Image / 2512 fp8 (~20 GB + 9.4 GB
  `qwen_2.5_vl_7b_fp8_scaled` encoder) rated a **resource risk** on 12 GB VRAM / 32 GB RAM; GGUF forbidden (custom-node policy `none`).
  It says "no Qwen-Image weights installed" — it only checked Comfy folders and the HF cache; correct this.
- `MODEL_PROFILES.md` never mentions Qwen (§1/§2/§4/§13 gap); `PR-IMG-MODELS-150` L77 calls juggernautZ "no recognized signature" (stale).
- Ledger: `IMG-Q1.qwen-image` and `IMG-Q1.other-generic-families` are UNSUPPORTED (`tools/qualification/system840/ledger.v1.json`);
  do not change statuses (owner-accepted edits only) — note in the report that they become plannable.

## Design

1. **Structural family identity** (assets): add `qwen_image` and `z_image` to `ModelFamily`; record their layouts in
   `checkpoint_header_evidence` using the existing `component_evidence` detectors (hidden size, layer count, required encoder hidden
   size, VAE channels); map in `registry._build_record`; keep header-only reads (no full-file hashing in the picker path).
2. **Z-Image family profile (Forge):** a `zimage_turbo_family@v1` profile matched structurally (z_image_dit, Turbo layout) that reuses
   the exact profile's validated execution settings, admits bf16 and fp8 finetunes (`zImageTurbo_turbo`, `juggernautZ_*`), records the
   file's SHA-256 at dispatch as identity (like FLUX.1), and keeps the exact FP8 profile untouched for stored jobs. If a finetune's
   recommended steps/CFG differ, keep the profile's defaults and let the advisory generation profile (`MODEL_PROFILES.md` §17) suggest.
3. **Qwen-Image 20B fp8 profile (ComfyUI):** `qwen_image_20b_fp8@v1` in `comfy_qwen_image_profile.py` (structural match + recorded
   SHA-256), its own frozen graph `_qwen_image_t2i_fp8` (UNETLoader fp8 e4m3fn weight dtype, CLIPLoader type `qwen_image` with the
   Qwen2.5-VL-7B encoder, the Qwen VAE, stock sampler per ComfyUI's Qwen-Image example), readiness floors set conservatively (VRAM
   ≥ 11 GB free, RAM ≥ 28 GB available, ComfyUI `--lowvram`/offload only if already in the pinned flags — do not add flags without
   the owner), `_require_profile` widened to the profile union, `_qwen_image_offers` extended. Without the encoder: readiness refuses
   at Preview with "Qwen-Image needs the Qwen2.5-VL-7B text encoder (`qwen_2.5_vl_7b_fp8_scaled.safetensors`, ~9.4 GB) in
   `models/text_encoders`" — never at dispatch.
4. **FLUX.1 schnell:** `flux1_schnell@v1` beside `flux1_dev_gguf@v1` (4 steps, CFG 1, distilled guidance off) — one-file addition per
   FLUX-130 §4.1; replace the refusal text for schnell.
5. **Precise picker reasons:** `_classify_pickers` keeps " (unsupported)" but the tooltip/readiness panel shows the policy's reason
   and the missing component (e.g. FLUX.1 dev: "needs `clip_l.safetensors` and `t5xxl_fp8_e4m3fn.safetensors`"; Klein 9B: "refused by
   owner decision (resource risk)"). Presentation only; the reason string comes from the policy/readiness result.
6. **Docs:** `MODEL_PROFILES.md` (§1, §2, §4 resolution order, §13), `IMAGE_PIPELINE.md` profile list, COMFY-100 §2.1 correction,
   PR-IMG-MODELS-150 L77, FLUX-130 §12, `STATUS.md` image line (edit, don't add), `docs/CODEX_MAP.md` image row if a module is added.

## Owner gates (stop and ask; never self-authorize)

1. Download of the Qwen2.5-VL-7B fp8 text encoder (name, source repo@revision, size) — the Qwen profile ships either way and refuses
   with a readiness reason until it exists.
2. Given COMFY-100's resource-risk rating, the first physical Qwen-20B run needs a frozen plan + owner authorization
   (`docs/runbooks/qual_system_840.md` §2). Same for the first Z-Image family run (Z-Image shutdown hold).
3. FLUX.1 dev downloads (transformer, `clip_l`, `t5xxl_fp8_e4m3fn`) only if the owner wants FLUX.1.

## Acceptance criteria

1. Header fixtures for `qwen_image_dit` and `z_image_dit` (build synthetic safetensors headers like `tests/assets/flux_fixtures_130.py`)
   resolve to the new families, policies and backends; the real file names above are not hard-coded anywhere.
2. A Z-Image family NJR compiles and dispatches to Forge with fake transport; the exact FP8 profile and stored jobs are unchanged.
3. A Qwen-20B NJR compiles to `comfyui`, builds a graph validating against fake `object_info`, runs end-to-end with
   `tests/helpers/comfy_image_fakes.py`, and with the encoder absent is refused at Preview with the encoder message.
4. Klein 9B / `flux3Klein` still refused with their owner-decision reasons; FLUX.1 schnell admitted; FLUX.1 dev reports missing
   components.
5. No silent fallback; no GUI payload building; `AppController` unchanged (it is exactly at its 4,775-line ceiling).

## Token-efficient validation plan

1. Focused: `tests/image_backends/test_model_policy_130a.py`, `test_comfy_qwen_image_profile_comfy100.py`,
   `test_comfy_image_backend_comfy100.py`, `test_comfy_image_readiness_comfy100.py`, `test_forge_flux1_profile_130.py`,
   `test_forge_zimage_profile.py`, `test_forge_webui_backend.py`; `tests/assets/test_flux_variant_130.py`, `test_asset_topology_152.py`,
   `test_asset_registry.py`, `test_picker_compatibility_370.py`; integration `tests/integration/test_pr_img_flux_130_canonical_path.py`,
   `test_pr_img_models_150_readiness.py`, `test_pr_img_155_zimage_canonical_path.py`; GUI `tests/gui_v2/test_qwen_image_gui_comfy100.py`,
   `test_model_policy_panel_130a.py`. Add new tests next to them.
2. Optional read-only sanity on the owner's real folder: `python tools/asset_topology_report.py` (header-only) — report the new
   classification of each file listed above; do not hash 20 GB files.
3. `python tools/ci/run_pr_gate.py` from the isolated worktree; real ratchet tools before pushing (strict mypy / BLE001 ratchets only shrink).
4. `git diff --check`.

## Stop conditions

- Running Qwen-20B needs a custom node, GGUF, or new ComfyUI launch flags → stop for owner.
- Structural identity can't distinguish Turbo from a Z-Image base/edit variant with header evidence alone → keep exact profiles for the
  ambiguous ones and report.
- Any change to the owner-refused Klein decisions → out of scope.

## Completion report

`AGENTS.md` §8 categories (implementation / demonstration / qualification none / held: downloads, physical runs, ledger statuses).
`Model / usage` line. Feature-branch commits; publish only with owner authorization.
