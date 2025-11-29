Timestamp: 2025-11-22 20:59 (UTC-06:00)
PR Id: PR-#54-GUI-V2-OutputSettingsPanel-001
Spec Path: docs/pr_templates/PR-#54-GUI-V2-OutputSettingsPanel-001.md

# PR-#54-GUI-V2-OutputSettingsPanel-001: Output Settings Panel V2 (Filename, Save, Batch Size)

## 1. Title

**PR-#54-GUI-V2-OutputSettingsPanel-001: Output Settings Panel V2 (Filename, Save, Batch Size)**

---

## 2. Summary

This PR introduces an **Output Settings Panel V2** that gives users control over:

- Output directory (or named location profile).
- Filename pattern.
- Number of images per run (batch size).
- Image format (PNG/JPEG/WebP; subject to what WebUI supports).
- Seed strategy (fixed, random, or per-image sequence) – if already modeled.

These settings:

- Live entirely in GUI V2 as a dedicated panel.
- Flow into `GuiOverrides` and then into `PipelineConfigAssembler`.
- Are used to populate `PipelineConfig` output-related fields (paths, batch size, seed mode), without changing the underlying pipeline semantics.

Assumed baseline: repo state after PR-#51 and PR-#53 on top of `StableNew-main-11-22-2025-1815.zip`.

---

## 3. Problem Statement

### 3.1 Symptoms & Gaps

Currently:

- Output behavior is mostly driven by:
  - WebUI defaults.
  - Legacy configuration.
- GUI V2 does not expose a clean, dedicated surface for:
  - Where files are saved.
  - How files are named.
  - How many images are generated per run.

This causes:

- Difficulty in organizing outputs (especially for long runs and many experiments).
- Needing to manually rename or move files after the fact.
- Risk of accidental overwrites if filenames are not clearly controlled.

### 3.2 Design Constraints (Architecture_v2)

- GUI:
  - Must remain UI-only, no direct filesystem writes for final outputs.
  - May allow users to choose from known output directories or patterns.
- Controller/pipeline:
  - Already own actual I/O behavior.
  - Must receive output config fields via `PipelineConfig`.

Therefore:

- The new Output Settings Panel must:
  - Collect output preferences.
  - Provide them via `GuiOverrides`.
  - Let `PipelineConfigAssembler` map them into the `PipelineConfig` object used by the pipeline, which then uses them according to existing API contracts.

---

## 4. Goals

1. Implement an **OutputSettingsPanelV2** widget that allows:
   - Choosing an output location/profile.
   - Setting a filename pattern (with simple tokens: date, time, seed, etc., if already supported).
   - Configuring batch size (image count per run).
   - Selecting image format (PNG/JPEG/WebP).
   - Optionally specifying a seed strategy if modeled.
2. Integrate panel into GUI V2 layout (sidebar or a dedicated “Output” section).
3. Ensure settings flow via `GuiOverrides` into `PipelineConfigAssembler`, then into `PipelineConfig`.
4. Add tests verifying:
   - Panel behavior.
   - Assembler mapping.
5. Document the new output configuration path.

---

## 5. Non-goals

This PR will **not**:

- Change the underlying output directory structure or WebUI path logic.
- Implement complex token parsing for filenames beyond what is already supported.
- Introduce network or cloud storage targets.
- Modify history or manifest logging structure.

Those are future enhancements once core output control is reliable.

---

## 6. Allowed Files

Codex may modify:

**GUI V2 – Output Panel**

- `src/gui/output_settings_panel_v2.py`  *(new)*
- `src/gui/sidebar_panel_v2.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py` *(wiring only)*

**Adapter / Assembler**

- `src/gui/pipeline_adapter_v2.py`   *(extend `GuiOverrides` with output settings)*
- `src/controller/pipeline_config_assembler.py` *(map output overrides into `PipelineConfig`)*

**Config Defaults (if necessary)**

- `src/config/app_config.py` *(default output directory, filename pattern, batch size, format)*

**Tests**

- `tests/gui_v2/test_output_settings_panel_v2.py` *(new)*
- `tests/controller/test_pipeline_config_assembler_output_settings.py` *(new)*

**Docs**

- `docs/PIPELINE_RULES.md`
- `docs/ARCHITECTURE_v2_COMBINED.md`
- `docs/codex_context/ROLLING_SUMMARY.md`

---

## 7. Forbidden Files

Do **not** modify:

- `src/pipeline/*`
- `src/queue/*`
- `src/controller/job_history_service.py`
- `src/controller/job_execution_controller.py`
- `src/controller/cluster_controller.py`
- `src/cluster/*`
- `src/learning*`
- `src/randomizer*`
- `src/api/*`
- Files performing actual disk writes for outputs (beyond respecting `PipelineConfig`).

