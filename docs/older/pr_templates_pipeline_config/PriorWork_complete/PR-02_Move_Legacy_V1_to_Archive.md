# PR-02 — Move Legacy/V1 Files to Archive

## Summary

Using the outputs of **PR-01** (`repo_inventory.json`, `ACTIVE_MODULES.md`, and `LEGACY_CANDIDATES.md`), create a **clear separation** between:

- the **active V2 codebase** that is reachable from `src/main.py`, and  
- **legacy/V1 and unused code** that should be preserved but no longer live in the main source tree.

This PR **moves**, but does not delete, legacy code into an `archive/` hierarchy and ensures the application still runs.

> This PR assumes PR-01 has already produced `repo_inventory.json`, `ACTIVE_MODULES.md`, and `LEGACY_CANDIDATES.md` at the repo root or under `docs/`.

---

## Inputs from PR-01

- `repo_inventory.json`  
  - Machine-readable list of all code files with:
    - `reachable_from_main` flag  
    - `is_gui` / `has_tk` flags  
    - `has_v1_marker` hints  
    - module path and basic import info

- `ACTIVE_MODULES.md`  
  - Human-readable narrative of modules reachable from `src/main.py` (the “active” surface).

- `LEGACY_CANDIDATES.md`  
  - Curated list of likely V1 / legacy files (GUI, pipeline, tests, utils).

This PR **must** treat those three artifacts as the **source of truth** for deciding what is safe to archive.

---

## Goals

1. **Remove V1/legacy noise from the active source tree** without deleting code.  
2. Ensure that **no archived modules are imported** during normal app startup and basic pipeline runs.  
3. Make it obvious to future contributors and agents **where V2 work lives** and where legacy code is kept for reference.  
4. Preserve enough structure in `archive/` that we can still refer back to legacy implementations if needed.

---

## Non-Goals

- Refactoring the logic of any module beyond minimal import path adjustments.  
- Changing the behaviour of the app beyond what is strictly necessary to keep it running.  
- Implementing V2 GUI layout or theme improvements (Phase 2).  
- Implementing Roadmap features (Phase 3).

---

## Target Archive Structure

Create a top-level `archive/` folder with subfolders grouped by domain:

```text
archive/
  gui_v1/           # Old stage cards and legacy GUI panes
  pipeline_v1/      # Obsolete pipeline modules
  tests_v1/         # Old tests that target legacy code
  utils_legacy/     # Utilities that are no longer referenced
  docs_legacy/      # Old docs superseded by V2 docs
  README.md         # Explains archive conventions
  ARCHIVE_MAP.md    # Lists original → archive paths
```

The exact mapping of files will be driven by `LEGACY_CANDIDATES.md` + `repo_inventory.json`.

---

## Selection Criteria

### Files that SHOULD be archived

A file is a **strong archive candidate** if **all** of the following are true:

1. `reachable_from_main == false` in `repo_inventory.json`, **and**  
2. It appears in `LEGACY_CANDIDATES.md`, **and**  
3. It is either:
   - clearly part of older GUI stage panels (e.g., `txt2img_stage_card.py`, `upscale_stage_card.py`, older `center_panel`–style layouts), or  
   - an earlier pipeline implementation now superseded by current V2 runner, or  
   - tests that only target those legacy modules, or  
   - a utility with no references from any active module.

If in doubt, favor **keeping** a module in-place rather than archiving it.

### Files that MUST NOT be archived

- Any file marked `reachable_from_main == true` in `repo_inventory.json`.  
- All core controller modules, e.g.:
  - `src/controller/app_controller.py`
  - `src/controller/pipeline_controller.py`
  - `src/controller/job_execution_controller.py`
  - `src/controller/learning_execution_controller.py`
  - `src/controller/job_history_service.py`
- All V2 GUI components, e.g.:
  - `src/gui/main_window_v2.py`
  - `src/gui/app_layout_v2.py`
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/randomizer_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - `src/gui/job_history_panel_v2.py`
  - `src/gui/learning_review_dialog_v2.py`
  - `src/gui/prompt_pack_panel_v2.py`
  - `src/gui/core_config_panel_v2.py`
  - `src/gui/model_manager_panel_v2.py`
  - `src/gui/negative_prompt_panel_v2.py`
  - `src/gui/output_settings_panel_v2.py`
  - `src/gui/pipeline_command_bar_v2.py`
  - `src/gui/stage_cards_v2/*`
- All current pipeline modules:
  - `src/pipeline/pipeline_runner.py`
  - `src/pipeline/executor.py`
  - `src/pipeline/stage_sequencer.py`
  - `src/pipeline/variant_planner.py`
- Queue and job lifecycle modules:
  - `src/queue/job_model.py`
  - `src/queue/job_queue.py`
  - `src/queue/job_history_store.py`
  - `src/queue/single_node_runner.py`
