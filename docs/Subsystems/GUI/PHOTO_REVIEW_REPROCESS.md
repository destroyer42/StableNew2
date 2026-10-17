# Review, reprocess, batch operations and Photo Optimize

Status: living document, edit in place
Owner area: the Review tab, reprocess compilation (`src/pipeline/reprocess_builder.py`), whole-selection Review preflight, the Queue-side batch operations view, Photo Optimize (`src/photo_optimize/`), image metadata read back into Review, and the GUI-ownership rules for these surfaces

How to keep this true:
- Change this file in the same PR that changes Review, reprocess, batch operations or Photo Optimize behavior, ownership or a safety rule. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.
- Companion: `docs/Subsystems/Image/IMAGE_PIPELINE.md` owns backends, stages, exact profiles and `operation_compatibility`. This file only says how Review/Photo reach them.

## 1. Scope and the canonical path

Covered: Review tab (`ReviewTabFrame`), the reprocess panel and masked image edit paths, `ReprocessJobBuilder`, Review whole-selection preflight, the Batches view over the repository, Photo Optimize, embedded metadata used as a reprocess baseline, thumbnails and compare. Out of scope: Learning ratings beyond the Review feedback hand-off, the Video Workflow tab, PromptPack compile.

None of these surfaces has its own execution path. All of them produce immutable NJRs and cross the one admission boundary:

| Step | Reality here | Where |
|---|---|---|
| Intent | Review selection plus prompt/stage deltas; Reprocess panel; masked edit; Photo Optimize plan; Learning curation hand-off; failed-job retry | `src/gui/views/review_tab_frame_v2.py`, `src/gui/views/photo_optimize_tab_frame_v2.py`, `src/gui/batch_operations_panel_v2.py` |
| Compiler | `ReprocessJobBuilder` for every image reprocess. Retry uses `compile_replay_intent` (replay, not reprocess) | `src/pipeline/reprocess_builder.py`, `src/pipeline/replay_njr_compiler.py` |
| NJR | `NormalizedJobRecord` with `ImageWorkloadSpec`, `start_stage` = first requested stage, `input_image_paths`, `SourceKind.REPROCESS` (or `IMAGE_EDIT`, `LEARNING`, `HISTORY_REPLAY`, `VIDEO_WORKFLOW` by `source` alias) | `src/pipeline/job_models_v2.py` |
| Preflight | `assess_njr` (pure) per source at preview, `require_njr_operation` again at admission | `src/image_backends/operation_compatibility.py` |
| JobService | `submit_reprocess_njrs` assesses the whole list, then calls `JobService.submit_njrs` exactly once | `src/controller/reprocess_admission.py` |
| Queue/Repository, Runner, Handler | Unchanged canonical path; reprocess jobs start at `start_stage` and skip txt2img | see `IMAGE_PIPELINE.md` section 1 |
| Artifacts/History | Output PNG with embedded `stablenew:*` payload; Photo Optimize additionally copies outputs into its own workspace on completion | section 6 |

Nothing in these surfaces may build a backend payload, call a runner, or add a queue. The Batches view and Review preview read the repository; they never store batch state.

## 2. Reprocess compilation

### 2.1 `ReprocessJobBuilder` (`src/pipeline/reprocess_builder.py`)

| Piece | Role |
|---|---|
| `ReprocessSourceItem` | One source: path, prompt, negative prompt, model, vae, `config`, `metadata`, optional `output_dir`, optional `ImageEditSpec` (mask inpaint) |
| `build_grouped_reprocess_jobs` | The entry point every UI path uses. Merges `fallback_config` with the item config, applies model/VAE, prompt overrides and image-edit overrides, groups items by (prompt, negative, model, config signature, output dir), chunks each group by `batch_size`, then calls `build_reprocess_job` per chunk. Returns `ReprocessJobPlan` |
| `build_reprocess_job` | Builds one NJR for N input images. Validates that every input exists and every stage is in `VALID_REPROCESS_STAGES`. Calls `normalize_image_backend_options` with the resolved model so a Klein transformer keeps its versioned profile |
| `build_effective_settings_preview` | The "what would be queued" projection (`ReprocessEffectiveSettingsPreview`) with a per-value source label: artifact metadata, then current stage baseline, then built-in `DEFAULT_STAGE_VALUES` |
| `apply_model_vae_to_config`, `apply_prompt_overrides`, `apply_image_edit_overrides`, `_merge_nested_dicts` | Static helpers also used by Photo Optimize and by GUI adapters |
| `extract_reprocess_output_paths` | Maps a finished job to its output files (used by the Photo Optimize completion handler) |

