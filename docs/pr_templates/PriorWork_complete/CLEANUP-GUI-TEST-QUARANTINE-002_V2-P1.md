# CLEANUP-GUI-TEST-QUARANTINE-002_V2-P1 — Quarantine Old GUI V2 & V1 Tests

**Snapshot Baseline:** `StableNew-snapshot-20251128-144410.zip`  
**Inventory Baseline:** `docs/StableNew_V2_Inventory_V2-P1.md` + `repo_inventory.json`

> Phase-1 Objective Alignment:  
> - “Tests must match the current architecture – don’t keep testing ghosts.”  
> - “CI for Phase 1 should assert: it boots, it runs pipeline, dropdowns populate, payloads are correct.”

This PR **shrinks the GUI test surface** down to a small, Phase-1-aligned core and quarantines the rest of the GUI tests that still assume the old `StableNewGUI` / `AppLayoutV2` / adapter-driven architecture.

---

## 1. Goal & Scope

### Goal

- Define a **small, reliable GUI V2 test set** that matches the current `MainWindowV2` zone-map.
- Move the remaining GUI V2 + V1 GUI tests into an archive namespace (or clearly-marked legacy folder) so they:
  - No longer run as part of the default test suite.
  - Are still available as reference for future phases (advanced prompt editor, learning, randomizer, job history, etc.).

### In Scope

- `tests/gui_v2/*.py`
- Existing `archive/tests_v1/gui_v1_legacy/`
- `tests/legacy/*.py` (for classification, not content changes)

### Out of Scope

- Non-GUI tests (API, pipeline, learning, queue, cluster).
- Any changes to runtime GUI code (that is handled in other PRs).

---

## 2. Core Phase-1 GUI Test Set (to **keep** under `tests/gui_v2/`)

Keep the following tests as the **Phase-1 GUI V2 core**:

1. `tests/gui_v2/conftest.py`  
   - Provides the `gui_app_factory` fixture and any necessary Tk setup/teardown.
   - Must be aligned to build `MainWindowV2` via `build_v2_app`.

2. `tests/gui_v2/test_gui_v2_layout_skeleton.py`  
   - Verifies key layout regions exist and are interactive for the V2 window.

3. `tests/gui_v2/test_entrypoint_uses_v2_gui.py`  
   - Asserts that:
     - `ENTRYPOINT_GUI_CLASS` in `src.gui.main_window_v2` is `MainWindowV2`.
     - `ENTRYPOINT_GUI_CLASS` in `src.main` re-exports `MainWindowV2`.

4. `tests/gui_v2/test_theme_v2.py`  
   - Ensures `apply_theme` in `src.gui.theme_v2` defines the expected styles.

> These four files form the **minimal GUI V2 contract** for Phase 1.

---

## 3. GUI Tests to Quarantine

All other tests under `tests/gui_v2/*.py` should be **moved out of the default test path** and into a clearly separate legacy/experimental namespace.

Create:

- `archive/tests_gui_v2_legacy/`

Then move all GUI V2 tests **except** the four listed above:

