# D-NSFW-SFW-001 - Content Visibility Mode Discovery (SFW/NSFW)

Status: Discovery
Date: 2026-03-27

## 1) Problem Statement

StableNew currently has no canonical, global content-visibility mode that can be flipped between `SFW` and `NSFW` and then applied consistently across prompt surfaces, LoRA/resource selectors, queue/running/history job displays, learning/review panes, and output/preview/media pickers.

The user request is to add one mode toggle and have it:

1. persist across restarts
2. apply dynamically to all relevant content surfaces
3. avoid architecture drift (NJR -> Queue -> Runner remains unchanged)

## 2) Architectural Constraints (v2.6)

The feature must preserve:

1. GUI as intent/display layer only
2. controller/service layer as orchestration point
3. no alternate execution path outside NJR -> Queue -> Runner
4. no duplicate filtering logic scattered across tabs

Therefore this should be implemented as a **single canonical visibility policy contract** consumed by GUI/query surfaces, not per-widget ad hoc filtering.

## 3) Existing Persistence and State Hooks

### 3.1 Persistence already available

- `src/services/ui_state_store.py` already persists window + tab and arbitrary UI state payloads.
- `src/gui/main_window_v2.py` already loads/saves nested tab state blobs (`learning`, `movie_clips`, `svd`, `video_workflow`, etc.).
- `src/gui/app_state_v2.py` already holds global toggles (`help_mode_enabled`, `learning_enabled`, `auto_run_queue`) with listener notifications.

### 3.2 Best insertion point for mode state

A `content_visibility_mode` field should live in `AppStateV2` and be persisted via `ui_state_store` by `MainWindowV2` as a root-level UI preference section (for example `state["content_visibility"]`).

## 4) Surfaces That Benefit From SFW/NSFW Mode

The following areas currently display, derive, or route user-visible content and should consume the same mode contract.

## 4.1 Global shell + state

1. `src/gui/main_window_v2.py` (top-level toggle placement, persistence load/save)
2. `src/gui/app_state_v2.py` (canonical runtime state + notifications)
3. `src/services/ui_state_store.py` (schema path for persisted mode)

## 4.2 Prompt and pack authoring/selection surfaces

1. `src/gui/views/prompt_tab_frame_v2.py`
2. `src/gui/prompt_pack_panel_v2.py`
3. `src/gui/prompt_workspace_state.py`
4. `src/gui/sidebar_panel_v2.py` (pack preview + prompt-adjacent controls)
5. `src/gui/widgets/lora_picker_panel.py`

Potential behaviors:

- hide or de-prioritize NSFW-tagged prompts/packs in SFW mode
- hide NSFW-tagged LoRAs from selector lists
- prevent accidental NSFW prompt preview in compact summaries

## 4.3 Pipeline and queue runtime surfaces

1. `src/gui/views/pipeline_tab_frame_v2.py`
2. `src/gui/panels_v2/queue_panel_v2.py`
3. `src/gui/panels_v2/running_job_panel_v2.py`
4. `src/gui/panels_v2/history_panel_v2.py`
5. `src/controller/job_history_service.py`

Potential behaviors:

- redact or suppress NSFW prompt strings in list cells and summaries when mode is SFW
- filter history rows to SFW-safe entries by default while preserving access when switched back to NSFW

## 4.4 Review, learning, and discovered outputs

1. `src/gui/views/review_tab_frame_v2.py`
2. `src/gui/views/learning_tab_frame_v2.py`
3. `src/gui/views/learning_review_panel.py`
4. `src/gui/views/learning_review_panel_v2.py`
5. `src/gui/views/discovered_review_table.py`
6. `src/learning/output_scanner.py`
7. `src/learning/discovered_review_store.py`

Potential behaviors:

- SFW mode hides NSFW-rated discovered items from review queues
- metadata panels redact sensitive prompt tokens/tags
- learning recommendation feeds exclude NSFW evidence while mode is SFW

## 4.5 Output, preview, and file-oriented surfaces

1. `src/gui/preview_panel_v2.py`
2. `src/gui/views/photo_optimize_tab_frame_v2.py`
3. `src/gui/views/movie_clips_tab_frame_v2.py`
4. `src/gui/views/svd_tab_frame_v2.py`
5. `src/gui/views/video_workflow_tab_frame_v2.py`

Potential behaviors:

- file/media browsers hide NSFW-tagged outputs
- preview panel suppresses thumbnails flagged NSFW in SFW mode
- output metadata viewers redact sensitive fields

## 5) Data/Contract Gap To Close

Current code has no explicit cross-surface classification contract like `content_rating` / `content_tags` / `safe_for_work` that every view can trust.

This migration needs:

1. one canonical metadata contract for visibility classification
2. one resolver service to interpret mode + metadata consistently
3. one app-state event to refresh all affected surfaces

## 6) Recommended PR Series

1. **PR-CONFIG-271**: contract + persisted mode state
2. **PR-CTRL-272**: controller/service resolver + selector/query path wiring
3. **PR-GUI-273**: global toggle + surface integrations
4. **PR-TEST-274**: regression, integration, and journey coverage

This sequence minimizes risk by introducing contracts first, then behavior, then UX, then full test hardening.

## 7) Risks

1. Divergent filtering logic across tabs if resolver is not centralized
2. Breaking historical visibility assumptions in review/learning if metadata fallback rules are unclear
3. Over-filtering legitimate content due to missing/unknown metadata classification

Mitigation: treat unknown classification as configurable policy (default conservative in SFW mode), and log filtering decisions in diagnostics surfaces.