`VALID_REPROCESS_STAGES` also lists `animatediff`, `svd_native` and `video_workflow`: this builder is shared with the video paths (`src/controller/svd_controller.py`, `src/video/video_workflow_njr_builder.py`, `src/curation/curation_workflow_builder.py`). The Review path restricts stages to `adetailer`, `upscale`, `img2img` before calling it.

Klein single-reference edit is an explicit request, never inferred: `ReviewWorkflowAdapter.with_klein_edit_request` marks sources with `KLEIN_EDIT_METADATA_KEY`; `is_klein_edit_item` / `prepare_klein_edit_item` in `src/pipeline/klein_edit_reprocess.py` freeze the item to `latest_klein_profile()` (exactly one image, img2img only, empty config and negative prompt, source SHA-256 recorded) and force group size 1.

### 2.2 Who calls it

| Caller | Path |
|---|---|
| Review tab batch | `AppController.preview_review_reprocess_batch` -> `prepare_review_batch` -> dialog -> `submit_review_reprocess_batch_async` -> `submit_reprocess_njrs` |
| Review direct API | `AppController.on_reprocess_images_with_prompt_delta` (prepare + submit in one call) |
| Reprocess panel | `AppController.on_reprocess_images` (no embedded-metadata baseline; uses `_build_reprocess_config`) |
| Masked edit | `AppController.on_submit_image_edits` (`source="image_edit"`, `ImageEditSpec`) |
| Photo Optimize | `prepare_photo_plan` in `src/photo_optimize/submission.py` |
| Learning curation | `LearningController` calls `submit_reprocess_njrs` directly |

Every image reprocess NJR goes through `submit_reprocess_njrs`; do not add a path that calls `JobService.submit_njrs` with reprocess NJRs without it.

### 2.3 Compile-policy gap [V]

`ReprocessJobBuilder` does not call `apply_model_compile_policy` (grep: it is used in `job_builder_v2`, `cli_njr_builder`, `src/learning/model_comparison.py` and `src/learning/model_policy_service.py`, not here). `IMAGE_PIPELINE.md` section 1 describes the compiler step generically; for reprocess the protection is the combination of (a) `normalize_image_backend_options(model_name=...)` stamping the profile, (b) the Klein prepare step, (c) `assess_njr` / `require_njr_operation` refusing unsupported operations (Z-Image is txt2img only, so any reprocess of it is refused) and (d) backend validation. Profile-owned value normalization (`normalize_profile_owned_values`) is not applied to reprocess configs. Photo Optimize compensates after compile: `prepare_photo_plan` raises if the compiled `job.config` differs from the frozen `config_snapshot`.

## 3. Review tab

### 3.1 Ownership

| Concern | Owner |
|---|---|
| Widgets, event wiring, dialogs | `ReviewTabFrame` (`src/gui/views/review_tab_frame_v2.py`, ~2,000 lines); `ReviewBatchDialog` (`src/gui/review_batch_dialog.py`) |
| Non-render logic: prompt delta (append/replace/modify), effective-settings text, readiness projection, staged-curation hand-off, feedback payload | `ReviewWorkflowAdapter` (`src/gui/controllers/review_workflow_adapter.py`, Tk-free) |
| Whole-selection compile and preflight | `prepare_review_batch` and `ReviewBatchPreview` (`src/controller/review_batch_service.py`) |
| Threading of preview and admission | `BackgroundTaskCoordinator` (`src/controller/app_controller_services/background_task_coordinator.py`), keys `review:batch` and `review:admit:<batch_id>`, latest-wins |
| Metadata baseline extraction | `AppController._extract_reprocess_baseline_from_image` using `src/utils/image_metadata.py` |
| Prior-review summary, feedback save/undo | `LearningController` (`save_review_feedback`, `undo_review_feedback`, `get_prior_review_summary`), reached through `app_controller.main_window.learning_tab` |
| ADetailer before/after pair | `resolve_adetailer_pair` (`src/review/adetailer_outcome.py`) |
| Metadata inspector | `ArtifactMetadataInspector` (`src/review/artifact_metadata_inspector.py`), `ArtifactMetadataInspectorDialog` |
| Content visibility (redaction) | `ContentVisibilityResolver`; every prompt shown in Review/Photo/Batches is passed through it |

