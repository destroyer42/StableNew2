Timestamp: 2025-11-22 20:59 (UTC-06:00)
PR Id: PR-#51-GUI-V2-CoreConfigPanel-001
Spec Path: docs/pr_templates/PR-#51-GUI-V2-CoreConfigPanel-001.md

# PR-#51-GUI-V2-CoreConfigPanel-001: GUI V2 Core Config Panel → Assembler Integration

## 1. Title

**PR-#51-GUI-V2-CoreConfigPanel-001: GUI V2 Core Config Panel → Assembler Integration**

---

## 2. Summary

This PR introduces a **Core Config Panel V2** in the GUI that exposes the most important and frequently used pipeline configuration controls in a way that is:

- Fully aligned with **Architecture_v2** (GUI → controller → assembler → pipeline).
- Backed by **PipelineConfigAssembler** instead of ad-hoc dicts.
- Safe to evolve (tests enforce the config path).

The Core Config Panel V2 will:

- Provide **readable, adjustable controls** for:
  - **Model/checkpoint** (string or dropdown, depending on what’s already available).
  - **Sampler** (Euler, DPM++, etc.).
  - **Steps** (integer).
  - **CFG scale** (float).
  - **Resolution preset** (e.g., 512² / 768² / 1024²).
- Feed those values into **GuiOverrides**, then into **PipelineConfigAssembler**, then into **PipelineConfig**.
- Respect existing defaults in `app_config` and assembler logic.

This PR does **not** change underlying pipeline semantics. It only makes the existing configuration path **visible, explicit, and test-backed** in GUI V2.

Assumed baseline: repo state after PR-#47B, PR-#48, PR-#49, and PR-#50 have been applied on top of `StableNew-main-11-22-2025-1815.zip`.

---

## 3. Problem Statement

### 3.1 Symptoms & Gaps

In the current post-queue, post-assembler world:

- **Core settings are opaque** to users in GUI V2:
  - Model, sampler, steps, CFG, and base resolution may be coming from defaults or legacy config.
  - Users must guess what the pipeline is actually using.
- **Adjusting core settings** can still require:
  - Legacy GUI panels, or
  - Editing config files or environment values directly.
- There is **no single, authoritative GUI V2 “core config” surface** that flows cleanly into `PipelineConfigAssembler`.

This leads to:

- Confusion when results differ from expectations (e.g. “Why is CFG so low?”, “What resolution is this actually using?”).
- Increased risk of config drift between GUI expectations and actual pipeline behavior.
- Harder debugging when comparing behavior across machines or runs.

### 3.2 Design Constraints (Architecture_v2)

Per Architecture_v2 and Pipeline Rules:

- GUI:
  - Must remain **UI-only**, with no pipeline or WebUI logic.
  - Can read defaults via controller/`app_config`, but must not talk directly to the API.
- Controller:
  - Owns lifecycle and state, but **must not** be burdened with layout concerns.
  - Must rely on **PipelineConfigAssembler** to build `PipelineConfig` from `GuiOverrides`.
- Assembler:
  - Is the **single source of truth** for mapping GUI/overrides → `PipelineConfig`.
  - Must be deterministic and testable.

Therefore:

- The new Core Config Panel must **only** manipulate GUI-side state and/or `app_config` values and feed them into `GuiOverrides`.
- All actual config used for runs must go through `PipelineConfigAssembler`.

---

## 4. Goals

1. Add a **CoreConfigPanelV2** that surfaces:
   - Model/checkpoint
   - Sampler
   - Steps
   - CFG scale
   - Resolution preset
2. Ensure **changes in this panel**:
   - Are reflected in `GuiOverrides`.
   - Are consumed by `PipelineConfigAssembler.build_from_gui_input`.
   - Show up correctly in `PipelineConfig` during a run.
3. Keep the **controller and queue behavior unchanged**, except for reading config from the strengthened config path.
4. Add **tests** that:
   - Verify the GUI panel’s controls behave as expected.
   - Verify assembler receives and maps these fields correctly.
5. Update project docs and rolling summary to reflect the new core config surface.

---

## 5. Non-goals

This PR will **not**:

- Introduce advanced/secondary config (LoRA, ControlNet, refiner stages, etc.).
- Change queue, job history, or worker/cluster behavior.
- Add or change any WebUI API calls.
- Implement per-stage overrides (e.g., different samplers per stage).
- Touch learning or randomizer semantics beyond correctly passing their current metadata through assembler.

