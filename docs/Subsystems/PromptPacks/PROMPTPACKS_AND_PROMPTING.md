# PromptPacks and prompting

Status: living document, edit in place
Owner area: PromptPack storage and compile (`src/promptpacks/`, `src/pipeline/prompt_pack_parser.py`, `src/pipeline/prompt_pack_job_builder.py`, `src/pipeline/resolution_layer.py`, `src/pipeline/compile_evidence.py`), randomization (`src/randomizer/`, `src/pipeline/config_variant_plan_v2.py`), prompt compatibility and adaptation (`src/prompting/`), global prompt user state, and the Prompt tab

How to keep this true:
- Change this file in the same PR that changes PromptPack format, compile behavior, Matrix or randomization semantics, prompt adaptation, global prompt storage or the Prompt tab projection. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.
- Image stages, model profiles, backends and the adaptation engine's rules are owned by `docs/Subsystems/Image/IMAGE_PIPELINE.md`. This file links there instead of repeating them.

## 1. Scope and the canonical path

A PromptPack is the primary authored intent surface for still-image work: one JSON file holding prompt rows ("slots"), an optional Matrix, and a saved pipeline configuration. This document covers how that file is stored, how it is compiled into immutable NJRs, how Matrix and randomization multiply jobs, how prompts are adapted to a target model, and how the Prompt tab edits and projects it. Other intent surfaces (Pipeline-tab state, Review/reprocess, CLI, Learning) also end in NJRs and are out of scope except where they share code.

The path is the repository-wide one (authority: `AGENTS.md`, `docs/ARCHITECTURE_v2.6.md` section 7). For PromptPack work:

| Step | PromptPack reality | Where |
|---|---|---|
| Intent | `PackJobEntry` (pack id, row index, stage flags, config snapshot, Matrix values) in the Job Draft, produced by the Prompt/Pipeline tabs | `src/contracts/models.py` (`PackJobEntry`, `JobDraft`), `src/gui/app_state_v2.py` |
| Compiler | `PromptPackNormalizedJobBuilder.build_jobs`, built by `get_prompt_pack_builder` with the Klein LoRA selection policy and review bridge enabled | `src/pipeline/prompt_pack_job_builder.py`, `src/controller/prompt_pack_preflight.py`, `src/controller/pipeline_controller.py` (`_build_njrs_from_pack_bundle`) |
| NJR | `NormalizedJobRecord` with `SourceKind.PROMPT_PACK`, effective prompt strings, frozen global-prompt policy, frozen adaptation and conditioning evidence | `src/pipeline/njr_core_v26.py`, re-exported by `src/pipeline/job_models_v2.py` |
| JobService, Queue/Repository, Runner, Handler | Unchanged and not PromptPack-specific | `IMAGE_PIPELINE.md` section 1 |

Preview and submission use the same records: the Preview panel's NJRs (`PipelineController.get_preview_jobs_for_request`) are what `submit_preview_jobs_to_queue` submits [V]. There is no second compile at queue time and none at run time. Replay copies the persisted NJR and never reopens the pack or re-adapts [A: `PR-PROMPT-140`].

## 2. The PromptPack document

### 2.1 Format and versioning

JSON is the only runtime format. `src/promptpacks/storage.py` owns it; `CURRENT_PROMPTPACK_SCHEMA_VERSION` is `1`.

```text
{ "schema_version": 1,
  "pack_data":   { "name", "show_preview",
                   "slots":  [ { "index", "text", "negative", "template_id", "template_variables",
                                 "positive_embeddings", "negative_embeddings",
                                 "loras": [[name, weight], ...],
                                 "controlnet_openpose": {openpose.v1 declaration} } ],
                   "matrix": { "enabled", "mode", "limit", "slots": [ {"name", "values": [...]} ] } },
  "preset_data": { saved pipeline configuration: pipeline / txt2img / img2img / adetailer / upscale / ... } }
```

- `validate_prompt_pack_document` requires an object `pack_data` with a list-of-objects `slots`, an object `preset_data`, and `schema_version == 1`. A different version is refused (`PromptPackFormatError`); there is no migration chain, so a version 2 needs a real upgrade path in `load_prompt_pack_document` first [V].
- Unversioned JSON is an upgrade input only (`allow_unversioned=True`). It is accepted by `PromptPackModel.load_from_file`, `prompt_pack_rows` and `migrate_legacy_pairs`, and rejected by `discover_native_prompt_packs` and by the compiler's loaders [V].
- `save_prompt_pack_document` stamps the current version, validates, then writes through a same-directory temp file, `fsync` and `os.replace`. Output is `sort_keys` JSON, so saves are deterministic.
- `embeddings` serialize as a bare name when the weight is 1.0 and `[name, weight]` otherwise (`serialize_embedding_entries`).
- A slot may carry unknown keys; `PromptPackModel.save_to_file` preserves them by persisted slot index and always set-or-removes `controlnet_openpose` explicitly so clone/reorder cannot move a declaration to another slot [V].
- Prompt text may come from a template (`template_id` + `template_variables`, `src/utils/prompt_templates.py`, catalog `data/prompt_templates.json`, with a built-in fallback payload); `compose_prompt_text` renders `text` through it. Storage and compile both use that one function (`_slot_prompt_text`).