### 3.2 Whole-selection preview and admission

`prepare_review_batch` compiles every selected source with `ReprocessJobBuilder` (one job per source unless `batch_size > 1` was explicitly requested), reports every refusal, and queues nothing. Per source it: checks the file, hashes it (`_source_sha256`), loads it with PIL, extracts the baseline, applies prompt deltas, builds a `ReprocessSourceItem` with lineage metadata (`source_job_id`, `source_artifact_id = sha256:<bytes>`, `source_path`, plus `build_review_chunk_lineage_block`), compiles, runs `assess_njr`, then re-checks size/mtime/hash to detect a source that changed during preparation.

The result is a `ReviewBatchPreview` of `ReviewBatchItem` rows and the compiled NJRs. `require_queueable()` raises if any item is blocked, if there are no jobs, or if any source's size, mtime or SHA-256 changed since preview. `ReviewBatchDialog` has no "queue the good ones" path: blocked items disable submit, "Exclude blocked and re-preview" recompiles a smaller set. Confirmation submits the exact previewed NJRs (they are not recompiled). Each admitted job carries `review_batch = {batch_id, source_count, group_by_model}` plus top-level `batch_id` in provenance metadata; `group_by_model` only reorders jobs.

Rules:
1. Preview and admission must run off the Tk thread (they hash files and open images). `submit_review_reprocess_batch_async` does; the synchronous `submit_review_reprocess_batch` exists for the direct API.
2. The exception net in `prepare_review_batch` is `(ValueError, OSError, TypeError)`; `OperationNotSupportedError` and `KleinProfileError` are `ValueError` subclasses, so refusals become blocked rows. A new refusal type must subclass one of these or it aborts the whole preview.
3. Do not stamp or rewrite a source image between preview and confirm (section 5.3).

### 3.3 Thumbnails and compare

- `ThumbnailWidget` (`src/gui/widgets/thumbnail_widget_v2.py`): latest-request-wins, one in-flight decode per path, decode via `load_image_thumbnail` (`src/utils/image_utils.py`) on a thread from `ThreadRegistry.spawn`, result marshalled with `after(0)`. Responsive mode decodes once at the maximum edge and rescales on resize (`src/gui/view_contracts/workspace_density_contract.py`). A failed worker start releases only its own request marker and shows "Preview unavailable".
- There is no decoded-thumbnail cache and no thumbnail grid; the list is a `Listbox` with one preview pane [V].
- Compare view: `ReviewTabFrame._render_compare_viewer` opens both images at full resolution, converts to RGBA and composites on the Tk thread [V].

## 4. Batch operations (Queue-side "Batches" view)

A batch is not a stored entity. It is derived from `provenance.metadata` frozen into each job.

| Piece | Role |
|---|---|
| `src/queue/batch_membership.py` | `BatchKey(kind, batch_id)` (kinds `review`, `video_workflow`, `selected_retry`), descriptor shapes (`review_batch`, `batch` schema `stablenew.batch.v1`), `resolve_batch_membership`; contradictory identifiers are `AMBIGUOUS` and belong to no batch |
| `src/queue/batch_projection.py` | Pure derivation: `StatusCounts`, `derive_aggregate_state`, `BatchJobView`, `BatchSummary`, `BatchCatalog`, `build_catalog`, `collect_artifact_refs`. Display-only; never persisted |
| `src/queue/failure_triage.py` | `triage_failure`: classification from typed `failure_evidence` only, never from message text |
| `src/controller/batch_operations_service.py` | `BatchOperationsService`: `refresh` (bounded repository scan, newest first), `plan_cancel_remaining` / `cancel_remaining`, `preflight_retry` / `submit_retry`, `resolve_outputs`. Blocking and thread-agnostic: call from a worker |
| `src/controller/batch_output_resolution.py` | `resolve_job_outputs`: file existence plus PIL `verify` for hand-off to Review/Video |
| `src/gui/view_contracts/batch_operations_contract.py` | `BatchOperationsSession`: Tk-free state and action gating, work via `BackgroundWorkRunner`, stale results dropped |
| `src/gui/batch_operations_panel_v2.py`, `src/gui/batch_retry_dialog.py` | Thin Tk renderer and retry acknowledgement dialog |