If a forbidden file appears to need changes, Codex must stop and propose a separate PR.

---

## 8. Step-by-step Implementation

### 8.1. Implement OutputSettingsPanelV2

Create `src/gui/output_settings_panel_v2.py`:

- `class OutputSettingsPanelV2(ttk.Frame):`
  - Controls:
    - Output location/profile: `ttk.Combobox` or `ttk.Entry` with a browse button (if selection is supported).
    - Filename pattern: `ttk.Entry` (with placeholder or description).
    - Image count (batch size): `ttk.Spinbox` (with a safe max).
    - Format: `ttk.Combobox` containing `"png"`, `"jpg"`, and `"webp"` if supported.
    - Seed strategy (optional if modeled): radio buttons or combo – “random each run”, “fixed”, “per-image”.

- Methods:
  - `get_output_overrides() -> dict` (or small dataclass).
  - `apply_from_overrides(overrides)` – used by tests and future state restore.

### 8.2. Integrate into Layout

In `src/gui/sidebar_panel_v2.py` and `src/gui/app_layout_v2.py`:

- Place OutputSettingsPanelV2 into a reasonable location (e.g., “Output” group).
- Ensure it is constructed with defaults from `app_config`.

### 8.3. Extend GuiOverrides

In `src/gui/pipeline_adapter_v2.py`:

- Extend `GuiOverrides` to include fields like:

  - `output_dir` or `output_profile`
  - `filename_pattern`
  - `batch_size`
  - `image_format`
  - `seed_mode` (if modeled)

- Populate these from OutputSettingsPanelV2, with fallbacks to existing defaults.

### 8.4. Map to PipelineConfig in Assembler

In `src/controller/pipeline_config_assembler.py`:

- Accept output-related overrides and map them into `PipelineConfig`:

  - Ensure that existing output fields are used and consistent.
  - Do not change how manifests are written.

### 8.5. Tests

1. `tests/gui_v2/test_output_settings_panel_v2.py`:

   - `test_output_panel_get_overrides`:
     - Set panel fields.
     - Call `get_output_overrides()`.
     - Assert correct dict/values.

   - `test_output_panel_defaults_loaded_from_app_config`:
     - Stub defaults in `app_config`.
     - Instantiate panel.
     - Assert fields match defaults.

2. `tests/controller/test_pipeline_config_assembler_output_settings.py`:

   - `test_output_settings_roundtrip`:
     - Provide `GuiOverrides` with specific output settings.
     - Call assembler.
     - Assert `PipelineConfig` contains the expected values.

---

## 9. Required Tests (Failing First)

Codex must run:

1. Focused:

   - `pytest tests/gui_v2/test_output_settings_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`

2. Suites:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`

3. Regression:

   - `pytest -v`

Existing skips for Tk env issues are fine; no new skips.

---

## 10. Acceptance Criteria

PR-#54 is complete when:

1. OutputSettingsPanelV2 exists and is integrated into GUI V2.
2. Changing fields in the panel updates `GuiOverrides` output-related fields.
3. `PipelineConfigAssembler` maps those into `PipelineConfig` correctly.
4. All tests in §9 pass.
5. No regressions appear in pipeline, queue, or learning behavior.
6. Docs/summary are updated.

---

## 11. Rollback Plan

If needed:

1. Revert:

   - `src/gui/output_settings_panel_v2.py`
   - Changes in `sidebar_panel_v2.py`, `app_layout_v2.py`, `main_window.py`
   - `pipeline_adapter_v2` output fields
   - Assembler mapping
   - New tests
   - Doc updates

2. Re-run:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v`

to restore pre-PR-#54 behavior.

---

## 12. Codex Execution Constraints

Codex must:

- Stay within Allowed Files (no touching pipeline or queue internals).
- Treat tests as authoritative.
- Keep the output path purely config → assembler → pipeline; no direct GUI file writes.

Before completing, Codex must:

1. List tests run.
2. Paste outputs for:
   - `pytest tests/gui_v2/test_output_settings_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v` (if run).

---

## 13. Smoke Test Checklist

Human verification:

1. Launch GUI V2.
2. Locate **Output Settings** section.
3. Set a custom filename pattern and small batch size.
4. Run the pipeline.
5. Confirm generated images:
   - Are written under the expected directory.
   - Follow the filename pattern (as far as existing pipeline logic supports).
   - Respect the batch size.
6. Change format and re-run, confirming output format change (within WebUI capabilities).

If all checks and tests pass, PR-#54 is successful.

