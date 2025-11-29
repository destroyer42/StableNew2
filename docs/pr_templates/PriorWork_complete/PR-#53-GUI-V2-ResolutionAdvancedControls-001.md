Timestamp: 2025-11-22 20:59 (UTC-06:00)
PR Id: PR-#53-GUI-V2-ResolutionAdvancedControls-001
Spec Path: docs/pr_templates/PR-#53-GUI-V2-ResolutionAdvancedControls-001.md

# PR-#53-GUI-V2-ResolutionAdvancedControls-001: Advanced Resolution Controls V2 + Safe Clamps

## 1. Title

**PR-#53-GUI-V2-ResolutionAdvancedControls-001: Advanced Resolution Controls V2 + Safe Clamps**

---

## 2. Summary

This PR extends GUI V2 with an **Advanced Resolution Panel** that allows:

- Direct control of **width** and **height**.
- Resolution **presets** (square and common ratios).
- Visual hints about **megapixel limits** and clamping behavior.

All of this feeds into:

- `GuiOverrides` → `PipelineConfigAssembler` → `PipelineConfig`.

We will **not** change the clamping logic itself (it already exists around megapixel limits), but we will:

- Expose a clearer GUI for resolution selection.
- Ensure the assembler properly interprets and clamps width/height derived from the GUI.

Assumed baseline: repo state after PR-#51 (Core Config Panel) and PR-#52 (Negative Prompt Panel) on top of `StableNew-main-11-22-2025-1815.zip`.

---

## 3. Problem Statement

### 3.1 Symptoms & Gaps

Currently:

- Resolution may be controlled via:
  - Legacy controls, or
  - Implicit defaults in `app_config` or WebUI.
- Users lack:
  - A coherent **V2 resolution control** surface.
  - Clear feedback on when resolution is being clamped to avoid VRAM blow-ups.

This can cause:

- Confusion about what resolution is actually being generated.
- Frequent trial-and-error when trying to push resolution higher without crashes.
- Difficulty in establishing reproducible settings across runs and machines.

### 3.2 Design Constraints (Architecture_v2)

- GUI:
  - Must remain UI-only; no manual VRAM detection or pipeline introspection.
  - Can give **hints** about megapixel constraints (using assembler constants or doc text), but not dynamic runtime introspection.
- Assembler:
  - Is responsible for:
    - Converting GUI resolution inputs into width/height fields.
    - Applying megapixel clamp rules.
  - Must remain deterministic and testable.

Therefore:

- ResolutionPanelV2 must:
  - Supply intended width/height or preset.
  - Let assembler enforce limits.
  - Provide static hints to the user (e.g., “Values may be clamped to X MP”).

---

## 4. Goals

1. Implement a **ResolutionPanelV2** that:
   - Lets users set width and height directly.
   - Provides resolution presets (e.g., 512×512, 768×768, 1024×1024, 896×1152, 1152×896).
   - Offers a simple ratio helper (e.g., 1:1, 3:2, 16:9, 9:16).
2. Wire this panel into GUI V2:
   - Integrated into CoreConfigPanelV2 or as a companion panel.
3. Ensure resolution values flow through:
   - `GuiOverrides` → `PipelineConfigAssembler` → `PipelineConfig`.
4. Ensure assembler:
   - Respects width/height from overrides.
   - Applies megapixel clamping as needed.
5. Add tests:
   - For GUI behavior (preset application, manual edits).
   - For assembler mapping and clamping.

---

## 5. Non-goals

This PR will **not**:

- Change the underlying megapixel clamp policy (thresholds, exact formula).
- Implement dynamic VRAM detection or GPU capability probing.
- Introduce per-stage resolutions.
- Change WebUI upscaler behavior or tiling.

Those are out of scope and require separate pipeline-focused PRs.

---

## 6. Allowed Files

Codex may modify only:

**GUI V2 – Resolution Controls**

- `src/gui/resolution_panel_v2.py`  *(new)*
- `src/gui/core_config_panel_v2.py` *(integration hooks)*
- `src/gui/sidebar_panel_v2.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py` *(wiring only)*

**Adapter / Assembler**

- `src/gui/pipeline_adapter_v2.py`   *(ensure `GuiOverrides` carries width/height or preset info)*
- `src/controller/pipeline_config_assembler.py` *(interpret overrides into width/height and apply clamps)*

**Config Defaults (if needed)**

- `src/config/app_config.py` *(resolution preset defaults, safe ranges)*

**Tests**

- `tests/gui_v2/test_resolution_panel_v2.py` *(new)*
- `tests/controller/test_pipeline_config_assembler_resolution.py` *(new or extended)*

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
- Legacy GUI files outside of minimal import fixes.