Behavior that must hold:
- Cancel Remaining acts only through `JobQueue.cancel_queued_jobs`, re-checking QUEUED at the transition; confirmed ids bound the targets.
- Retry Selected Failed accepts only FAILED jobs, refuses a job that already has a QUEUED/RUNNING/COMPLETED retry child (`_BLOCKING_CHILD_STATUSES`), re-verifies frozen inputs (`frozen_input_checks`, `verify_inputs`), re-applies today's submission validation, `require_njr_operation` and workflow governance, and requires acknowledgement where failure evidence says the earlier request may have run. Admission is one `submit_njrs` call; a single-use plan token blocks double submission. More than one retry gets a `selected_retry` batch descriptor (`build_selected_retry_descriptor`); replays do not inherit the original batch membership.
- Repository scan limits: window 2,000 rows, listing cap 20,000 candidates; operations scan with no cap so a batch is seen whole.
- The panel is constructed in `src/gui/views/pipeline_tab_frame_v2.py` via `build_batch_operations_service(queue_controller)` (a widget acting as a composition root; audit D3).

## 5. Image metadata round trip into Review and reprocess

### 5.1 Contract

`src/utils/image_metadata.py` (`ImageMetadataContractV26`, schema `stablenew.image-metadata.v2.6`): PNG text chunks (iTXt) or JPEG EXIF (`UserComment` with an `SNMETA:` base64 envelope plus `ImageDescription` and `Software`). `extract_embedded_metadata` returns a `ReadPayloadResult` with status `ok`, `missing` (also when the schema key differs), `omitted`, `corrupt` (bad gzip, hash mismatch, bad JSON). Only PNG and JPEG are read; WebP is selectable in Review but yields `missing` [V]. The image-side producer is described in `IMAGE_PIPELINE.md` section 8.

### 5.2 How Review turns it into a baseline

`AppController._extract_reprocess_baseline_from_image` returns `{stage, prompt, negative_prompt, model, vae, config}` from `resolve_prompt_fields`, `resolve_model_vae_fields` and `stage_manifest.config`, or `{}` on any non-`ok` status. These resolvers walk many alias keys and history entries in a fixed precedence (stage manifest, generation, stage config, history, top level). Consequences:
- An image without a StableNew payload still reprocesses, with `baseline_source` `fallback` (or `fallback (metadata <status>)` when the payload exists but is unreadable) and the live stage config. The preview shows that origin per row.
- The model recorded in the artifact wins over the live pipeline model; preview and submission use the same precedence (`effective_model`).
- Never infer a profile from the file name; `normalize_image_backend_options` resolves it from the resolved model name.

### 5.3 Review stamping rewrites the image [V]

`LearningController.save_review_feedback` calls `ReviewMetadataService.stamp_review_metadata`, which calls `write_portable_review_metadata`: it adds a `stablenew_review` key by re-saving the image (`write_png_metadata` / `write_jpg_metadata`: temp file then replace; fixed `<stem>.tmp<suffix>` name) or, if that fails, writes `<image>.review.json` (`write_review_sidecar`, plain `write_text`). The pixels are unchanged but the file bytes and SHA-256 are not. `source_artifact_id` is computed from current bytes, so saving feedback on an image after a Review preview makes `require_queueable` refuse ("Source content changed; preview again"), and lineage ids refer to the stamped file.

## 6. Photo Optimize

### 6.1 Modules

| Module | Role |
|---|---|
| `src/photo_optimize/models.py` | `PhotoOptimizeAsset`, `PhotoOptimizeBaseline` (prompt, model, vae, `stage_defaults`, `config`, `working_image_path`, `geometry_policy` auto/custom), `PhotoOptimizeHistoryEntry`, `PhotoOptimizeBaselineSnapshot`; `PHOTO_OPTIMIZE_SCHEMA_VERSION` `1.0` |
| `src/photo_optimize/store.py` | `PhotoOptimizeStore`, `get_photo_optimize_store`: managed workspace `<output>/PhotoOptimize/workspace/` with `assets/<asset_id>/{sidecar.json, original/, outputs/, manifests/}` and `staging_runs/`. The sidecar is the only draft authority |
| `src/photo_optimize/settings.py` | `FIELDS` alias table, `normalize_settings`, `resolve_geometry`, `validate_settings`, `copy_pipeline_settings` |
| `src/photo_optimize/submission.py` | `pipeline_defaults`, `prepare_photo_plan`, `describe_photo_plan`: per-asset baseline -> `ReprocessSourceItem` -> `ReprocessJobBuilder` |
| `src/controller/photo_optimize_submission.py` | `prepare` / `submit`: thin controller wrappers (log, summary, `_submit_reprocess_njrs`) |
| `src/photo_optimize/editing.py` | Batch Edit: `prepare_edit` / `apply_edit` with a per-asset sidecar fingerprint (mask of fields; absent means unchanged) |
| `src/photo_optimize/results.py` | Result candidates and historical baseline promotion: `list_candidates`, `validate_candidate`, `prepare_promotion` -> `PromotionPlan` |
| `src/photo_optimize/migration.py` | Verified copy-only migration from the legacy `data/photo_optimize` workspace |
| `src/photo_optimize/paths.py` | `io_path` (Windows extended paths), `canonical_path`, `rename_without_replace` |
| `src/gui/views/photo_optimize_tab_frame_v2.py` plus mixins `photo_optimize_layout.py`, `photo_optimize_scope.py`, `photo_optimize_results.py`, `photo_optimize_editors.py` | Tk tab; the mixins are presentation only |

