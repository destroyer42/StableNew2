Timestamp: 2025-11-22 20:59 (UTC-06:00)
PR Id: PR-#55-GUI-V2-ModelManagerPanel-001
Spec Path: docs/pr_templates/PR-#55-GUI-V2-ModelManagerPanel-001.md

# PR-#55-GUI-V2-ModelManagerPanel-001: Model Manager Panel V2 (Checkpoint + VAE Selection)

## 1. Title

**PR-#55-GUI-V2-ModelManagerPanel-001: Model Manager Panel V2 (Checkpoint + VAE Selection)**

---

## 2. Summary

This PR introduces a **Model Manager Panel V2** that lets users:

- Select a **primary model/checkpoint** from available models.
- Select a **VAE** if supported by the pipeline/WebUI client.
- Refresh the list of models/VAEs without restarting the app.

These selections:

- Are surfaced in GUI V2 as a dedicated “Model” section.
- Flow through `GuiOverrides` → `PipelineConfigAssembler` → `PipelineConfig`.
- Do not change how WebUI or the pipeline loads models internally—they only choose which entries are requested.

Assumed baseline: repo state after PR-#51 through PR-#54 applied on top of `StableNew-main-11-22-2025-1815.zip`.

---

## 3. Problem Statement

### 3.1 Symptoms & Gaps

Today:

- Model selection is often:
  - Done via WebUI directly.
  - Controlled by config or startup flags, not GUI V2.
- VAE selection is:
  - Hidden or only available in WebUI.
- There is **no V2-centric model management surface** that integrates with the rest of StableNew’s controller/assembler flow.

Consequences:

- Users must context-switch between WebUI and StableNew for model choices.
- It’s hard to verify what model a given run used from the GUI alone.
- CI/testing and learning flows have weaker guarantees around model identity unless they inspect manifests/logs.

### 3.2 Design Constraints (Architecture_v2)

- GUI:
  - May present model lists and selection controls.
  - Must not implement model loading logic (no direct disk scanning or WebUI reload calls beyond approved client APIs).
- Controller/assembler:
  - Must treat model selection as config.
  - Map selected model/vae names/hashes into `PipelineConfig`.

Thus, the Model Manager Panel must:

- Use existing client/config functions to obtain model/vae lists (or a precomputed list).
- Expose selection in GUI V2.
- Feed the choice into assembler via overrides.

---

## 4. Goals

1. Implement **ModelManagerPanelV2** with:
   - A dropdown for model/checkpoint selection.
   - A dropdown for VAE selection (if available).
   - A “Refresh list” button to repull model/vae info.
2. Integrate panel into GUI V2 (sidebar or core config area).
3. Ensure selected model/vae is exposed via:
   - `GuiOverrides` → `PipelineConfigAssembler` → `PipelineConfig`.
4. Add tests:
   - For panel behavior (selection + refresh).
   - For assembler mapping of model/vae fields.
5. Document this path as the preferred way to choose models in GUI V2.

---

## 5. Non-goals

This PR will **not**:

- Implement model downloading or remote repository integration.
- Change how WebUI or the pipeline loads models internally.
- Provide advanced model management (e.g., tagging/favorites, multi-model ensembles).
- Touch randomizer or learning logic except to ensure they see the chosen model through normal config.

Those features belong in future, more specialized PRs.

---

## 6. Allowed Files

Codex may modify:

**GUI V2 – Model Manager Panel**

- `src/gui/model_manager_panel_v2.py`  *(new)*
- `src/gui/sidebar_panel_v2.py`
- `src/gui/app_layout_v2.py`
- `src/gui/main_window.py` *(wiring only)*

**Adapter / Assembler / Model listing**

- `src/gui/pipeline_adapter_v2.py` *(extend `GuiOverrides` to carry model/vae selection)*
- `src/controller/pipeline_config_assembler.py` *(map model/vae into `PipelineConfig`)*
- **Optional small adapter**:
  - `src/gui/model_list_adapter_v2.py` *(new)* – a thin wrapper over existing model listing calls.

**Config Defaults (if needed)**

- `src/config/app_config.py` *(default model/vae names)*

**Tests**

- `tests/gui_v2/test_model_manager_panel_v2.py` *(new)*
- `tests/controller/test_pipeline_config_assembler_model_fields.py` *(new or extended)*

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
- `src/api/*` (beyond possibly using existing model-list methods through a small adapter)

If a forbidden dependency seems required, Codex must stop and propose a separate PR for it.

---

## 8. Step-by-step Implementation

### 8.1. Model list adapter (if necessary)

If there is no existing GUI-friendly helper:

- Add `src/gui/model_list_adapter_v2.py`:

  - Functions:
    - `get_available_models() -> list[ModelInfo]`
    - `get_available_vaes() -> list[VAEInfo]`
  - Implementation:
    - Wraps existing APIs or config-based lists (no new scanning logic).

If such helpers already exist, reuse them instead.

### 8.2. Implement ModelManagerPanelV2

Create `src/gui/model_manager_panel_v2.py`:

- `class ModelManagerPanelV2(ttk.Frame):`
  - Widgets:
    - Model `ttk.Combobox` bound to model names.
    - VAE `ttk.Combobox` bound to VAE names (optional if none available).
    - “Refresh” `ttk.Button` that reloads model/vae lists from adapter.
  - Methods:
    - `get_selections() -> dict` with `model_name` and `vae_name` (optional).
    - `set_selections(model_name: str | None, vae_name: str | None)`.

No direct pipeline or WebUI operations.

### 8.3. Integrate into GUI V2 Layout

In `src/gui/sidebar_panel_v2.py` and `src/gui/app_layout_v2.py`:

- Place ModelManagerPanelV2 in a “Model” or “Models & VAE” section.
- Ensure it is initialized when GUI launches.

### 8.4. Extend GuiOverrides

In `src/gui/pipeline_adapter_v2.py`:

- Ensure `GuiOverrides` has:

  - `model_name: str | None`
  - `vae_name: str | None` (if relevant)

- Populate them from ModelManagerPanelV2 selections and/or `app_config` defaults.

### 8.5. Map into PipelineConfig via Assembler

In `src/controller/pipeline_config_assembler.py`:

- Accept these fields in `build_from_gui_input`.
- Map them into `PipelineConfig` model/vae fields.
- Use safe defaults if values are missing or invalid.

### 8.6. Tests

1. `tests/gui_v2/test_model_manager_panel_v2.py`:

   - `test_model_panel_populates_and_selects_model`:
     - Provide fake list of models.
     - Instantiate panel with injected list.
     - Assert combobox entries and selection behavior.

   - `test_model_panel_refresh_calls_adapter`:
     - Mock adapter’s list function.
     - Trigger refresh.
     - Assert it was called.

2. `tests/controller/test_pipeline_config_assembler_model_fields.py`:

   - `test_model_and_vae_roundtrip`:
     - Provide `GuiOverrides` with model/vae names.
     - Call assembler.
     - Assert `PipelineConfig` fields are set accordingly.

---

## 9. Required Tests (Failing First)

Codex must run:

1. Focused:

   - `pytest tests/gui_v2/test_model_manager_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`

2. Suites:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`

3. Regression:

   - `pytest -v`

Tk skips for GUI tests are acceptable; no additional skips.

---

## 10. Acceptance Criteria

PR-#55 is complete when:

1. ModelManagerPanelV2 exists and is integrated in GUI V2.
2. Users can select model and VAE via GUI V2.
3. Selected values are reflected in `GuiOverrides` and `PipelineConfig`.
4. All tests in §9 pass.
5. No regressions occur in other controller or pipeline behaviors.
6. Docs/summary call out the new Model Manager path.

---

## 11. Rollback Plan

If needed:

1. Revert:

   - `src/gui/model_manager_panel_v2.py`
   - `src/gui/model_list_adapter_v2.py` (if added)
   - Layout changes in `sidebar_panel_v2.py`, `app_layout_v2.py`, `main_window.py`
   - Adapter and assembler changes for model/vae fields
   - New tests
   - Docs updates

2. Re-run:

   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v`

to confirm rollback.

---

## 12. Codex Execution Constraints

Codex must:

- Use only Allowed Files.
- Not touch pipeline, queue, or low-level WebUI mechanics.
- Treat tests as defining the expected behavior.
- Keep diffs concise and well-scoped.

Before finishing, Codex must:

1. List tests run.
2. Paste outputs for:
   - `pytest tests/gui_v2/test_model_manager_panel_v2.py -v`
   - `pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v`
   - `pytest tests/gui_v2 -v`
   - `pytest tests/controller -v`
   - `pytest -v` (if run).

---

## 13. Smoke Test Checklist

A human should:

1. Launch GUI V2.
2. Open the **Model Manager** section.
3. See a list of available models (and VAEs if configured).
4. Select a non-default model and run a pipeline.
5. Confirm (via logs/manifest or WebUI status) that the chosen model was used.
6. Change models again and run another pipeline, confirming the effective model changes without restart.

If all steps behave as expected and tests are green, PR-#55 is successful.

