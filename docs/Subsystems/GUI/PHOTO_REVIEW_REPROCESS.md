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

`VALID_REPROCESS_STAGES` also lists `svd_native` and `video_workflow` (a request for `animatediff` is refused with `AnimateDiffRetiredError`; its execution is retired): this builder is shared with the video paths (`src/controller/svd_controller.py`, `src/video/video_workflow_njr_builder.py`, `src/curation/curation_workflow_builder.py`). The Review path restricts stages to `adetailer`, `upscale`, `img2img` before calling it.

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
| Widgets, event wiring, dialogs | `ReviewTabFrame` (`src/gui/views/review_tab_frame_v2.py`, ~3,600 lines; Tk-free state and gating live in `ReviewWorkspaceSession`, section 3.7); `ReviewBatchDialog` (`src/gui/review_batch_dialog.py`) |
| Non-render logic: prompt delta (append/replace/modify), effective-settings text, readiness projection, staged-curation hand-off, feedback payload | `ReviewWorkflowAdapter` (`src/review/workflow_adapter.py`, Tk-free) |
| Whole-selection compile and preflight | `prepare_review_batch` and `ReviewBatchPreview` (`src/controller/review_batch_service.py`) |
| Threading of preview and admission | `BackgroundTaskCoordinator` (`src/controller/app_controller_services/background_task_coordinator.py`), keys `review:batch` and `review:admit:<batch_id>`, latest-wins |
| Metadata baseline extraction | `AppController._extract_reprocess_baseline_from_image` using `src/utils/image_metadata.py` |
| Prior-review summary, feedback save/undo | `LearningController` (`save_review_feedback`, `undo_review_feedback`, `get_prior_review_summary`), reached through `app_controller.main_window.learning_tab` |
| ADetailer before/after pair | `resolve_adetailer_pair` (`src/review/adetailer_outcome.py`) |
| Metadata inspector | `ArtifactMetadataInspector` (`src/review/artifact_metadata_inspector.py`), `ArtifactMetadataInspectorDialog` |
| Content visibility (redaction) | `ContentVisibilityResolver`; every prompt shown in Review/Photo/Batches is passed through it |
| Background file work (PR-GUI-UX-580): folder scan, per-image metadata and ADetailer pair, bounded comparison decode | Tk-free `src/review/workspace_io.py`, run through `EditWorkRunner` (`src/gui/view_contracts/edit_work_runner.py`, a thin wrapper over `BackgroundTaskCoordinator`, keys `review:folder-scan`, `review:image-context`, `review:compare`) |
| Latest-request-wins revisions | `ReviewSelectionRevisions` (`src/gui/view_contracts/review_selection_contract.py`); counters only |

Quick Edit is Review's operator-facing name: select images, inspect or edit, preview the effective job, add it to the queue. It keeps nothing per photo (the Managed Photo Set, section 6, does).

#### 3.1a Selection revisions and asynchronous presentation (PR-GUI-UX-580)

Every route that replaces Review's selection is an *accepted selection* and bumps one revision (`_begin_selection_context`): Select Images, Select Folder, Clear, Learning staged-curation handoff, History Iterate handoff, and the Queue/History and Photo Optimize image handoffs. A folder scan, an image-context read or a comparison decode carries the revision it started under and is dropped on delivery when it is no longer current, so a late result can never replace a newer selection, its History claim, stage choices, prompt edits or status. Rules:

- The folder scan, `extract_embedded_metadata`, `resolve_adetailer_pair` and the comparison composite run on a worker; the Tk thread only shows the preview and publishes a result. Effective settings wait for the image context (`_image_ready`); the one remaining synchronous reader is `AppController.get_review_reprocess_effective_settings_preview` (its config builder is Tk-bound and `AppController` is at its ceiling): known debt.
- A folder with more than `MAX_FOLDER_IMAGES` (20,000) supported images is refused, never loaded partially. An empty or unreadable result leaves the selection alone and says so. Comparison decode is bounded (`COMPARE_MAX_EDGE` 2048 per side, `COMPARE_MAX_PIXELS` 120 M per source; refusal text never contains prompts) and reports "scaled to fit; the files are unchanged".
- An incoming selection over unsent Review work asks Replace/Cancel once (`_confirm_incoming_replacement`, the History handoff's convention; a `_confirm_replace_hook` test seam). Cancel returns `0` / `False` / `[]` from `load_selected_images` / `load_staged_curation_handoff` / `route_images_to_review`, leaves the selection, edits, History claim and navigation exactly as they were, and queues nothing. History's own service has already asked, so `load_history_iterate_handoff` passes `confirmed=True`.
- A manual replacement (any incoming route that is not the History handoff) clears `_active_handoff`: the History claim is attached to its image and file bytes only, and `prepare_review_batch` still refuses a changed source or contradicting embedded identity.
- Sending images to the Managed Photo Set is a *distinct operation* (`route_images_to_photo_optimize`, section 6.6): it carries file paths only, leaves Review's selection, edits and History claim untouched, and a History-origin image is imported with no parent job or artifact.

### 3.1.1 Shared media inspection

Review's selected-image preview and Photo Optimize's independent Original / Candidate previews use the shared `MediaInspector`
for local Show, Fit, zoom/pan and detach/return. Inspection never changes Review's selection, prompts or metadata, or Photo
Optimize's working baseline, candidate, batch selection or sidecar. Photo Optimize validates candidate identity on its existing
worker before handing the path to the inspector. Review withholds SFW media until the selected image's metadata arrives;
content visibility is then resolved from that same image context. Review's specialized ADetailer comparison remains separate
and closes when the primary inspector is hidden. Mask, outpaint and Smart Review editor canvases retain their editing behavior.

### 3.2 Whole-selection preview and admission

`prepare_review_batch` compiles every selected source with `ReprocessJobBuilder` (one job per source unless `batch_size > 1` was explicitly requested; every job's output root is the configured `output_dir`, route folders stripped, via `review_output_dir`, so children land in `<output root>/Reprocess/<run>/` beside the Pipeline folders and under the same root the archive uses; Review mask edits and outpaint use the same root; a source image that recorded no checkpoint takes it from its parent job's snapshot, `parent_job_model`), reports every refusal, and queues nothing. Per source it: checks the file, hashes it (`_source_sha256`), loads it with PIL, extracts the baseline, applies prompt deltas, builds a `ReprocessSourceItem` with lineage metadata (`source_job_id`, `source_artifact_id = sha256:<bytes>`, `source_path`, plus `build_review_chunk_lineage_block`), compiles, runs `assess_njr`, then re-checks size/mtime/hash to detect a source that changed during preparation.

The result is a `ReviewBatchPreview` of `ReviewBatchItem` rows and the compiled NJRs. `require_queueable()` raises if any item is blocked, if there are no jobs, or if any source's size, mtime or SHA-256 changed since preview. `ReviewBatchDialog` has no "queue the good ones" path: blocked items disable submit, "Exclude blocked and re-preview" recompiles a smaller set. Confirmation submits the exact previewed NJRs (they are not recompiled). Each admitted job carries `review_batch = {batch_id, source_count, group_by_model}` plus top-level `batch_id` in provenance metadata; `group_by_model` only reorders jobs.

Rules:
1. Preview and admission must run off the Tk thread (they hash files and open images). `submit_review_reprocess_batch_async` does; the synchronous `submit_review_reprocess_batch` exists for the direct API.
2. The exception net in `prepare_review_batch` is `(ValueError, OSError, TypeError)`; `OperationNotSupportedError` and `KleinProfileError` are `ValueError` subclasses, so refusals become blocked rows. A new refusal type must subclass one of these or it aborts the whole preview.
3. Do not stamp or rewrite a source image between preview and confirm (section 5.3).

### 3.3 Review mask editing

`ReviewTabFrame` offers **Edit Mask** for exactly one PNG, JPEG or WebP still image: for the image shown from the always-visible
**Edit image...** menu (Inpaint / Outpaint, no Re-work mark needed), and for the one marked image from the Re-work region
(section 3.7). `MaskEditorDialog` owns transient
editing only; `MaskDocument` / `MaskViewport` keep brush strokes, erasing, bounded undo/redo, clear, zoom and pan aligned to
original-image coordinates. Red overlay / white mask means change; black means preserve. Source files are never overwritten.

The operator supplies a replacement editing prompt, denoising strength, mask blur, masked-region padding and the
masked-region/whole-image choice. **Preview frozen job** calls `prepare_mask_edit` off Tk: it uses the existing
`ReprocessJobBuilder`, captures source and mask into job-owned content-addressed mutable-state snapshots, and freezes an
img2img NJR with source lineage. Preview shows original source, mask identity/hash/geometry, model, prompt, backend,
resolved stage settings and restrictions. Any edit invalidates that preview; late worker results are discarded.

**Add prepared job to Queue** rechecks the original source and both snapshots, assesses operation compatibility and submits
the exact previewed NJR through `submit_reprocess_njrs` -> `JobService.submit_njrs`. A failed admission preserves the draft
and requires a fresh preview before another attempt. The dialog admits a preview at most once; no automatic replay occurs.
Loading, hashing, snapshot writes, compilation and admission run off Tk; widget updates return through the existing
`BackgroundWorkRunner` / `TkUiDispatcher`. Source decode limits are 20 MiB, 64–4096 pixels per side; animations are refused.

This first slice supports SDXL checkpoints on Forge only. `masked_inpaint` projects the existing ModelPolicy through the
N1b SDXL verdict (`src/image_backends/sdxl_target.py`; owner decision 2026-11-25) at preparation, admission and backend
validation. A registry-resolved SDXL base, or a checkpoint that has completed the same edit on Forge here, is verified. An
unclassified checkpoint (no registry record, unclassified or conflicting header) previews with a warning (why and the fix)
in the Preview summary and the outpaint support line; Add to Queue records it in `provenance.metadata.accepted_warnings`
and dispatch does not refuse it. Other backends, exact profiles and positively identified other families fail before
admission. Physical output quality is not qualified by these CPU contracts. See
`IMAGE_PIPELINE.md` section 3.2 for the persisted input contract and dispatch integrity.

### 3.3.1 Review canvas extension (outpainting)

**Extend Canvas…** sits beside Edit Mask and opens `OutpaintDialog` (`src/gui/outpaint_dialog.py`) for exactly one PNG, JPEG
or WebP still image. The operator sets independent nonnegative left/right/top/bottom extensions, an outpainting prompt,
denoising strength and mask blur, and sees the proposed canvas with the original's boundary kept at (left, top)
(`src/gui_v2/outpaint_canvas_view.py`; **Show mask** draws the generation mask) plus the exact new size, the target's support
status and, after Preview, a bounded Details projection (`outpaint_preview_summary`): original and expanded geometry, mask
policy and hashes, model/backend, prompt, denoising, preservation policy, snapshot hashes, parent lineage, resource pressure
and the notice that physical quality is unqualified.

Rules: both expanded sides must be multiples of 8 and at most 4096; geometry is refused with its reason, never adjusted.
**Align to 8** is the one inspectable rule (it grows the right and bottom extensions to the next multiple and shows the
result). An `unsafe` resource-pressure band (the executor's effective-load bands, a parity test pins them) refuses Preview;
`high_pressure` is reported. Any change to a margin, the prompt or a setting discards the approved Preview; late worker
results are discarded; Preview and Add to Queue follow the mask editor's worker, single-admission and close-during-work
behavior. Preview creates no job; Add to Queue submits the same frozen NJR through `submit_reprocess_njrs` ->
`JobService.submit_njrs`. `src/controller/outpaint_edit_service.py` shares the mask editor's builder
(`build_frozen_edit_preview`); first release is one img2img stage, SDXL base on Forge. A1111, Comfy, other families and
exact profiles are refused. Canvas preparation, the frozen contract and the original-pixel guarantee are in
`IMAGE_PIPELINE.md` section 3.3.

### 3.3.2 Smart Review (opt-in assisted masking and caption suggestions)

**Smart Review…** (below Edit Mask / Extend Canvas) opens `SmartReviewDialog` (`src/gui/smart_review_dialog.py`) for exactly one
PNG, JPEG or WebP still image. Everything in it is a **suggestion**: nothing runs on open or selection, each capability
(object selection: SAM 2.1 Small; image analysis: Florence-2 Base FT) is off until the operator ticks it for the session, and a
model runs once, on a tracked worker and in a contained CPU child process, only when its button is pressed. Capability state is
per Review tab and in memory only (a new session starts off); no model is ever downloaded, installed or fallen back from.

- **Object selection.** The operator places up to four foreground/background points and/or one box on the same zoom/pan canvas
  geometry the mask editor uses (`MaskViewport`; points outside the image are refused, not clamped). **Propose mask** returns
  low-resolution logits; positive logits (> 0) become white (change), everything else black (preserve), upscaled
  nearest-neighbor to the exact source size and revalidated (8-bit `L` PNG, strictly 0/255, not empty, <= 95% of the image).
  The mask is tinted over the image; **Accept mask** hands its bytes to a new `MaskEditorDialog(suggested_mask=...)`, where it is
  one undoable document step. **Reject**, **Cancel analysis**, changing prompts, closing, or a different selection discard it.
  Preview, the frozen edit contract and `JobService.submit_njrs` admission (once, after explicit confirmation) are unchanged and
  stay in the mask editor; Smart Review never builds a job, calls a runner or touches a queue.
- **Image analysis.** **Analyze image** shows a sanitized caption (control/format characters removed, <= 600 characters) and up
  to 16 labelled boxes, labelled with the model and runtime, as an unverified suggestion. **Copy**, **Add to prompt draft** (once,
  reversible; **Undo** restores the draft only if the operator has not edited it since) and **Dismiss** are explicit; nothing
  writes a rating, prompt record or Learning data. Content hidden by the Review content-visibility mode is not shown, copied or
  applied.
- **Identity and staleness.** Each request is bound to the file's SHA-256, size and EXIF orientation (not its name) and to a
  session epoch; replies for another image, an older request or a closed session are dropped, and the file is re-hashed before a
  mask is used. The coordinate frame is the mask editor's: stored pixels, with the EXIF orientation recorded in the identity but
  not applied, so a mask always has the exact size of the edit source.
- **Models.** `src/review/assist/` reuses the PR-IMG-CNET-230 seam: `AssetRegistry` byte verification of the catalog resource
  (`sam-2-1-small`, `florence-2-base-ft`), hash-verified staging into a private job directory, and the bounded worker protocol
  (`providers.run_worker`, own OS container, timeout, output cap, cooperative cancel). The child (`src/review/assist/worker.py`)
  loads only native Transformers classes with `local_files_only=True`, `trust_remote_code=False`, safetensors and
  `load_state_dict(strict=True)`; it never initializes a missing weight. Transformers must be >= 5.17 and < 6 (qualified on
  5.17.0; checked at run time, not pinned). Files alone never make a capability ready: both catalog entries stay
  `needs_integration` with `inference_not_qualified`.
- **Limits.** Real-image mask and caption quality and GPU use are not qualified. Each model child runs under a verified 6,144 MB
  committed-memory limit, per child and not an application-wide budget (`run_bounded(memory_limit_mb=...)`: the child does not
  start unless the OS itself reports that limit, read back from the job object or cgroup; actual peak use and model fit are
  unmeasured). On Windows a limit that cannot be established means no child. A host other than Windows that cannot
  establish it (for example Linux without a delegated StableNew cgroup) runs the child **without** a memory limit, logs a
  warning, and shows "WARNING: this host could not enforce the 6,144 MB memory limit..." with the map or "MEMORY LIMIT NOT
  ENFORCED" in the Smart Review model label. AI provenance is not recorded in the frozen edit record. Tests:
  `tests/review/assist/test_assist_pure_320.py`, `tests/review/assist/test_assist_session_320.py`,
  `tests/gui_v2/test_smart_review_320.py`, `tests/assets/test_review_assist_catalog_320.py`.

### 3.3.3 Inspect & Improve

Select and show one still image in Review, then open **Inspect & Improve**. Draw a box on the shared
image inspector or choose **Whole image**. Fill in the visible issue, category, certainty and confirmation,
then **Record finding**. A session supports up to 24 findings. Coordinates use half-open rectangles
in the stored pixel orientation, matching Edit Mask even when EXIF specifies a display rotation.
Changing the Review selection or hiding it closes inspection and drops late replies.

**Smart Review** still requires explicit enablement and a separate Analyze or Propose action.
**Send to inspection** imports an unreviewed suggestion with its existing model label and
unqualified status. Confirming an imported suggestion requires the operator to describe the
visible issue. Caption text stays in inspection. A model result cannot open a draft or queue work.

The action picker explains eligibility from the recorded target, ModelPolicy, stage compatibility,
and the current cached checkpoint and detector lists. **Check correction availability**
reads the connected backend's script catalog. Face and hand passes require an ADetailer
entry for img2img. Guided img2img and ADetailer require an SDXL target by the same N1b verdict: an unclassified target is offered with
its warning in the action's reason and carried on the previewed job until Queue records it as accepted; a positively
identified other family or an exact profile is refused.
Edit Mask also requires Forge. A face or hand pass may affect
other regions that its detector finds. A rectangular finding marks the region for manual painting
in Edit Mask. An explicitly imported, source-matched SAM mask is editable there.

**Open correction draft** checks the source digest on a worker and opens the editable mask or
reprocess draft. **Preview frozen job** uses the existing mask or Review batch compiler. Edit any
draft field to expire that Preview. **Add to Queue** uses the existing confirmed admission and
checks the source again. A correction records the selected action and region with the job's
source artifact identity. Finding text stays in the inspection session.

**Save inspection** (AI-VL-243) records what the operator concluded about this exact image without queuing anything.
**Save inspection** saves the findings whose Confirmation is Confirmed (category, region, certainty, optional **Severity**
minor or major) as `defects_confirmed`; it is enabled only when there is at least one. **No defect seen** is the explicit
choice, enabled only when no finding is Confirmed (and refused while one is Uncertain), and saves `no_defect_seen`. An
optional **Subjects in image** (1 to 12; empty means not recorded) is saved with either. The record is closed vocabulary:
the visible-issue text, the finding's origin and any suggestion label are never stored. It is refused, with a message and
nothing written, when Learning evidence is not connected, the image is hidden by the content visibility mode, is not a
PNG/JPEG/WebP still image or is no longer the image shown, or its bytes changed since the dialog opened (checked on the
worker immediately before the write). It creates no job, opens no draft and does not touch the file; the dialog stays open.
The record is a `review_inspection` row (section 5.3) and the image's row in the Review list then shows
`(inspected: no defect)` or `(inspected: defects)`.

On a completed result, **Compare completed result** checks History and the recorded source
digest. It can show an unverified recorded pair for inspection. Saving region judgments requires
verified source lineage. The summary shows request and backend acknowledgement, pixel change,
operator region judgments, overall preference and controlled experiment evidence independently.
Review Feedback keeps the existing rating and Undo behavior. Guided judgments are stored in
Learning with both file digests. Normal Review feedback never rewrites the image (section 5.3),
so it does not expire a source-bound Preview. Mask edits freeze input snapshots. Ordinary
reprocess checks the source at Preview and admission, then the runner opens its recorded path.

### 3.4 Thumbnails and compare

- `ThumbnailWidget` (`src/gui/widgets/thumbnail_widget_v2.py`): latest-request-wins, one in-flight decode per path, decode via `load_image_thumbnail` (`src/utils/image_utils.py`) on a thread from `ThreadRegistry.spawn`, result marshalled with `after(0)`. Responsive mode decodes once at the maximum edge and rescales on resize (`src/gui/view_contracts/workspace_density_contract.py`). A failed worker start releases only its own request marker and shows "Preview unavailable".
- There is no decoded-thumbnail cache and no thumbnail grid; the list is a `Listbox` with one preview pane [V].
- Compare view: `ReviewTabFrame._render_compare_viewer` opens the viewer at once and fills it when `prepare_compare` (`src/review/workspace_io.py`, bounded decode and composite) finishes on a worker; closing the viewer or starting a newer comparison discards a decode still running (section 3.1a).

### 3.5 Iterate from History (PR-HISTORY-610A)

Two deliberate choices over one completed single-still-image job, offered by the compact History panel and Browse All through `HistoryIterateService` (`src/gui/controllers/history_iterate_service.py`). The service re-reads the canonical record (`JobHistoryService.get_history_record`) and applies the pure eligibility `assess_history_iterate` (`src/gui_v2/history_iterate_model.py`); a missing, mutated, video, thumbnail-only or multi-image artifact blocks both choices with a reason that never contains prompt text.

- **Edit Image in Review** loads the recorded image (no stages selected) through `route_history_handoff_to_review` and `ReviewTabFrame.load_history_iterate_handoff`. The handoff carries `source_job_id`, `source_artifact_id=sha256:<bytes>` and a `history_iterate` claim in `source_metadata_by_path`; `prepare_review_batch` verifies them again (`_require_history_iterate_identity`): a different embedded job id or changed bytes is a blocked source, never a silent re-attribution. The compiled reprocess job records the History job as `parent_job_id` and the image hash as `parent_artifact_id`. Existing Review preview, dialog and admission are unchanged.
- **Regenerate with Changes** makes a `HistoryVariationDraft` (`src/pipeline/history_variation_compiler.py`) the Pipeline's unsent draft (`JobDraft.history_variation`, `AppStateV2.begin_history_variation` / `update_history_variation`). The editor is `HistoryVariationPanelV2`; it edits only the positive prompt, the negative prompt (only when the frozen profile accepts one), seed, steps and CFG, and lists the rest read-only. `get_preview_jobs_for_request` compiles it purely (`compile_history_variation`: new job id, `SourceKind.HISTORY_REPLAY` with `parent_job_id` and `parent_artifact_id`, `assess_njr` and Z-Image validation) and Add to Queue admits exactly the accepted Preview through the usual `enqueue_draft_jobs`. Every edit invalidates the Preview; a build in flight for an older draft cannot publish. Variation children are excluded from `list_replay_child_rows`, so they do not count as exact-Replay children.
- Loading never queues a job. Replacing unsent Review or Pipeline work asks first (Replace / Cancel); Cancel leaves it untouched. Draft modes never mix: adding a pack or part while a variation is open is refused (sidebar message, nothing changed) until it is queued or discarded. Review Video Experiment, Learning staged curation and exact Replay are separate and unchanged.

### 3.6 Compare with Parent (PR-HISTORY-610B)

A read-only viewer for one completed still-image job and its direct recorded parent, offered by the compact History panel and Browse All (`HistoryActionState.compare`; the button is gated only on the cached row having a `source.parent_job_id`). `HistoryCompareService` (`src/gui/controllers/history_compare_service.py`) re-reads both jobs from the canonical repository by id (`controller.job_service.history_store`, the same reach as Browse All) and runs on a worker: it hydrates both frozen NJRs, requires each snapshot to be its own job and the child's frozen `source.parent_job_id`, source/provenance metadata claims and persisted `get_lineage` projection to agree, and requires both to be completed image jobs. Relationship is never inferred from names, prompts, timestamps or folders, and `list_replay_child_rows` is not used (it excludes edited variations). A grandchild compares with its immediate parent only.

- **Images.** `verify_image` (`src/gui/view_contracts/history_comparison_artifact.py`) takes the one image from `resolve_single_still_image` (never a thumbnail, first variant or folder scan), checks size, format, single frame, pixel budget, embedded job id and any recorded digest, and hashes the bytes. A `sha256:<digest>` `parent_artifact_id` on the child must equal the parent image's hash or the comparison is refused; a missing or non-SHA-256 claim is shown as **not independently verified** (a parent job link alone does not prove the parent's pixels conditioned the child). The viewer's `MediaInspector`s decode the verified bytes only (`image_decoder`), so a file changed afterwards is refused.
- **Settings.** `recipe_differences` (`src/gui_v2/history_compare_model.py`) is a pure, deterministically ordered typed projection of the two frozen NJRs (identity, prompts, model, sampling, dimensions, seed, LoRA, embeddings, per-stage settings, editing, prompt transformations, provenance, other frozen config). Each row is changed, unchanged, only in parent/child, not recorded or not comparable; nothing is filled from today's defaults, and a stage-specific value is never merged into a global one. Values the backend reported (actual seed) or the verified file shows (size) are separate `observed` rows. Frozen settings are not proof of execution or of visually identical output.
- **Visibility and lifecycle.** Images use the shared `MediaInspector` content policy per side and text is redacted through `ContentVisibilityResolver` (re-rendered, not re-fetched, when the mode changes); the viewer uses the keyed latest-wins `EditWorkRunner`, drops results after close or a newer request, and never writes a record, queues a job or touches a draft. Not covered: arbitrary image pairs, grids, video, recursive lineage.

### 3.6.1 More info (NAME-INFO)

**More info** in Review (the selected image), in the compare window (both images) and in Compare with Parent opens a
read-only table: stage path, model (short and full name), prompt pack, prompt number and variant, date, seed, batch
and file name, one column per image. It is the same derivation the phone shows (`src/review/output_info.py`), read on
a worker; values pass through content visibility redaction.

### 3.7 Task-first workspace (PR-REVIEW-LIFECYCLE-621)

Review is one lifecycle: open images, decide each (Retain / Discard / Re-work, with an optional rating), re-work the marked ones through the existing Preview and Queue path, and decide again on the results that return. The tab ID is unchanged; its controls are grouped by task:

| Area | What it holds |
|---|---|
| Set bar | one **Open** menu (Folder, Files, Recent job, Batch), the state filter (Active by default, To review, Retained, Re-work, Archived, All) with counts, hand-off messages and one Help toggle |
| Review | the image list with each image's state and rating, preview, Prev/Next, one contextual **Compare**, Inspect Metadata, Make Video, **Send to** (Learning staged curation, Photo Optimize), **Edit image...** (Inpaint (Edit Mask), Outpaint (Extend Canvas) on the image shown, no mark needed), the decision bar (Retain `R`, Discard `D`, Re-work `W`, Undo `U`, rating), the prompt and provenance panel, Details (quality, subscores), notes and **Apply rating to N selected** |
| Re-work (only while images are marked) | the scope line, stage choices, prompt modes and edits with the Before/After diff, Edit Mask, Extend Canvas, Smart Review, Inspect & Improve, Klein, effective settings, batch options and **Preview and queue...** |
| Returned (only when something returned or failed) | finished children beside their source (verified or labelled unverified), Compare with source, Review result, Re-work again, Refresh, and a pointer to Pipeline > Batches for failed jobs |

State. Only decisions, ratings and inspections are stored, as Learning evidence rows through the single `LearningRecordWriter` (`review_tab_disposition`, `review_tab` and `review_tab_inspection`; section 5.3); a decision is bound to the image bytes (SHA-256) and the latest row wins. A saved inspection (AI-VL-243) is not a decision: it adds the one-line `(inspected: ...)` verdict mark to the image's list row (`ItemFacts.inspection`) and changes no state, filter or re-work scope. Everything about jobs is derived from `JobRepository` each time (`src/review/review_lineage.py`: a job names a source by `parent_artifact_id = sha256:<bytes>`, which is verified, or only by a parent job id, which is shown as unverified; a job claiming different bytes is not a child). The states are To review, Retained, Archived, Re-work marked, Re-work queued, Re-work failed, Returned and Changed since reviewed; after a restart they are re-derived from the evidence file and the repository, so nothing else is persisted and nothing can drift. A source whose re-work finished after its mark is Returned (awaiting a decision) and leaves the re-work scope; a newer mark puts it back (`decided_at` in the disposition record orders the two).

Rules.
- **Nothing is deleted or rewritten; Discard moves the file, reversibly (section 3.7.1).** Discard moves the image into `<output root>/_archive/`; it leaves the default view and appears under Archived. Undo and Restore move it back and record a clearing row (Undo appends the earlier decision, or a clearing row); the writer's delete only handles ratings, so decisions are never removed. Retain and Re-work never touch a file (on an archived image they put it back first). Undo (button or `U`) undoes the most recent of a decision, a saved inspection or a rating; for an inspection it appends a `cleared` row.
- **Re-work is the existing path.** Marked images go to `_reprocess` -> `preview_review_reprocess_batch` -> `ReviewBatchDialog` -> `submit_review_reprocess_batch_async`: one Preview, one `submit_njrs`, each job carrying the batch id, parent job and parent artifact. A failed child is never retried automatically; retrying is Pipeline > Batches. Single-image tools (mask, canvas, Smart Review, Inspect & Improve, Klein) are disabled with a reason while more than one image is marked. The no-preview fallbacks in `_reprocess` (`on_reprocess_images_with_prompt_delta`, `on_reprocess_images`) remain for controllers without the Preview API; production wiring cannot prove them unreachable.
- **The original prompt is the baseline.** `resolve_rework_baseline` (`src/utils/image_metadata.py`) returns the recorded original prompt (stage manifest, then generation); when none was recorded it returns the prompt as sent and the panel says "as sent". The Review display, the effective-settings preview, `prepare_review_batch` and the queued NJR all use it, because the stage optimizer runs again on every stage's prompt. The panel (`src/review/effective_prompt.py`) shows original and final prompts per stage and the ADetailer prompts, or "not recorded", redacted by `ContentVisibilityResolver` in SFW mode.
- **Open > Recent job / Batch** resolve outputs through the existing output resolution (`resolve_job_outputs`) and load them with `load_selected_images` (the Replace/Cancel rule of section 3.1a applies).
- **Threading.** Hashing, the file moves of section 3.7.1, the evidence read, the repository child read (`JobRepository.read_review_child_rows`, read-only, bounded by `REVIEW_CHILD_LIMIT`, keeping the newest rows when it is cut; there is no index on the parent columns, so it scans the table) and every decision write run on `EditWorkRunner` workers; a late result of a superseded set or a closed tab is dropped. A refresh never overwrites a decision, Undo/Restore or rating recorded after that refresh began (its lineage is still applied), and an image whose path, size and mtime are unchanged is hashed and its embedded job id read once per set (`FileFactsCache`), so the 5 s poll re-reads the repository, not the files; a replaced file is read again, which keeps "Changed since reviewed" working. The batch rating save (Apply rating to N selected) reads its Tk values once and hashes, reads metadata and saves off the Tk thread. While a re-work job is queued or running the tab re-reads the repository every few seconds; it never submits.
- The decision UI needs the Learning evidence writer, which the Learning tab owns; Review reaches it through `_resolve_learning_controller()` (`learning_record_writer` or `_learning_record_writer`): documented debt, and decisions are disabled with a reason when it is not connected.

Live-app acceptance of this lifecycle (owner-run, on a copy of real outputs): `docs/runbooks/review_lifecycle_live_acceptance.md` (PR-REVIEW-ACCEPT-624).

### 3.7.1 Discard archives the file (PR-REVIEW-ARCHIVE-623)

Owner decisions (2026-11-16): Discard archives and never deletes; "archive" is a physical move; the archive is one central folder. `src/review/archive.py` (Tk-free; blocking, so only on the Review worker) plans and applies every move: `plan_archive` / `plan_restore` are read-only, `apply_archive` / `apply_restore` move, `archived_location` and `archived_reason` answer "was this archived?" for readers. There is no new store or ledger: the archive path is a function of the original path, and the original is derived from it.

- **Location.** `<output root>/_archive/<path relative to the output root>`, using the application's output-root resolution (`output_dir`, route folders stripped). A file outside the output root goes to `_archive/_external/<drive letter>/<path without the drive>` (UNC under `_external/_unc/<server>/<share>/...`, POSIX under `_external/_posix/...`). `_archive` is deliberately not in `KNOWN_OUTPUT_ROUTE_DIRS`.
- **Move rules.** Same-volume `rename_without_replace` only (a cross-volume file is not moved), never an overwrite, never a copy-then-remove; the SHA-256 is verified after the move and a changed file is put back. A different file already at the target keeps both: the incoming one is named `<stem>.<first 8 of sha256><suffix>`; an identical one leaves the source in place and reports the duplicate. `<image>.review.json` travels with its image (never replacing one already there); manifests stay. A sharing violation (WinError 5, 32, 33) is retried briefly. Empty archive folders are left in place after a Restore (nothing is deleted).
- **Refusals.** The image is still discarded (hidden, under Archived) but stays where it is, with the reason shown in the status line (and `(not moved)` in its row): a different volume; a queued or running job lists it as an input (`active_input_paths` over `JobQueue.list_active_jobs_ordered`; an unreadable queue fails closed); it is inside the Photo Optimize workspace or the Learning discovered store; the file or a folder on its path (from the output root down, or every ancestor for an external file) is a link, junction or reparse point; it is already in the archive; it cannot be hashed. Pressing Discard again retries (for example after the job finished). A job admitted between the check and the move is not covered: replay and batch retry then report the file as archived.
- **Restore** (and Undo, Retain, Re-work on an archived image) moves the file home first, then records; a refused restore records nothing. When a different file now sits at the original path nothing is replaced: the tab offers a free name (`<stem>.restored-<8 of sha256><suffix>`) and, if accepted, adds that file to the set. An identical file at the original keeps the archived copy and says so.
- **Review.** `ReviewWorkspaceSession` records the decision, then moves on the existing `EditWorkRunner` worker, after the view has advanced off the image. Where a file is comes from the file system on every refresh (`FileFactsCache` reads an archived image from its archive location, so the digest and the evidence lookup still resolve by original path and digest). Open > Recent job and Open > Batch add outputs Review archived to the set (listed under Archived, restorable there; the status says how many). The Archived filter lists images from their records when a folder was opened (images discarded from it whose file is now only in the archive), each row saying `(in archive)` or `(not moved)`; an archived image is never loaded for preview. Discarding several highlighted images asks once (an injectable confirmation; tests never open a real modal).
- **Readers never read the archive.** When a recorded image is absent and its archived copy exists, History's artifact projection, Compare with Parent (`verify_image`), replay and batch-retry input verification (`verify_inputs`) and Batches output resolution (`resolve_job_outputs`) say "archived by Review; Restore to use it" and use nothing. `resolve_output_artifact_path` never resolves into `_archive`. Readers find the archive from the recorded path itself (an `_archive` folder beside one of its ancestors) and, for a file outside the output root, from the configured output root (`output_dir` in `presets/settings.json`, default `output`; read directly, `ConfigManager` is not built), so an archived external input is reported too. The copy is never hashed or opened.
- **Enumerators skip the archive:** `scan_image_folder` (default: the configured archive; opening the archive folder on purpose still lists it), `OutputScanner` (`<root>/_archive`) and `iter_output_run_dirs`.
- **Same path, several discards.** The archive keeps every file ever discarded from a path (a different file at an occupied archive name is named `<stem>.<8 of sha256><suffix>`). An item resolves to the copy whose digest the latest Discard record for that path names, so Restore and Undo return the last-discarded file, also after a refresh or restart; older copies stay in the archive and the status line says an earlier file is also there (`ItemFacts.other_archived`).
- **Known debt.** A multi-image Discard runs on one worker job, one image after another; one image's refusal does not stop the rest. A job admitted between the queue check and the move is not covered; a job input named by an 8.3 short name will not match.
- **Limits.** Video, frame folders and multi-image jobs are not covered. Behaviour on network drives and cloud-synced folders is not demonstrated (a reparse point, as cloud placeholders are, is refused). No deletion or emptying of the archive exists. A re-work result that was discarded leaves the Returned table (output resolution reports it archived). If two different files are discarded from the same original path, the later one is archived under the digest-suffixed name and nothing is lost; Restore brings the latest-discarded one back to the path and puts every earlier one beside it as `<stem>.restored-<8 of sha256><suffix>` (never over an existing file; the status line names them).

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

`AppController._extract_reprocess_baseline_from_image` returns `{stage, prompt, negative_prompt, model, vae, config}` from `resolve_prompt_fields`, `resolve_model_vae_fields` and `stage_manifest.config`, or `{}` on any non-`ok` status. These resolvers walk many alias keys and history entries in a fixed precedence (stage manifest, generation, stage config, history, top level). The Review display, the effective-settings preview, `prepare_review_batch` and the queued NJR all take the prompt from `resolve_rework_baseline`, which prefers the recorded *original* prompt over the optimized final prompt (section 3.7). Consequences:
- An image without a StableNew payload still reprocesses, with `baseline_source` `fallback` (or `fallback (metadata <status>)` when the payload exists but is unreadable) and the live stage config. The preview shows that origin per row.
- The model recorded in the artifact wins over the live pipeline model; preview and submission use the same precedence (`effective_model`).
- Never infer a profile from the file name; `normalize_image_backend_options` resolves it from the resolved model name.

### 5.3 Review evidence does not rewrite the image [V]

PR-REVIEW-EVIDENCE-620 (owner decision 2026-11-15). `LearningController.save_review_feedback` delegates to `src/review/review_evidence.py` and appends one `review_tab_feedback` record through `LearningRecordWriter.append_record`; it never opens the image for writing. The record carries `artifact_sha256` (the SHA-256 of the bytes Review showed, hashed in the image-context worker, or by the controller for other images; the path stays as a locator) and `source_job_id`. A path that cannot be read yields a path-only record. `rating_revision_key` keys a digest-bound row by `sha256:<digest>`, so the same bytes at two paths are one rated sample, and legacy rows without a digest stay keyed by path. A `review_disposition` record kind (retain / discard / rework; latest row wins per digest; read/write API only, no UI yet) is bound the same way (read/write API in `review_evidence.py`; the Review workspace's decision bar writes it, section 3.7); it uses its own `source`, so rating lists and Undo ignore it, and the recommendation engine's record-kind allow-list ignores it.

A `review_inspection` record kind (AI-VL-243, owner decision D25; written by Inspect & Improve's **Save inspection** / **No defect seen**, section 3.3.3) is bound to the bytes the same way and has its own `source` (`review_tab_inspection`), so rating listing, disposition lookup and Undo Last Save never see it. `metadata`: `inspection_schema` `stablenew.review-inspection` and `inspection_schema_version` 1, `artifact_sha256`, `verdict` (`no_defect_seen`, `defects_confirmed`, or `cleared` written by Undo), `findings[]` of exactly `{category, region [left, top, right, bottom] | null, certainty, severity minor | major | null}`, `subject_count` (1 to 12 or null), `reviewed_at`. Only operator-Confirmed findings are stored and **no observation text, origin or suggestion label** is: reading refuses any finding with another key. Latest row per digest wins; a row for different bytes is reported `changed` and never applied. `lookup_inspection`, `EvidenceIndex.inspection` and `EvidenceIndex.inspection_rows` read it; `tools/qualification/vl240` exports it (`docs/runbooks/ai_visual_real_set.md`). `Finding` has an optional `severity` that nothing else serializes.

Reading (`get_prior_review_summary`, used when an image is shown): by digest, then by path (a legacy row, `identity_status` `path`), then the legacy embedded or sidecar stamp. A path whose rating was recorded for different bytes is returned as `identity_status: "changed"` only when nothing else describes the file; Review says so and leaves its rating controls unrated. Review loads the saved rating into its controls when an image is shown and resets them to the unrated state (3 / 3 / 3, "okay", no notes) first, so an unrated image never shows the previous image's values.

The explicit **Write rating to file...** action (beside Undo Last Save) (`write_rating_into_file`) is the only way a rating reaches a file now: PNG is embedded (the file's bytes, and so its identity, change; History lineage, Compare with Parent and Review Preview treat it as a different file, and Review asks first and says so); JPEG and WebP get a `<image>.review.json` sidecar and are never re-encoded (before this change a JPEG was re-encoded, so both its bytes and its pixels changed on every save). Files already stamped, and existing records, are not migrated or rewritten.

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
| `src/photo_optimize/managed_import.py` | `plan_managed_import` (read-only: existence, type, decode, SHA-256, existing managed asset with identical bytes) and `apply_managed_import` (operator-confirmed; uses the store's existing `import_photo`; originals untouched; no lineage) |
| `src/gui/view_contracts/photo_baseline_save_contract.py` | `PhotoBaselineSaveSession`: per-photo ordered, coalesced, conditional baseline saves with truthful status (no Tk) |
| `src/gui/views/photo_optimize_tab_frame_v2.py` plus mixins `photo_optimize_layout.py`, `photo_optimize_scope.py`, `photo_optimize_results.py`, `photo_optimize_editors.py`, `photo_optimize_handoff.py` | Tk tab; the mixins are presentation only |
| `src/gui/view_contracts/photo_optimize_layout_contract.py` | Pure fit rules: `choose_body_mode`, `body_placements`, `flow_rows`, `selection_summary` (no Tk) |

### 6.2 Submission

1. The Tk thread captures the live Pipeline settings (`AppController.build_photo_optimize_defaults` -> `pipeline_defaults`) and the selected assets' baselines.
2. A worker (`_run_photo_operation`) runs `prepare_photo_optimize_plan` -> `prepare_photo_plan`. Per asset it normalizes aliases, resolves geometry from the decoded working image (Auto = image size, Custom = validated width/height), validates numbers, applies prompt deltas, and partitions assets by stage plan. Each partition is compiled by `build_grouped_reprocess_jobs` with `source="photo_optimize_tab"` and `extra_metadata["photo_optimize"]` (run id, per-asset effective prompts, frozen `config_snapshot`, `geometry_policy`).
3. The operator reviews the frozen per-photo targets (`review_dialog`). Confirmation submits that exact plan with no recompilation (`submit_prepared_photo_plan` -> `submit_reprocess_njrs`), so exact-profile refusal is the shared one.
4. On completion, `AppController._handle_photo_optimize_completion` (registered through `_create_photo_optimize_completion_handler`) maps `extract_reprocess_output_paths` to assets by index and calls `PhotoOptimizeStore.record_optimize_history`, which copies outputs and manifests into the asset directory, records SHA-256 per output, and is idempotent per (run id, job ids).

### 6.2a Layout

- Header: a one-line role statement ("Managed Photo Set - persistent per-photo settings and results ...", flow and scope in its tooltip: Active photo = the one being edited, Selected photos = highlighted rows, All visible = every unarchived photo), then a primary row (Import Photos, Review Selected, Review All Visible, a **More actions** disclosure, and the selection line `Single Photo: <name> | Batch: N selected | M visible`) plus always-visible submission and migration status text. Refresh, Open Selected in Quick Edit, Review Pipeline Copy, Interrogate, the batch-size spinbox and Migration Details/Retry sit in the collapsible "More actions" section. A migration summary containing "incomplete" expands it automatically. Header items wrap into rows with `flow_rows` (placed, never clipped); status labels wrap to the header width.
- Body: assets, previews and the editor are three existing regions that `_apply_body_layout` re-grids into `wide` (side by side), `split` (assets over previews, editor beside them) or `stacked` (one column with section headings) by `choose_body_mode`. The decision compares each region's minimum width (character widths of the real label font, so it follows Tk scaling, plus the 2 x 200 px preview floor) with the width the body actually has; there is no screen-size breakpoint. The body scrolls vertically through `ScrollableFrame`; regions keep their natural height instead of stretching to the editor.
- Resizing only calls `grid`/`place` on existing widgets. It never recreates or reparents a region, so selection, typed text, baselines and the sidecars are untouched.
- Review Selected / Review All Visible still call `_optimize` (prepare -> `review_dialog` -> `submit_prepared_photo_plan`); layout owns no execution path.

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

### 6.6 Baseline saves and Quick Edit hand-offs (PR-GUI-UX-580)

- **Saving the active photo.** Edits mark the draft dirty and start a 400 ms debounce (`BASELINE_SAVE_DEBOUNCE_MS`); focus-out saves at once. The view captures an immutable `BaselineDraft` (pure, no file access) and `PhotoBaselineSaveSession` sends it to the store on a worker: one asset at a time in submission order, a burst coalesced into the latest draft, the draft always naming its asset (a delayed write cannot land on another photo). The write is conditional on the baseline the form was loaded against (`update_asset_fields(..., expected_baseline=...)`, `StaleBaselineError`), so a stale form can never replace a newer promotion, revert or batch edit; the refusal is shown ("Not saved: ...") and the edit is not reported saved. `baseline_save_status_var` reads Saved / Unsaved changes / Saving... / Not saved.
- **Sidecar locking.** `PhotoOptimizeStore.asset_lock` is one reentrant lock per asset; `save_asset`, `update_asset_fields`, archive, restore, promotion, revert, `record_optimize_history` and Batch Edit's check-then-write take it, and `save_asset` now writes through `src/utils/atomic_io.py`. It is a store-local lock, not a transaction authority; there is still no cross-process lock (one app instance per workspace is assumed).
- **Active photo and list clicks.** Clicking a photo in the list (or moving to it with Up/Down) makes it the active photo, so Preview & Asset Metadata and the Single Photo editor follow it; plain, Ctrl and Shift clicks all show the clicked row when it ends up highlighted. Removing a highlight (Ctrl-click on a highlighted row), the Active Single Photo chooser and a selection change without a click (refresh, restored state) keep the active photo. The row is noted by widget `<ButtonPress-1>` / `<KeyPress-Up|Down>` bindings, which run before Tk's Listbox class bindings send `<<ListboxSelect>>`.
- **Stages a photo runs.** Each photo runs its own saved stage choices. Import copies the live Pipeline's stage toggles, and when none of img2img / ADetailer / Upscale is on there (a txt2img Pipeline) the photo is imported with img2img on (`runnable_stage_defaults`). Review Selected / Review All Visible from the Batch Edit workspace first saves its checked fields to the selected photos through the same reviewed, fingerprinted `prepare_edit` / `apply_edit` as "Review selected-photo changes..." (one confirmation listing every change; skipped when nothing would change; cancelling saves and queues nothing; a partial save stops before the queue plan), then reviews the queue plan. Single Photo scope never applies pending Batch Edit fields. Photos with no stage are refused together, by file name, with the fix.
- **Waiting for a save.** Preparing a plan, promotion, revert, Batch Edit preparation and Interrogate run only after the active photo's write settles (`_with_saved_baseline`); a failed write stops the action with the reason. Closing the tab sends a pending draft to its worker first.
- **Quick Edit -> Managed Photo Set.** Review's "Manage Selected Photos..." sends the Listbox's highlighted images (explicit selection, list order) through `route_images_to_photo_optimize` (the single navigation owner is `video_workspace_handoff`) to `receive_review_handoff`. A worker plans the import (`plan_managed_import`: content SHA-256 identity, never filename; refused rows carry a reason), the operator confirms exactly what would be copied (new / already managed / refused; for already-managed images either open the existing asset or import a separate copy), and only then does a worker import with `_build_import_defaults()` (Photo Optimize's own baseline authority). Nothing is copied or queued before confirmation, the result selects the imported and opened photos and lists per-file outcomes, and Review keeps its selection, edits and History claim. Only paths cross: History lineage never reaches a managed asset.
- **Managed Photo Set -> Quick Edit.** "Open Selected in Quick Edit" resolves the selected photos' current working images on a worker and calls `route_images_to_review`; Review asks Replace/Cancel for unsent work. A managed photo carries no History lineage into Review.

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
- Rule 9 (filesystem lookups through latest-wins background services) is now met by the Review folder scan, image context and comparison (section 3.1a); remaining exceptions are listed under D5.

## 8. Known debt and traps

Audit GUI findings as they stand on these surfaces:

- **D3 composition roots and two-way coupling** [A, V examples]: `ReviewTabFrame._resolve_learning_controller` walks `app_controller.main_window.learning_tab`; the batches panel builds its own service in `pipeline_tab_frame_v2.py`. Shared Review policy is now `src/review/workflow_adapter.py`, imported directly by `AppController`, `ReviewBatchService`, Photo Optimize and Tk consumers; those policy imports no longer contribute controller-to-GUI debt. The remaining composition-root and two-way controller coupling is unchanged (audit P3-2).
- **D4 tab failures swallowed** [A, partly fixed V]: `MainWindowV2.add_tab` now logs the traceback and shows an error placeholder naming the tab. A failure of `center_notebook.add` is now logged, recorded in `MainWindowV2.tab_failures()` and leaves the tab unregistered (PR-GUI-410).
- **D5 blocking work on the Tk thread** [A, V]: PR-GUI-UX-580 moved the Photo baseline save (debounced, ordered, conditional; section 6.6), the Photo asset list and per-photo sidecar reads, plan preparation's asset reads, the Review folder scan, per-image metadata and ADetailer-pair lookup, and the comparison composite off Tk. Still on the Tk thread: (a) `AppController.get_review_reprocess_effective_settings_preview` (Tk-bound `_build_reprocess_config`; `AppController` is at its line ceiling, so it was not touched); (b) Photo archive/restore, Interrogate, and the single-image Review feedback save (the batch rating save and the decision writes are off Tk, section 3.7); (c) `HistoryIterateService.edit_in_review` hashes the recorded image synchronously (History's own Replace/Cancel flow is synchronous, so moving it off Tk would change that contract; recorded rather than changed by PR-GUI-UX-580). Already off-thread: Review preview and admission, Photo prepare/submit/promotion/result thumbnails, batch repository reads. Fix direction: audit P4-7.
- **D6 background-work patterns** [A, V]: these surfaces use four: `BackgroundTaskCoordinator` (Review), `BackgroundWorkRunner` (Batches), `ThreadPoolExecutor` polled with `after(50)` (Photo tab workspace and operations, result previews), and `ThreadRegistry.spawn` per thumbnail (one non-daemon thread per decode, no pool, no cache). The architecture baseline in `tools/ci/` caps raw and daemon threads but does not unify the patterns.
- **D10 polish** [V]: the tab and window titles are corrected (PR-GUI-410: "Photo Optimize", "StableNew"); the import file dialog title in `photo_optimize_tab_frame_v2.py` still says "Photo Optomize". `ReviewTabFrame` has 52 `messagebox.show*`/`ask*` call sites, including a modal "Saved" after each feedback save [V count of call sites].

Other traps found while reading:

- Two parallel precedence implementations in `ReprocessJobBuilder`: `_resolve_stage_*` (used to build the job) and `_resolve_stage_*_with_source` (used by the preview). They must change together or the preview will describe different values than the job carries [V].
- Three independent default tables for the same stages: `ReprocessJobBuilder.DEFAULT_STAGE_VALUES`, Photo `FIELDS` fallbacks, and the executor's own fallbacks (see `IMAGE_PIPELINE.md` section 11). For example img2img defaults to 15 steps in the builder but 20 in Photo `FIELDS` [V].
- `prepare_photo_plan` has a filesystem side effect: its `output_dir_factory` calls `PhotoOptimizeStore.create_staging_run_dir`, so previewing a plan that is never submitted leaves empty `staging_runs/` directories [V].
- Photo history is recorded only by the in-process completion handler for COMPLETED jobs; no code reconciles a job that finished while the app was closed [V: `record_optimize_history` has one caller].
- Persistence: `PhotoOptimizeStore.save_asset` now writes through `src/utils/atomic_io.py` under the per-asset lock (PR-GUI-UX-580); `write_review_sidecar` still uses plain `write_text` [V]. The audit (B4) lists the photo store as already safe [A]; that is only partly true. `PhotoOptimizeStore._read_asset` returns `None` on any exception, so a corrupt sidecar silently disappears from the list.
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
| Iterate from History | `tests/pipeline/test_history_variation_compiler_610a.py`, `tests/queue/test_history_variation_lineage_610a.py`, `tests/controller/test_history_variation_preview_610a.py`, `tests/gui_v2/test_history_iterate_model_610a.py`, `tests/gui_v2/test_history_iterate_service_610a.py`, `tests/gui_v2/test_history_iterate_gui_610a.py` | Real Tk and `AppStateV2`, temp SQLite, fake runner; synthetic PNGs |
| Compare with Parent | `tests/gui_v2/test_history_compare_610b.py` | Real Tk, temp SQLite, synthetic PNGs; threaded work for ordering and late delivery |
| Batch membership, catalog, cancel, retry atomicity | `tests/queue/test_batch_membership_201.py`, `tests/queue/test_batch_catalog_201.py`, `tests/queue/test_batch_cancel_201.py`, `tests/queue/test_batch_admission_atomicity.py`, `tests/controller/test_batch_operations_service_201.py` | Temp SQLite repository |
| Batches view | `tests/gui_v2/test_batch_operations_session_201.py`, `tests/gui_v2/test_batch_operations_view_201.py`, `tests/gui_v2/test_batch_operations_review_handoff_201.py` | Session tested without Tk |
| Photo store, settings, migration, editing, promotion | `tests/photo_optimize/` (`test_photo_220.py`, `test_photo_optimize_store.py`, `test_migration_recovery_221.py`, `test_scope_editing_222.py`, `test_historical_results_223.py`) | Temp workspace roots; never the operator workspace |
| Photo tab | `tests/gui_v2/test_photo_optimize_tab_v2.py`, `tests/gui_v2/test_photo_scope_222.py`, `tests/gui_v2/test_photo_results_223.py` | Headless projection where possible |
| Quick Edit / Managed Photo Set (PR-GUI-UX-580) | `tests/gui_v2/test_review_async_580.py`, `tests/gui_v2/test_photo_baseline_save_580.py`, `tests/gui_v2/test_photo_save_gui_580.py`, `tests/gui_v2/test_edit_handoff_580.py`, `tests/photo_optimize/test_managed_import_580.py` | `tests/gui_v2/edit_work_helpers.py` (`ManualRegistry` runs a worker when the test says; `HeldDelivery` holds the UI-thread delivery so a result can arrive after the operator moved on); the autouse `inline_edit_work` fixture in `tests/gui_v2/conftest.py` runs this work inline everywhere else |
| Thumbnails | `tests/gui_v2/test_thumbnail_widget_v2.py`, `tests/gui_v2/test_thumbnail_tooltip_recovery_111.py` | Fake loader |
| Metadata contract and review stamping | `tests/utils/test_image_metadata_contract.py`, `tests/review/test_review_metadata_service.py`, `tests/review/test_artifact_metadata_inspector.py` | Synthetic PNG/JPEG |
| Task-first Review workspace (PR-REVIEW-LIFECYCLE-621) | `tests/review/test_review_workspace_621.py`, `tests/review/test_review_lineage_621.py`, `tests/gui_v2/test_review_lifecycle_621_gui.py` | Temp records file and temp SQLite; the session is tested without Tk; the GUI tests reuse the `test_review_batch_200.py` fixture and assert files are byte-identical |
| Reversible Review archive (PR-REVIEW-ARCHIVE-623) | `tests/review/test_review_archive_623.py` (every move, refusal and no-data-loss path), `tests/review/test_review_archive_session_623.py`, `tests/review/test_review_archive_readers_623.py` (History, Compare, replay, batch retry, output resolution, enumerators), `tests/gui_v2/test_review_archive_623_gui.py` | Temp output roots and synthetic images only; injected rename, hash, volume and queue probes; GUI tests always set `tab._output_root` to a temp root and answer confirmations through `_confirm_discard_hook` / `_confirm_alternative_hook` |
| Non-mutating, digest-bound Review evidence (PR-REVIEW-EVIDENCE-620) | `tests/review/test_review_evidence_620.py`, `tests/gui_v2/test_review_evidence_620_gui.py`, `tests/gui_v2/test_history_iterate_service_610a.py`, `tests/gui_v2/test_history_compare_610b.py` | Temp records file; assert file SHA-256, size and pixels unchanged after rating |

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