### 6.2 Submission

1. The Tk thread captures the live Pipeline settings (`AppController.build_photo_optimize_defaults` -> `pipeline_defaults`) and the selected assets' baselines.
2. A worker (`_run_photo_operation`) runs `prepare_photo_optimize_plan` -> `prepare_photo_plan`. Per asset it normalizes aliases, resolves geometry from the decoded working image (Auto = image size, Custom = validated width/height), validates numbers, applies prompt deltas, and partitions assets by stage plan. Each partition is compiled by `build_grouped_reprocess_jobs` with `source="photo_optimize_tab"` and `extra_metadata["photo_optimize"]` (run id, per-asset effective prompts, frozen `config_snapshot`, `geometry_policy`).
3. The operator reviews the frozen per-photo targets (`review_dialog`). Confirmation submits that exact plan with no recompilation (`submit_prepared_photo_plan` -> `submit_reprocess_njrs`), so exact-profile refusal is the shared one.
4. On completion, `AppController._handle_photo_optimize_completion` (registered through `_create_photo_optimize_completion_handler`) maps `extract_reprocess_output_paths` to assets by index and calls `PhotoOptimizeStore.record_optimize_history`, which copies outputs and manifests into the asset directory, records SHA-256 per output, and is idempotent per (run id, job ids).

Do not give Photo Optimize its own compiler, queue, runner or job history. Its history is a per-asset sidecar projection; job truth stays in `JobRepository`.

### 6.3 Settings aliases

Photo form values exist as nested stage dicts, aliases inside them (for example `ad_model`, `upscale_factor`) and flat legacy root keys. `normalize_settings` is the single synchronizer: explicit nested values win (including 0, False and empty string), then nested aliases, then flat legacy keys, then fallback, and it writes the aliases back so the form, compiler and executor agree. Root-level flat keys are img2img projections only. New settings must be added to `FIELDS` and to `validate_settings` expectations, or they will not survive a round trip.

### 6.4 Baselines, snapshots and historical promotion

- `PhotoOptimizeAsset.baseline` is the working baseline; `original_baseline` is recorded at import; `baseline_snapshots` is a stack of earlier baselines.
- Promotion is two-phase and stale-safe: `prepare_result_promotion` reads the sidecar digest, validates the chosen candidate (original, working, or a recorded history output) and returns a `PromotionPlan`; `apply_result_promotion` re-prepares and refuses if the sidecar digest, image SHA-256 or resulting baseline differ. Modes: `recorded` (restore the recorded prompt/settings with the image) or `image_only` (keep current prompt/settings). A snapshot of the prior baseline is pushed in the same sidecar write; `revert_baseline` pops it. Original files, outputs, manifests, history and queued jobs are never modified.
- `_safe_file` in `results.py` only accepts files inside the managed asset directory (or a hash-verified migration copy), rejects links and junctions, and re-hashes before and after a PIL decode.
- History entries recorded before geometry policy was stored warn and keep the current policy; entries with incomplete config refuse `recorded` mode.

### 6.5 Migration

`migrate_assets` copies each legacy asset into a staging directory, verifies SHA-256 of every file, rewrites current-photo paths, writes `migration.json` (source and per-file hashes), and publishes with `rename_without_replace`. It never deletes or overwrites a source or destination, retries only Windows share/ACL errors (5, 32, 33) three times, and reports per-asset `MigrationIssue`s in a `MigrationReport`. `PhotoOptimizeStore.retry_migration` re-runs it from a worker. The global store skips migration when a test has overridden `PHOTO_OPTIMIZE_ROOT`.