Those belong in follow-on PRs once the core config path is rock solid.

---

## 6. Allowed Files

Codex may modify **only** the following (or closely equivalent) files:

**GUI V2 – Config Panel + Layout**

- `src/gui/core_config_panel_v2.py`  *(new – main widget for core config controls)*
- `src/gui/sidebar_panel_v2.py`      *(wire panel into sidebar, if used as host)*
- `src/gui/app_layout_v2.py`         *(connect panel into overall layout)*
- `src/gui/main_window.py`           *(wiring only, no controller logic)*

**Config / Assembler Integration**

- `src/gui/pipeline_adapter_v2.py`   *(extend `GuiOverrides` extraction to include core config fields)*
- `src/controller/pipeline_config_assembler.py` *(ensure assembler accepts core config overrides and maps into `PipelineConfig`)*
- `src/config/app_config.py`         *(expose defaults + getters/setters for model/sampler/steps/cfg/resolution presets)*

**Tests**

- `tests/gui_v2/test_core_config_panel_v2.py` *(new)*
- `tests/controller/test_pipeline_config_assembler_core_fields.py` *(new or extend existing assembler tests)*

**Docs**

- `docs/PIPELINE_RULES.md`
- `docs/ARCHITECTURE_v2_COMBINED.md`
- `docs/codex_context/ROLLING_SUMMARY.md`

If a path differs slightly, Codex should adapt but **stay within these responsibilities**.

---

## 7. Forbidden Files

Do **not** modify in this PR:

- Any pipeline implementation modules:
  - `src/pipeline/*`
- Queue/cluster internals:
  - `src/queue/*`
  - `src/controller/job_history_service.py`
  - `src/controller/job_execution_controller.py`
  - `src/controller/cluster_controller.py`
  - `src/cluster/*`
- Learning / randomizer logic:
  - `src/learning*`
  - `src/randomizer*`
- API / WebUI client:
  - `src/api/*`
- Legacy GUI components:
  - Any pre-V2 panels unless absolutely required for imports (and even then, minimal and documented).

If Codex believes a forbidden file must be changed, it must **stop and report** instead of editing.

---

## 8. Step-by-step Implementation

### 8.1. Extend app_config for core fields (if needed)

In `src/config/app_config.py`:

- Add/default getters and setters for:

  - `core_model_name`
  - `core_sampler_name`
  - `core_steps`
  - `core_cfg_scale`
  - `core_resolution_preset`

- Ensure these are safe:
  - Provide **sensible defaults** (e.g., existing global model/sampler defaults).
  - Do not break existing config files.

### 8.2. Implement CoreConfigPanelV2

In `src/gui/core_config_panel_v2.py` (new file):

- Implement `CoreConfigPanelV2(ttk.Frame)` that:

  - On initialization:
    - Reads starting values from `app_config` (or passed-in config snapshot).
  - Provides controls for:
    - Model: `ttk.Combobox` or `ttk.Entry` (depending on what is available).
    - Sampler: `ttk.Combobox` with a short list of supported sampler names.
    - Steps: `ttk.Spinbox` or `ttk.Entry` constrained to a reasonable range.
    - CFG: `ttk.Spinbox` or `ttk.Entry` (float).
    - Resolution preset: `ttk.Combobox` with string labels like `"512x512"`, `"768x768"`, `"1024x1024"`.

- Provide public methods:

  - `get_overrides()` → returns a small dataclass or dict with the current config values.
  - `apply_from_overrides(overrides)` → applies values, useful for tests or future syncing.

- The panel must **not** talk to pipeline, queue, or WebUI.

### 8.3. Integrate panel into sidebar / layout

In `src/gui/sidebar_panel_v2.py` and `src/gui/app_layout_v2.py`:

- Create and place an instance of `CoreConfigPanelV2`.
- Decide location (e.g., a “Core Settings” section in the sidebar).
- Ensure:

  - The panel is constructed with appropriate initial values.
  - A reference to the panel can be used when building `GuiOverrides`.

### 8.4. Extend GuiOverrides and pipeline_adapter_v2

In `src/gui/pipeline_adapter_v2.py`:

- Make sure that `GuiOverrides` (or equivalent structure) includes:

  - `model_name`
  - `sampler_name`
  - `steps`
  - `cfg_scale`
  - `resolution_preset` (or explicit width/height if already decomposed).

- Implement logic to read these values from:

  - `CoreConfigPanelV2` (primary source).
  - Or `app_config` defaults if panel is not available.