### 2.2 Storage location

`resolve_prompt_pack_dir` (`src/promptpacks/paths.py`) is a pure function: explicit argument, then `STABLENEW_PROMPTPACK_DIR`, then `%LOCALAPPDATA%\StableNew\PromptPacks` (Windows) or `$XDG_DATA_HOME/StableNew/PromptPacks` / `~/.local/share/StableNew/PromptPacks`. It never consults a repository-relative `packs/` directory. `ConfigManager.packs_dir`, the Prompt tab, the sidebar adapter, the Learning experiment panel and the operator readiness service all call it. A pack id is a file stem under that directory; an absolute path id is also honored (`PromptPackNormalizedJobBuilder._resolve_pack_json_path`) [V].

`discover_native_prompt_packs` creates the directory (`mkdir`) and silently skips any file that fails validation [V].

### 2.3 Interchange and migration

TXT and TSV are lossy, flattened interchange, used only by explicit actions:

- `import_prompt_pack` (TXT/TSV -> native JSON, one slot per row, Matrix disabled) and `export_prompt_pack` (native JSON -> TXT/TSV). Exporting a pack with OpenPose declarations logs that the conditioning is dropped (`slots_with_conditioning`).
- `parse_prompt_pack_text` (`src/pipeline/prompt_pack_parser.py`) is the TXT parser and owns the `PackRow` dataclass that the compiler also consumes. Blank lines separate rows, `neg:` lines are negatives, a line of only embeddings or only `<lora:name:w>` tags is structural, and the first remaining line is the "quality line".
- `migrate_legacy_pairs` plus `tools/migrate_prompt_packs.py`: dry-run by default; `--apply` requires `--backup-dir` and only upgrades the version or merges text rows into an empty JSON. A JSON/TXT disagreement is reported as `CONFLICT` and never overwritten.

## 3. Compiling a pack into NJRs

### 3.1 Order of work in `build_jobs`

1. Deep-copy the entries; start the selection review if the review bridge has one.
2. Create one `CompileEvidence` for the whole build (`src/pipeline/compile_evidence.py`): a lazy `AssetRegistry` read of the persisted snapshot only (no refresh, scan or hash), one `ModelPolicy` per distinct model name, one LoRA lookup per distinct name.
3. For each entry, `_expand_entry_by_matrix` (section 5), then `_prepare_entry` per expansion. An entry with no `pack_id` is skipped with a warning; an entry whose pack config cannot be loaded is skipped with an error log, except pack ids starting `learning_`, which compile from `config_snapshot` [V]. Skipped entries do not fail the build.
4. `_freeze_conditioning`: every slot's OpenPose declaration is verified and frozen before any NJR exists, so one defective slot aborts the build (section 7).
5. When `lora_selection_policy` is on (the production factory), assess LoRAs for the exact Klein target, ask the operator once for the whole batch if any prompt has more than one verified-compatible LoRA, and abort the build on cancel or stale source (`KleinSelectionError`) (section 6.3).
6. `_build_jobs_for_entry` for each prepared prompt: adapt, render, assemble the config payload, call `JobBuilderV2.build_jobs` for the randomization/batch fan-out, then construct each `NormalizedJobRecord` (the PromptPack construction site; audit C2 [A]) and run `validate_zimage_njr` on each.

### 3.2 Configuration precedence

`ConfigManager.resolve_config(pack_overrides=<pack preset_data>, runtime_params=<entry.config_snapshot>)` merges: code defaults, then the pack's `preset_data`, then the entry's config snapshot (the Pipeline tab and the frozen global-prompt policy) [V]. No named preset is applied on this path. The result is cached per (pack file fingerprint, runtime params). The builder keeps two copies: `source_config` (what the operator configured) and the effective config after `apply_model_compile_policy` (and, for exact Z-Image, `normalize_profile_owned_values`). Adaptation evidence and the structured intent read the source copy; the executable payload reads the effective copy (`IMAGE_PIPELINE.md` section 4.2).

The Pipeline-tab "Override pack configs" choice (`AppController.override_pack_config_enabled`, `ConfigMergerV2`) and the stage flags decide which stages run; an editor cannot reproduce that, which is why the editor never claims execution readiness (section 9).

### 3.3 Structure, adapt, render