## 7. GUI-ownership rules for these surfaces

Authority: `AGENTS.md` sections 3 and 4, `docs/ARCHITECTURE_v2.6.md` section 11. Rules that matter here:

1. The GUI captures intent and renders projections. It never builds a backend payload, calls a runner, or writes queue or repository state. `src/gui/` owns Tk; `src/gui/view_contracts/` and `src/gui_v2/` must stay importable without Tk [V: no `tkinter` import in either today].
2. Anything that reads or hashes files, decodes images or scans the repository runs off the Tk thread and marshals results back (`_ui_dispatch`, `BackgroundTaskCoordinator`, `BackgroundWorkRunner`, `after`). Results from superseded requests are dropped.
3. A preview is a projection of what admission would do. The thing the operator confirmed is what is submitted.
4. Prompts shown to the operator pass through `ContentVisibilityResolver`.
5. Refusals surface as blocked rows or readiness text before admission (`assess_readiness`, `ReviewBatchItem.error`); no silent drop of a selected source.
6. New toolkit-neutral logic goes in a Tk-free module (view-contract style: a frozen view dataclass, a Tk-free session, injected services), then a thin Tk renderer. `BatchOperationsSession` plus `BatchOperationsPanelV2` is the pattern to copy.

### 7.1 Stale parts of `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` [V]

The map is still the right file-placement reference, with these corrections:
- It says `src/gui_v2/` holds only `adapters/` and `validation/`. It also holds Tk-free projection modules at its top level (for example `model_policy_projection.py`, `openpose_conditioning_view.py`, `prompt_adaptation_preview.py`). `AGENTS.md` describes it as "toolkit-neutral adapters/view models", which is accurate.
- Rule "controllers in `controllers/` orchestrate; they do not own prompt construction or job submission" is not true today: `LearningController` (~4,000 lines) compiles prompts and NJRs (audit D1 [A]), and `ReviewWorkflowAdapter.apply_prompt_delta` composes prompts inside `src/gui/controllers/`.
- "Controllers must not mutate Tk widgets" is violated by `src/controller` (`AppController` reaches `main_window` and tabs directly; audit D3 [A]).
- The Forbidden Patterns list does not mention the current accepted shape: Tk-free `view_contracts` sessions and the `BackgroundTaskCoordinator` / `BackgroundWorkRunner` pair.
- Rule 9 (filesystem lookups through latest-wins background services) is not met by the Review folder scan (section 8).

## 8. Known debt and traps

Audit GUI findings as they stand on these surfaces:

- **D3 composition roots and two-way coupling** [A, V examples]: `ReviewTabFrame._resolve_learning_controller` walks `app_controller.main_window.learning_tab`; the batches panel builds its own service in `pipeline_tab_frame_v2.py`; `src/controller/review_batch_service.py` imports `src/gui/controllers/review_workflow_adapter.py` (recorded in `tools/ci/architecture_baseline.json` as a controller-to-GUI import), and so do `src/photo_optimize/submission.py` and `src/photo_optimize/editing.py` (a domain package importing the GUI package, not yet ratcheted). Fix direction: move `ReviewWorkflowAdapter.apply_prompt_delta` and the prompt-term helpers to a Tk-free module under `src/prompting/` or `src/pipeline/` and import from there (audit P3-2).
- **D4 tab failures swallowed** [A, partly fixed V]: `MainWindowV2.add_tab` now logs the traceback and shows an error placeholder naming the tab. Still silent: a failure of `center_notebook.add` is swallowed with `pass`.
- **D5 blocking work on the Tk thread** [A, V]: still true for (a) Photo Optimize saves on every `<KeyRelease>` and variable write via `_persist_current_asset_baseline` (sidecar read, directory creation, write; no debounce); (b) the Review folder scan (`_on_select_folder`: `rglob` with `is_file` per entry); (c) per-selection metadata decode in `ReviewTabFrame._show_image` plus a second decode in `resolve_adetailer_pair`; (d) the full-resolution compare composite. Already off-thread: Review preview and admission, Photo prepare/submit/promotion/result thumbnails, batch repository reads. Fix direction: audit P4-7.
- **D6 background-work patterns** [A, V]: these surfaces use four: `BackgroundTaskCoordinator` (Review), `BackgroundWorkRunner` (Batches), `ThreadPoolExecutor` polled with `after(50)` (Photo tab workspace and operations, result previews), and `ThreadRegistry.spawn` per thumbnail (one non-daemon thread per decode, no pool, no cache). The architecture baseline in `tools/ci/` caps raw and daemon threads but does not unify the patterns.
- **D10 polish** [V]: the tab is still titled "Photo Optomize" (`main_window_v2.py`, also in the import file dialog title and a docstring); the window title is "StableNew V2 (Spine)". `ReviewTabFrame` has 52 `messagebox.show*`/`ask*` call sites, including a modal "Saved" after each feedback save [V count of call sites].