If a forbidden file appears to need changes, Codex must stop and report.

---

## 8. Step-by-step Implementation

### 8.1. Implement ResolutionPanelV2

Create `src/gui/resolution_panel_v2.py`:

- `class ResolutionPanelV2(ttk.Frame):`
  - Widgets:
    - Width `ttk.Entry` or `ttk.Spinbox`.
    - Height `ttk.Entry` or `ttk.Spinbox`.
    - Preset `ttk.Combobox` with a curated set of resolutions.
    - Ratio `ttk.Combobox` or buttons for 1:1, 3:2, 16:9, etc.
    - Optional label showing approximate megapixel (width*height/1e6).
  - Methods:
    - `get_resolution() -> tuple[int, int]`
    - `set_resolution(width: int, height: int)`
    - `apply_preset(label: str)` (sets width and height accordingly).

### 8.2. Integrate with CoreConfigPanelV2 or Sidebar

In `src/gui/core_config_panel_v2.py` and/or `src/gui/sidebar_panel_v2.py`:

- Embed `ResolutionPanelV2` either:
  - Inside CoreConfigPanelV2 (as a nested group), or
  - As a sibling section in the sidebar.

The integrated design should still feel cohesive and not cluttered.

### 8.3. Capture resolution in GuiOverrides

In `src/gui/pipeline_adapter_v2.py`:

- Ensure `GuiOverrides` includes `width: int | None` and `height: int | None`.
- When building overrides:
  - Read width/height from `ResolutionPanelV2`.
  - If not set, fall back to existing resolution defaults.

### 8.4. Interpret width/height in PipelineConfigAssembler

In `src/controller/pipeline_config_assembler.py`:

- Extend `build_from_gui_input` to:

  - Accept explicit width/height.
  - If both present:
    - Use them as the pre-clamp resolution.
  - Apply existing megapixel clamp logic to produce final width/height.
  - Set them on `PipelineConfig`.

Leave clamp thresholds unchanged; if they need to move, that’s another PR.

### 8.5. Tests

1. `tests/gui_v2/test_resolution_panel_v2.py`:

   - `test_resolution_panel_preset_sets_width_height`:
     - Initialize panel.
     - Select a preset.
     - Assert `get_resolution()` returns the expected dimensions.

   - `test_resolution_panel_manual_edit_overrides_preset`:
     - Set preset.
     - Manually edit width/height.
     - Assert `get_resolution()` matches manual values.

2. `tests/controller/test_pipeline_config_assembler_resolution.py`:

   - `test_assembler_maps_resolution_and_clamps`:
     - Create `GuiOverrides` with large width/height.
     - Call assembler.
     - Assert output width/height are clamped within expected MP limit.

---

## 9. Required Tests (Failing First)

Codex must run:

1. Focused:

   - `pytest tests/gui_v2/test_resolution_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`

2. Suites:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`

3. Regression:

   - `pytest -v`

Tk skips from environment constraints are acceptable; no new skips.

---

## 10. Acceptance Criteria

PR-#53 is complete when:

1. ResolutionPanelV2 exists and is integrated into GUI V2.
2. Width/height can be controlled via presets and manual edits.
3. `GuiOverrides` carries the intended resolution.
4. `PipelineConfigAssembler` maps and clamps resolution as expected.
5. All tests in §9 pass (modulo known skips).
6. No changes to queue, learning, or pipeline behavior beyond resolution mapping.

---

## 11. Rollback Plan

If issues arise:

1. Revert:

   - `src/gui/resolution_panel_v2.py`
   - Changes in `core_config_panel_v2.py`, `sidebar_panel_v2.py`, `app_layout_v2.py`, `main_window.py`
   - `pipeline_adapter_v2` resolution changes
   - Assembler resolution changes
   - New tests
   - Docs/summary entries

2. Re-run:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v`

to verify return to pre-PR-#53 behavior.

---

## 12. Codex Execution Constraints

Codex must:

- Respect Allowed/Forbidden files.
- Not change clamp logic semantics beyond wiring in new inputs.
- Avoid introducing GUI → pipeline/API coupling.
- Keep diffs focused and minimal.

Before completing, Codex must:

1. List tests run.
2. Paste outputs for:
   - `pytest tests/gui_v2/test_resolution_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_resolution.py -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v` (if run).

---

## 13. Smoke Test Checklist

A human should:

1. Launch GUI V2.
2. Open the resolution controls.
3. Select a preset (e.g., 1024×1024) and run a pipeline.
4. Confirm (via logs or manifests) that the output resolution matches the clamped or preset width/height.
5. Manually enter a large resolution that should be clamped and run again.
6. Confirm the final resolution does not exceed the configured megapixel limit.

If all this works and tests are green, PR-#53 is successful.

