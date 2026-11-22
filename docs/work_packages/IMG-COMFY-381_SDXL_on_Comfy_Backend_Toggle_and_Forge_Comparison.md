# IMG-COMFY-381 — SDXL on the ComfyUI still-image backend, a Forge/ComfyUI default toggle, and a Forge-vs-ComfyUI comparison

Hand-off prompt for a fresh Claude Code or Codex session. Discovery is done; read only the files named here.

## Objective

- **Outcome (owner request 2026-11-22):** the operator can pick **Forge or ComfyUI** for still images with one easy control in
  Settings, SDXL runs on either backend through the canonical path, and a reproducible Forge-vs-ComfyUI comparison (SDXL first,
  then the other families each backend supports) exists and is ready for an owner-authorized run and blind owner review.
- **Two PRs, one package** (same outcome, validate separately):
  - **PR A — capability + toggle (offline, deterministic):** SDXL txt2img on `comfyui`; new setting + Settings control; model
    policy and routing accept it; refusals for unsupported features are explicit (never a silent fallback).
  - **PR B — comparison harness:** a driver through the real queue/runner path for matched Forge/ComfyUI pairs, plus a
    report (settings agreement, timing, VRAM/RAM, contact sheet, blind owner review sheet). Physical runs are owner-gated.
- **Explicit exclusions:** no change to Forge as the shipped default; no ComfyUI custom nodes (policy `none`); no ADetailer, hires
  fix, img2img, upscale or ControlNet on ComfyUI in this package (refuse them clearly; list as follow-ups); no external ComfyUI
  adoption; no promotion verdict.

## Execution class and model recommendation

- Execution class: **Architectural-lite / Standard-high** — it touches backend selection (an architecture rule in
  `docs/Subsystems/Image/IMAGE_PIPELINE.md` §2 and invariants L355-361). The owner's request authorizes the outcome; record
  the decision in the docs (below). If you find the change needs a new runtime owner or queue behavior, stop.
- Model recommendation: Claude Code **Opus 5.5 High** for PR A (or Sonnet 5.5 XHigh); **Sonnet 5.5 High** for PR B.
  Codex **GPT-6.1 Sol XHigh** (A) / **High** (B).
- Expected usage: PR A about 20M cache-read, 150k output; PR B about 10M / 80k.

## Exact start state and sequencing

- `origin/main` at hand-off `d8ea1c86`; isolated worktree, branch `image/img-comfy-381-sdxl-toggle` (PR B stacks on A).
  Use main's `.venv` interpreter in the worktree. Record task-start timestamp and session ID.
- **Overlap:** package `IMG-POLICY-380` (Qwen / generic Flux policy wiring) edits `src/image_backends/model_policy.py` and
  `src/image_backends/model_backend_routing.py` too. Rebase onto it if it merged first; never run both writers on one checkout.

## Research already done

### Current ComfyUI image backend (Qwen-Image 2.1 only)
- `src/image_backends/comfy_image_backend.py::ComfyImageBackend` (L112-121): `backend_id="comfyui"`, `stage_types=("txt2img",)`,
  `supports_negative_prompt=False`, `runtime_family="comfy"`. `_require_profile` (L151-168) refuses ordinary checkpoints
  ("runs only the frozen Qwen-Image 2.1 profiles"). `execute` (L210-239): validate → asset SHA-256 →
  `RuntimeTransitionCoordinator.prepare_for("comfy")` → owned runtime → `object_info` probe + VRAM/RAM floors → one
  `queue_prompt` → history poll → download → re-save PNG with StableNew metadata + manifest → **release ComfyUI on every exit**.
  Payload L264-277.
- Graphs are Python builders, not JSON: `src/image_backends/comfy_image_graphs.py` — `_qwen_image_21_t2i` (L88),
  `_qwen_image_21_turbo_t2i` (L110), `_GRAPHS` (L203), `graph_for_profile` (L206); `GraphSlots` (L41) only has prompt, seed,
  width, height, prefix. `release_owned_runtime_after_job=True` at L153 → every job is a cold load.