Other traps found while reading:

- Two parallel precedence implementations in `ReprocessJobBuilder`: `_resolve_stage_*` (used to build the job) and `_resolve_stage_*_with_source` (used by the preview). They must change together or the preview will describe different values than the job carries [V].
- Three independent default tables for the same stages: `ReprocessJobBuilder.DEFAULT_STAGE_VALUES`, Photo `FIELDS` fallbacks, and the executor's own fallbacks (see `IMAGE_PIPELINE.md` section 11). For example img2img defaults to 15 steps in the builder but 20 in Photo `FIELDS` [V].
- `prepare_photo_plan` has a filesystem side effect: its `output_dir_factory` calls `PhotoOptimizeStore.create_staging_run_dir`, so previewing a plan that is never submitted leaves empty `staging_runs/` directories [V].
- Photo history is recorded only by the in-process completion handler for COMPLETED jobs; no code reconciles a job that finished while the app was closed [V: `record_optimize_history` has one caller].
- Persistence is not on `src/utils/atomic_io.py` [V]: `PhotoOptimizeStore.save_asset` writes a temp file and `Path.replace` without fsync or the Windows retry; `write_review_sidecar` uses plain `write_text`. The audit (B4) lists the photo store as already safe [A]; that is only partly true. `PhotoOptimizeStore._read_asset` returns `None` on any exception, so a corrupt sidecar silently disappears from the list.
- `write_png_metadata` / `write_jpg_metadata` swallow every exception and return `False`; `write_portable_review_metadata` then falls back to the sidecar file. Both are best-effort.
- `decode_payload` gunzips without a size bound (audit B11 [A]); Review opens arbitrary user files with it.
- `AppController` (ceiling 7,307 lines, `tools/ci/controller_surface_baseline.json`) still hosts the Review/reprocess/image-edit/Photo entry points and `_extract_reprocess_baseline_from_image`; do not grow it. New logic goes into the service modules above.
- Audit C2 [A]: `NormalizedJobRecord(` construction sites differ in policy; reprocess is one of them (section 2.3). A change to compile policy must be checked here too.

## 9. How to test

Configuration is `pyproject.toml` only. Run focused tests first, then `python tools/ci/run_pr_gate.py`. No test may touch a WebUI, model, GPU or real runtime.

| Area | Tests | Hermetic seam |
|---|---|---|
| Reprocess builder, batching, defaults | `tests/pipeline/test_reprocess_builder_defaults.py`, `tests/pipeline/test_reprocess_batching.py`, `tests/pipeline/test_klein_compile_policy.py` | `tests/helpers/njr_factory.py`, synthetic PIL images in `tmp_path` |
| Review exact-profile preflight and controller paths | `tests/controller/test_review_exact_profile_preflight_158.py`, `tests/controller/test_app_controller_reprocess_review_tab.py`, `tests/controller/test_learning_controller_review_feedback.py` | Stub job service; use absolute `tmp_path` images (a bare relative name writes a review sidecar into the working directory) |
| Whole-selection preview and dialog | `tests/gui_v2/test_review_batch_200.py` | Real Tk root with a real SQLite `JobRepository`/`JobQueue`, no runtime dispatch |
| Review tab prompt modes, view contracts, ADetailer pair | `tests/gui_v2/test_review_tab_prompt_modes.py`, `tests/gui_v2/test_review_view_contracts.py`, `tests/gui_v2/test_review_adetailer_outcome_160.py` | Tk-free where the contract allows |
| Batch membership, catalog, cancel, retry atomicity | `tests/queue/test_batch_membership_201.py`, `tests/queue/test_batch_catalog_201.py`, `tests/queue/test_batch_cancel_201.py`, `tests/queue/test_batch_admission_atomicity.py`, `tests/controller/test_batch_operations_service_201.py` | Temp SQLite repository |
| Batches view | `tests/gui_v2/test_batch_operations_session_201.py`, `tests/gui_v2/test_batch_operations_view_201.py`, `tests/gui_v2/test_batch_operations_review_handoff_201.py` | Session tested without Tk |
| Photo store, settings, migration, editing, promotion | `tests/photo_optimize/` (`test_photo_220.py`, `test_photo_optimize_store.py`, `test_migration_recovery_221.py`, `test_scope_editing_222.py`, `test_historical_results_223.py`) | Temp workspace roots; never the operator workspace |
| Photo tab | `tests/gui_v2/test_photo_optimize_tab_v2.py`, `tests/gui_v2/test_photo_scope_222.py`, `tests/gui_v2/test_photo_results_223.py` | Headless projection where possible |
| Thumbnails | `tests/gui_v2/test_thumbnail_widget_v2.py`, `tests/gui_v2/test_thumbnail_tooltip_recovery_111.py` | Fake loader |
| Metadata contract and review stamping | `tests/utils/test_image_metadata_contract.py`, `tests/review/test_review_metadata_service.py`, `tests/review/test_artifact_metadata_inspector.py` | Synthetic PNG/JPEG |

