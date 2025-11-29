# PR-015-SETTINGS-DIALOG-V2-P1 — Engine Settings Dialog (V2 Integration)

**Intent:**  
Restore the **Engine Settings Dialog** functionality in V2, replacing the current stubbed `on_open_settings` with a fully wired dialog that:

- Reads/writes engine-related settings from/to ConfigManager.
- Validates configuration values.
- Reflects WebUI status where appropriate.
- Fits within the V2 theming and controller architecture.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (settings UI)
- Controller (settings orchestration)
- ConfigManager / Preferences
- WebUI (optional read-only indicators)

**Files to modify:**

- `src/gui/engine_settings_dialog.py`
- `src/controller/app_controller.py`
- `src/utils/config.py` (or related config manager)
- `src/gui/main_window_v2.py` (if needed to host dialog)

---

## 2. High-Level Design

### 2.1 UX Behavior

- The existing “Settings” button (toolbar / menu) should open a modal **Engine Settings** dialog.
- Dialog fields:

  - Core paths (WebUI path, output dir, model directory).
  - Core behavior toggles (auto-launch WebUI, retry behavior, etc.).
  - Possibly performance knobs (batch size, default steps) — only if already represented in config.

- Buttons:

  - **Save & Close** — persist config changes and close.
  - **Cancel** — close without saving.
  - **Restore Defaults** — reset to ConfigManager defaults (optional, if supported).

### 2.2 Architecture Role

- Config remains **single source of truth**:
  - ConfigManager loads on app start.
  - Settings dialog reads from ConfigManager.
  - Saving updates ConfigManager and triggers any necessary runtime refresh via AppController (e.g., WebUI reconnect or pipeline reload if needed).

---

## 3. Detailed Changes

### 3.1 `src/gui/engine_settings_dialog.py` — Modernization

- Ensure the dialog uses `ttk` + `theme_v2` styles.
- Define a class:

  ```python
  class EngineSettingsDialog(ttk.Frame):
      def __init__(self, master, config_manager, on_save=None, theme=None, *args, **kwargs):
          ...
  ```

- Populate fields from `config_manager`:

  - Use methods like `config_manager.get("webui.path")`, etc.
  - Do **not** hard-code paths; use existing config keys if available.

- Implement `collect_values()` to produce a dict of updated values:

  ```python
  def collect_values(self) -> Dict[str, Any]:
      return {
          "webui.path": self._webui_path_var.get(),
          ...
      }
  ```

### 3.2 `src/controller/app_controller.py` — on_open_settings

Replace the stub body:

```python
def on_open_settings(self) -> None:
    self._append_log("[controller] Settings clicked (stub).")
```

with:

```python
def on_open_settings(self) -> None:
    self._append_log("[controller] Opening settings dialog…")
    window = self._app_state.get("main_window_v2")
    if window is None:
        return
    window.open_engine_settings_dialog(config_manager=self._config_manager)
```

Add a method to handle save:

```python
def on_settings_saved(self, new_values: Dict[str, Any]) -> None:
    for key, value in new_values.items():
        self._config_manager.set(key, value)
    self._config_manager.save()
    self._append_log("[controller] Settings updated and saved.")
```

### 3.3 `src/gui/main_window_v2.py` — Dialog Host

Add:

```python
def open_engine_settings_dialog(self, config_manager) -> None:
    dialog_win = tk.Toplevel(self)
    dialog_win.title("Engine Settings")

    def _on_save(values: Dict[str, Any]) -> None:
        controller = self.app_state.get("controller")
        if controller is not None:
            controller.on_settings_saved(values)
        dialog_win.destroy()

    dialog = EngineSettingsDialog(
        dialog_win,
        config_manager=config_manager,
        on_save=_on_save,
        theme=self.theme,
    )
    dialog.pack(fill=tk.BOTH, expand=True)
```

> Names should match existing app_state keys (e.g., `"controller"` and `"main_window_v2"` if already stored).

---

## 4. Validation

### 4.1 Tests

Add:

- `tests/gui_v2/test_engine_settings_dialog_v2.py`:

  - Instantiates dialog with a fake ConfigManager.
  - Ensures fields initialize from provided config.
  - Ensures `collect_values()` returns expected dict.

- Extend controller tests:

  - `tests/controller/test_app_controller_settings_v2.py`:

    - Mocks ConfigManager.
    - Calls `on_settings_saved` with a dict.
    - Asserts `set`/`save` called with correct values.

### 4.2 Manual

- Launch GUI.
- Click Settings.
- Modify a setting, click Save & Close.
- Restart app; confirm setting persisted.

---

## 5. Definition of Done

This PR is complete when:

1. Clicking the Settings button opens a functional Engine Settings dialog.
2. Changes are persisted via ConfigManager and visible after restart.
3. No legacy `StableNewGUI` assumptions remain in `engine_settings_dialog.py`.
4. Tests for dialog and controller settings path pass reliably.
