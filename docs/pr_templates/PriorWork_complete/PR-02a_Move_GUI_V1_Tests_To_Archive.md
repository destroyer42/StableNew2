# PR-02a — Move GUI V1 Tests to Archive (Safe Subset)

## Summary

This PR is a **narrow, low‑risk subset** of the original PR‑02.  
It only moves **clearly-identified GUI V1 test files** into an archive directory and does **not** touch any V2 or in‑progress V2 modules (including the stage cards).

The goal is to start the repo cleanup in a way that:

- Is obviously safe.
- Does not require deep graph analysis.
- Cannot accidentally break the running app or V2 work.

Once this PR is merged and validated, we can follow with additional, similarly small PRs for other legacy clusters.

---

## Scope

**In scope:**

- Move everything under `tests/gui_v1_legacy/` into `archive/tests_v1/gui_v1_legacy/`.
- Move any GUI V1 helper tests that are clearly V1-only into `archive/tests_v1/`.

**Explicitly out of scope:**

- Any file whose name contains `stage_card` (e.g. `txt2img_stage_card.py`, `img2img_stage_card.py`, `upscale_stage_card.py`).
- Any file under `src/gui/stage_cards_v2/`.
- Any V2 panels (`*_panel_v2.py`) and V2 layout files.
- Any controller, pipeline, learning, or randomizer modules.

Stage cards and related V2 GUI modules are **intentional V2 work**, even if they are currently not wired correctly into `src/main.py`. They must remain in the active tree for now.

---

## Files to Move

Based on `LEGACY_CANDIDATES.md` and directory naming, the following are **safe, clearly V1 GUI tests** and should be moved as a unit.

### 1. GUI V1 Legacy Tests (Full Folder)

**From:**

```text
tests/gui_v1_legacy/__init__.py
tests/gui_v1_legacy/conftest.py
tests/gui_v1_legacy/test_adetailer_panel.py
tests/gui_v1_legacy/test_api_status_panel.py
tests/gui_v1_legacy/test_config_meta_updates.py
tests/gui_v1_legacy/test_config_panel.py
tests/gui_v1_legacy/test_controller_lifecycle.py
tests/gui_v1_legacy/test_editor_and_summary.py
tests/gui_v1_legacy/test_functional_buttons.py
tests/gui_v1_legacy/test_gui_test_mode.py
tests/gui_v1_legacy/test_gui_thread_marshaling.py
tests/gui_v1_legacy/test_layout_dedup.py
tests/gui_v1_legacy/test_load_config_behavior.py
tests/gui_v1_legacy/test_log_panel.py
tests/gui_v1_legacy/test_logpanel_binding.py
tests/gui_v1_legacy/test_main_window_pipeline.py
tests/gui_v1_legacy/test_main_window_threading.py
tests/gui_v1_legacy/test_matrix_ui.py
tests/gui_v1_legacy/test_pipeline_controls_panel.py
tests/gui_v1_legacy/test_pipeline_double_run.py
tests/gui_v1_legacy/test_pipeline_runs.py
tests/gui_v1_legacy/test_pipeline_state_cleanup.py
tests/gui_v1_legacy/test_pr1_layout_cleanup.py
tests/gui_v1_legacy/test_progress_eta.py
tests/gui_v1_legacy/test_prompt_pack_editor.py
tests/gui_v1_legacy/test_prompt_pack_panel.py
```

**To:**

```text
archive/tests_v1/gui_v1_legacy/__init__.py
archive/tests_v1/gui_v1_legacy/conftest.py
archive/tests_v1/gui_v1_legacy/test_adetailer_panel.py
archive/tests_v1/gui_v1_legacy/test_api_status_panel.py
archive/tests_v1/gui_v1_legacy/test_config_meta_updates.py
archive/tests_v1/gui_v1_legacy/test_config_panel.py
archive/tests_v1/gui_v1_legacy/test_controller_lifecycle.py
archive/tests_v1/gui_v1_legacy/test_editor_and_summary.py
archive/tests_v1/gui_v1_legacy/test_functional_buttons.py
archive/tests_v1/gui_v1_legacy/test_gui_test_mode.py
archive/tests_v1/gui_v1_legacy/test_gui_thread_marshaling.py
archive/tests_v1/gui_v1_legacy/test_layout_dedup.py
archive/tests_v1/gui_v1_legacy/test_load_config_behavior.py
archive/tests_v1/gui_v1_legacy/test_log_panel.py
archive/tests_v1/gui_v1_legacy/test_logpanel_binding.py
archive/tests_v1/gui_v1_legacy/test_main_window_pipeline.py
archive/tests_v1/gui_v1_legacy/test_main_window_threading.py
archive/tests_v1/gui_v1_legacy/test_matrix_ui.py
archive/tests_v1/gui_v1_legacy/test_pipeline_controls_panel.py
archive/tests_v1/gui_v1_legacy/test_pipeline_double_run.py
archive/tests_v1/gui_v1_legacy/test_pipeline_runs.py
archive/tests_v1/gui_v1_legacy/test_pipeline_state_cleanup.py
archive/tests_v1/gui_v1_legacy/test_pr1_layout_cleanup.py
archive/tests_v1/gui_v1_legacy/test_progress_eta.py
archive/tests_v1/gui_v1_legacy/test_prompt_pack_editor.py
archive/tests_v1/gui_v1_legacy/test_prompt_pack_panel.py
```

