# Learning subsystem

Status: living document, edit in place
Owner area: designed experiments, ratings, recommendations, discovered-output review, staged curation (`src/learning/`, `src/curation/`, `src/gui/controllers/learning_controller.py`, the Learning tab under `src/gui/views/`)

How to keep this true:
- Change this file in the same PR that changes Learning behavior, ownership, a record kind, a persisted location or a safety rule. Edit the existing row or sentence.
- Do not append per-PR sections, dates or test counts. History lives in `git log` and the per-PR records listed at the end.
- Labels: **[V]** read in the code when this was written; **[A]** taken from `docs/audits/2026-10-16_repo_audit_and_roadmap.md`, not re-checked.

## 1. Scope and the canonical path

Learning is a post-execution subsystem plus a thin experiment designer. It designs controlled one-variable image experiments, turns them into ordinary queued jobs, collects ratings and review/curation decisions as evidence records, and derives advisory parameter recommendations. It also reviews outputs that were not produced by an experiment (Discovered Outputs) and advances chosen candidates through derived stages (Staged Curation). Video Workflow experiments are reviewed by hand and the review is kept as separate evidence (section 3.3) that never feeds recommendations. One bounded multi-variable study exists, the exploratory Two-Axis Grid (section 3.7); automated video learning, three-axis sweeps and automatic tuning do not exist.

Learning adds no queue, runner, history or compiler authority. Every job it creates is an NJR submitted through `JobService.submit_njrs`:

| Step | Learning-specific reality | Where |
|---|---|---|
| Intent | An experiment definition (`LearningExperiment`: stage, variable, values, images per value, prompt source) frozen by Build Preview into canonical JSON; or a staged-curation advancement; or a Model Comparison study | `src/gui/learning_state.py`, `src/learning/experiment_execution.py`, `src/learning/model_comparison.py` |
| Compiler | txt2img variants: `LearningController._build_variant_njr` builds the NJR itself (section 9, debt). img2img/adetailer/upscale variants: `ReprocessJobBuilder.build_reprocess_job(source="learning")`. Model Comparison: `materialize_njr`. Curation: `CurationWorkflowBuilder` plus `ReprocessJobBuilder`. All call the canonical `apply_model_compile_policy` seam (via `compile_variant`) | `src/gui/controllers/learning_controller.py`, `src/pipeline/reprocess_builder.py`, `src/learning/model_comparison.py`, `src/curation/curation_workflow_builder.py` |
| NJR | `SourceKind.LEARNING`, `LearningJobContext` in `NJRProvenance` (experiment id/name, variant index, variable, value) | `src/pipeline/njr_core_v26.py` |
| JobService | Experiments: one `submit_njrs(records, SubmissionPolicy())` per Run through `LearningExecutionController.submit_experiment_jobs`. Curation: `submit_reprocess_njrs` (whole-batch operation preflight, then one `submit_njrs`) | `src/learning/execution_controller.py`, `src/controller/reprocess_admission.py` |
| Queue/Repository, Runner, Handler | Unchanged. The runner only reads `learning_context` to choose the output folder and file prefix (`build_learning_folder_label`, `build_learning_filename_prefix`) | `src/pipeline/pipeline_runner.py`, `src/learning/experiment_naming.py` |
| Artifacts/History | Images and manifests as for any job; Learning adds evidence records (section 4) and never rewrites a historical artifact or NJR | section 4 |

Compile first, then admit once: `ExperimentAdmissionService.compile_all` builds every NJR before the single `submit_njrs`, so a compile or validation failure admits no variant. Learning checks the returned IDs against the compiled NJRs before marking them queued and immediately checkpoints their variant associations through the existing atomic session stores. An exception or inconsistent admission response triggers exact-ID repository reads: proven absence leaves the compiled draft pending, while existing or unreadable records retain their IDs with visible attention guidance and no automatic retry. After admission each NJR has the normal independent SQLite lifecycle [V: `LearningController.run_plan`, `LearningExecutionController.submit_experiment_jobs`].

## 2. Where things live

### 2.1 `src/learning/` (about 8.4k lines; no Tk widgets)

