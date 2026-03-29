# PR-RUFF-001 — Ruff + Lint Cleanup (Folder-by-Folder)

## Objective
Use **Ruff** to fix lint violations and formatting issues **folder-by-folder** in a controlled, reviewable way:
1) `tools/`  
2) `scripts/`  
3) `tests/`  
4) `src/`

This PR is intended to be executed by an automated implementer (Codex). The implementer must **only** edit files listed in **Allowed Files** and must follow the step order.

## Ground Rules
- Do **not** change runtime behavior intentionally. This is a lint/format cleanup PR.
- Prefer mechanical Ruff autofixes over manual refactors.
- If a fix is ambiguous or would change behavior, **add a targeted `# noqa: <RULE>` with a short comment** rather than refactoring.
- Keep diffs small and folder-scoped. Do not mix folders in one commit.
- After each folder pass: run `ruff` + minimal tests relevant to that folder.

## Ruff Inputs (the “report”)
If an external Ruff report is provided, use it as the baseline.
If not, generate an equivalent baseline report before making changes:

```cmd
ruff check tools scripts tests src --output-format=github > ruff_report_github.txt
ruff check tools scripts tests src --output-format=json > ruff_report.json
```

Do not edit the report files unless explicitly required by the repo’s conventions.

## Commands (per folder)
For each folder in order:

```cmd
ruff check <FOLDER> --fix
ruff format <FOLDER>
```

Then re-run:

```cmd
ruff check <FOLDER>
```

## Test Commands (per folder)
Use the fastest applicable checks after each folder pass:

### tools/
```cmd
python -m compileall tools
```

### scripts/
```cmd
python -m compileall scripts
```

### tests/
```cmd
pytest -q tests
```

### src/
```cmd
pytest -q
```

If full test suite is too slow, run the repo’s “golden path” subset if defined in docs, otherwise:
```cmd
pytest -q tests/controller tests/gui_v2 tests/pipeline tests/learning
```

## Commit Plan
Make **one commit per folder**, plus an optional final “sweep” commit if needed for shared config updates (only if config files are in Allowed Files).

Commit messages:
- `chore(ruff): fix tools lint`
- `chore(ruff): fix scripts lint`
- `chore(ruff): fix tests lint`
- `chore(ruff): fix src lint`

## Acceptance Criteria
- `ruff check tools scripts tests src` exits 0 OR remaining violations are intentionally suppressed with `noqa` and briefly justified.
- Code is formatted (`ruff format`) in all touched folders.
- Tests pass at the level specified above (or better).
- No functional behavior changes beyond lint/format.

## Allowed Files (EXPLICIT LIST)
The implementer may edit **only** the files listed below.

### Config (only if present in repo)
- `pyproject.toml`
- `.pre-commit-config.yaml`

### tools/ (*.py)
- `tools/__init__.py`
- `tools/archive_unused.py`
- `tools/check_pr_scope.py`
- `tools/codex_autofix_runner.py`
- `tools/inventory_repo.py`
- `tools/summarize_file_access_v2_5_2025_11_26.py`
- `tools/test_helpers/journey_harness.py`
- `tools/test_helpers/process_inspection.py`
- `tools/v2_classify_and_archive.py`

### scripts/ (*.py)
- `scripts/__init__.py`
- `scripts/a1111_batch_run.py`
- `scripts/a1111_upscale_folder.py`
- `scripts/bootstrap_agents.py`
- `scripts/launch_webui.py`
- `scripts/list_pipeline_config_refs.py`
- `scripts/manual_acceptance_add_to_queue.py`
- `scripts/manual_acceptance_add_to_queue2.py`
- `scripts/reorg_repo.py`