> These tests are already under a `gui_v1_legacy` namespace and marked as **unreachable** in the PR‑01 inventory. They are not part of the active GUI V2 harness.

### 2. Optional: Prior-Work GUI V1 Tests Under `docs/pr_templates`

If you want this PR to sweep up a little more V1-only test noise (still low-risk), include:

**From:**

```text
docs/pr_templates/PriorWork_complete/PR-GUI-LEFT-01_PacksPanel_Wiring_Bundle/tests_controller_test_app_controller_packs_integration.py
docs/pr_templates/PriorWork_complete/PR-GUI-LEFT-01_PacksPanel_Wiring_Bundle/tests_utils_test_prompt_packs_service.py
```

**To:**

```text
archive/tests_v1/prior_work/PR-GUI-LEFT-01_PacksPanel_Wiring_Bundle/tests_controller_test_app_controller_packs_integration.py
archive/tests_v1/prior_work/PR-GUI-LEFT-01_PacksPanel_Wiring_Bundle/tests_utils_test_prompt_packs_service.py
```

These are clearly prior-work artifacts and not part of the current test suite.

---

## Explicit "Do Not Move" List (Protected V2 Work)

To avoid confusion with the original PR‑02 draft, **the following files must NOT be moved or deleted in this PR**, even though some appear in `LEGACY_CANDIDATES.md` as "unreachable":

- `src/gui/txt2img_stage_card.py`
- `src/gui/img2img_stage_card.py`
- `src/gui/upscale_stage_card.py`
- Any file under `src/gui/stage_cards_v2/`
- Any `*_panel_v2.py` files (e.g., `sidebar_panel_v2`, `pipeline_panel_v2`, `preview_panel_v2`, `randomizer_panel_v2`, `status_bar_v2`)
- Any controller, pipeline, learning, or randomizer modules

These stage cards and V2 panels are **intentional V2 design**, not legacy, even if they are not yet fully wired into `main.py`.

---

## Archive Structure

Ensure the following directories exist:

```text
archive/
  README.md              # if not already present
  ARCHIVE_MAP.md         # if not already present
  tests_v1/
    gui_v1_legacy/
    prior_work/          # optional, only if moving prior-work tests
```

For each moved file, append an entry to `archive/ARCHIVE_MAP.md`, for example:

```text
tests/gui_v1_legacy/test_log_panel.py -> archive/tests_v1/gui_v1_legacy/test_log_panel.py  # GUI V1 legacy test
```

---

## Changes to Test Configuration

In most setups, simply moving these tests out of `tests/` into `archive/` is enough to prevent them from running in the default test suite.

If you have custom pytest config:

- Verify that `archive/` is not collected by default.
- If needed, update `pytest.ini` or equivalent to exclude `archive/` from test discovery (e.g., via `norecursedirs = archive`).

No changes are required to active V2 test modules.

---

## Implementation Steps

1. **Create archive directories**

   - `archive/tests_v1/gui_v1_legacy/`
   - `archive/tests_v1/prior_work/PR-GUI-LEFT-01_PacksPanel_Wiring_Bundle/` (if including prior-work tests)

2. **Move GUI V1 legacy tests**

   - Move all files from `tests/gui_v1_legacy/` into `archive/tests_v1/gui_v1_legacy/` preserving filenames.

3. **Move prior-work GUI V1 tests (optional)**

   - Move the two `docs/pr_templates/...` test files into `archive/tests_v1/prior_work/...` as listed above.

4. **Update `archive/ARCHIVE_MAP.md`**

   - Add one line per moved file: `src_path -> archive_path  # reason`.

5. **Verify test collection**

   - Run `pytest -q` or your usual test command.
   - Confirm that:
     - Tests still pass.
     - No `tests/gui_v1_legacy/...` tests are collected or run.

---

## Tests & Validation

- **Automated:**

  - `pytest tests/controller -v`
  - `pytest tests/gui_v2 -v`
  - Any other core test groups you normally run.

- **Manual:**

  - Confirm that the `archive/tests_v1/gui_v1_legacy/` and `archive/tests_v1/prior_work/` directories exist and contain the moved tests.
  - Confirm that `tests/gui_v1_legacy/` no longer exists in the active tree.

---

## Acceptance Criteria

- All `tests/gui_v1_legacy/*` files are moved to `archive/tests_v1/gui_v1_legacy/`.
- (Optional) Prior-work GUI V1 tests under `docs/pr_templates/...` are moved to `archive/tests_v1/prior_work/...`.
- No stage card or V2 GUI files are moved or deleted.
- The main application still runs without changes.
- The default test suite passes and no longer executes GUI V1 tests by default.