### 8.5. Map core fields in PipelineConfigAssembler

In `src/controller/pipeline_config_assembler.py`:

- Update `build_from_gui_input` (or equivalent) to:

  - Accept these core fields from `GuiOverrides`.
  - Apply safe defaults when fields are missing.
  - Populate the resulting `PipelineConfig` with:

    - `model_name`
    - `sampler_name`
    - `steps`
    - `cfg_scale`
    - `width`/`height` (via resolution preset logic – basic preset mapping or existing resolution handling).

- Preserve any existing megapixel clamp rules.

### 8.6. Tests (TDD-first where possible)

1. **GUI test**: `tests/gui_v2/test_core_config_panel_v2.py`

   - `test_core_panel_initializes_from_app_config`:
     - Mock or stub `app_config` values.
     - Instantiate `CoreConfigPanelV2`.
     - Assert that widgets reflect those initial values.

   - `test_core_panel_get_overrides_roundtrip`:
     - Set values in the panel.
     - Call `get_overrides()`.
     - Assert they match expected values.

2. **Assembler test**: `tests/controller/test_pipeline_config_assembler_core_fields.py`

   - `test_assembler_maps_core_fields_to_pipeline_config`:
     - Construct `GuiOverrides` with model/sampler/steps/cfg/resolution.
     - Call `build_from_gui_input`.
     - Assert resulting `PipelineConfig` fields match.

Run tests in §9 after implementation.

### 8.7. Docs and Rolling Summary

- `docs/PIPELINE_RULES.md`:
  - Add/clarify rule that **core config GUI must feed into assembler via GuiOverrides**.
- `docs/ARCHITECTURE_v2_COMBINED.md`:
  - Update GUI V2 section to mention CoreConfigPanelV2.
- `docs/codex_context/ROLLING_SUMMARY.md`:
  - Append an entry for PR-#51 (see §12).

---

## 9. Required Tests (Failing First)

Codex must run (and ideally see red → green progression):

1. Focused new tests:

   - `pytest tests/gui_v2/test_core_config_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`

2. Suites:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`

3. Regression (if runtime is acceptable):

   - `pytest -v`

Pre-existing Tk-related skips are acceptable. No new skips should be introduced.

---

## 10. Acceptance Criteria

This PR is acceptable when:

1. **CoreConfigPanelV2** exists and is integrated into GUI V2.
2. Changing values in the panel updates the `GuiOverrides` used by `PipelineConfigAssembler`.
3. `PipelineConfigAssembler` correctly maps core config fields into `PipelineConfig`.
4. All tests in §9 pass (modulo known skips).
5. No behavioral regressions appear in controller, queue, or pipeline tests.
6. Docs and rolling summary reflect the new core config path.

---

## 11. Rollback Plan

If regressions occur:

1. Revert changes in:

   - `src/gui/core_config_panel_v2.py`
   - `src/gui/sidebar_panel_v2.py`
   - `src/gui/app_layout_v2.py`
   - `src/gui/main_window.py`
   - `src/gui/pipeline_adapter_v2.py`
   - `src/controller/pipeline_config_assembler.py`
   - `src/config/app_config.py`
   - New/modified tests
   - PR-#51 doc/summary entries

2. Re-run:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v`

to confirm behavior is back to the pre-PR-#51 baseline.

Because this PR is strictly about GUI/assembler integration of core fields, rollback is low-risk.

---

## 12. Codex Execution Constraints

When implementing this PR, Codex must:

- Stay within the **Allowed Files** list in §6.
- Treat tests as **authoritative checks** of the desired behavior.
- Keep diffs **small and focused**, especially in assembler and adapter code.
- Not loosen any assertions or skip tests to “make it pass”.
- Not introduce new dependencies from GUI to pipeline or WebUI clients.

Before finishing, Codex must:

1. List the tests it ran.
2. Paste the full output of:
   - `pytest tests/gui_v2/test_core_config_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v` (if run).

---

## 13. Smoke Test Checklist

After merging and installing this PR, a human should be able to:

1. Launch StableNew (GUI V2).
2. Locate the **Core Config** section/panel.
3. Adjust:
   - Model
   - Sampler
   - Steps
   - CFG
   - Resolution preset
4. Run a pipeline and verify (via logged config or manifest, if available) that:
   - The chosen model/sampler/steps/CFG/resolution were actually used.
5. Change values again and run another pipeline, confirming that updates are reflected without needing to restart the app.

If all of the above behave as expected and tests remain green, PR-#51 is successful.