- Examples (non-exhaustive list; Codex should move all matching patterns):
  - `tests/gui_v2/test_advanced_prompt_editor_v2.py`
  - `tests/gui_v2/test_api_status_panel_webui_states_v2.py`
  - `tests/gui_v2/test_command_bar_v2.py`
  - `tests/gui_v2/test_core_config_panel_v2.py`
  - `tests/gui_v2/test_gui_v2_advanced_stage_cards_layout.py`
  - `tests/gui_v2/test_gui_v2_advanced_stage_cards_roundtrip.py`
  - `tests/gui_v2/test_gui_v2_advanced_stage_cards_validation.py`
  - `tests/gui_v2/test_gui_v2_ai_settings_button_guarded.py`
  - `tests/gui_v2/test_gui_v2_mainwindow_split_structure.py`
  - `tests/gui_v2/test_gui_v2_panel_wiring.py`
  - `tests/gui_v2/test_gui_v2_pipeline_adapter.py`
  - `tests/gui_v2/test_gui_v2_pipeline_button_wiring.py`
  - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`
  - `tests/gui_v2/test_gui_v2_randomizer_integration.py`
  - `tests/gui_v2/test_gui_v2_randomizer_variant_count_banner.py`
  - `tests/gui_v2/test_gui_v2_randomizer_variant_count_preview.py`
  - `tests/gui_v2/test_job_history_panel_v2.py`
  - `tests/gui_v2/test_learning_review_dialog.py`
  - `tests/gui_v2/test_learning_toggle.py`
  - `tests/gui_v2/test_main_window_tabs_v2.py`
  - `tests/gui_v2/test_negative_prompt_panel_v2.py`
  - `tests/gui_v2/test_output_settings_panel_v2.py`
  - `tests/gui_v2/test_packs_and_presets_left_panel_v2.py`
  - `tests/gui_v2/test_pipeline_prompt_integration_v2.py`
  - `tests/gui_v2/test_pipeline_stage_cards_v2.py`
  - `tests/gui_v2/test_pipeline_tab_layout_v2.py`
  - `tests/gui_v2/test_pipeline_tab_stage_cards.py`
  - `tests/gui_v2/test_preview_panel_v2.py`
  - `tests/gui_v2/test_prompt_pack_panel_v2.py`
  - `tests/gui_v2/test_prompt_pack_to_prompt_roundtrip_v2.py`
  - `tests/gui_v2/test_resolution_panel_v2.py`
  - `tests/gui_v2/test_run_button_queue_mode_toggle.py`
  - `tests/gui_v2/test_run_button_queue_smoke.py`
  - `tests/gui_v2/test_scrollable_pipeline_panel_v2.py`
  - `tests/gui_v2/test_stagecard_base_v2.py`
  - `tests/gui_v2/test_status_bar_v2_composite.py`
  - …and any other `tests/gui_v2/test_*.py` not in the “keep” list.

After moving, these paths should look like:

- `archive/tests_gui_v2_legacy/test_advanced_prompt_editor_v2.py`
- etc.

> Content of these tests should **not** be changed in this PR; only their location.

---

## 4. V1 & Legacy Tests

There are already legacy test areas:

- `archive/tests_v1/gui_v1_legacy/*`
- `tests/legacy/*.py`

### Actions

- **No file moves** required here.
- Update `docs/StableNew_V2_Inventory_V2-P1.md` to explicitly say:
  - `archive/tests_v1/gui_v1_legacy/*` and `tests/legacy/*` are **out of scope for Phase 1**.
  - They are not expected to pass and are kept as reference for V1 behavior and advanced features.

Optionally:

- Add a short `README.md` in `archive/tests_gui_v2_legacy/` explaining:
  - These tests target deprecated/experimental GUI behaviors.
  - They may be used later as a template when Phase 3–4 features (learning, randomizer, advanced editor) are rewired into the new GUI.

---

## 5. Pytest Configuration

If you use a central pytest config (e.g., `pyproject.toml` or `pytest.ini`), you may:

- Add `archive/` to `norecursedirs`, **or**
- Keep as-is if `archive/` is already excluded.

The PR should **not** add new markers or complicated config; simply moving the files under `archive/` is enough to prevent default discovery.

---

## 6. Files **Not** to Touch

- Any code under `src/` (GUI or otherwise) – this PR is tests-only.
- Any non-GUI tests:
  - `tests/api*`, `tests/pipeline*`, `tests/utils/*`, etc.

---

## 7. Validation & Definition of Done

### Validation

- Run:

  ```bash
  pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
  pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
  pytest tests/gui_v2/test_theme_v2.py -q
  ```

- Confirm the above tests pass (or fail only for known GUI wiring issues unrelated to test moves).
- Run full suite:

  ```bash
  pytest -q
  ```

  - Expect failures only from known non-GUI areas; there should be **no failures** due to moved GUI tests not being found.

### Definition of Done

This PR is complete when:

1. Only the four core Phase-1 GUI V2 tests remain under `tests/gui_v2/`.
2. All other GUI tests have been moved under `archive/tests_gui_v2_legacy/`.
3. `archive/tests_v1/gui_v1_legacy/*` and `tests/legacy/*` are explicitly documented as non-Phase-1 scopes in `docs/StableNew_V2_Inventory_V2-P1.md`.
4. `pytest` no longer attempts to run the archived GUI tests by default.
5. The remaining Phase-1 GUI V2 tests run successfully against `MainWindowV2`.