| Concern | Module (key symbols) |
|---|---|
| Frozen preview and admission | `experiment_execution.py` (`freeze_snapshot`, `thaw_snapshot`, `snapshot_digest`, `ExperimentAdmissionService`); `experiment_freeze.py` (`freeze_prompt_pack_source`, `freeze_seed_policy`, `apply_frozen_seed_policy`, `seed_vector_matches`); `ordinary_prompt_freeze.py` (`freeze_ordinary_prompt_source`, `freeze_preview_global_policy`, `validate_ordinary_prompt_snapshot`, `apply_executor_base_prompts`) |
| Model/profile validation | `model_policy_service.py` (`validate_experiment`, `compile_variant`, `frozen_definition`, `recommendation_query`, `validate_recommendation_apply`); `model_capabilities.py` (`policy_context`, `project_learning_capabilities`, `compatible_context`). Canonical `ModelPolicy` (`src/image_backends/model_policy.py`) owns every capability fact; Learning only projects it |
| Stage and variable catalogue | `stage_capabilities.py` (`get_stage_capability`, `list_supported_stages`: txt2img, img2img, adetailer, upscale); `variable_metadata.py` (`VariableMetadata`, `get_variable_metadata`: config path, type, resource key); `variable_selection_contract.py` (stable internal values vs display labels); `resource_access.py` (reads the live `AppStateV2.resources` projection, never the WebUI); `lora_variant.py`, `lora_variable_service.py` (LoRA strength/identity variants, executed-prompt proof) |
| Model Comparison | `model_comparison.py` (`build_comparison_snapshot`, `verify_arms_admissible`, `frozen_arm`, `materialize_njr`, `rating_classification`, `runtime_prompt_readback`, `RECORD_KIND`); `model_evidence_readiness.py` (`prepare_comparison_evidence`: refresh checkpoint evidence through `AssetRegistry`) |
| Two-Axis Grid | `two_axis_grid.py` (`parse_axis`, `plan_cells`, `build_grid_snapshot`, `frozen_cell`, `materialize_njr`, `rating_classification`, limits); `grid_results.py` (`build_grid_model`: exact cell/job/artifact projection, placeholders, visibility); `grid_contact_sheet.py` (`render_contact_sheet`, `export_contact_sheet`, bounded `load_thumbnail`); `learning_njr.py` (`assemble_txt2img_njr`, the one assembly Model Comparison and the grid share) |
| Execution tracking and recovery | `execution_controller.py` (`LearningExecutionController`: sole job-to-variant callback owner, admission integrity, serialized restore/completion); `experiment_reconciliation.py` (exact repository lookup, immutable Learning identity/snapshot checks, evidence and status projections) |
| Evidence records and ratings | `learning_record.py` (`LearningRecord`, `LearningRecordWriter`, `extract_rating_detail`); `rating_schema.py`; `learning_record_builder.py` (record from a pipeline run result); `learning_profile_sidecar.py` |
| Recommendations | `recommendation_engine.py` (`RecommendationEngine.recommend`, `RecommendationSet`, evidence tiers); `staged_recommendations.py` (`build_derived_recommendation_patch`, `apply_derived_recommendation_patch`); `model_profiles.py` (style priors, not `ModelPolicy`; the name-substring GUI defaults and `model_defaults_resolver.py` were removed. Generation recommendations now live in `src/generation_profiles/`, whose `GenerationProfileStore.publish_learning_profile` is the narrow seam a later Learning package uses to publish immutable Learning profile revisions) |
| Persistence | `experiment_store.py` (`LearningExperimentStore`), `discovered_review_store.py` (`DiscoveredReviewStore`), `learning_paths.py`, `learning_controller_services/experiment_persistence.py` (resume payload helpers), `experiment_lifecycle.py` (Draft/Queued/Review Needed/Complete classification) |
| Discovered outputs | `output_scanner.py` (`OutputScanner.scan_incremental`), `output_scan_models.py`, `discovered_scan_service.py` (`apply_scan`), `discovered_grouping.py` (`GroupingEngine`), `discovered_review_models.py` |
| Guided workflow presentation (PR-LEARN-UX-590; pure, no Tk, no persistence) | `guided_workflow.py` (`project_guided_workflow`: Design/Preview/Run/Compare/Rate step states, the one primary action and notices, derived each refresh from experiment/plan/rating facts; `build_rating_progress`); `preview_summary.py` (`build_preview_summary`: counts and rows read from the frozen snapshot); `design_estimate.py` (`estimate_design`: variants x images before any Preview); `recommendation_summary.py` (`build_recommendation_summary`, `apply_availability`: setting, scope, tier, confidence and why Apply is or is not offered). They restate facts other modules computed and add no gate |
| Review and analytics | `review_workspace.py` (`build_review_projection`), `experiment_conclusion.py`, `learning_analytics.py` (`LearningAnalytics`, JSON/CSV export), `experiment_naming.py` |
| Legacy plan runner | `learning_plan.py` (`LearningPlan`, `LearningMode`), `learning_runner.py` (`LearningRunner`, a stub that fabricates pending artifacts), `learning_execution.py` (`LearningExecutionRunner`), `learning_adapter.py`, `learning_contract.py` (placeholder optimizer presets). Not the experiment path; see section 9 |
| Other | `run_metadata.py` (`write_run_metadata`, called by the runner), `feedback_manager.py` and `learning_feedback.py` (no callers in `src`), `dataset_builder.py` (`build_learning_dataset`; its former `src/ai` consumer was retired) |

### 2.2 GUI and controller layers

| Concern | Location |
|---|---|
| The coordinator | `LearningController` in `src/gui/controllers/learning_controller.py` (about 4k lines). Experiment design/plan, Run, ratings and drafts, recommendations and Apply, review feedback from the Review tab, discovered inbox, staged curation, resume state, background scan |
| UI state | `LearningState`, `LearningExperiment`, `LearningVariant` in `src/gui/learning_state.py` (dataclasses with `to_dict`/`from_dict`; `review_drafts` live here) |
| The live tab | `LearningTabFrame` in `src/gui/views/learning_tab_frame_v2.py`, three notebook tabs: Designed Experiments (`ExperimentDesignPanel` in `experiment_design_panel.py`, `LearningPlanTable` in `learning_plan_table.py`, `LearningReviewPanel` in `learning_review_panel.py`), Discovered Outputs (`discovered_review_inbox_panel.py`, `discovered_review_table.py`), Staged Curation |
| Two-Axis Grid views | `grid_design_frame.py` (`TwoAxisDesignFrame`: axes, values or ranges, fixed LoRA, live cell/image totals) inside `ExperimentDesignPanel`; `learning_grid_view.py` (`LearningGridView`: the Comparison Grid pane, lazy thumbnails on a tracked worker, Export Contact Sheet) added to the workspace panes by `LearningTabFrame` only while a grid experiment is open |
| Guided workflow widgets | `LearningWorkflowBar` (`learning_workflow_bar.py`: five step buttons, status, headline, the single primary button) and `LearningPreviewCard` (`learning_preview_card.py`) render the projections above; `LearningTabFrame` owns the tab-local viewed step and the pane layout per step |
| Analytics window | `learning_analytics_panel.py` opened from the review panel's View Analytics |
| Recommendation target map | `src/gui_v2/recommendation_targets.py` (`recommendation_target`, `checkpoint_for_stage`, `prepare_recommendation_patch`) |
| Curation domain | `src/curation/` (`models.py`, `curation_workflow_builder.py`, `curation_manifest.py`, `workflow_summary.py`, `learning_bridge.py`: `CurationLearningBridge` turns a `SelectionEvent` into a `staged_curation_event` record) |
| Review tab entry | `src/gui/views/review_tab_frame_v2.py` calls `save_review_feedback`/`undo_review_feedback` on the learning controller; `src/gui/controllers/review_workflow_adapter.py` hands curation selections to Review |
| Completion routing | `src/controller/app_controller_services/learning_completion_router.py` |

## 3. Workflows

### 3.1 Designed experiment (txt2img, img2img, adetailer, upscale)

