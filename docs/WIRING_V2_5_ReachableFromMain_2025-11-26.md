# StableNew Wiring Checklist (V2.5)

> Auto-generated from `repo_inventory.json` (reachable_from_main = true)  
> Inventory timestamp: 2025-11-25T02:49:25.647606Z

Status legend (to be filled in manually):
- `wired` – actively used in current V2/V2.5 flow
- `stub` – present but not yet functionally connected
- `legacy_candidate` – likely V1/obsolete, under review
- `future_feature` – reserved for planned capabilities (video, cluster, etc.)
- `unknown` – needs review

## AI / Smart Defaults

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/ai/settings_generator_v2.py` |  |  |  |  |  |
| `src/ai/settings_suggester_v2.py` |  |  |  |  |  |
| `src/ai/settings_templates_v2.py` |  |  |  |  |  |

## API / WebUI

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/api/webui_client.py` |  |  |  |  |  |
| `src/api/webui_config.py` |  |  |  |  |  |
| `src/api/webui_healthcheck.py` |  |  |  |  |  |
| `src/api/webui_process_manager.py` |  |  |  |  |  |

## Cluster / Distributed

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/cluster/cluster_controller_v2.py` |  |  |  |  |  |
| `src/cluster/cluster_state_v2.py` |  |  |  |  |  |

## Config / Settings

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/config/app_config_v2.py` |  |  |  |  |  |

## Controller

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/controller/app_controller_v2.py` |  |  |  |  |  |
| `src/controller/controller_state_v2.py` |  |  |  |  |  |
| `src/controller/gui_event_router_v2.py` |  |  |  |  |  |
| `src/controller/job_controller_v2.py` |  |  |  |  |  |
| `src/controller/pipeline_controller_v2.py` |  |  |  |  |  |
| `src/controller/profile_controller_v2.py` |  |  |  |  |  |
| `src/controller/settings_controller_v2.py` |  |  |  |  |  |
| `src/controller/startup_controller_v2.py` |  |  |  |  |  |
| `src/controller/webui_controller_v2.py` |  |  |  |  |  |
| `src/controller/window_lifecycle_v2.py` |  |  |  |  |  |

## Entry / Root

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/main.py` |  |  |  |  |  |

## GUI

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/gui/__init__.py` |  | yes |  |  |  |
| `src/gui/app_layout_v2.py` |  | yes | yes |  |  |
| `src/gui/center_panel.py` |  | yes | yes |  |  |
| `src/gui/controls_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/job_list_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/log_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/main_menu_v2.py` |  | yes | yes |  |  |
| `src/gui/main_window.py` |  | yes | yes |  |  |
| `src/gui/main_window_v2.py` |  | yes | yes |  |  |
| `src/gui/model_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/output_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/packs_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/pipeline_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/profiles_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/prompts_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/randomizer_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/run_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/settings_dialog_v2.py` |  | yes | yes |  |  |
| `src/gui/status_bar_v2.py` |  | yes | yes |  |  |
| `src/gui/theme.py` |  | yes | yes |  |  |
| `src/gui/txt2img_stage_card.py` |  | yes | yes |  |  |
| `src/gui/img2img_stage_card.py` |  | yes | yes |  |  |
| `src/gui/upscale_stage_card.py` |  | yes | yes |  |  |
| `src/gui/stage_chooser.py` |  | yes | yes |  |  |
| `src/gui/model_status_widget_v2.py` |  | yes | yes |  |  |
| `src/gui/progress_overlay_v2.py` |  | yes | yes |  |  |
| `src/gui/panels_v2/advanced_prompt_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/panels_v2/history_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/panels_v2/learning_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/panels_v2/queue_panel_v2.py` |  | yes | yes |  |  |
| `src/gui/panels_v2/webui_status_panel_v2.py` |  | yes | yes |  |  |
| `src/gui_v2/__init__.py` |  | yes |  |  |  |
| `src/gui_v2/app_root_v2.py` |  | yes | yes |  |  |
| `src/gui_v2/driver_v2.py` |  | yes | yes |  |  |
| `src/gui_v2/geometry_v2.py` |  | yes |  |  |  |
| `src/gui_v2/layout_v2.py` |  | yes | yes |  |  |
| `src/gui_v2/theme_v2.py` |  | yes | yes |  |  |
| `src/gui_v2/top_level_v2.py` |  | yes | yes |  |  |

## Learning

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/learning/learning_dataset_builder_v2.py` |  |  |  |  |  |
| `src/learning/learning_dataset_v2.py` |  |  |  |  |  |
| `src/learning/learning_pipeline_v2.py` |  |  |  |  |  |
| `src/learning/learning_plan_v2.py` |  |  |  |  |  |
| `src/learning/learning_record_v2.py` |  |  |  |  |  |
| `src/learning/learning_record_writer_v2.py` |  |  |  |  |  |
| `src/learning/learning_registry_v2.py` |  |  |  |  |  |
| `src/learning/learning_roles_v2.py` |  |  |  |  |  |
| `src/learning/learning_runner_v2.py` |  |  |  |  |  |
| `src/learning/learning_state_v2.py` |  |  |  |  |  |

## Pipeline

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/pipeline/pipeline_config_v2.py` |  |  |  |  |  |
| `src/pipeline/pipeline_executor_v2.py` |  |  |  |  |  |
| `src/pipeline/pipeline_models_v2.py` |  |  |  |  |  |
| `src/pipeline/pipeline_state_v2.py` |  |  |  |  |  |

## Queue / Jobs

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/queue/job_defs_v2.py` |  |  |  |  |  |
| `src/queue/job_events_v2.py` |  |  |  |  |  |
| `src/queue/job_queue_v2.py` |  |  |  |  |  |
| `src/queue/job_state_v2.py` |  |  |  |  |  |
| `src/queue/job_worker_v2.py` |  |  |  |  |  |

## Services

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/services/startup_service_v2.py` |  |  |  |  |  |

## Utils

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `src/utils/app_paths_v2.py` |  |  |  |  |  |
| `src/utils/app_state_v2.py` |  |  |  |  |  |
| `src/utils/config_loader_v2.py` |  |  |  |  |  |
| `src/utils/config_schema_v2.py` |  |  |  |  |  |
| `src/utils/logging_setup_v2.py` |  |  |  |  |  |
| `src/utils/path_utils_v2.py` |  |  |  |  |  |
| `src/utils/settings_utils_v2.py` |  |  |  |  |  |
| `src/utils/system_info_v2.py` |  |  |  |  |  |
| `src/utils/validation_v2.py` |  |  |  |  |  |
| `src/utils/webui_cache_v2.py` |  |  |  |  |  |