The prompt is never string-edited. `resolution_layer.py` keeps three steps separate:

| Step | Symbol | Contract |
|---|---|---|
| Structure | `resolve_pack_intent` -> `PackPromptIntent` | Matrix tokens substituted; LoRAs ordered actor, then pack row, then Style Consistency, de-duplicated by lower-cased name (first wins); trigger phrases carry the LoRA names that own them; frozen, serializable (`pack_prompt_intent_to_dict`, contract `pack_prompt_intent/1`) |
| Adapt | `adapt_pack_intent` -> `AdaptedPackIntent` | Maps components into `adapt_structured_prompt` and back by role. No rule lives here. |
| Render | `render_pack_intent` -> `PromptResolution` | Historical string order. Positive: embeddings, triggers, quality, subject, `<lora:>` tokens. Negative: global, pack, embeddings, phrases, safety. An empty positive renders the literal `professional photo, high quality` so a negative can never become the positive. |

`UnifiedPromptResolver.resolve_from_pack` is the structure-then-render wrapper kept for the Learning freeze path (`src/learning/experiment_freeze.py`); it does no target adaptation [V]. Global positive terms for an exact Z-Image target are composed by the compiler (`compose_global_positive`, using `merge_global_positive`) because that executor cannot apply them.

### 3.4 What is frozen into the NJR