- Profiles `src/image_backends/comfy_qwen_image_profile.py` (L118-190: fixed sampler/steps/cfg, `_GEOMETRIES`, `_UNSUPPORTED_FLAGS`).
- Readiness `src/image_backends/comfy_image_readiness.py` (`comfy_model_folders` L49, `check_installation` L120,
  `probe_object_info` L166, `evaluate_floors` L197).
- Transport: `src/video/comfy_api_client.py::ComfyApiClient` + helpers from `src/video/comfy_workflow_backend.py`. Image and video
  share the one managed ComfyUI (`_resolve_process_manager` L317-340; `config/managed_comfy_runtime.json` v0.38.0 `6b747c04`,
  flags `--disable-pinned-memory --disable-auto-launch`, `custom_nodes.policy: "none"`). External ComfyUI refused (L342-362).

### Backend selection today
- Registry `src/image_backends/image_backend_registry.py::build_default_image_backend_registry` (L47-58): a1111, forge, diffusers,
  comfyui (comment L56: comfyui "selected only by a frozen Qwen-Image profile … never a fallback").
- NJR field `backend_options.image.backend_id`, stamped by `src/image_backends/image_backend_types.py::normalize_image_backend_options`
  (L56-111; called from `src/pipeline/njr_compiler.py::_prepare_raw` L233 and the builders). Precedence: explicit id → model-required
  backend (`src/image_backends/model_backend_routing.py::required_backend_for_model` L89, `_RESOLVERS = (_ideogram4, _qwen_image)` L36)
  → `configured_image_backend_id()` (L39).
- `configured_image_backend_id()` → `src/api/webui_runtime_identity.py::resolve_configured_webui_runtime_identity` (L135) →
  `normalize_webui_runtime_identity` (L118) **raises outside {a1111_webui, forge_webui}**. `load_backend_settings` (L156) fails closed.
- Runner: `src/pipeline/pipeline_runner.py::_resolve_image_backend_id` (L1534-1562) → `validate_stage_chain` → backend
  `validate_njr_intent`; ADetailer check uses `policy.allowed_backends`.
- Model policy: `src/image_backends/model_policy.py::_sdxl_policy` (L464-476) and `_unverified_policy` (L479):
  `allowed_backends=(FORGE, A1111)`.
- Presentation readers of the configured backend: `src/gui_v2/backend_capabilities.py` L40 (path may be under `src/gui*`; grep),
  `model_policy_panel_projection.py` L78, `prompt_tab_frame_v2.py` L1952, `guided_review_dialog.py` L351; model list
  `base_generation_panel_v2.py` L617/L1167 (`offered_backend_models()`).

### Settings plumbing (the toggle's home)
- `src/gui/engine_settings_dialog.py::EngineSettingsDialog`: existing "Runtime:" radios (L184-194, `RUNTIME_DEFAULT`/`RUNTIME_A1111`
  L47-51), `_load_runtime_choice` (L595), `collect_values` writes `webui_runtime_identity` only when changed (L683-685),
  `restart_required` (L620), and a "Video runtime (ComfyUI)" section (`_build_comfy_section` L294).
- Flow: `src/gui/main_window_v2.py::open_engine_settings_dialog` (L1640) → dialog → `_handle_settings_saved` (L1693) →
  `src/controller/app_controller.py::on_settings_saved` (L2873) → `src/utils/config.py::ConfigManager.update_settings` (L757) →
  `presets/settings.json` (`_default_settings` L784-819). Note: `presets/` mixes recipes and app settings (memory) — add the key
  through `ConfigManager`, never hand-edit the owner's `presets/settings.json` (it is locally modified in the main checkout).