For a new refusal, assert both the error and that nothing was submitted (the repository has no new identities). For a source-changing race, mutate the file between prepare and confirm and assert `require_queueable` refuses.

## 10. How to change or extend today

- **New Review/reprocess option**: extend `ReprocessSourceItem` or its `config`, apply it in `build_grouped_reprocess_jobs`, add it to the preview resolvers (both the plain and `_with_source` variants), keep the group-key signature correct (an option that changes the job must change the grouping key), then expose it through `ReviewWorkflowAdapter` and the tab. Keep the operation assessable by `assess_njr`.
- **New refusal for a model family**: implement it in the profile/policy layer (`IMAGE_PIPELINE.md` section 12), not in Review. Review and Photo pick it up through `assess_njr` / `require_njr_operation`.
- **New Photo setting**: add to `FIELDS` (nested key, aliases, flat legacy keys, fallback), validate in `validate_settings`, add to the form load/collect methods in `photo_optimize_tab_frame_v2.py`, to `editing.py` masks if batch-editable, and to the `config_snapshot` equality check expectations. Bump `PHOTO_OPTIMIZE_SCHEMA_VERSION` only with a migration; `_read_asset` ignores sidecars with any other version.
- **New batch operation**: derive state in `batch_projection.py` (pure), act only through `JobQueue`/`JobService` in `BatchOperationsService`, gate in `BatchOperationsSession`, render in `BatchOperationsPanelV2`. Never persist batch state.
- **New heavy GUI action**: use `BackgroundTaskCoordinator` (controller-initiated, keyed, latest-wins) or `BackgroundWorkRunner` (view-contract sessions); do not add a sixth pattern.

## 11. Evidence records

Per-PR records stay as historical evidence. They may describe superseded behavior; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/GUI/PR-REVIEW-BATCH-200_Evidence_and_Preflight.md` | Reproduced Review batching defects and the whole-selection preview/admission design |
| `docs/Subsystems/GUI/PR-BATCH-OPS-201_Unified_Batch_Operations.md` | Batch membership, projection, Cancel Remaining and Retry Selected Failed contracts |
| `docs/Subsystems/Image/PR-IMG-MODELS-158_Cross_Workflow_Model_Compatibility.md` | Operation compatibility preflight applied to Review, reprocess and Photo |
| `docs/Subsystems/Image/PR-IMG-PHOTO-220_Photo_Optimize_Settings_and_Workspace.md` | Photo settings, geometry, grouping, persistence authorities |
| `docs/Subsystems/Image/PR-IMG-PHOTO-221_Windows_Migration_Recovery.md` | Legacy workspace migration and Windows path behavior |
| `docs/Subsystems/Image/PR-IMG-PHOTO-222_Scope_Aware_Editing.md` | Single-photo vs batch edit, field masks, frozen-target review |
| `docs/Subsystems/Image/PR-IMG-PHOTO-223_Historical_Result_Promotion.md` | Result candidates, promotion modes, snapshots |
| `docs/Subsystems/GUI/PR-GUI-110_Focused_Operator_Workspace.md` | Responsive previews and workspace density contract |
| `docs/Subsystems/GUI/PR-GUI-111_Thumbnail_Recovery_and_Tooltip_Correctness.md` | Thumbnail request recovery rules |
| `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` | File-placement map (see section 7.1 for what is stale) |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Audit D1 to D11, B4, B11, C2 and the P3-2 / P4-7 plan referenced above |