- Effective positive/negative strings, embeddings and `LoRATag`s (first-class NJR fields).
- `NJRProvenance.metadata["prompt_adaptation"]`: `{"contract": "prompt_adaptation/1", ...plan.to_diagnostics()}`, content-free (operation codes and counts, no prompt text or asset names).
- With a Klein selection: `klein_lora_selection` (contract `klein_lora_selection/1`) and `source_prompt_intent`, copied into both provenance and executable config metadata; the backend requires them to agree.
- With OpenPose: the frozen `controlnet_openpose` config and `provenance.metadata["conditioning"]` (no image bytes).
- Matrix values, mode and name, randomizer summary, config-variant label, `PackUsageInfo` (pack name, path, row index), `source.revision` (the pack's `preset_data.version`, if any) [V].
- Global prompt policy (section 8).

## 4. Prompt compatibility and adaptation (`src/prompting/`)

The engine, its rules, the module table and the compile-safe semantics (a component is deleted only on a definitive policy fact or definitive `incompatible` LoRA evidence; unverified or conflicting evidence preserves it; the backend stays final) are documented in `IMAGE_PIPELINE.md` section 4.4. Not repeated here. What is PromptPack-specific:

- The compiler consumes the engine through `adapt_pack_intent`; the Prompt tab and `assess_pack_readiness` consume the same `adapt_prompt_for_target`, so preview and execution share rules. The tab's LoRA read is stricter than compile: it omits unverified LoRAs from the projection, while compile keeps them (`PR-PROMPT-140`) [A].
- Trigger ownership: actor and Style LoRAs own their trigger phrases and drop them together. PromptPack-row LoRAs have no trigger metadata, so no prose is ever guessed or substring-deleted (operation `pack_lora_trigger_not_tracked`). Hand-typed inline `<lora:...>` tokens are left as written and remain subject to backend validation.
- Non-prompt features (ADetailer, hires, refiner, upscale, ControlNet, stage chain, geometry) are never adapted; they stay with `ModelPolicy`, the exact profile and the backend.
- `ADAPTATION_RULESET_VERSION` (`src/prompting/prompt_adaptation.py`) is recorded in the manifest; changing the engine never alters a queued NJR.
- The prompt optimizer modules in `src/prompting/` (`prompt_optimizer_*`, `sdxl_prompt_optimizer.py`, `stage_policy_engine.py`) are executor-side and are refused under exact profiles; see `IMAGE_PIPELINE.md`. `src/prompting/contracts.py` holds shared analysis dataclasses.

## 5. Matrix, randomization and job multiplicity

Final job count for one pack row, as built today:

`matrix expansions` x `randomization variants` x `batch_runs` (`pipeline.loop_count`), each job producing `images_per_prompt` images [V: `_expand_entry_by_matrix`, `_build_randomizer_plan`, `_build_batch_settings`, `JobBuilderV2.build_jobs`].

### 5.1 Matrix (prompt-level)

- Authored in `pack_data.matrix` (`MatrixConfig`: `enabled`, `mode`, `limit`, slots of `{name, values}`). A prompt uses `[[slot_name]]`; slot names resolve exactly, then by normalized alias (`normalize_matrix_slot_name` lower-cases and strips non-alphanumerics, so `hair-color`, `hair_color` and `Hair Color` match) (`src/utils/prompt_pack_utils.py`).
- Expansion happens in the builder before NJR construction, one `PackJobEntry` per combination (`matrix_slot_values`). A disabled Matrix, or one with no slot that has both a name and values, expands to the entry unchanged (`get_matrix_slots_dict`).
- Modes: the builder treats `"random"` specially and everything else (`fanout`, `sequential`, or a missing key, which the builder defaults to `sequential`) as the first N of the Cartesian product (`itertools.product`, last slot varies fastest). `fanout` and `sequential` therefore behave identically at compile time [V]. The Matrix panel offers `fanout`, `sequential` and `random` (`src/gui/widgets/matrix_tab_panel.py`).
- Limit: `matrix.limit` if positive; otherwise the randomizer `max_variants` hint; otherwise 8 (`_DEFAULT_MATRIX_EXPANSION_LIMIT`), with a warning when that silently truncates a larger product.
- `random` mode samples with the unseeded global `random.sample` and sorts the sampled indexes, so every compile of the same pack yields a different set [V]. Preview and a later rebuild can disagree; the NJR submitted is whichever build was submitted.
- Unresolved `[[token]]` text (no matching slot) is left in the prompt. I found no check in the PromptPack compile path that rejects it, although `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md` section 5.3 says it must be [V]. The pack-editor validator warns about Matrix structure only (`validate_pack_structure`).

### 5.2 Config-level randomization

- `RandomizationPlanV2` and `generate_run_config_variants` (`src/randomizer/randomizer_engine_v2.py`) enumerate override combinations (model, vae, sampler, scheduler, cfg, steps, batch size), shuffle with `random.Random(rng_seed)`, cap at `max_variants`, and apply `RandomizationSeedMode` (`none`, `fixed`, `per_variant`). `JobBuilderV2` passes `rng_seed=None` from every production caller [V], so when a plan has more combinations than `max_variants` the surviving subset is not reproducible. The engine's determinism guarantee holds only when a caller supplies a seed.
- The PromptPack builder builds a plan with every choice list empty (`_build_randomizer_plan`), reading top-level `randomization_enabled`, `max_variants` and `seed` of the merged config. That yields one combination, so for packs "randomization" only affects the seed mode; real fan-out for packs comes from Matrix and `loop_count` [V].
- Config sweeps (`ConfigVariantPlanV2`, `ConfigVariant`, dot-path overrides such as `txt2img.cfg_scale`) are accepted by `JobBuilderV2.build_jobs` and recorded in provenance (`config_variant_label`, `config_variant_index`, `config_variant_overrides`). The only producer is `PipelineController._build_normalized_jobs_from_state` from `app_state.config_sweep_enabled`/`config_sweep_variants`; `PromptPackNormalizedJobBuilder` never passes a plan, so sweeps do not apply to PromptPack jobs [V]. That path also drops any exception (`JobBuilderV2 failed to build jobs`) into an empty preview.
- `src/utils/randomizer.py` (`PromptRandomizer`, wildcard and S/R rules) and `src/pipeline/randomizer_v2.py` are reached from the GUI randomizer adapter, not from `PromptPackNormalizedJobBuilder` [V]. The spec's wildcard and S/R claims describe that older layer, not the PromptPack compile path.

## 6. Reference evidence: saved settings, missing assets, LoRA selection

### 6.1 Saved-settings quality

`tools/promptpack_quality_census.py` is an offline, read-only census of PromptPacks and saved presets, run against raw JSON before any default-merge hides a problem. It reports alias contradictions (`model`/`model_name`/`sd_model`, `pipeline.<stage>_enabled` vs `<stage>.enabled`, hires flags, and so on, reusing `src/pipeline/config_normalizer.py`), asset-reference resolution against `AssetRegistry` (`resolved_unique`, `ambiguous_same_name`, `missing_file_backed_asset`, `offline_unverified`) and family compatibility against the selected checkpoint. It writes only to the paths given with `--out`, `--summary-out` and an audit-owned `--asset-cache`. Tests: `tests/tools/test_promptpack_quality_census.py`.

The one repair that came from it is persistence-level: `synchronize_adetailer_enablement` (`src/utils/config.py`) makes `pipeline.adetailer_enabled` (precedence), `adetailer.enabled` and `adetailer.adetailer_enabled` agree whenever a pack config is saved (`ConfigManager.save_pack_config`). Runtime stage admission already ORs the representations.

### 6.2 Missing-asset reference triage

`tools/missing_asset_reference_triage.py` (`scan`, with `validate_decision` / `validate_batch`) maps each aggregated `missing_file_backed_asset` finding to the exact raw JSON occurrences, attaches same-kind candidates from `AssetRegistry`, and emits a decisions template whose every item defaults to `leave_unresolved` (other actions: `replace_reference`, `remove_reference`, `clear_optional_reference`). It never writes to a pack or preset. Tests: `tests/tools/test_missing_asset_reference_triage.py`.

Reconciliation was executed once, under explicit owner approval, with a temporary utility that was deliberately not kept. No code path in the repository writes reconciled values into pack sources. Any future bulk repair of real packs is a new, separately authorized, backed-up and reversible operation, not a reuse of this tool. The one-time outcome (checkpoint names recorded as LoRAs removed, literal `"None"` refiner placeholders cleared, an unidentified LoRA left untouched) is in `PR-PACK-130`.

### 6.3 Klein LoRA selection (exact Klein target only)

`src/prompting/pack_lora_selection.py` (contract `klein_lora_selection/1`) applies only when the target policy has an explicit one-LoRA Klein-4B compatibility rule (`applies`). Zero verified-compatible LoRAs: none selected. One: selected at its authored weight. Two or more: one batch operator review before any NJR exists (`SelectionReviewBridge` in `src/controller/prompt_pack_preflight.py`, dialog `src/gui/klein_lora_selection_dialog.py`). Evidence preparation (`prepare_selection_evidence` in `src/prompting/pack_lora_evidence.py`, via `CompileEvidence.prepare_lora_selection`) refreshes only the LoRA roots, off the Tk thread, and refuses the build when roots are unavailable or metadata is unreadable. Uncertainty is `unverified`, never `incompatible`. The backend's refreshing admission and served-file SHA check stay final. Learning keeps its own gate and does not enter this policy.

## 7. OpenPose slot declaration

A slot may carry `controlnet_openpose`, the `openpose.v1` declaration defined only in `src/conditioning/openpose.py` (`SLOT_FIELD`, `parse_declaration`, `declaration_problems`, `declaration_enabled`). It is structural conditioning input, never prompt text, and names a library image by relative identity, never bytes. In this subsystem:

- `prompt_pack_rows` copies the raw declaration into `PackRow.conditioning` with its slot, so Matrix variants and row selection keep it; TXT/TSV have no field for it.
- `PromptPackModel` / `PromptSlot.openpose` keep the value verbatim (a malformed value is preserved and reported, never dropped).
- The builder calls `OpenPoseCompiler` once per build session (`_freeze_conditioning`), which owns target gating, image verification and the job-owned snapshot. Target rules, dispatch and wire behavior are in `IMAGE_PIPELINE.md` section 3.1.
- The editor reports declaration problems and target blocks in Validate (`validate_pack_structure`, `assess_pack_readiness`).

## 8. Global prompt user state

Saved Global Positive and Global Negative text is per-user state, not repository content. Text lives in `<GlobalPrompts>/global_positive.txt` and `global_negative.txt`; the enabled flags stay in `presets/settings.json` through `ConfigManager`. `resolve_global_prompt_dir` (`src/prompting/global_prompt_paths.py`, pure) resolves: explicit argument, `STABLENEW_GLOBAL_PROMPT_DIR`, then `%LOCALAPPDATA%\StableNew\GlobalPrompts` or the XDG equivalent. `ConfigManager` (`get_/save_global_positive_prompt`, `..._negative_prompt`, `save_global_*_state`) is the only persistence API; the directory is created on first write. Code defaults: `DEFAULT_GLOBAL_POSITIVE_PROMPT` (empty) and `DEFAULT_GLOBAL_NEGATIVE_PROMPT` in `src/utils/config.py`.

Freezing: the controller reads the editable policy at compile time (`overlay_current_policy` in `src/controller/global_prompt_policy_service.py`, reading the sidebar, falling back to saved values) and writes it into each entry's config through `apply_global_prompt_policy` (`src/pipeline/global_prompt_policy.py`): `global_positive_prompt`, `global_negative_prompt`, the stage `apply_global_*` flags and `global_prompt_policy_source = "frozen_njr"`. Execution consumes the frozen values (`has_frozen_global_prompt_policy`); the executor falls back to the stored files only for NJRs without a complete frozen policy, labeled `legacy_runtime_fallback` (`Pipeline._global_prompt_terms`) [V]. The pack builder also marks a config `legacy_runtime_fallback` when it lacks the frozen policy. The global negative is a structured intent component (`PackPromptIntent.global_negative`) so adaptation can omit it with the rest of an unsupported negative channel.

## 9. The PromptPack editor and Prompt tab

- Tab: `PromptTabFrame` in `src/gui/views/prompt_tab_frame_v2.py`, built by `src/gui/panels_v2/layout_manager_v2.py` and `src/gui/main_window_v2.py`. State: `PromptWorkspaceState` (`src/gui/prompt_workspace_state.py`: current pack, dirty flag, current slot). Model: `PromptPackModel`, `PromptSlot`, `MatrixConfig`, `MatrixSlot` (`src/gui/models/prompt_pack_model.py`), which persist only through `save_prompt_pack_document` and drop empty padding slots on save (default 10 slots on a new pack).
- Pack list and add-to-draft: `PromptPackAdapterV2` and `PromptPackListManager` feed the sidebar; selected packs enter the Job Draft as `PackJobEntry` (`PipelineController`/`AppController`).
- Projection, not authority. The Base Generation model-policy projection reaches the tab through `on_model_projection`; `project_prompt_target` (`src/prompting/prompt_compatibility.py`) produces advisories and `PromptTargetPresenter` (`src/gui/prompt_target_presenter.py`) applies them as labels and control availability only. Disabling the optimizer or embedding controls for a model leaves stored values untouched. The explicit "Adapt" preview (`PromptAdaptationDialog`, `src/gui_v2/prompt_adaptation_preview.py`) is read-only and never dirties or saves the pack.
- Validate reports structure and target readiness as two separate answers from the in-memory pack (`PromptWorkspaceState.pack_for_validation`, `assess_pack_readiness`, `validate_pack_structure` in `src/prompting/pack_target_readiness.py`). It is pure and states its own limit: execution readiness is only confirmed by Preview, because the compiler also applies Pipeline-tab stages, Override-pack-configs and saved settings. Do not rebuild that configuration inside the editor; that would be a second compile authority.
- Hidden-content mode redacts prompt text and asset names in the tab and in the Klein review dialog (`ContentVisibilityResolver`).
- The Prompt tab never calls a backend, the queue or a runner.

## 10. Out-of-box state (audit G5)

A fresh install has zero PromptPacks, because the resolver never reads the repository `packs/` directory [V]. Status of the audit's evidence [V unless marked]:

- `packs/` tracks 68 files, all legacy `.txt` or `.json.bak` except `packs/README.md`, which still describes stage-aligned presets and is stale. None is reachable by the application.
- `presets/` tracks preset JSON plus runtime-looking state (`presets/settings.json`, `presets/last_settings.json`, `presets/.default_preset`); `ConfigManager.presets_dir` defaults to the working-directory-relative `presets`. The tracked-state rule is `docs/runbooks/TRACKED_RUNTIME_STATE_HYGIENE_v2.6.md`.
- `src/config/app_config.py` defines `STABLENEW_WEBUI_ROOT = "C:\\Users\\rob\\stable-diffusion-webui"`, a machine-specific default; other readers use the `STABLENEW_WEBUI_ROOT` environment variable.
- `README.md` still reads "Project state: MVP recovery"; there is no user guide.
- Planned fix: roadmap package P5-6 (starter packs seeded when the directory is empty, presets moved to user data, one asset-root resolver) [A]. Until it lands, seed packs by writing versioned JSON through `save_prompt_pack_document` or by `import_prompt_pack` from a TXT file; do not point code at the repository `packs/` directory.

## 11. Invariants that must not be broken

1. Canonical path only. The Prompt tab and controllers capture intent and render projections; they never build backend payloads, call a runner, or compile a second way. Preview records are the submitted records.
2. A PromptPack is authored once and is never mutated or copied by compile. Adaptation changes the NJR, never the pack. The NJR is immutable; replay never re-adapts, re-expands Matrix or reopens the pack.
3. JSON is the only runtime format. Every write goes through `save_prompt_pack_document` (atomic, versioned). TXT/TSV only through explicit import/export/migration.
4. Prompt content is structured until the last step: structure, adapt, render. No string surgery on prose, no guessing trigger ownership, no deletion on unverified evidence.
5. All evidence and operator decisions finish before the first NJR exists; cancel or a stale source admits nothing.
6. Compile-time evidence reads the persisted registry snapshot only (no scan or network), except the explicit background Klein selection preparation. The editor and presenters never scan, hash or write.
7. Frozen manifests are content-free: no prompt text, asset names or image bytes.
8. The editor's view of a model is advisory; the compiler and the backend are final.
9. Matrix and randomization happen at compile time only, never at run time.
10. Tests must not contact a WebUI, model or GPU. Tools in `tools/` that touch real packs are read-only unless a separately authorized, backed-up operation says otherwise.

## 12. How to test

Run focused tests first; the required gate is `python tools/ci/run_pr_gate.py`.

| Area | Tests | Hermetic seam |
|---|---|---|
| Storage, migration, user paths, OpenPose slot | `tests/promptpacks/` | `tmp_path` pack dirs; `resolve_prompt_pack_dir(environ=..., system_name=..., home_dir=...)` |
| Parser and TXT rows | `tests/pipeline/test_prompt_pack_parser.py` | Strings |
| Builder, intent, adaptation, NJR invariants, Klein selection, OpenPose compile, global policy | `tests/pipeline/test_prompt_pack_job_builder.py`, `test_pack_prompt_intent_140.py`, `test_prompt_pack_adaptation_140.py`, `test_klein_pack_selection_143.py`, `test_openpose_compile_210.py`, `test_global_prompt_policy.py`, `test_njr_prompt_pack_invariants.py` | Inject `model_family_lookup` and `lora_resolver` into `PromptPackNormalizedJobBuilder` (no registry); `tests/helpers/njr_factory.py` |
| Adaptation engine and compatibility | `tests/image_backends/test_prompt_adaptation_130c.py`, `test_prompt_adaptation_140.py`, `test_prompt_compatibility_130b.py`, `test_operation_compatibility_158.py` | Pure policies |
| Randomizer engine and prompt randomizer | `tests/randomizer/`, `tests/utils/test_prompt_randomizer.py`, `test_randomizer_matrix_prompt_modes.py` | Seeded RNG |
| Global prompt state and config | `tests/utils/test_global_prompt_paths.py`, `test_config_manager_global_prompts.py`, `tests/controller/test_global_prompt_flags.py` | Temp dirs |
| Preview and submission wiring | `tests/controller/test_pack_draft_to_normalized_preview_v2.py`, `test_pack_selection_preflight_143.py`, `test_prompt_pack_preview_v2.py` | Stub controllers |
| Prompt tab and editor | `tests/gui_v2/test_pack_editor_readiness_158.py`, `test_prompt_target_130b.py`, `test_pack_lora_dialog_143.py`, `test_prompt_tab_openpose_210.py`, `test_prompt_pack_model_matrix.py` | Isolated `tk_root` fixture; hidden-identity cases |
| Census and triage tools | `tests/tools/test_promptpack_quality_census.py`, `test_missing_asset_reference_triage.py` | Synthetic pack/preset trees |

For a new refusal, assert the error and that no NJR was produced. For adaptation, assert the manifest codes, not prompt text.

## 13. Known debt and traps

- Single compile core missing [A]: `NormalizedJobRecord(` is built at eight sites with different policy subsets (audit C2, plan P4-2). Anything added to PromptPack compile must be checked against `JobBuilderV2`, `ReprocessJobBuilder`, `cli_njr_builder.py` and `src/learning/model_comparison.py`. The audit also notes the pack builder builds jobs twice; in the current code each prepared prompt is built once (`build_jobs` passes `prepared=`), but `JobBuilderV2` still runs `apply_model_compile_policy` again on the pack-supplied payload [V].
- Builder size [V]: `src/pipeline/prompt_pack_job_builder.py` is 1.3k lines; family names (Klein, Z-Image) are branched inside it (audit C1, 25 mentions [A]). Add model-specific rules in `src/image_backends/`.
- Silent skips [V]: a missing pack file, an unloadable `preset_data`, or an entry without `pack_id` is logged and skipped; `get_preview_jobs_for_request` converts any builder exception into an empty list (and may fall back to the generic state builder, which stamps `SourceKind.CLI`, audit C2 [A]). An empty Preview can mean a failed compile; read the log.
- Row index [V]: `_selected_pack_row` indexes the list returned by `prompt_pack_rows` (empty slots dropped) and clamps an out-of-range index to the last row without warning. GUI saves drop empty slots, so persisted `index` equals list position there; a hand-edited pack with an empty slot does not. `prompt_pack_row_by_index` uses the persisted index and is not the compiler's lookup.
- Matrix: `random` mode is non-reproducible; `fanout` equals `sequential`; unresolved `[[token]]` is not rejected (section 5.1). Three separate `MATRIX_TOKEN_RE` patterns exist (`prompt_pack_parser.py` is narrow and unused for substitution; `resolution_layer.py` and `src/utils/randomizer.py` allow hyphen and space) [V].
- Randomization: unseeded variant shuffle, empty choice lists for packs, no config sweep for packs (section 5.2). The Randomizer spec (`Randomizer_Spec_v2.6.md`) states determinism and token rejection guarantees the PromptPack path does not meet; trust the code.
- Non-atomic config writes [V]: `ConfigManager.save_pack_config`, `save_preset` and `save_pack_overrides` write with plain `open(..., "w")` + `json.dump`, not the atomic helper. `save_pack_config` preserves an existing versioned document but, for a missing file or one without `pack_data`, writes a document with no `schema_version`, which discovery skips and the compiler's loader refuses. The audit's remark that `promptpacks/storage.py` writes safely is true for that module only. It is applied from the Pipeline tab ("apply config to selected packs", "apply saved recipe to packs") in `AppController`.
- Layering [A/V]: `src/promptpacks/storage.py` imports `src.pipeline.prompt_pack_parser` and `src.utils.prompt_templates`; `src/utils/prompt_pack_utils.py` imports `src.promptpacks`; `src/controller/prompt_pack_preflight.py` imports a GUI dialog inside a function (audit C1/C6).
- Dead or unreferenced [V: no importers in `src` or `tests`]: `src/gui/views/prompt_tab_frame.py` (the older Prompt tab) and `src/gui/prompt_pack_panel_v2.py`. The live tab is `prompt_tab_frame_v2.py`. `src/pipeline/randomizer_v2.py` and `src/pipeline/variant_planner.py` serve the GUI randomizer adapter, not the pack compile.
- Stale text [V]: `packs/README.md` (describes presets), the README "MVP recovery" line, and `src/pipeline/prompt_pack_parser.py` has no module docstring.
- Learning compiles through `resolve_pack_intent` / `resolve_from_pack` and its own gate; changing `PackPromptIntent` or render order changes Learning's frozen prompts (a 1,088-case equivalence grid exists for the wrapper [A]).

## 14. Adding or changing PromptPack behavior today

- New slot or pack field: add it to `PromptSlot`/`PromptPackModel.load_from_file` and `save_to_file` (preserve unknown keys), `prompt_pack_rows` and `PackRow` if the compiler needs it, `_rows_to_slots`/`_render_*` for interchange (state in a docstring that it is lossy), and the Prompt tab. Do not bump `CURRENT_PROMPTPACK_SCHEMA_VERSION` for an additive optional field; if a bump is unavoidable, add the upgrade path in `load_prompt_pack_document` and `migrate_legacy_pairs` first.
- New compile-time behavior: add it as a step inside `PromptPackNormalizedJobBuilder` that finishes before NJR construction and freezes content-free evidence into `NJRProvenance.metadata`. Preserve source-versus-effective config separation. Keep `PackPromptIntent` order and render order unless Learning is updated with it.
- New adaptation rule: change `src/prompting/prompt_adaptation.py` (policy-driven, no model-name conditionals), bump `ADAPTATION_RULESET_VERSION`, update `IMAGE_PIPELINE.md` section 4.4, and extend the 130C/140 tests.
- New Matrix or randomization semantics: change `_expand_entry_by_matrix` and the Matrix panel together, keep `MatrixConfig.mode` values in step, and decide seeding explicitly (add a seed to provenance if you make `random` reproducible).
- New Prompt-tab availability or advisory: derive it from `ModelPolicy` through `project_prompt_target`; the presenter applies, it does not decide.
- Fixing the out-of-box state: seed through `save_prompt_pack_document` into `resolve_prompt_pack_dir()`; keep tests on temp dirs.
- Always update this file, `STATUS.md` if a supported capability changes, and add tests from section 12.

## 15. Evidence records

Per-PR records stay in their folders as historical evidence. They may describe superseded behavior; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/PromptPacks/PR-PROMPT-140_Model_Adaptive_PromptPack_Compilation.md` | Structure, adapt, render; compile-safe semantics; the frozen adaptation manifest |
| `docs/Subsystems/PromptPacks/PR-PROMPT-143_Klein_Compatible_LoRA_Selection.md` | Klein LoRA selection contract, batch review, frozen selection evidence |
| `docs/Subsystems/PromptPacks/WP-PACK-AUDIT-100_PromptPack_Saved_Settings_Quality_Census.md` | Census method, alias groups, finding classes |
| `docs/Subsystems/PromptPacks/PR-PACK-110_ADetailer_Stage_Enablement_Persistence_Repair.md` | ADetailer enablement synchronization at the persistence boundary |
| `docs/Subsystems/PromptPacks/PR-PACK-120_Missing_Asset_Reference_Triage.md` | Read-only triage tool and decision vocabulary |
| `docs/Subsystems/PromptPacks/PR-PACK-130_Approved_Missing_Reference_Reconciliation.md` | The one-time owner-approved reconciliation and why no write tool remains |
| `docs/Subsystems/Prompting/PR-DEVEX-PROMPTS-170_Global_Prompt_User_State.md` | Global prompt storage precedence and semantics |
| `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md` | Intended randomizer contract (partly aspirational for packs, see section 5) |
| `docs/Subsystems/Image/PR-IMG-130C_Explicit_Model_Aware_Prompt_Adaptation.md` | The adaptation engine's original rules |
| `docs/Subsystems/Image/PR-IMG-130B_Model_Aware_Prompt_Compatibility_UX.md` | Prompt-tab target projection and presenter |
| `docs/Subsystems/Image/PR-IMG-MODELS-158_Cross_Workflow_Model_Compatibility.md` | Editor readiness versus operation compatibility |
| `docs/Subsystems/Image/PR-IMG-CNET-210_SDXL_OpenPose_ControlNet.md` | OpenPose declaration, compile and dispatch end to end |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit C1, C2, C6, G5 and the P4-2 and P5-6 plans referenced above |
