# GUI-SEAM-700 Controller Presentation-State Isolation

Date: 2026-10-25
Assessment class: Focused
Implementation class: Standard
Base: `origin/main` `612deb1e67f0acd3f152b9abf313fda169476aad` (PR #212 merge), re-verified at task start.

## Outcome

GUI-SEAM-700 adds a toolkit-neutral presentation-state and UI-dispatch seam without changing the production Tk host,
application composition, execution ownership, persisted formats, queue/repository behavior, NJR contracts or
backend/process lifecycle. It does not authorize a Qt migration.

## Boundary established

1. No module under `src/controller` has an import-time transitive path to `tkinter`
   (`tools/ci/check_controller_tk_boundary.py`, run by `run_pr_gate.py` and hosted `required`).
2. `AppController` does not read or write Pipeline Tk variables.
3. `AppStateV2` depends on the `UiDispatcher` protocol (`src/controller/ports/ui_dispatcher.py`), not `GuiInvoker`.
4. Tk presentation stays in `src/gui`; `GuiInvoker` remains as an alias of `TkInvoker`.
5. Controller-to-GUI layering debt stays ratcheted independently (`controller_gui_imports` is still 17).
6. The single-composition-root decision (owner decision 11) is untouched.

## Presentation-state seam

    Tk view variable -> PipelineTabFrame trace -> AppStateV2 projection -> controller reads
    controller intent -> AppStateV2 projection -> `pipeline_stage_enabled` notification -> Tk view variable

The projection (stage flags, prompt text, upscale parameters) is held in non-dataclass attributes: never persisted, never
execution authority. Stage notifications use `run_on_ui_thread` so same-thread controller writes stay synchronous, as the
old `BooleanVar.set()` was.

## Differences from the research plan (found while implementing)

- `DropdownLoader` takes the controller's `ConfigManager`; it is constructed lazily in `_update_gui_dropdowns` with that
  argument (the plan's `DropdownLoader()` would have been wrong).
- There were eight Tk-variable access sites, not seven: `_collect_current_stage_configs` also read
  `adetailer_enabled.get()` for the ADetailer section. It now reads the projection.
- `AppStateV2` queues through `schedule` and falls back to `invoke`, because existing test fakes and any older dispatcher
  expose only `invoke`.
- `build_photo_optimize_defaults` overrides the stage `enabled` flags only when an `app_state` exists, which keeps the
  previous behavior when no presentation was attached.
- `UiCallback` uses the `type` statement (ruff `UP040`).
- The hosted `required` workflow (`.github/workflows/ci.yml`) also runs the new check; the plan only named the local gate.
- `controller_surface_baseline.json` lowered `app_controller.py` from 6919 to 6860 lines (the ratchet requires it).
- Existing tests that used stand-in Tk variables on the controller now publish through `AppStateV2`:
  `test_scope_editing_222`, `test_pack_draft_to_normalized_preview_v2`,
  `test_working_settings_startup_630`.

## Runtime and persistence impact

None: no dependency, database migration, stored-config migration, queue/history change, runner, NJR, JobService, backend,
process-manager, generation, model or GPU change. Rollback is source-only.

## Validation (local, base `612deb1e`)

- `python tools/ci/run_pr_gate.py`: PASS (repository completeness, controller surface, ruff, mypy smoke, mypy ratchet,
  ruff ratchets, architecture ratchets, controller Tk import boundary, isolated collection 13549 tests, required smoke
  358 passed).
- Ratchet baselines locked in (improvements only): `controller_surface_baseline.json` app_controller 6919 -> 6860,
  `mypy_baseline.json` total 1486 -> 1480, `ruff_ratchet_baseline.json` improved. `controller_gui_imports` unchanged at 17.
- New tests: `tests/tools/test_controller_tk_boundary.py`, `tests/controller/test_controller_presentation_seam_700.py`,
  `tests/gui_v2/test_app_state_presentation_seam_700.py`, `tests/gui_v2/test_pipeline_presentation_seam_700.py`,
  `tests/gui_v2/test_ui_dispatcher_700.py`: PASS.
- `tests/controller`, `tests/app`, `tests/photo_optimize`, `tests/gui_v2`, `tests/integration`, `tests/api`, `tests/utils`:
  PASS except `tests/utils/test_process_containment_failsafe.py::test_output_of_a_pump_abandoned_by_stop_never_leaks_into_the_restarted_process`,
  which failed once under load in a concurrent run and passes alone (26 passed in that file); it touches no changed code.
- Negative check: the checker, run on the base tree, reports `src.controller.app_controller -> src.gui.dropdown_loader_v2 -> tkinter`;
  on this branch it reports none. A runtime import of `src.controller.app_controller` leaves `tkinter` out of `sys.modules`.
- Not run locally: `run_pr_gate.py --full` (sharded census). Hosted `required`, `full-suite` and `windows` run only after
  publication, which is not authorized by this package.

## Acceptance verdict

CONDITIONAL PASS: all local gates above are green; the full census and hosted checks are outstanding.

## Tk import inventory (direct import-time `tkinter`, `python tools/ci/check_controller_tk_boundary.py --inventory-tk`)

123 modules: `src/main.py`, `src/app_factory.py` and 121 under `src/gui/**`. None is under `src/controller`.

```text
src/app_factory.py
src/gui/advanced_prompt_editor.py
src/gui/ai_suggestion_dialog.py
src/gui/api_status_panel.py
src/gui/artifact_metadata_inspector_dialog.py
src/gui/base_generation_panel_v2.py
src/gui/batch_operations_panel_v2.py
src/gui/batch_retry_dialog.py
src/gui/controllers/video_workspace_handoff.py
src/gui/design_system_v2.py
src/gui/dialogs/multi_folder_selector.py
src/gui/dropdown_loader_v2.py
src/gui/engine_settings_dialog.py
src/gui/enhanced_slider.py
src/gui/generation_profile_strip.py
src/gui/gui_invoker.py
src/gui/history_browser_panel_v2.py
src/gui/history_iterate_dialog.py
src/gui/job_history_panel_v2.py
src/gui/klein_lora_selection_dialog.py
src/gui/layout_v2.py
src/gui/learning_review_dialog_v2.py
src/gui/log_trace_panel_v2.py
src/gui/main_window.py
src/gui/main_window_v2.py
src/gui/mask_editor_dialog.py
src/gui/model_readiness_presenter.py
src/gui/outpaint_dialog.py
src/gui/output_settings_panel_v2.py
src/gui/panels_v2/api_failure_visualizer_v2.py
src/gui/panels_v2/asset_readiness_tab_v2.py
src/gui/panels_v2/debug_hub_panel_v2.py
src/gui/panels_v2/debug_log_panel_v2.py
src/gui/panels_v2/history_variation_panel.py
src/gui/panels_v2/job_explanation_panel_v2.py
src/gui/panels_v2/operator_readiness_panel_v2.py
src/gui/panels_v2/queue_panel_v2.py
src/gui/panels_v2/reprocess_panel_v2.py
src/gui/panels_v2/running_job_panel_v2.py
src/gui/panels_v2/widgets/stage_timeline_widget.py
src/gui/pipeline_panel_v2.py
src/gui/preview_panel_v2.py
src/gui/prompt_adaptation_dialog.py
src/gui/prompt_ai_suggestions.py
src/gui/prompt_target_presenter.py
src/gui/randomizer_panel_v2.py
src/gui/review_batch_dialog.py
src/gui/scrolling.py
src/gui/sidebar_panel_v2.py
src/gui/smart_review_dialog.py
src/gui/stage_cards_v2/adetailer_stage_card_v2.py
src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py
src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py
src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py
src/gui/stage_cards_v2/base_stage_card_v2.py
src/gui/stage_cards_v2/components.py
src/gui/status_bar_v2.py
src/gui/theme_v2.py
src/gui/tooltip.py
src/gui/view_contracts/edit_work_runner.py
src/gui/views/character_training_frame.py
src/gui/views/diagnostics_dashboard_v2.py
src/gui/views/discovered_review_inbox_panel.py
src/gui/views/discovered_review_table.py
src/gui/views/error_modal_v2.py
src/gui/views/experiment_design_panel.py
src/gui/views/grid_design_frame.py
src/gui/views/learning_analytics_panel.py
src/gui/views/learning_baseline_editor.py
src/gui/views/learning_grid_view.py
src/gui/views/learning_plan_table.py
src/gui/views/learning_preview_card.py
src/gui/views/learning_review_panel.py
src/gui/views/learning_tab_frame_v2.py
src/gui/views/learning_workflow_bar.py
src/gui/views/movie_clips_tab_frame_v2.py
src/gui/views/photo_optimize_editors.py
src/gui/views/photo_optimize_handoff.py
src/gui/views/photo_optimize_layout.py
src/gui/views/photo_optimize_results.py
src/gui/views/photo_optimize_scope.py
src/gui/views/photo_optimize_tab_frame_v2.py
src/gui/views/pipeline_tab_frame_v2.py
src/gui/views/prompt_tab_frame_v2.py
src/gui/views/review_tab_frame_v2.py
src/gui/views/stage_cards_panel_v2.py
src/gui/views/svd_tab_frame_v2.py
src/gui/views/video_eval_panel_v2.py
src/gui/views/video_experiment_review_window.py
src/gui/views/video_workflow_batch_panel_v2.py
src/gui/views/video_workflow_controls_panel_v2.py
src/gui/views/video_workflow_experiment_panel_v2.py
src/gui/views/video_workflow_motion_prep_panel_v2.py
src/gui/views/video_workflow_motion_readiness_panel_v2.py
src/gui/views/video_workflow_recent_outputs_panel_v2.py
src/gui/views/video_workflow_runtime_strip_v2.py
src/gui/views/video_workflow_sequence_panel_v2.py
src/gui/views/video_workflow_tab_frame_v2.py
src/gui/widgets/action_explainer_panel_v2.py
src/gui/widgets/config_sweep_widget_v2.py
src/gui/widgets/controlnet_units_panel.py
src/gui/widgets/disclosure_section_v2.py
src/gui/widgets/embedding_picker_panel.py
src/gui/widgets/expander_v2.py
src/gui/widgets/image_thumbnail.py
src/gui/widgets/lora_browser_dialog.py
src/gui/widgets/lora_keyword_dialog.py
src/gui/widgets/lora_picker_panel.py
src/gui/widgets/matrix_helper_widget.py
src/gui/widgets/matrix_slot_picker.py
src/gui/widgets/matrix_tab_panel.py
src/gui/widgets/media_inspector.py
src/gui/widgets/openpose_picker_panel.py
src/gui/widgets/reference_map_browser.py
src/gui/widgets/reference_map_dialog.py
src/gui/widgets/responsive_wrap_v2.py
src/gui/widgets/scrollable_frame_v2.py
src/gui/widgets/submission_notice_v2.py
src/gui/widgets/tab_overview_panel_v2.py
src/gui/widgets/task_navigation_bar_v2.py
src/gui/widgets/thumbnail_widget_v2.py
src/gui/widgets/video_preview_widget_v2.py
src/main.py
```
