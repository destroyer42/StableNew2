# PR-GUI-235 - Core Config to Base Generation Ownership Reset and Saved Recipe UX

Status: Implemented 2026-03-21

Status: Specification Revised
Priority: HIGH
Effort: LARGE
Phase: Pipeline UX Cleanup
Date: 2026-03-20

## Why This PR Must Be Rewritten

The earlier spec was under-scoped. It only allowed `core_config` and `recipe`
files, but the real user-facing sidebar surface and the legacy ownership seams
live across multiple files:

- `src/gui/sidebar_panel_v2.py` owns the visible card titles, recipe dropdown,
  action menu, and config-source text.
- `src/gui/core_config_panel_v2.py` owns the embedded base controls, but still
  exposes the legacy `Core Config` concept and only covers a subset of the
  intended base-generation fields.
- `src/gui/views/stage_cards_panel_v2.py` still serializes txt2img base fields
  as if the stage card were the authoritative global source.
- `src/gui/views/pipeline_tab_frame_v2.py` currently syncs pipeline overrides
  from `StageCardsPanel.to_overrides(...)` only, which means the sidebar base
  card is not actually authoritative.
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py` still duplicates
  many of the exact fields that the `Base Generation` surface is supposed to
  own.
- `src/controller/app_controller.py`, `src/gui/main_window_v2.py`,
  `src/gui/dropdown_loader_v2.py`, and `src/main.py` still use `core_*`
  vocabulary and accessors.

If this PR only changes labels, it becomes a partial migration and leaves the
legacy precedence model alive underneath the new names. That is not allowed.

## Intent

This PR is the clean ownership reset for the Pipeline sidebar:

1. Remove the legacy `Core Config` concept from the active v2 GUI path.
2. Replace it with an explicit `Base Generation` boundary.
3. Remove duplicated base-field ownership from the txt2img stage card path.
4. Rename user-facing `Pipeline Presets` to `Saved Recipes`.
5. Make recipe selection readable without memorizing names.
6. Make precedence visible instead of implied.

This PR is not just a cosmetic rename. It is the GUI-facing ownership reset for
base generation fields.

## Product Rules Locked By This PR

1. `Base Generation` owns the common image-generation defaults:
   - model
   - VAE
   - sampler
   - scheduler
   - steps
   - CFG
   - resolution preset
   - width
   - height
   - seed
2. Stage cards own only stage-local overrides and stage-local toggles.
3. The txt2img stage card must not remain a second owner for the above base
   fields after this PR lands.
4. `Saved Recipes` is the user-facing label for persisted reusable pipeline
   configurations in the Pipeline tab.
5. The active sidebar must show readable recipe summaries:
   - base model
   - resolution
   - sampler
   - enabled stages
   - last updated
6. Precedence must be explicit:
   - base generation applies globally
   - stage cards only override stage-local behavior
7. No compatibility shim methods such as `get_core_config_panel()` or
   `refresh_core_config_from_webui()` may remain in the active v2 path after
   this PR.

## Ground Truth In The Current Repo

The current implementation still has these legacy seams:

1. `SidebarPanelV2` still renders cards titled `Pipeline Presets` and
   `Core Config`.
2. `CoreConfigPanelV2` still has legacy naming and does not yet own scheduler
   or seed.
3. `StageCardsPanel.to_overrides(...)` still emits base/global fields from the
   txt2img card:
   - `model`
   - `model_name`
   - `vae_name`
   - `sampler`
   - `steps`
   - `cfg_scale`
   - `width`
   - `height`
4. `PipelineTabFrameV2._sync_state_overrides()` only reads
   `StageCardsPanel.to_overrides(...)`, which means the sidebar base card is
   not truly authoritative.
5. `AppController` still applies recipe-derived base fields through
   `_extract_core_overrides_from_preset(...)` and `_apply_core_overrides(...)`.
6. `main_window_v2.py`, `dropdown_loader_v2.py`, and `main.py` still wire the
   GUI through `core_config_panel` and `refresh_core_config_from_webui()`.

## Goals

1. Replace the legacy `Core Config` surface with a real `Base Generation`
   surface.
2. Move base-field ownership out of the txt2img stage card path.
3. Rename `Pipeline Presets` to `Saved Recipes` in the live Pipeline UI.
4. Add readable recipe summaries without changing the underlying preset storage
   contract.
5. Make base-vs-stage precedence visible in the active sidebar.
6. Remove the active `core_*` GUI API vocabulary from the v2 path in the same
   PR.

## Non-Goals

1. Do not replace saved recipes with learning-driven recommendations yet.
2. Do not change the `ConfigManager` on-disk preset storage contract in this
   PR.
3. Do not touch runner, executor, queue, or backend logic.
4. Do not rewrite the GUI toolkit.
5. Do not broaden this into a full controller refactor beyond the base
   generation/recipe boundary.

## Required File Boundary

### Files That Must Be Modified

#### Active GUI surface

- `src/gui/sidebar_panel_v2.py`
- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/views/stage_cards_panel_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`