1. `ExperimentDesignPanel` collects stage, variable, value spec and prompt source and calls `LearningController.update_experiment_design`, then `build_plan` (Build Preview).
2. `build_plan` captures the effective baseline from the live stage cards once (`_get_baseline_config`), applies the current Global Prompt policy, freezes the prompt source, validates against `ModelPolicy` (`validate_experiment`), freezes the seed policy, and stores everything as canonical JSON in `LearningExperiment.execution_snapshot_json` (schema 2, includes `model_policy_context` and `seed_policy`). The plan is one `LearningVariant` per value.
3. `run_plan` compiles every pending variant without an existing job association from the snapshot (`_build_variant_njr`: variable override via `_apply_variant_override_with_metadata`, `compile_variant` proves the model compile policy did not erase the tested value, `apply_frozen_seed_policy`), then submits all NJRs at once. Confirmed IDs are recorded against the correct variants and checkpointed immediately. A completion that arrives before the submission response stays terminal. A failed checkpoint retains admitted IDs and reports action required with explicit no-retry guidance.
4. Completion arrives through `LearningExecutionController._handle_job_finished` (a `JobService` `job_finished` callback; `AppController` sets `job_service.set_event_dispatcher(self._run_in_gui_thread)` so it runs on the Tk thread) and calls `LearningController._on_variant_job_completed`. That validates seed read-back and LoRA execution; a variant whose readback is missing or inconsistent becomes `uncontrolled` and is excluded from recommendation inference.
5. Review: `LearningReviewPanel` shows completed samples grouped by variant (`build_review_projection`), Next Unrated, side-by-side compare. Ratings are saved with `record_rating` (see 3.3).

Rules that hold [V]: Run never reads live stage cards (only the snapshot); a programmatic caller that skips Build Preview gets a legacy snapshot frozen on first compile; model identity, policy id, family and exact profile are frozen at preview and independently re-validated at Run; changing a live stage-card model does not reinterpret a saved experiment. Saved previews that predate the frozen Global Prompt policy are refused with Rebuild Preview guidance (`validate_ordinary_prompt_snapshot`).

### 3.2 Model Comparison Study

A separate `study_type == "model_comparison"` experiment (`study_type()` in `src/learning/model_comparison.py`): image txt2img, PromptPack-only, at least two distinct registry-evidenced SDXL or exact qualified targets. `build_comparison_snapshot` freezes one row and the first canonical Matrix vector, and every effective arm (policy, structured prompt adaptation, compile policy, path-free `checkpoint_evidence`). Preview first prepares evidence for the exact served checkpoint files (`prepare_comparison_evidence`, cancellable worker, no directory scan or startup hashing). Run validates frozen arms (`verify_arms_admissible`) and builds NJRs with `materialize_njr` without reopening the PromptPack, reading live model evidence or re-running adaptation; all arms compile before one atomic admission. Ratings use record kind `learning_model_comparison_rating` and the claim is `target_envelope_preference` with `causal_one_variable=false`. These ratings and snapshots are excluded from ordinary parameter recommendations and automatic Model selection.

### 3.7 Two-Axis Grid