- Learning system modules:
  - `src/learning/learning_record.py`
  - `src/learning/learning_record_builder.py`
  - `src/learning/learning_plan.py`
  - `src/learning/learning_runner.py`
  - `src/learning/model_profiles.py`
  - `src/learning/run_metadata.py`
- Any test that clearly targets active V2 modules.

If a file is marked reachable in `repo_inventory.json`, **do not move it** in this PR, even if it looks “old”.

---

## Implementation Plan

### Step 1 — Create Archive Folders & README

1. Create `archive/` at the repo root with the subdirectories shown above.  
2. Add `archive/README.md` to explain:
   - Why code is archived instead of deleted.  
   - Rules for when to move something into or out of `archive/`.  
3. Add `archive/ARCHIVE_MAP.md`:
   - A simple table or list of `original_path → archive_path + reason`.
   - CODEX can append entries as it moves files.

### Step 2 — Build Move List from Artifacts

1. Read `LEGACY_CANDIDATES.md`.  
2. For each candidate path, look it up in `repo_inventory.json`:
   - If `reachable_from_main == false`, mark it as **safe-to-archive**.  
   - If `reachable_from_main == true`, **skip** and annotate in `ARCHIVE_MAP.md` as “still active”.  
3. Classify each safe-to-archive file into one of the archive buckets (`gui_v1`, `pipeline_v1`, etc.) based on its path prefix (`src/gui/`, `src/pipeline/`, `tests/`, `src/utils/`, etc.).

### Step 3 — Move the Files

For each safe-to-archive file:

1. Create the destination directory if needed, e.g.:  
   - `src/gui/txt2img_stage_card.py` → `archive/gui_v1/txt2img_stage_card.py`  
2. Move the file.  
3. Add an entry to `archive/ARCHIVE_MAP.md`, for example:

   ```text
   src/gui/txt2img_stage_card.py -> archive/gui_v1/txt2img_stage_card.py  # superseded by stage_cards_v2/advanced_txt2img_stage_card_v2.py
   ```

4. If the file had associated tests (from `tests/...`), move those into `archive/tests_v1/` and map them as well.

### Step 4 — Clean Up Imports (Minimal)

1. Run a simple pass over the remaining active code to detect imports of moved modules.  
2. For any import of a now-archived module:
   - If the importing module is itself legacy, consider archiving it too.  
   - If the importing module is **active** and the usage is dead/unreachable, remove the unused import.  
   - If the importing module is active and the usage is real, **stop and flag for manual review** in `ARCHIVE_MAP.md` as a potential mistake in classification.

The goal is to avoid **active code depending on `archive/` modules**.

### Step 5 — Update ACTIVE_MODULES.md (If Needed)

If any files previously thought to be active are now confirmed legacy and moved:

- Update `ACTIVE_MODULES.md` to:

  - Remove them from the “active” narrative, or  
  - Add a short note indicating they’ve been archived.

If the list was purely reachability-based and remains consistent with `repo_inventory.json`, minimal edits may be needed.

---

## Files Expected to Change / Be Added

**New:**

- `archive/README.md`  
- `archive/ARCHIVE_MAP.md`  
- `archive/gui_v1/**` (moved files)  
- `archive/pipeline_v1/**`  
- `archive/tests_v1/**`  
- `archive/utils_legacy/**`  
- `archive/docs_legacy/**` (if docs are moved)

**Updated:**

- `docs/ACTIVE_MODULES.md` (if needed)  
- `docs/LEGACY_CANDIDATES.md` (optional notes)  
- Any module whose imports are cleaned up after the move.

No changes should be made to:

- `src/main.py`  
- Active V2 GUI and controller files  
- Active pipeline, queue, or learning modules

beyond import cleanup.

---

## Tests & Validation

1. **App Startup Check**  
   - Run: `python -m src.main`  
   - Expectation: the GUI starts with current behaviour (even if layout/theme is still rough).  
   - No `ImportError` or `ModuleNotFoundError` from moved files.

2. **Smoke Pipeline Run**  
   - From the GUI (or CLI), run a simple txt2img job.  
   - Expectation: job completes successfully, outputs image(s) as before.

3. **Archive Import Guard (Optional but Recommended)**  
   - Add a basic test that imports all `src.*` modules and fails if any of them import `archive.*` modules.  
   - This ensures the archive remains “cold storage” rather than creeping back into active code.

4. **Repo Inventory Refresh (Optional)**  
   - Re-run the PR-01 inventory script.  
   - Confirm that:
     - `repo_inventory.json` no longer lists archived paths under `src/`.  
     - `ACTIVE_MODULES.md` remains consistent.

---

## Acceptance Criteria

- Obvious legacy/V1 modules are moved out of `src/` into `archive/` according to the criteria above.  
- The StableNew app still starts and can run at least one basic job.  
- No active code imports modules from `archive/`.  
- `archive/ARCHIVE_MAP.md` documents what was moved and why.  
- The separation between **active V2** and **legacy** code is clear to a new contributor or agent reading the tree.