#### Base generation boundary

- `src/gui/core_config_panel_v2.py`
- `src/gui/base_generation_panel_v2.py`

Note:

- This PR should move/rename the active panel from `core_config_panel_v2.py`
  to `base_generation_panel_v2.py` and remove the old active import path in the
  same PR.
- Leaving the old file as a live shim is forbidden.

#### Recipe summary and config helpers

- `src/gui/config_adapter_v26.py`
- `src/controller/app_controller_services/gui_config_service.py`
- `src/gui/recipe_summary_v2.py`

#### Active controller / app wiring touched by the rename

- `src/controller/app_controller.py`
- `src/gui/main_window_v2.py`
- `src/gui/dropdown_loader_v2.py`
- `src/main.py`

#### Tests

- `tests/gui_v2/test_sidebar_presets_v2.py`
- `tests/gui_v2/test_pipeline_presets_ui_v2.py`
- `tests/gui_v2/test_gui_v2_layout_skeleton.py`
- `tests/gui_v2/test_core_config_controller.py`
- `tests/gui_v2/test_core_config_webui_resources_v2.py`
- `tests/gui_v2/test_recipe_summary_v2.py`
- `tests/gui_v2/test_pipeline_base_generation_ownership_v2.py`
- `tests/test_core_config_controller.py`
- `tests/gui_v2/validate_core_config.py`
- `tests/validate_core_config.py`

#### Docs

- `docs/StableNew Roadmap v2.6.md`
- `docs/GUI_Ownership_Map_v2.6.md`
- `docs/PR_Backlog/PR-GUI-235-Core-Config-to-Base-Generation-and-Recipe-Summary-UX.md`

### Files Explicitly Forbidden

- `src/pipeline/**`
- `src/video/**`
- `src/refinement/**`
- `src/learning/**`
- `src/utils/config.py`
- `src/queue/**`

## Implementation Plan

### 1. Rename the boundary cleanly, not cosmetically

1. Move the active panel from `CoreConfigPanelV2` to
   `BaseGenerationPanelV2`.
2. Update the active sidebar card title to `Base Generation`.
3. Rename the active sidebar/public accessors in the same PR:
   - `core_config_panel` -> `base_generation_panel`
   - `core_config_card` -> `base_generation_card`
   - `get_core_config_panel()` -> `get_base_generation_panel()`
   - `refresh_core_config_from_webui()` -> `refresh_base_generation_from_webui()`
   - `get_core_overrides()` -> `get_base_generation_overrides()`
4. Update every active v2 caller in the same PR:
   - `AppController`
   - `main_window_v2.py`
   - `dropdown_loader_v2.py`
   - `main.py`
5. Do not leave alias methods or compat shims behind.

### 2. Make Base Generation the actual owner of base fields

1. Expand the new `BaseGenerationPanelV2` so it owns:
   - model
   - VAE
   - sampler
   - scheduler
   - steps
   - CFG
   - resolution preset
   - width
   - height
   - seed
2. Remove those same fields from the active txt2img stage-card ownership path.
3. `AdvancedTxt2ImgStageCardV2` must keep only txt2img-local controls after
   the PR.
4. `StageCardsPanel.to_overrides(...)` must stop emitting global/base fields.
   It should emit stage-local payload only.
5. `PipelineTabFrameV2._sync_state_overrides()` must merge:
   - base generation overrides from the sidebar
   - stage-local overrides from the stage cards
   instead of treating stage cards as the only source.

### 3. Make Saved Recipes readable and intentional

1. Rename the visible sidebar card from `Pipeline Presets` to `Saved Recipes`.
2. Keep the underlying stored preset format unchanged in this PR.
3. Add a recipe summary helper/view model that produces:
   - display name
   - base model
   - sampler
   - resolution
   - enabled stages
   - last updated timestamp from file metadata