A `study_type == "two_axis_grid"` experiment compares two of CFG Scale, Steps and LoRA Strength (one fixed LoRA, only its weight varies) on one frozen prompt, one model and one seed set. Supported target: image txt2img on a registry-verified SDXL checkpoint (decided from `ModelPolicy` evidence and the policy's own control modes, never a name); fixed/restricted controls, unverified or conflicting models, extra stages, hires, refiner, ControlNet, aesthetic/hypernetwork, unresolved or policy-blocked LoRAs, and PromptPack rows with structural conditioning are refused, never silently disabled.

- **Bounds** (`two_axis_grid.py`): 2-4 distinct canonical values per axis (Decimal ranges; Steps whole numbers; CFG 1-30 and LoRA weight above 0 up to 2, two decimals), at most 16 cells, 1-3 images per cell, at most 36 images. An oversized or malformed design is refused with its reason; nothing is truncated or repaired.
- **Cells**: each cell is one `LearningVariant`; `param_value` is the frozen coordinate `{cell_id, x_variable, x_value, y_variable, y_value}` and `cell_id` hashes `(experiment_id, x variable/value, y variable/value)`. Row-major order (X across columns, Y down rows, selected order kept) lives in the frozen `two_axis_grid` block of the snapshot, so row and column are never inferred from job order, completion time or file names.
- **Build Preview** (`build_grid_snapshot`): freezes the baseline and Global Prompt policy, prompt source, model-policy context, both ordered axes, the common seed vector and every cell's effective configuration (`effective`: CFG, steps, LoRA, seed, prompt digests), sealed by `grid_sha256`. It compiles every cell, proves both axis values survive `apply_model_compile_policy` and (for LoRA) the executed prompt, and queues nothing. Any failure refuses the whole grid.
- **Run**: `LearningController.run_plan` is unchanged: every pending cell compiles through `two_axis_grid.materialize_njr` (via `learning_njr.assemble_txt2img_njr`) and is compared with its Preview `effective` block before the single `submit_njrs`; a double click admits nothing more. Cell N of sample k uses the same frozen requested seed/subseed as every other cell, and the existing completion rules (`observed_seed_vector`, launch profile, LoRA executed-prompt proof) mark a cell `uncontrolled` when read-back is missing or inconsistent.
- **Review**: the Comparison Grid pane (`LearningGridView`) shows each cell at its coordinate with status, expected/completed images, thumbnails, ratings summary and explicit placeholders (Pending, Queued, Running, Failed, Cancelled, Artifact missing, Uncontrolled evidence, Hidden by content-visibility policy). Selecting a cell opens it in the existing review panel; ratings use the existing controls and writer. Images come only from the variant that owns the admitted job (`grid_results.build_grid_model`); a missing file is a placeholder, never a neighbouring image. SFW mode withholds thumbnails and prompt-derived text when the frozen prompt classifies as explicit.
- **Contact sheet**: Export Contact Sheet (`grid_contact_sheet.export_contact_sheet`) renders a labeled PNG (title, model/prompt identity, axis names and values, per-sample seed and manual rating, legend) from recorded artifacts only, with bounded output (8192 px per side, 40 MP), bounded source decode (50 MP; corrupt, oversized and decompression-bomb images become placeholders) and an optional JSON manifest of coordinates, jobs, statuses and artifact references. It refuses to overwrite without confirmation, never writes over a recorded artifact, and publishes through `atomic_write_bytes`/`atomic_write_json`. A contact sheet is not an NJR, rating or job.
- **Evidence**: grid ratings use record kind `learning_grid_rating` (`study_type=two_axis_grid`, `causal_one_variable=false`, `grid_cell` with experiment/cell/sample/seed identity). `RecommendationEngine` and `LearningAnalytics.get_experiment_summary` exclude them; the conclusion shows no winner. They never change recommended settings, never reach Apply to Pipeline and are separate from one-variable, Model Comparison, Review-tab and video evidence.
- **Save and reopen**: the existing schema-1 session carries the grid (experiment metadata `grid`, frozen snapshot, cell-coordinate variants, selected variant, drafts). Restoring reconciles exact job IDs through `JobRepository` (section 5) and never rebuilds, recompiles or resubmits.

### 3.3 Ratings and review evidence

| Source | Entry point | Record kind (`metadata.record_kind`) |
|---|---|---|
| Designed experiment image | `LearningController.record_rating` (aggregate rating, subscores, context flags, notes; embeds the frozen snapshot, executed config, seed read-back) | `learning_experiment_rating` |
| Model Comparison image | same method; `rating_classification` picks the kind | `learning_model_comparison_rating` |
| Two-Axis Grid image | same method; `two_axis_grid.rating_classification` | `learning_grid_rating` |
| Review tab | `LearningController.save_review_feedback` (also stamps embedded/sidecar review metadata through `ReviewMetadataService`) | `review_tab_feedback` |
| Staged curation decision | `record_staged_curation_selection` -> `CurationLearningBridge.build_learning_record` | `staged_curation_event` |
| Video experiment clip review and manual preference | Review Experiment window -> `VideoReviewService` (`src/learning/video_review_service.py`, `video_quality_review.py`) | `video_workflow_quality_rating` |

`record_rating` raises when `LearningRecordWriter.append_record` returns `False`, so a failed write is shown and not cached as saved. Review drafts (`save_review_draft`) are resumable UI state in `LearningState.review_drafts`, not evidence, until they are committed: Save Rating / Save & Next, leaving the image (navigation commits a rated draft), **Save All Drafts** in the review panel, or **Save Stored Drafts...** in the tab header (the drafts left in other saved sessions, with a preview first; `learning_stored_drafts.py`). `src/learning/draft_commit.py` is the one rule: only a draft with an overall rating, only for an image with no saved rating (replacing a saved rating stays an explicit, confirmed Save Rating); everything else stays a draft. Viewing an image with untouched controls, or with controls equal to its saved rating, creates no draft, and a resumed session keeps its drafts. Controlled experiment ratings and observational review/curation records stay semantically distinct; only the former can reach the `experiment_strong` tier.

Guided rating behavior (PR-LEARN-UX-590) [V]: saving a rating that is identical to the saved one appends nothing; replacing a different saved rating asks first; Save & Next moves to the next unrated sample after the current one in stable variant/sample order (wrapping), skipping results whose file is unavailable. Saved, draft, unrated and unavailable counts are kept distinct and an unavailable file is never counted as rated. The plan table's average rating reads records by `experiment_id` through `build_review_projection` (it previously compared the experiment name and showed nothing).

**Video review evidence is isolated by construction.** `video_workflow_quality_rating` records keep every field inside `metadata.video_quality_review` (schema `stablenew.video-quality-review.v1`) and carry none of the image keys other readers use (`user_rating`, `image_path`, `experiment_id`, `experiment_name`, `learning_context`, `variant_value`, `variable_under_test`), so the recommendation engine (unknown kind), `LearningAnalytics` and the `LearningRecordWriter` per-experiment readers ignore them even at 5 stars. A clip review is identified by `(job_id, artifact_sha256)`, edits append a higher `revision` (readers resolve the latest valid one), an unchanged save appends nothing and a failed write raises (`ReviewSaveError`) so no UI reports a save that did not happen. The rubric separates the overall 1 to 5 rating from the requested-action outcome (achieved, partially, not, cannot assess); a manual preference is the operator's own pick, not a computed winner. Detail: `docs/Subsystems/Video/PR-VID-QUALITY-211_Experiment_Review.md`.

### 3.4 Discovered Outputs

`LearningController.trigger_background_scan` runs `OutputScanner.scan_incremental` over the output root in a thread spawned through `get_thread_registry().spawn`, groups artifacts (`GroupingEngine`), and writes groups with `apply_scan` into `DiscoveredReviewStore`. Artifacts that carry a `learning_context.experiment_id` are skipped (they have their own Experiment Review). The completion callback is marshalled to the Tk thread through `app_controller._run_in_gui_thread` (audit B6 is fixed here [V]). Items are rated in the table (`save_discovered_item_rating`); groups can be closed, ignored, reopened, pruned or reset.

### 3.5 Staged Curation

Discovered items, Review selections, History entries or controlled artifacts are imported into a staged-curation group (`import_review_images_to_staged_curation`, `send_controlled_artifacts_to_staged_curation`, `import_history_entry_to_staged_curation`). The operator records a decision per candidate with reason tags and a face-triage tier. "Queue Refine/Face/Upscale Now" calls `submit_staged_curation_advancement`: `CurationWorkflowBuilder` builds derived reprocess NJRs with lineage, then `submit_reprocess_njrs` admits them. "Edit ... in Review" builds a `ReviewWorkspaceHandoff` without queueing. "Preview Suggested Changes" / "Apply to Derived Job" run the recommendation engine for that candidate and apply a bounded stage-local patch (`apply_derived_recommendation_patch`) to the derived job only, after a confirmation dialog. This is the one place a recommendation can influence generation from the current UI.

### 3.6 Recommendations and the Apply path

`RecommendationEngine.recommend(prompt, stage, ...)` reads `learning_records.jsonl` (mtime-cached), filters by stage and compatible frozen model-policy context, computes weighted optimal settings (rating-detail adjustment bounded at +/-0.15, floor 0.05), and tags the set with an evidence tier:

| Tier | Condition | `automation_eligible` |
|---|---|---|
| `experiment_strong` | one durable experiment with at least `MIN_CONTROLLED_VARIANTS` (2) distinct tested values and `MIN_CONTROLLED_RATINGS` (3) controlled ratings | yes |
| `experiment_sparse_plus_review` | controlled rows below the bar, merged with review rows | no |
| `review_only` | only review/curation rows | no |
| `no_evidence` | nothing usable; no recommendation returned | no |

Incomplete historical rows (no durable id, snapshot or executed config) stay readable and are excluded; unknown record kinds are ignored. Exact-profile recommendations need compatible frozen profile evidence (`recommendation_applicable`).

**Apply to Pipeline** (`LearningController.apply_recommendations_to_pipeline`, button in `LearningReviewPanel`): refuses in `suggest_only`; revalidates the whole patch against the current model/stage policy (`validate_recommendation_apply`); resolves every target and rollback value before any Tk mutation (`prepare_recommendation_patch`), rolls back on a setter failure (`rollback_last_recommendation_apply`). It mutates only current Pipeline draft stage cards, never prior jobs, artifacts or PromptPacks. In `auto_micro_experiment` mode it also submits one preview job via `pipeline_controller.submit_preview_jobs_to_queue(source="learning_auto_micro")`, gated by `can_enqueue_learning_jobs` (queue cap), which is still the canonical queue path.

**Reachability [V]:** the Learning tab header has a **Recommendations** selector (`LearningTabFrame.automation_mode_box`; modes and labels in `src/learning/automation_modes.py`) that defaults to `apply_with_confirm`, with `suggest_only` and `auto_micro_experiment` still selectable. A saved mode counts only when it carries `automation_mode_user_set` (an older saved `suggest_only` was the hard-coded value, so it reads back as the default). Changing the mode refreshes the recommendations so `LearningReviewPanel` enables or disables Apply at once; Apply still asks in a confirmation dialog first. The review status line shows how many more ratings a recommendation needs (`get_evidence_progress`, the engine's own thresholds). `tests/controller/test_learning_automation_modes.py` drives the controller directly.

### 3.8 Guided workflow (PR-LEARN-UX-590)

The Designed Experiments tab is presented as Design, Preview, Run, Compare, Rate. This is presentation only [V]: the step state is projected from the experiment, plan and rating facts on every refresh (`guided_workflow.project_guided_workflow`) and is never persisted, so restore and restart reopen at the step the facts imply (a queued experiment reopens at Run and never resubmits). The viewed step is tab-local; only explicit actions (Build Preview, Run, restore, a new experiment, a step button) move it, never a timer refresh.

- Design defaults to Controlled Variable with an estimate line (variants x images). Model Comparison and Two-Axis Grid sit under *Advanced study types* and keep their own forms, validation and ratings isolation.
- Build Preview freezes the snapshot and queues nothing. The Preview card reads counts from that frozen snapshot. The design inputs are fingerprinted at Preview; editing them afterwards marks the Preview out of date and blocks Run until it is rebuilt. A Preview built elsewhere has no fingerprint and is not called stale. Staleness only blocks Run before admission.
- Run is the existing `run_plan` path: compile every variant, admit once through `JobService.submit_njrs`, all or none. A second click while admitting does nothing. The message reports what the repository confirmed; an ambiguous admission stays *Requires attention* and is never retried automatically.
- Compare and Rate open the review panel in a results-first or rating-first layout (`LearningReviewPanel.set_mode`, `show_results`). Rate shows the image, the star rating and Save & Next; sub-scores, context flags and notes are under *Rating details*.
- Recommendations remain the outcome of ratings. The summary names the setting, value, stage/model scope and evidence tier, and lists what Apply would change (current -> recommended, read-only dry run through `recommendation_targets.describe_apply_changes`). The tiers, the thresholds (2 distinct tested values, 3 controlled ratings), the three automation modes, `automation_mode_user_set`, the all-or-none Apply with rollback and the model/stage revalidation are unchanged. The mode selector lives with the recommendations (`LearningReviewPanel.mode_host`).

## 4. Data and persistence

| Data | Location | Writer | Atomic |
|---|---|---|---|
| Evidence records (ratings, review feedback, curation events, video experiment reviews), append-only JSONL | `data/learning/learning_records.jsonl` (`get_learning_records_path`, `WorkspacePaths.learning_records`) | `LearningRecordWriter.append_record` (temp line, fsync, append, fsync; returns `False` and logs on failure) | Appended with fsync under a process-wide per-path lock (`evidence_file_lock`), each append staged through its own temp file; a torn final line is possible after a hard reset (the rating-count readers skip lines that fail to parse) |
| Experiment sessions | `data/learning/experiments/<experiment_id>/session.json`, `meta.json`, plus `index.json` | `LearningExperimentStore` via `atomic_write_text` | Yes |
| Discovered/curation groups | `data/learning/discovered_experiments/<group_id>/meta.json`, `items.json`, `review_state.json`, `selection_events.json`; `scan_index.json` in the same folder | `DiscoveredReviewStore` via `atomic_write_text` | Yes |
| Tab session, last experiment, learning toggle | `state/ui_state.json` key `learning` (`get_ui_state_store`) | `LearningTabFrame._persist_learning_session_state` | Yes (errors swallowed) |
| Run metadata, per-run feedback | `runs/<run_id>/run_metadata.json`, `feedback.json` | `write_run_metadata` (async worker or sync); `record_feedback` (no callers in `src`) | Yes |
| Review stamps | Embedded in the image or a sidecar next to it | `ReviewMetadataService.stamp_review_metadata` | Per service |
| Analytics export | caller-chosen path | `LearningAnalytics.export_to_json`/`export_to_csv` | No (`json.dump` direct) |

`data/learning/` is git-ignored operator data. Audit B4 is largely fixed: the experiment, discovered, UI-state, run-metadata and feedback writers use `src/utils/atomic_io.py`. Read paths scan the whole JSONL: `get_ratings_for_experiment`, `get_rating_details_for_experiment`, `get_average_rating_for_variant`, `LearningAnalytics._read_all_records`. Tests must point the writer at a temp path and never at the repository `data/learning/` (audit: tests have leaked debris there [A]).

Output folders for experiment jobs are `output/.../<bounded sanitized experiment label + short id>` with variable/value/variant in file names (`experiment_naming.py`); the full identity stays in metadata.

## 5. The Learning tab and what is reachable

Reachable and working [V]: Learning mode toggle (`LearningTabFrame._on_learning_toggle`; it stores a flag and does not gate `record_rating`); New / Clone / Experiment Library / save and resume; Build Preview and Run; plan table; per-image rating with subscores, Save & Next, drafts and Discard Draft; View Analytics; send to curation; Discovered Outputs scan, rating and cleanup; Staged Curation decisions, derived-job queueing, Review handoff and the derived-job suggestion preview/apply; Model Comparison; Two-Axis Grid design (Study Type), the Comparison Grid pane and Export Contact Sheet.

Apply to Pipeline is reachable through the Recommendations selector (section 3.6).

Resume after restart: `restore_resume_state` reconstructs the existing schema-1 session and delegates to `LearningExecutionController.reconcile`. Each recorded job ID is read through `JobRepository.get_job_model`; immutable NJR experiment/variant IDs, Learning context, frozen snapshot digest and variant value must agree with the saved plan. It never scans unrelated history or matches names, prompts, paths or dates. Missing IDs, corrupt snapshots, unavailable repositories and conflicting identities retain the association and show **Requires Attention** with the reason. Historical sessions without exact immutable identity cannot be recovered automatically and stay visibly unresolved.

Queued jobs remain queued even during GPU quarantine; running jobs show the repository's current state. Startup's existing interrupted-job recovery remains authoritative (`failed`, `INTERRUPTED_RESTART_ACTION_REQUIRED`, no automatic replay). Failed/cancelled jobs retain the recorded error/action. Completed jobs reuse the normal completion and seed/subseed, tested-variable/LoRA and runtime-profile evidence rules. Missing readback stays uncontrolled; existing uncontrolled evidence is never promoted. Recorded paths remain attached when files are missing, with an explicit warning; recovery neither fabricates a file nor writes ratings. Saved ratings, review drafts and the selected variant/image survive restoration. Model Comparison keeps its separate target-envelope evidence semantics.

The execution controller restores only genuine nonterminal callback mappings. One lock serializes reconciliation, admission and terminal updates; reentrant notifications wait for immutable identity validation. Completion evidence is interpreted on disposable variant/experiment copies, then published before presentation/checkpoint callbacks. Malformed structured readback or a rejected interpreter retains job/artifact associations as visibly uncontrolled evidence without publishing provisional seed/profile comparison boundaries. Only a safe terminal projection enters the cache; a rating without an explicit positive evidence result is uncontrolled. A resume-save warning stays distinct from a validation failure and does not reclassify valid execution readback. Repeated restore and duplicate terminal events do not duplicate artifacts, counters or callbacks, stale reads do not downgrade a newer terminal result, and switching experiments discards the old mappings. The same JobService listener pair is rebound when its Learning owner is recreated, and closing the tab makes queued callbacks inert. Tk callbacks still use JobService's existing application UI dispatcher. Opening Learning never dispatches, retries, replays, clears quarantine or mutates repository lifecycle. The header summarizes actual outcomes and per-variant rows show the status and required action. Resume persistence failures surface in that header instead of reporting success.

The unsuffixed-or-`_v2` duplicates `learning_tab_frame.py`, `learning_plan_table_v2.py` and `learning_review_panel_v2.py` were deleted (P3-1); the live files are `learning_tab_frame_v2.py`, `learning_plan_table.py` and `learning_review_panel.py`, despite their names.

## 6. Randomizer relation

The randomizer is a build-time expansion layer, owned by `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md` (current for the contract it states). Code: `src/randomizer/randomizer_engine_v2.py` (`RandomizationPlanV2`, `RandomizationSeedMode`, `generate_run_config_variants`: deterministic config variants over model, VAE, sampler, scheduler, CFG, steps, batch size), `src/pipeline/randomizer_v2.py`, `src/pipeline/variant_planner.py`, and prompt-level matrix/wildcard/S-R expansion in `src/utils/randomizer.py` and `src/utils/prompt_pack_utils.py`. Callers: `JobBuilderV2._generate_variants`, the PromptPack builder and `PipelineController`.

Learning does not use `RandomizationPlanV2`. Its sweeps come from `LearningController._generate_variant_values` and `VariableMetadata`. The only touchpoints:

- `freeze_prompt_pack_source` freezes one PromptPack row and the first canonical Matrix combination at Build Preview using `get_matrix_slots_dict`; the experiment is deliberately not re-randomized at Run. Rows with enabled structural conditioning (OpenPose) are refused.
- `LearningRecord.randomizer_mode` and `randomizer_plan_size` are reused as labels (`learning_experiment`, `review_feedback`); the name is historical.

Because both layers stay in the compiler, the invariant "randomization never happens at run time" holds for Learning too.

## 7. Invariants that must not be broken

1. Canonical path only. Learning submits NJRs through `JobService.submit_njrs` (or `submit_reprocess_njrs`); it never calls a runner, backend or executor, and never builds a payload for one.
2. Compile all, then admit once. No partial experiment may enter the queue. Run reads the frozen snapshot, not live GUI state.
3. The NJR and frozen snapshot are immutable. Learning never mutates a historical artifact, NJR, PromptPack or prior job; Apply affects only the current draft intent or a derived job.
4. `ModelPolicy` is the only source of model/profile applicability. Learning must not detect families by name or duplicate LoRA compatibility rules; fixed/restricted controls are not variables.
5. Evidence is gated: controlled data may recommend only the field the frozen experiment varied; `experiment_strong` needs two distinct values and three controlled ratings in one durable experiment; observational evidence is manual-only; insufficient evidence returns no recommendation.
6. Model Comparison ratings never feed ordinary recommendations or automatic Model selection; they claim preference under each frozen envelope, not causality.
6a. Two-Axis Grid ratings are exploratory and descriptive: record kind `learning_grid_rating`, excluded from `RecommendationEngine`, `LearningAnalytics.get_experiment_summary`, any winner/conclusion and Apply to Pipeline. A grid is refused whole rather than admitted with a dropped, clamped or overwritten axis, and cell identity comes from the frozen `cell_id`, never job or file order.
7. Uncontrolled results (seed read-back missing or mismatched, tested LoRA not executed, backend restart boundary) are excluded from inference, not repaired.
8. A rating shown as saved must be saved: do not ignore the `append_record` result.
8a. Video review evidence never reaches image Learning: keep it under `metadata.video_quality_review`, never give it the image rating keys, and never feed it to `RecommendationEngine` or analytics (`tests/learning/test_video_quality_review_211.py` runs the real readers).
9. Persisted Learning state is written with `src/utils/atomic_io.py` (or the fsync append of the records file). UI-thread-only: Tk variables and widgets are touched on the Tk thread (`app_controller._run_in_gui_thread`); background work uses `get_thread_registry().spawn`.
10. No image crops, detector frames or binary artifacts in records; adaptive-refinement context is stored only as compact scalar fields, mapped from the canonical `adaptive_refinement` carrier, and `face_detected` is nullable (a confirmed negative needs a successful zero-detection assessment).
11. Learning tests must not contact a WebUI, model or GPU.
12. Protected actions need explicit owner approval (`AGENTS.md` section 5).

## 8. How to test

Configuration is `pyproject.toml` only; run focused tests first, then `python tools/ci/run_pr_gate.py`.

| Area | Tests | Hermetic seam |
|---|---|---|
| Freeze, admission, seeds, naming, stores, scan/discovered, analytics, recommendation engine and evidence tiers, rating persistence, model capabilities, Model Comparison, global-prompt correctness | `tests/learning_v2/` | Temp record/store roots; fake job service; stub resources |
| Record builder/writer, plan factory, defaults, profiles | `tests/learning/` | Temp paths |
| Controller NJR construction, automation modes, resume state, review feedback, completion, run summary, queue cap | `tests/controller/test_learning_*.py`, `tests/controller/test_pipeline_controller_learning_queue_cap.py` | `unittest.mock.Mock` pipeline/app controllers with `SimpleNamespace` stage cards and var stubs |
| Tab and panel contracts, persistence, model-policy projection | `tests/gui_v2/test_learning_*.py`, `tests/gui_v2/test_discovered_review_inbox.py`, `tests/gui_v2/test_curation_exact_profile_preflight_158.py` | Tk-free where possible |
| Two-Axis Grid | `tests/learning_v2/test_two_axis_grid_270.py` (planning, frozen compile, admission, restart, ratings isolation, save/reopen), `tests/learning_v2/test_grid_contact_sheet_270.py` (known-pixel sheets, placeholders, visibility, bounds, atomic export), `tests/gui_v2/test_learning_grid_270.py` (real Tk: design, preview staleness, run, select, lazy thumbnails, scroll, stale results, destroy, tab switching) | Fake `JobService` over a temp `JobRepository`; coloured PNG fixtures; no WebUI |
| Curation | `tests/curation/` | In-memory models |
| Video experiment review evidence | `tests/learning/test_video_quality_review_211.py`, `test_video_review_service_211.py` | Temp record files and a temp `JobRepository`; no `data/learning` |
| Review metadata and sidecars | `tests/review/` | Temp image dirs |
| End to end | `tests/integration/test_learning_review_recommendation_e2e.py`, `tests/learning_v2/smoke_test_learning_workflow.py` | Stub runners |
| Guided workflow (PR-LEARN-UX-590) | `tests/learning_v2/test_guided_workflow_590.py` (pure projections), `tests/gui_v2/test_learning_guided_workflow_590.py` (real Tk navigation, Preview/Run guards, restore), `tests/gui_v2/test_learning_rating_flow_590.py` (rating and recommendation display), `tests/gui_v2/test_learning_guided_journey_590.py` (Design to rated evidence) | Fake `JobService` over a temp `JobRepository`; no runner, backend or generation |
| Tk-free guarantee for execution code | `tests/safety/test_learning_execution_no_tk_imports.py` | Import inspection |
| Randomizer | `tests/randomizer/`, `tests/controller/test_pipeline_randomizer_integration_v2.py`, `tests/utils/test_randomizer_parity.py`, `tests/utils/test_prompt_randomizer.py` | Seeds |

A Learning change should cover persistence/resume, stage capability validation, rating persistence, evidence-guard behavior and all-or-none admission. For a new refusal assert both the error and that nothing reached `submit_njrs`. Never write `img_a.png`-style relative review sidecars into the repository root (audit: one controller test does [A]).

## 9. Known debt and traps

- God controller (audit D2) [V]: `LearningController` is 4,027 lines in `src/gui/controllers/`, a directory the controller-surface ratchet does not cover (`tools/ci/check_controller_surface.py` scans `src/controller` only; `tools/ci/controller_surface_baseline.json` has no entry for it). It mixes design, compile, Run, completion validation, ratings, recommendations, Apply, review feedback, discovered inbox, curation workflow building, reprocess item construction and scan threading. Adding to it makes this worse; put new logic in `src/learning/` or `src/curation/` and keep the controller a thin binder. The planned split is audit P4-3.
- GUI layer compiles NJRs (audit D1) [V]: `LearningController._build_variant_njr` constructs `NormalizedJobRecord(` itself (one of the eight construction sites, audit C2) with hard-coded fallbacks (sampler "Euler a", 20 steps, CFG 7.0, clip skip 2) and the literal prompt `"a test prompt"` when neither snapshot nor experiment has one; it can also mutate the experiment (assigns `experiment_id`, `execution_snapshot_json`). Model Comparison already compiles in `src/learning` (`materialize_njr`), which is the pattern to follow. Any new image compile policy must be applied here too (see the Image document section 11).
- Two classes named `LearningExecutionController` [V]: the live one is `src/learning/execution_controller.py` (JobService callbacks); `src/controller/learning_execution_controller.py` wraps a `run_callable` over the legacy `LearningExecutionRunner` and the stub `LearningRunner`. The legacy pair is reachable from `AppController._learning_run_callable` and tests only; the stub returns fabricated pending artifacts. Do not wire new work to it.
- Legacy completion router [V]: `AppController` still calls `build_learning_completion_handler` through a widget lookup (audit D3), but `LearningController.on_job_completed_callback` is deliberately inert. Only the existing `LearningExecutionController` JobService `job_finished`/`job_failed` listeners own terminal delivery, preventing the old display-name/index route from bypassing identity or idempotency checks.
- Plan-table average rating [V by reading]: `_update_variant_ratings` queries `get_average_rating_for_variant(experiment.name, ...)`, but records store the opaque `experiment_id` first, so the average column is likely empty for new experiments. Use `experiment_id`.
- In-memory job tracking (section 5): restart loses the job-to-variant map.
- Silent failures [V]: `save_review_feedback` and `record_staged_curation_selection` ignore the `append_record` result (the latter also swallows exceptions); `_persist_learning_session_state` swallows every error; `learning_controller.py` has dozens of `except Exception: pass`. Audit B4 asks write failures to reach the status banner [A].
- Dead pipeline-side emitters [V: no callers in `src`]: `PipelineRunner._emit_learning_record`, so records are not produced automatically from runs; `PipelineController.handle_learning_record` is its receiver. Evidence comes only from operator actions in the Learning and Review tabs.
- Two-Axis Grid limits [V]: txt2img on registry-verified SDXL only; CFG Scale, Steps and one fixed LoRA's strength only; no three-axis sweeps, no automatic best-setting choice, no different-LoRA axis. A cell is one job with N images, so per-sample seeds are the backend's read-back vector (`actual_all_seeds`), shown only when its length equals the image count. Physical GPU behaviour of a grid has not been qualified by this package. Post-run read-back verifies a cell's LoRA only; that CFG and Steps were honoured by the backend is proven at compile time, as for single-variable experiments. `LearningAnalytics.get_overall_summary` still counts grid ratings in its global totals (descriptive only; nothing recommends from it).
- Unused declarations [V]: `LearningMode.MULTI_VARIABLE_EXPERIMENT` (the ordinary sweep is one variable; the bounded two-axis grid is section 3.7); `src/learning/learning_contract.py` is placeholder presets used by `learning_plan.py`.
- Reverse dependencies [V]: `src/learning/execution_controller.py` imports `src.gui.learning_state`; `model_policy_service.py` takes the GUI controller as a parameter and imports `src.gui_v2.recommendation_targets`; `src/learning` imports `src.controller` helpers. `LearningTabFrame` builds stores and services itself and reaches `pipeline_controller._job_service` (audit D3).
- Usage reality [A]: about 18k lines (roughly 10% of `src`), 77 experiments, 4 committed ratings, 504 rated drafts never saved at audit time (committable with Save Stored Drafts...), zero applied recommendations. The audit recommends pausing Learning expansion until usage is measured (audit P5-2, decision: Learning payoff before new surfaces, STATUS.md open decision 8).
- Banner label stacking "Workflow: Workflow: ..." (audit G8) [A], not re-checked.
- Spec drift [V]: see section 11.

- Snapshot size [V]: a Model Comparison job's NJR embeds the whole frozen experiment (`frozen_experiment.snapshot`, all arms, about 0.7 MB for a 48-arm study) under **both** `normalized_job.workload.metadata` and `normalized_job.provenance.metadata`, and every variant job of the experiment repeats it. In the owner's repository 10 experiments x about 49 jobs account for about 713 MB of 753 MB of those snapshots (about 7 MB if each experiment snapshot were stored once; `snapshot_sha256` identifies it). It is a design choice (a self-contained, replayable NJR), not corruption. Externalizing it by hash changes the NJR contract; the owner chose that, forward-only, with backfill and any prune decided after reading `tools/job_repository_report.py`, a read-only report (`src/queue/job_hygiene_report.py`) of space by column, the duplicated-snapshot saving and a prune dry run (`STATUS.md`).

## 10. Changing or extending Learning today

- New tested variable: add a `VariableMetadata` entry in `src/learning/variable_metadata.py` (config path, type, resource key), list it in the stage in `src/learning/stage_capabilities.py`, make `ModelPolicy` classify it as configurable (`src/learning/model_capabilities.py` projects it; do not add model names), and cover value generation (`LearningController._generate_variant_values`), `_apply_variant_override_with_metadata`, the `compile_variant` proof and a recommendation parameter map (`src/gui_v2/recommendation_targets.py`, `staged_recommendations._PARAMETER_KEYS`) if it should be recommendable.
- New stage: `StageCapability` plus an image-source rule; non-txt2img stages compile through `ReprocessJobBuilder`, so confirm `require_njr_operation` accepts it.
- New record kind: write it only through `LearningRecordWriter.append_record`, check the result, add `record_kind`, and decide explicitly in `RecommendationEngine` whether it is controlled evidence, observational evidence or ignored (unknown kinds must be ignored).
- New persisted file: use `atomic_write_text` and `WorkspacePaths`; add the location to section 4.
- Changing the default mode or adding a mode: edit `src/learning/automation_modes.py` (`DEFAULT_AUTOMATION_MODE`, `AUTOMATION_MODE_LABELS`) and keep `LearningController.apply_recommendations_to_pipeline` gating on the mode; the confirm gate and all-or-none patch validation stay.
- Moving compile out of the GUI (audit P4-3): create a new compile function (audit name: compile_variant_njr) in `src/learning/` following `materialize_njr`, move the defaults and fallbacks out, make it pure (no experiment mutation, no stage-card reads), then shrink the controller. Do it after the single compile core (audit P4-2) or alongside a golden NJR test.
- Update this file, `STATUS.md` (supported capabilities) and, for evidence, a record under `docs/Subsystems/Learning/`.

## 11. Other documents

`docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` is the older canonical contract. It is still accurate about frozen preview, admission, Model Comparison, stage capability, evidence rules and refinement context, and this file defers to it for exact wording of those. Where it lags the code: its section 7.1 describes an Apply flow (confirmation-gated, `suggest_only` disabled) that exists but is unreachable from the UI (section 3.6); its section 9 is a PR checkpoint (execution profile, "remaining acceptance work") rather than a contract; its section 5 and 4.3 numbering is interleaved; and it says Learning does not "automatically tune parameters" while `auto_micro_experiment` exists in `LearningController`. Treat its section 9 as historical. `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md` is current for the randomizer contract (section 6).

## 12. Evidence records

Per-PR records stay as historical evidence and may describe superseded behavior; the code and this file win.

| Record | Why it matters |
|---|---|
| `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` | Contract for frozen preview, admission, evidence tiers, refinement context, Apply semantics |
| `docs/Subsystems/Learning/PR-LEARN-130D_Model_Scoped_Learning_Capability_Correctness.md` | Model-scoped variable and recommendation applicability through `ModelPolicy` |
| `docs/Subsystems/Learning/PR-LEARN-140_Model_Comparison_Study.md` | Model Comparison contract, claim and bounded scope |
| `docs/Subsystems/Learning/PR-LEARN-141_Ordinary_Global_Prompt_Correctness.md` | Executor-base prompt freeze and legacy-preview refusal policy |
| `docs/Subsystems/Video/PR-VID-QUALITY-211_Experiment_Review.md` | Video experiment review: rubric, evidence record shape, revisions and isolation from image Learning |
| `docs/Subsystems/Learning/PR-LEARN-142_Model_Comparison_Evidence_Readiness.md` | Checkpoint evidence preparation for the study |
| `docs/Subsystems/Learning/PR-LEARN-COMPARE-145_Checkpoint_Evidence_and_Comparison_Compatibility.md` | Structural checkpoint evidence and comparison compatibility |
| `docs/Subsystems/Randomizer/Randomizer_Spec_v2.6.md` | Randomizer contract and ownership |
| `docs/Subsystems/Image/IMAGE_PIPELINE.md` | Image-side model policy, profiles and NJR construction sites that Learning must follow |
| `docs/audits/2026-10-16_repo_audit_and_roadmap.md` | Findings B4, B6, D1-D3, G2, G4 and the P4-3 / P5-2 plan referenced above |