- `AppController` is ratcheted and sits exactly at its ceiling (4,775 lines = `tools/ci/controller_surface_baseline.json` at
  `d8ea1c86`; STATUS's "5,010" is stale): add **no** lines there; the
  existing `on_settings_saved` path already persists arbitrary keys.

### Comparison material to reuse (PR B)
- `docs/Subsystems/Image/PR-IMG-BACKEND-QUAL-100_Forge_vs_Comfy_Still_Image_Qualification.md`: verdicts (L5-6) CONDITIONAL /
  INCONCLUSIVE / HOLD / NO-GO; no ComfyUI outputs exist (L91); fairness caveats (L93-101: approximate sampler/scheduler/CLIP-skip
  maps, unverified seed equality, differing torch, VAE "Automatic" not proof of same VAE; blind owner review, no numeric quality
  threshold); preconditions L110-117. The device-loss "fault clearance" precondition is satisfied by package DIAG-GPU-160
  (PCIe Gen4, owner 2026-11-22); `tools/qualification/system840/arms.py::_COMFY_IMAGE_HOLD` (L78-85) text needs the same update.
- `docs/Subsystems/Image/PR-IMG-COMFY-100_Comfy_Still_Image_Backend.md` decision 3 (L287) and exclusions (L301-302: "matched Forge
  comparison, default switch") — this package supersedes those exclusions by owner request; say so there.
- `tools/qualification/img_backend_qual_100/`: `spec.py` (S1 SDXL baseline, S3 SDXL+LoRA, S2 OpenPose; `SAMPLER_MAP`/`SCHEDULER_MAP`
  L81-82; frozen intent `tests/data/contracts/img_forge_100_frozen_intent.json`), `comfy_graphs.py::_sdxl_graph` (L35-128:
  CheckpointLoaderSimple, LoraLoader, CLIPSetLastLayer, KSampler; `validate_graph` vs `object_info`), `protocol.py` (cold/warm
  cases, `STOP_RULES`, `Preconditions`, `EVIDENCE_PER_CASE` L166, authorization digests), `inventory.py`. It has **no driver**.
- `tools/qualification/img_forge_100/compare.py::compare_pair`, `contact_sheet.py`, `runtime_capture.py`; driver template
  `tools/acceptance/img_forge_100_acceptance.py` (thin, through the real queue/runner path).
- No SSIM/LPIPS exists; docs forbid inventing a quality threshold.

## Design (PR A)

1. **Setting:** new key `image_backend_default` with values `"webui"` (default: follow `webui_runtime_identity` → Forge or A1111,
   today's behavior) and `"comfyui"`. Keep it **separate** from `webui_runtime_identity` (that names the WebUI process slot and
   requires restart). Read it in a sibling resolver next to `configured_image_backend_id()` in `image_backend_types.py`, fail
   closed on unknown values, and use it in `normalize_image_backend_options` precedence step 3. Precedence stays: explicit job id →
   model-required backend (Qwen/Ideogram) → configured default.
2. **Settings control:** in `EngineSettingsDialog`, add an "Image backend" segmented radio pair (`Forge (WebUI)` / `ComfyUI`) at the
   top of the image runtime area, with one line of help text ("ComfyUI supports txt2img for SDXL and Qwen-Image; hires fix,
   ADetailer, img2img and upscale need Forge"). No restart needed (ComfyUI jobs lease the GPU via `prepare_for`,
   `runtime_transition_service.py` L97-103). Also show the effective backend as a read-only badge where the prompt tab already
   shows backend capabilities (projection readers listed above) — presentation only.
3. **SDXL on ComfyUI:** new versioned graph `sdxl_t2i_v1` in `comfy_image_graphs.py`, ported from the qual `_sdxl_graph`; widen
   `GraphSlots` (negative prompt, steps, cfg, sampler, scheduler, clip_skip, LoRA list with weights, optional VAE file). Production
   maps in a new small module (e.g. `src/image_backends/comfy_sdxl_mapping.py`): Forge sampler/scheduler display names → ComfyUI ids
   (refuse unmapped names with the name in the message), `<lora:name:w>` stripped from the prompt into `LoraLoader` nodes resolved
   through the asset registry by SHA, textual-inversion names → `embedding:name` (cross-check memory: Forge strips `<embedding:X>`;
   do the equivalent translation), A1111-only syntax (`[from:to:n]`, `BREAK`, `AND`) refused with a clear message.
   `ComfyImageBackend`: `_require_profile` gets a second admission path for registry-verified SDXL checkpoints; capabilities
   `supports_negative_prompt=True` for that path. `model_policy._sdxl_policy.allowed_backends` gains `COMFY_IMAGE_BACKEND_ID`;
   `validate_stage_chain` refuses hires/refiner/ADetailer/img2img/upscale/ControlNet on comfyui **at Preview** with "switch the
   Image backend to Forge" guidance. Never fall back to Forge silently.
4. **Warm reuse (optional in A, required before timing claims in B):** add a bounded keep-warm for consecutive comfyui image jobs
   mirroring video VID-WARM-373 (`runtime_policy.keep_warm_between_jobs_seconds`, release on any other job/failure/idle). If it
   grows the backend by more than ~150 lines, defer it and make PR B measure cold and warm separately.
5. **Docs/ADR:** `IMAGE_PIPELINE.md` §2 (selection rules) and invariant L359 ("no per-job runtime switching" — a global default is
   not per-job switching; state it); `MODEL_PROFILES.md` SDXL backend row; PR-IMG-COMFY-100 exclusions note; `STATUS.md` image line
   (one edited line); `docs/CODEX_MAP.md` image-backends row.

## Design (PR B — comparison)

- Driver `tools/acceptance/img_comfy_381_compare.py` modelled on `img_forge_100_acceptance.py`: builds matched NJRs through the
  normal compile (only `backend_id` differs), submits through `JobService`, captures runtime identity, timing (cold + warm), VRAM/RAM
  (`runtime_capture.py`), output hashes; emits `compare.json`, a contact sheet (`contact_sheet.py`) and a **blind** review CSV
  (arm order shuffled with a recorded seed; owner rates fidelity to prompt, detail, artifacts, preference A/B/tie).
- Workloads (from `img_backend_qual_100/spec.py`): S1 SDXL baseline (≥ 6 prompts × 2 seeds), S3 SDXL + one LoRA, then any other
  family both backends support after IMG-POLICY-380 lands (Flux/Qwen are single-backend today: report "not comparable").
- Report fairness caveats verbatim from QUAL-100 L93-101; no numeric quality threshold; verdict field `OWNER_REVIEW_PENDING`.
- Physical run: frozen plan digest + owner authorization (`docs/runbooks/qual_system_840.md` §2); agents never self-authorize.

## Acceptance criteria

PR A
1. With `image_backend_default="comfyui"`, a registry-verified SDXL txt2img job compiles with `backend_id="comfyui"`, builds a
   graph whose nodes validate against a fake `object_info`, and runs end-to-end against `tests/helpers/comfy_image_fakes.py`.
2. With the default value, every existing path is byte-identical (Forge/A1111 behavior unchanged; Qwen still routes to comfyui).
3. Unsupported stages/syntax on comfyui are refused at Preview with an actionable message; no silent fallback anywhere.
4. Settings dialog persists the key via `ConfigManager`; reopening shows the saved choice; no restart prompt for this key.
5. No new lines in `AppController`; GUI builds no payloads.
PR B
6. Driver produces compare.json, contact sheet and blind CSV from a fake-backend dry run in tests; refuses to run physically
   without an authorization digest.

## Token-efficient validation plan

1. Focused: `tests/image_backends/test_comfy_image_backend_comfy100.py`, `test_comfy_qwen_image_profile_comfy100.py`,
   `test_image_backend_contract.py`, `tests/system/test_construction_identity_contract.py`, `tests/gui_v2/test_engine_settings_*`,
   `tests/gui_v2/test_qwen_image_gui_comfy100.py`, `tests/tools/test_img_backend_qual_100.py`,
   `test_img_forge_100_acceptance_driver.py`; plus new tests for mapping, graph, routing precedence, settings round-trip.
2. `python tools/ci/run_pr_gate.py` from the isolated worktree (memory: a running app in the main checkout trips collection);
   `python -m pytest tests/tools -q` for PR B (memory: the gate misses the tools census). Real ratchet tools before pushing.
3. `git diff --check`.

## Stop conditions

- Supporting SDXL on ComfyUI needs a custom node, a second ComfyUI, or a change to queue/runtime ownership → stop.
- Making the toggle work requires per-job runtime switching semantics beyond the existing `prepare_for` lease → stop for owner.
- Controller ceiling would rise → find a service home or stop.

## Completion report

`AGENTS.md` §8 categories; physical comparison and owner review listed as held. `Model / usage` line. Feature-branch commits; push/PR
only with owner authorization.