### tests/ (*.py)
- `tests/__init__.py`
- `tests/ai_v2/test_local_stub_settings_generator_behavior.py`
- `tests/ai_v2/test_settings_generator_adapter_from_learning.py`
- `tests/ai_v2/test_settings_generator_contract_roundtrip.py`
- `tests/ai_v2/test_settings_suggestion_controller_apply.py`
- `tests/api/test_client_generate_images.py`
- `tests/api/test_client_options_throttling_v2.py`
- `tests/api/test_healthcheck_v2.py`
- `tests/api/test_sdxl_payloads.py`
- `tests/api/test_webui_api_options_safemode.py`
- `tests/api/test_webui_api_options_throttle.py`
- `tests/api/test_webui_api_upscale_payload.py`
- `tests/api/test_webui_healthcheck.py`
- `tests/api/test_webui_options_throttle_v2.py`
- `tests/api/test_webui_process_manager.py`
- `tests/api/test_webui_process_manager_shutdown_v2.py`
- `tests/api/test_webui_resources.py`
- `tests/api/test_webui_resources_adetailer_v2.py`
- `tests/api/test_webui_retry_policy_v2.py`
- `tests/app/test_bootstrap_webui_autostart.py`
- `tests/app/test_webui_launch_opens_browser_v2.py`
- `tests/cluster/test_worker_model_and_registry.py`
- `tests/conftest.py`
- `tests/controller/conftest.py`
- `tests/controller/test_adetailer_stage_integration_v2.py`
- `tests/controller/test_app_controller_add_to_queue_v2.py`
- `tests/controller/test_app_controller_config.py`
- `tests/controller/test_app_controller_diagnostics.py`
- `tests/controller/test_app_controller_job_failure_v2.py`
- `tests/controller/test_app_controller_lora_runtime.py`
- `tests/controller/test_app_controller_njr_exec.py`
- `tests/controller/test_app_controller_packs.py`
- `tests/controller/test_app_controller_pipeline_bridge.py`
- `tests/controller/test_app_controller_pipeline_draft_v2.py`
- `tests/controller/test_app_controller_pipeline_integration.py`
- `tests/controller/test_app_controller_run_bridge_v2.py`
- `tests/controller/test_app_controller_run_mode_defaults.py`
- `tests/controller/test_app_controller_run_now_bridge.py`
- `tests/controller/test_app_controller_settings_v2.py`
- `tests/controller/test_app_controller_shutdown_v2.py`
- `tests/controller/test_app_controller_start_run_shim.py`
- `tests/controller/test_app_to_pipeline_run_bridge_v2.py`
- `tests/controller/test_builder_pipeline_contract_v2_6.py`
- `tests/controller/test_cluster_controller.py`
- `tests/controller/test_controller_event_api_v2.py`
- `tests/controller/test_controller_job_lifecycle.py`
- `tests/controller/test_controller_learning_toggle.py`
- `tests/controller/test_controller_queue_execution.py`
- `tests/controller/test_core_run_path_v2.py`
- `tests/controller/test_gui_thread_dispatch_contract.py`
- `tests/controller/test_job_construction_b3.py`
- `tests/controller/test_job_execution_controller_queue_v2.py`
- `tests/controller/test_job_execution_controller_ui_dispatch.py`
- `tests/controller/test_job_history_controller_v2.py`
- `tests/controller/test_job_history_service.py`
- `tests/controller/test_job_lifecycle_logger_v2.py`
- `tests/controller/test_job_queue_integration_v2.py`
- `tests/controller/test_job_retry_metadata_v2.py`
- `tests/controller/test_job_service_container_cleanup.py`
- `tests/controller/test_job_service_di_v2.py`
- `tests/controller/test_job_service_history_v2.py`
- `tests/controller/test_job_service_njr_validation.py`
- `tests/controller/test_job_service_normalized_v2.py`
- `tests/controller/test_job_service_process_cleanup.py`
- `tests/controller/test_job_service_unit.py`
- `tests/controller/test_job_service_watchdog.py`
- `tests/controller/test_learning_execution_controller_gui_contract.py`
- `tests/controller/test_manual_acceptance_add_to_queue.py`
- `tests/controller/test_pack_draft_to_normalized_preview_v2.py`
- `tests/controller/test_pipeline_config_assembler_output_settings.py`
- `tests/controller/test_pipeline_controller_config_path.py`
- `tests/controller/test_pipeline_controller_history_refresh_v2.py`
- `tests/controller/test_pipeline_controller_job_specs_v2.py`
- `tests/controller/test_pipeline_controller_jobbuilder_integration_v2.py`
- `tests/controller/test_pipeline_controller_queue_mode.py`
- `tests/controller/test_pipeline_controller_run_modes_v2.py`
- `tests/controller/test_pipeline_controller_webui_gating.py`
- `tests/controller/test_pipeline_model_defaults_v2.py`
- `tests/controller/test_pipeline_preview_to_queue_v2.py`
- `tests/controller/test_pipeline_randomizer_config_v2.py`
- `tests/controller/test_pipeline_randomizer_integration_v2.py`
- `tests/controller/test_pipeline_replay_job_v2.py`
- `tests/controller/test_presets_integration_v2.py`
- `tests/controller/test_preview_queue_history_flow_v2.py`
- `tests/controller/test_profile_integration.py`
- `tests/controller/test_prompt_pack_preview_v2.py`
- `tests/controller/test_queue_callback_gui_thread_marshaling.py`
- `tests/controller/test_queue_operations_v2.py`
- `tests/controller/test_queue_worker_threading.py`
- `tests/controller/test_resource_refresh_adetailer_v2.py`
- `tests/controller/test_shutdown_inspector_v2.py`
- `tests/controller/test_stage_sequencer_controller_integration.py`
- `tests/controller/test_ui_dispatch_threading.py`
- `tests/controller/test_webui_connection_controller.py`
- `tests/controller/test_webui_connection_controller_health_v2.py`
- `tests/controller/test_webui_connection_ready_callback_v2.py`
- `tests/controller/test_webui_lifecycle_ux_v2.py`
- `tests/controller/test_webui_readiness_gate_v2.py`
- `tests/gui/test_gui_controller_bindings.py`
- `tests/gui/test_state_manager_legacy.py`
- `tests/gui_v2/conftest.py`
- `tests/gui_v2/test_adetailer_stage_card_v2.py`
- `tests/gui_v2/test_advanced_txt2img_stage_card_v2.py`
- `tests/gui_v2/test_advanced_upscale_stage_card_v2.py`
- `tests/gui_v2/test_api_failure_visualizer_v2.py`
- `tests/gui_v2/test_color_validation.py`
- `tests/gui_v2/test_core_config_webui_resources_v2.py`
- `tests/gui_v2/test_debug_hub_panel_v2.py`
- `tests/gui_v2/test_debug_log_panel_v2.py`
- `tests/gui_v2/test_diagnostics_dashboard_v2.py`
- `tests/gui_v2/test_engine_settings_dialog_v2.py`
- `tests/gui_v2/test_entrypoint_uses_v2_gui.py`
- `tests/gui_v2/test_error_modal_v2.py`
- `tests/gui_v2/test_gui_cancel_process_cleanup.py`
- `tests/gui_v2/test_gui_logging_integration.py`
- `tests/gui_v2/test_gui_v2_layout_skeleton.py`
- `tests/gui_v2/test_gui_v2_workspace_tabs_v2.py`
- `tests/gui_v2/test_job_explanation_panel_v2.py`
- `tests/gui_v2/test_job_history_panel_v2.py`
- `tests/gui_v2/test_job_queue_v2.py`
- `tests/gui_v2/test_log_display_v2.py`
- `tests/gui_v2/test_log_trace_panel_v2.py`
- `tests/gui_v2/test_logging_details_default_v2.py`
- `tests/gui_v2/test_main_window_smoke_v2.py`
- `tests/gui_v2/test_pipeline_adetailer_toggle_v2.py`
- `tests/gui_v2/test_pipeline_config_panel_lora_runtime.py`
- `tests/gui_v2/test_pipeline_defaults_v2.py`
- `tests/gui_v2/test_pipeline_dropdown_refresh_v2.py`
- `tests/gui_v2/test_pipeline_layout_scroll_v2.py`
- `tests/gui_v2/test_pipeline_left_column_config_v2.py`
- `tests/gui_v2/test_pipeline_presets_ui_v2.py`
- `tests/gui_v2/test_pipeline_queue_preview_v2.py`
- `tests/gui_v2/test_pipeline_run_controls_v2_add_to_queue_button.py`
- `tests/gui_v2/test_pipeline_run_controls_v2_pr203.py`
- `tests/gui_v2/test_pipeline_run_controls_v2_run_button.py`
- `tests/gui_v2/test_pipeline_run_controls_v2_run_now_button.py`
- `tests/gui_v2/test_pipeline_stage_cards_v2.py`
- `tests/gui_v2/test_pipeline_stage_checkbox_order_v2.py`
- `tests/gui_v2/test_pipeline_tab_layout_v2.py`
- `tests/gui_v2/test_pipeline_tab_wiring_v2.py`
- `tests/gui_v2/test_preview_panel_summary_v2.py`
- `tests/gui_v2/test_preview_panel_v2_normalized_jobs.py`
- `tests/gui_v2/test_process_logging_v2.py`
- `tests/gui_v2/test_queue_panel_autorun_and_send_job_v2.py`
- `tests/gui_v2/test_queue_panel_behavior_v2.py`
- `tests/gui_v2/test_queue_panel_v2.py`
- `tests/gui_v2/test_queue_panel_v2_normalized_jobs.py`
- `tests/gui_v2/test_queue_persistence_v2.py`
- `tests/gui_v2/test_queue_run_controls_restructure_v2.py`
- `tests/gui_v2/test_refiner_hires_upscale_ux_v2.py`
- `tests/gui_v2/test_run_control_bar_randomizer_summary_v2.py`
- `tests/gui_v2/test_run_controls_states.py`
- `tests/gui_v2/test_running_job_panel_controls_v2.py`
- `tests/gui_v2/test_running_job_panel_v2.py`
- `tests/gui_v2/test_scrolling_helper_v2.py`
- `tests/gui_v2/test_shutdown_journey_v2.py`
- `tests/gui_v2/test_sidebar_pack_preview_v2.py`
- `tests/gui_v2/test_sidebar_panel_v2_add_to_job.py`
- `tests/gui_v2/test_sidebar_presets_v2.py`
- `tests/gui_v2/test_stage_cards_layout_v2.py`
- `tests/gui_v2/test_status_bar_v2.py`
- `tests/gui_v2/test_status_bar_webui_controls_v2.py`
- `tests/gui_v2/test_theme_v2.py`
- `tests/gui_v2/test_theming_dark_mode_v2.py`
- `tests/gui_v2/test_tooltip_helper_v2.py`
- `tests/gui_v2/test_window_layout_normalization_v2.py`
- `tests/gui_v2/test_zone_map_card_order_v2.py`
- `tests/gui_v2/test_zone_map_v2.py`
- `tests/helpers/__init__.py`
- `tests/helpers/factories.py`
- `tests/helpers/gui_harness.py`
- `tests/helpers/gui_harness_v2.py`
- `tests/helpers/job_helpers.py`
- `tests/helpers/job_service_di_test_helpers.py`
- `tests/helpers/pipeline_fakes.py`
- `tests/helpers/pipeline_fixtures_v2.py`
- `tests/helpers/webui_mocks.py`
- `tests/history/test_history_replay_integration.py`
- `tests/history/test_history_roundtrip.py`
- `tests/history/test_history_schema_roundtrip.py`
- `tests/history/test_history_schema_v26.py`
- `tests/history/test_history_store_recording_v2.py`
- `tests/integration/__init__.py`
- `tests/integration/test_end_to_end_pipeline_v2.py`
- `tests/integration/test_golden_path_suite_v2_6.py`
- `tests/journey/test_phase1_pipeline_journey_v2.py`
- `tests/journeys/__init__.py`
- `tests/journeys/fakes/fake_pipeline_runner.py`
- `tests/journeys/journey_helpers_v2.py`
- `tests/journeys/test_jt01_prompt_pack_authoring.py`
- `tests/journeys/test_jt02_lora_embedding_integration.py`
- `tests/journeys/test_jt03_txt2img_pipeline_run.py`
- `tests/journeys/test_jt04_img2img_adetailer_run.py`
- `tests/journeys/test_jt05_upscale_stage_run.py`
- `tests/journeys/test_jt06_prompt_pack_queue_run.py`
- `tests/journeys/test_shutdown_no_leaks.py`
- `tests/journeys/test_v2_full_pipeline_journey.py`
- `tests/journeys/utils/__init__.py`
- `tests/journeys/utils/tk_root_factory.py`
- `tests/learning/test_learning_adapter_stub.py`
- `tests/learning/test_learning_adapter_v2.py`
- `tests/learning/test_learning_feedback_packaging.py`
- `tests/learning/test_learning_hooks_controller.py`
- `tests/learning/test_learning_hooks_pipeline_runner.py`
- `tests/learning/test_learning_plan_factory.py`
- `tests/learning/test_learning_record_builder.py`
- `tests/learning/test_learning_record_serialization.py`
- `tests/learning/test_learning_record_writer_integration.py`
- `tests/learning/test_learning_runner_stubs.py`
- `tests/learning/test_model_defaults_resolver.py`
- `tests/learning/test_model_profiles.py`
- `tests/learning_v2/smoke_test_learning_workflow.py`
- `tests/learning_v2/test_dataset_builder.py`
- `tests/learning_v2/test_learning_contract.py`
- `tests/learning_v2/test_learning_execution_controller_integration.py`
- `tests/learning_v2/test_learning_execution_runner_happy_path.py`
- `tests/learning_v2/test_recommendation_engine.py`
- `tests/learning_v2/test_run_metadata_and_feedback.py`
- `tests/legacy/tests_gui_v2_legacy/test_gui_v2_advanced_stage_cards_validation.py`
- `tests/pipeline/__init__.py`
- `tests/pipeline/test_config_merger_v2.py`
- `tests/pipeline/test_config_sweeps_v2.py`
- `tests/pipeline/test_executor_cancellation.py`
- `tests/pipeline/test_executor_generate_errors.py`
- `tests/pipeline/test_executor_model_switch_noop.py`
- `tests/pipeline/test_job_builder_v2.py`
- `tests/pipeline/test_job_model_unification_v2.py`
- `tests/pipeline/test_job_queue_persistence_v2.py`
- `tests/pipeline/test_job_service_njr_validation.py`
- `tests/pipeline/test_job_ui_summary_v2.py`
- `tests/pipeline/test_last_run_store_v2_5.py`
- `tests/pipeline/test_legacy_njr_adapter.py`
- `tests/pipeline/test_njr_prompt_pack_invariants.py`
- `tests/pipeline/test_payload_normalization_v2.py`
- `tests/pipeline/test_pipeline_adetailer_config.py`
- `tests/pipeline/test_pipeline_io_contracts.py`
- `tests/pipeline/test_pipeline_learning_hooks.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_pipeline_runner_cancel_token.py`
- `tests/pipeline/test_pipeline_runner_njr_diagnostics.py`
- `tests/pipeline/test_pipeline_runner_sdxl_refiner_hires.py`
- `tests/pipeline/test_pipeline_runner_variants.py`
- `tests/pipeline/test_prompt_pack_job_builder.py`
- `tests/pipeline/test_prompt_pack_njr_invariants.py`
- `tests/pipeline/test_prompt_pack_parser.py`
- `tests/pipeline/test_prompt_pack_resolution.py`
- `tests/pipeline/test_replay_run_plan_v2.py`
- `tests/pipeline/test_replay_vs_fresh_v2.py`
- `tests/pipeline/test_resolution_e2e.py`
- `tests/pipeline/test_run_config_prompt_source.py`
- `tests/pipeline/test_run_modes.py`
- `tests/pipeline/test_stage_plan_builder_v2_5.py`
- `tests/pipeline/test_stage_sequencer_plan_builder.py`
- `tests/pipeline/test_stage_sequencer_runner_integration.py`
- `tests/pipeline/test_stage_sequencing.py`
- `tests/pipeline/test_unified_config_resolution.py`
- `tests/pipeline/test_unified_job_summary_v2.py`
- `tests/pipeline/test_unified_prompt_resolution.py`
- `tests/pipeline/test_upscale_hang_diag.py`
- `tests/queue/test_job_history_store.py`
- `tests/queue/test_job_model.py`
- `tests/queue/test_job_queue_basic.py`
- `tests/queue/test_job_service_pipeline_integration_v2.py`
- `tests/queue/test_job_variant_metadata_v2.py`
- `tests/queue/test_jobrunner_integration.py`
- `tests/queue/test_queue_completion_to_history.py`
- `tests/queue/test_queue_njr_path.py`
- `tests/queue/test_single_node_runner.py`
- `tests/queue/test_single_node_runner_loopback.py`
- `tests/randomizer/test_randomizer_engine_v2.py`
- `tests/regression/test_snapshot_regression_v2.py`
- `tests/safety/test_advanced_stage_cards_import_safety.py`
- `tests/safety/test_ai_settings_generator_no_tk_imports.py`
- `tests/safety/test_gui_v2_adapters_no_tk_imports.py`
- `tests/safety/test_gui_v2_randomizer_ux_no_tk_imports.py`
- `tests/safety/test_learning_execution_no_tk_imports.py`
- `tests/safety/test_no_gui_imports_in_utils_safety.py`
- `tests/safety/test_randomizer_import_isolation_safety.py`
- `tests/scripts/test_batch_run_memory_hygiene.py`
- `tests/scripts/test_upscale_memory_hygiene.py`
- `tests/state/test_prompt_workspace_state.py`
- `tests/system/test_watchdog_ui_stall.py`
- `tests/test_api_client.py`
- `tests/test_cancel_token.py`
- `tests/test_config_passthrough.py`
- `tests/test_main_single_instance.py`
- `tests/tools/test_v2_classify_and_archive.py`
- `tests/unit/test_config_presets_v2.py`
- `tests/utils/test_api_failure_store_v2.py`
- `tests/utils/test_config_manager_presets.py`
- `tests/utils/test_diagnostics_bundle_v2.py`
- `tests/utils/test_error_envelope_v2.py`
- `tests/utils/test_file_access_logger_v2_5.py`
- `tests/utils/test_inmemory_log_handler.py`
- `tests/utils/test_jsonl_codec.py`
- `tests/utils/test_logger_integration.py`
- `tests/utils/test_logger_v2.py`
- `tests/utils/test_lora_embedding_parser.py`
- `tests/utils/test_negative_helpers_v2.py`
- `tests/utils/test_no_gui_imports_in_utils.py`
- `tests/utils/test_process_auto_scanner_service.py`
- `tests/utils/test_process_container_v2.py`
- `tests/utils/test_process_inspector_v2.py`
- `tests/utils/test_prompt_packs.py`
- `tests/utils/test_prompt_randomizer.py`
- `tests/utils/test_randomizer_import_isolation.py`
- `tests/utils/test_randomizer_matrix_base_prompt.py`
- `tests/utils/test_randomizer_matrix_prompt_modes.py`
- `tests/utils/test_randomizer_parity.py`
- `tests/utils/test_randomizer_sanitization.py`
- `tests/utils/test_snapshot_builder_v2.py`
- `tests/utils/test_watchdog_v2.py`