4. Show the summary directly in the sidebar when a recipe is selected.
5. Replace the old `Defaults` / `Preset: <name>` label with clearer state:
   - `Working state`
   - or a selected saved recipe name and summary
6. `+ New` remains allowed, but all visible wording must use `Recipe` rather
   than `Preset`.

### 4. Make precedence visible

1. Add concise helper text to the base generation surface explaining that these
   defaults apply across the image pipeline.
2. Add clear copy to the txt2img card indicating that stage-local controls do
   not replace the global base-generation contract.
3. Add a regression test proving that stage-card serialization no longer
   redefines base model/sampler/resolution ownership.

### 5. Update controller recipe application to the new boundary

1. `AppController` must stop talking in `core_overrides` terms on the active
   v2 path.
2. Recipe extraction/application helpers must follow the new base-generation
   contract and include the full base field set that the panel now owns.
3. No direct stage-card fallback is allowed for base-generation-owned fields in
   the active Pipeline tab path.

### 6. Test and cleanup the adjacent legacy artifacts

1. Update or remove the duplicate root-level `core_config` validation scripts
   in the same PR so the renamed panel does not leave broken or stale test
   utilities behind.
2. Update GUI ownership and roadmap docs so the new boundary is explicit.

## Adjacent Legacy Elements Identified

### Must Be Absorbed By This PR

1. `StageCardsPanel.to_overrides(...)` flattening base fields out of txt2img.
2. `PipelineTabFrameV2._sync_state_overrides()` ignoring the sidebar base card.
3. `AppController` base-field application via `core_*` helper names.
4. `main_window_v2.py`, `dropdown_loader_v2.py`, and `main.py` hard-coded
   `core_config_*` names.
5. Duplicate `core_config` validation/import scripts under `tests/`.

### Explicitly Flagged But Deferred

1. `ConfigManager` still stores saved recipes under `presets/` and still uses
   `preset` API names internally.
   - This is acceptable for this PR because the user-facing migration boundary
     is the Pipeline sidebar, not the on-disk storage contract.
   - If desired, a later controller/config cleanup PR can rename the internal
     storage vocabulary.
2. The older non-v2 `src/gui/views/pipeline_tab_frame.py` path is not in scope.
   The active product path is v2.

## Testing Plan

1. Update the existing sidebar preset tests to the new `Saved Recipes` copy and
   summary behavior.
2. Update the existing base-generation dropdown/resource tests to the renamed
   panel and expanded field set.
3. Add a focused ownership regression test proving:
   - base fields come from the base-generation panel
   - stage cards emit stage-local data only
   - pipeline override sync merges the two surfaces correctly
4. Run `pytest --collect-only -q`.
5. Run focused GUI tests for:
   - sidebar recipes
   - base generation resources
   - pipeline override sync / ownership
   - layout skeleton

## Verification Criteria

### Success Criteria

1. No user-facing `Core Config` string remains in the active v2 Pipeline UI.
2. No user-facing `Pipeline Presets` string remains in the active v2 Pipeline
   UI.
3. `Base Generation` owns model, VAE, sampler, scheduler, steps, CFG,
   resolution, width, height, and seed.
4. The txt2img stage card no longer acts as a second owner for those base
   fields.
5. `StageCardsPanel.to_overrides(...)` no longer emits global/base fields.
6. Saved recipes show readable summaries without memorizing names.
7. All active v2 call sites use the renamed base-generation API and there are
   no active `core_config_*` accessors left behind.

### Failure Criteria

1. The sidebar labels change but the base/stage ownership split does not.
2. `core_config_panel_v2.py` remains as a live active GUI shim.
3. The txt2img card still serializes global/base fields after the PR.
4. `PipelineTabFrameV2` still ignores the base-generation panel during state
   sync.
5. Recipe UI remains name-only with no readable summary.

## Reviewer Checklist

1. Confirm the active file/class rename is complete and not shimmed.
2. Confirm stage-card serialization no longer carries global/base fields.
3. Confirm the sidebar now clearly distinguishes `Base Generation` from
   stage-local controls.
4. Confirm recipe summaries are rendered from real saved recipe content, not
   placeholder text.
5. Confirm no adjacent `core_*` GUI vocabulary remains in the active v2 path.

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending
