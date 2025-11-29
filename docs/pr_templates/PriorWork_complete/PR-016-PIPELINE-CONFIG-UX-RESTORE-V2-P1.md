# PR-016-PIPELINE-CONFIG-UX-RESTORE-V2-P1 — Pipeline Validation & UX Parity

**Intent:**  
Restore the most valuable **validation and UX behaviors** from the legacy `ConfigPanel` / `PipelineControlsPanel` into the V2 pipeline configuration experience, without reintroducing legacy architecture.

Focus on:

- Clear validation messages for incomplete/invalid config.
- Banners or inline warnings where critical settings are missing.
- Smooth model/vae/sampler dropdown updates.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (Pipeline tab views)
- Controller (pipeline configuration operations)
- API / WebUI (model list retrieval as needed)

**Files to modify:**

- `src/gui/views/pipeline_config_panel_v2.py`
- `src/gui/views/run_control_bar_v2.py`
- `src/controller/app_controller.py` or `src/controller/pipeline_controller.py`
- Optional: `src/api/client.py` (if we centralize dropdown refresh logic)

---

## 2. High-Level UX Goals

- When critical config is missing (e.g., no model selected, invalid sampler):

  - Show a **visible warning** in the pipeline config area.
  - Disable the “Run pipeline” command until issues are resolved.

- When WebUI dropdowns are refreshed:

  - Show “Refreshing model list…” status.
  - Disable dropdowns briefly to avoid race conditions.

- For common misconfigurations (e.g., CFG too low/high if you preserved those rules in legacy):

  - Show non-blocking informational banners (optional for Phase 1.5).

---

## 3. Detailed Changes

### 3.1 `pipeline_config_panel_v2.py` — Validation Surface

- Add a validation state representation:

  ```python
  class PipelineConfigPanelV2(ttk.Frame):
      def __init__(...):
          ...
          self._validation_message_var = tk.StringVar(value="")
  ```

- Add a small banner area (label or frame) at the top or bottom of the panel:

  - Background styled for warnings (e.g., `Warning.TLabel`).
  - Bound to `_validation_message_var`.

- Add method:

  ```python
  def set_validation_message(self, message: str) -> None:
      self._validation_message_var.set(message)
  ```

### 3.2 Controller — Validation Logic

In `pipeline_controller` or `AppController` (where pipeline config lives), add a method:

```python
def validate_pipeline_config(self) -> Tuple[bool, str]:
    cfg = self._current_config  # or config builder
    # Minimal checks: model selected, sampler non-empty, steps > 0, etc.
    if not cfg.model_name:
        return False, "Please select a model before running the pipeline."
    if cfg.steps <= 0:
        return False, "Steps must be a positive integer."
    return True, ""
```

Where the config is built, call this before pipeline run:

```python
is_valid, message = self.validate_pipeline_config()
pipeline_panel = self._app_state.get("pipeline_config_panel_v2")
if pipeline_panel is not None:
    pipeline_panel.set_validation_message(message)

if not is_valid:
    self._append_log(f"[controller] Pipeline validation failed: {message}")
    return
```

### 3.3 `run_control_bar_v2.py` — Run Button State

- Wire the Run button to disable when validation fails:

  - Provide a method `set_run_enabled(bool)` in `RunControlBarV2`.
  - When `validate_pipeline_config` is called, update:

    ```python
    run_bar = self._app_state.get("run_control_bar_v2")
    if run_bar is not None:
        run_bar.set_run_enabled(is_valid)
    ```

### 3.4 Dropdown Refresh Feedback

If the V2 pipeline panel already supports a “Refresh from WebUI” control:

- When clicked:

  - Trigger an AppController method (e.g., `on_refresh_models_clicked()`).
  - Show “Refreshing model list…” in validation banner or a small inline label.
  - Disable dropdowns until refresh completes.

- When finished:

  - Clear the banner or show “Model list updated.”
  - Re-enable dropdowns.

Implementation sketch:

```python
def on_refresh_models_clicked(self) -> None:
    self._append_log("[controller] Refreshing model list from WebUI…")
    ok = self._model_service.refresh_from_webui()
    panel = self._app_state.get("pipeline_config_panel_v2")
    if panel is not None:
        if ok:
            panel.set_validation_message("Model list updated from WebUI.")
        else:
            panel.set_validation_message("Failed to refresh model list from WebUI.")
```

---

## 4. Validation

### 4.1 Tests

Add:

- `tests/gui_v2/test_pipeline_config_validation_v2.py`:

  - Simulate invalid config (no model).
  - Assert that the panel shows a validation message and that Run button is disabled.

- Controller test:

  - `tests/controller/test_pipeline_config_validation_v2.py`:

    - Tests `validate_pipeline_config` logic independently (unit-level).

### 4.2 Manual

- Remove model selection in GUI, attempt to run pipeline.

  - Observe: warning banner and disabled Run button.

- Provide valid config, attempt to run.

  - Observe: banner cleared (or informational only), Run enabled, pipeline executes.

---

## 5. Definition of Done

This PR is complete when:

1. Pipeline config panel can display validation messages.
2. The Run button is disabled when config is invalid.
3. Attempts to run with invalid config produce logs and user-visible feedback, not silent failures.
4. Basic dropdown refresh UX (if present) shows clear feedback during/after refresh.