### src/ (*.py)
- `src/__init__.py`
- `src/ai/settings_generator_adapter.py`
- `src/ai/settings_generator_contract.py`
- `src/ai/settings_generator_driver.py`
- `src/api/__init__.py`
- `src/api/client.py`
- `src/api/healthcheck.py`
- `src/api/types.py`
- `src/api/webui_api.py`
- `src/api/webui_process_manager.py`
- `src/api/webui_resource_service.py`
- `src/api/webui_resources.py`
- `src/app_factory.py`
- `src/cli.py`
- `src/cluster/__init__.py`
- `src/cluster/worker_model.py`
- `src/cluster/worker_registry.py`
- `src/config/app_config.py`
- `src/controller/__init__.py`
- `src/controller/app_controller.py`
- `src/controller/cluster_controller.py`
- `src/controller/job_execution_controller.py`
- `src/controller/job_history_service.py`
- `src/controller/job_lifecycle_logger.py`
- `src/controller/job_service.py`
- `src/controller/learning_execution_controller.py`
- `src/controller/pipeline_controller.py`
- `src/controller/process_auto_scanner_service.py`
- `src/controller/settings_suggestion_controller.py`
- `src/controller/webui_connection_controller.py`
- `src/gui/__init__.py`
- `src/gui/adetailer_config_panel.py`
- `src/gui/advanced_prompt_editor.py`
- `src/gui/api_status_panel.py`
- `src/gui/app_layout_v2.py`
- `src/gui/app_state_v2.py`
- `src/gui/center_panel.py`
- `src/gui/config_panel.py`
- `src/gui/controller.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/core_config_panel_v2.py`
- `src/gui/design_system_v2.py`
- `src/gui/dropdown_loader_v2.py`
- `src/gui/engine_settings_dialog.py`
- `src/gui/enhanced_slider.py`
- `src/gui/gui_invoker.py`
- `src/gui/job_history_panel_v2.py`
- `src/gui/layout_v2.py`
- `src/gui/learning_review_dialog_v2.py`
- `src/gui/learning_state.py`
- `src/gui/log_panel.py`
- `src/gui/log_trace_panel_v2.py`
- `src/gui/main_window.py`
- `src/gui/main_window_v2.py`
- `src/gui/model_list_adapter_v2.py`
- `src/gui/model_manager_panel_v2.py`
- `src/gui/models/prompt_metadata.py`
- `src/gui/models/prompt_pack_model.py`
- `src/gui/negative_prompt_panel_v2.py`
- `src/gui/output_settings_panel_v2.py`
- `src/gui/panels_v2/__init__.py`
- `src/gui/panels_v2/api_failure_visualizer_v2.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/panels_v2/debug_log_panel_v2.py`
- `src/gui/panels_v2/history_panel_v2.py`
- `src/gui/panels_v2/job_explanation_panel_v2.py`
- `src/gui/panels_v2/layout_manager_v2.py`
- `src/gui/panels_v2/pipeline_config_panel_v2.py`
- `src/gui/panels_v2/pipeline_panel_v2.py`
- `src/gui/panels_v2/pipeline_run_controls_v2.py`
- `src/gui/panels_v2/preview_panel_v2.py`
- `src/gui/panels_v2/queue_panel_v2.py`
- `src/gui/panels_v2/randomizer_panel_v2.py`
- `src/gui/panels_v2/running_job_panel_v2.py`
- `src/gui/panels_v2/sidebar_panel_v2.py`
- `src/gui/panels_v2/status_bar_v2.py`
- `src/gui/pipeline_command_bar_v2.py`
- `src/gui/pipeline_controls_panel.py`
- `src/gui/pipeline_panel_v2.py`
- `src/gui/preview_panel_v2.py`
- `src/gui/prompt_pack_adapter_v2.py`
- `src/gui/prompt_pack_list_manager.py`
- `src/gui/prompt_pack_panel.py`
- `src/gui/prompt_pack_panel_v2.py`
- `src/gui/prompt_workspace_state.py`
- `src/gui/randomizer_panel_v2.py`
- `src/gui/resolution_panel_v2.py`
- `src/gui/scrolling.py`
- `src/gui/sidebar_panel_v2.py`
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`
- `src/gui/stage_cards_v2/base_stage_card_v2.py`
- `src/gui/stage_cards_v2/components.py`
- `src/gui/stage_cards_v2/validation_result.py`
- `src/gui/stage_chooser.py`
- `src/gui/state.py`
- `src/gui/status_bar_v2.py`
- `src/gui/theme.py`
- `src/gui/theme_v2.py`
- `src/gui/tooltip.py`
- `src/gui/utils/lora_embedding_parser.py`
- `src/gui/views/__init__.py`
- `src/gui/views/diagnostics_dashboard_v2.py`
- `src/gui/views/error_modal_v2.py`
- `src/gui/views/experiment_design_panel.py`
- `src/gui/views/experiment_design_panel_v2.py`
- `src/gui/views/learning_plan_table.py`
- `src/gui/views/learning_plan_table_v2.py`
- `src/gui/views/learning_review_panel.py`
- `src/gui/views/learning_review_panel_v2.py`
- `src/gui/views/learning_tab_frame.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/pipeline_tab_frame.py`
- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/views/prompt_tab_frame.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/views/run_control_bar.py`
- `src/gui/views/run_control_bar_v2.py`
- `src/gui/views/stage_cards_panel.py`
- `src/gui/views/stage_cards_panel_v2.py`
- `src/gui/widgets/config_sweep_widget_v2.py`
- `src/gui/widgets/expander_v2.py`
- `src/gui/widgets/matrix_helper_widget.py`
- `src/gui/widgets/scrollable_frame_v2.py`
- `src/gui/zone_map_v2.py`
- `src/gui_v2/adapters/__init__.py`
- `src/gui_v2/adapters/learning_adapter_v2.py`
- `src/gui_v2/adapters/pipeline_adapter_v2.py`
- `src/gui_v2/adapters/randomizer_adapter.py`
- `src/gui_v2/adapters/randomizer_adapter_v2.py`
- `src/gui_v2/adapters/status_adapter_v2.py`
- `src/gui_v2/validation/__init__.py`
- `src/gui_v2/validation/pipeline_txt2img_validator.py`
- `src/history/history_record.py`
- `src/history/history_schema_v26.py`
- `src/history/job_history_store.py`
- `src/learning/dataset_builder.py`
- `src/learning/feedback_manager.py`
- `src/learning/learning_adapter.py`
- `src/learning/learning_contract.py`
- `src/learning/learning_execution.py`
- `src/learning/learning_feedback.py`
- `src/learning/learning_plan.py`
- `src/learning/learning_profile_sidecar.py`
- `src/learning/learning_record.py`
- `src/learning/learning_record_builder.py`
- `src/learning/learning_runner.py`
- `src/learning/model_defaults_resolver.py`
- `src/learning/model_profiles.py`
- `src/learning/recommendation_engine.py`
- `src/learning/run_metadata.py`
- `src/main.py`
- `src/pipeline/__init__.py`
- `src/pipeline/config_merger_v2.py`
- `src/pipeline/config_variant_plan_v2.py`
- `src/pipeline/executor.py`
- `src/pipeline/job_builder_v2.py`
- `src/pipeline/job_models_v2.py`
- `src/pipeline/job_queue_v2.py`
- `src/pipeline/job_requests_v2.py`
- `src/pipeline/last_run_store_v2_5.py`
- `src/pipeline/legacy_njr_adapter.py`
- `src/pipeline/payload_builder.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/pipeline/prompt_pack_parser.py`
- `src/pipeline/randomizer_v2.py`
- `src/pipeline/replay_engine.py`
- `src/pipeline/resolution_layer.py`
- `src/pipeline/run_config.py`
- `src/pipeline/run_plan.py`
- `src/pipeline/stage_models.py`
- `src/pipeline/stage_sequencer.py`
- `src/pipeline/variant_planner.py`
- `src/pipeline/video.py`
- `src/queue/__init__.py`
- `src/queue/job_history_store.py`
- `src/queue/job_model.py`
- `src/queue/job_queue.py`
- `src/queue/single_node_runner.py`
- `src/queue/stub_runner.py`
- `src/randomizer/__init__.py`
- `src/randomizer/randomizer_engine_v2.py`
- `src/services/config_service.py`
- `src/services/diagnostics_service_v2.py`
- `src/services/queue_store_v2.py`
- `src/services/watchdog_system_v2.py`
- `src/utils/__init__.py`
- `src/utils/_extract_name_prefix.py`
- `src/utils/aesthetic.py`
- `src/utils/aesthetic_detection.py`
- `src/utils/api_failure_store_v2.py`
- `src/utils/cgroup_v2.py`
- `src/utils/config.py`
- `src/utils/debug_shutdown_inspector.py`
- `src/utils/diagnostics_bundle_v2.py`
- `src/utils/error_envelope_v2.py`
- `src/utils/exceptions_v2.py`
- `src/utils/file_access_log_v2_5_2025_11_26.py`
- `src/utils/file_io.py`
- `src/utils/graceful_exit.py`
- `src/utils/jsonl_codec.py`
- `src/utils/logger.py`
- `src/utils/logging_helpers_v2.py`
- `src/utils/negative_helpers_v2.py`
- `src/utils/preferences.py`
- `src/utils/process_container_v2.py`
- `src/utils/process_inspector_v2.py`
- `src/utils/prompt_pack.py`
- `src/utils/prompt_packs.py`
- `src/utils/queue_helpers_v2.py`
- `src/utils/randomizer.py`
- `src/utils/retry_policy_v2.py`
- `src/utils/single_instance.py`
- `src/utils/snapshot_builder_v2.py`
- `src/utils/state.py`
- `src/utils/system_info_v2.py`
- `src/utils/watchdog_v2.py`
- `src/utils/webui_discovery.py`
- `src/utils/webui_launcher.py`
- `src/utils/win_jobobject.py`

## Disallowed Changes
- Do not modify non-Python assets, JSON prompt packs, UI themes, or pipeline executor logic outside mechanical lint fixes.
- Do not introduce new dependencies.
- Do not change public APIs unless required to satisfy type/lint rules, and even then prefer `noqa` to interface churn.

## Notes for Codex
- If Ruff suggests a fix that changes semantics (e.g., replacing `== None` with `is None` is fine; rewriting logic is not), prefer a `noqa` or minimal local change.
- When suppressing: use the narrowest rule code (e.g., `# noqa: PLR2004`) and add a short reason.
