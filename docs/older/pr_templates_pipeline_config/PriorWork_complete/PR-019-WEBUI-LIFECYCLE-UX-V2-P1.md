# PR-019-WEBUI-LIFECYCLE-UX-V2-P1 — WebUI Retry / Reconnect UX (V2)

**Intent:**  
Recreate and modernize the **WebUI lifecycle UX** that existed in legacy `main_window.py`:

- Clear indicators of WebUI state (connecting, connected, error).
- User-facing controls to **retry**, **reconnect**, or **launch** WebUI.
- Integration with StatusBarV2 and the new logging/trace model.

This must be implemented **without** reviving V1 patterns; it should sit on top of `WebUIProcessManager` and healthcheck V2.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (status bar, buttons)
- WebUI process / healthcheck
- Controller

**Files to modify:**

- `src/gui/status_bar_v2.py`
- `src/controller/app_controller.py`
- `src/api/webui_process_manager.py`
- `src/gui/main_window_v2.py` (if additional controls live in the main window)

---

## 2. UX Behavior

- WebUI state summary visible in StatusBarV2:

  - States: `Disconnected`, `Connecting…`, `Connected`, `Error`.
  - Color or icon variations for error/connected.

- Controls:

  - “Launch WebUI” (if not running).
  - “Retry Connection” (if last check failed).
  - Optional “Open WebUI in browser” (if URL is known and healthy).

- Automatic:

  - On app start, WebUIProcessManager tries to detect & connect.
  - On failures, status bar shows an error state with optional tooltip.

---

## 3. Detailed Changes

### 3.1 `WebUIProcessManager` — Signals

Ensure `WebUIProcessManager` (or a small adapter) exposes:

- Methods:

  ```python
  def ensure_running(self) -> bool: ...
  def check_health(self) -> bool: ...
  ```

- Callbacks or return values that clearly indicate success/failure.

Do not deeply refactor; just ensure the controller can make clear decisions based on these APIs.

### 3.2 `AppController` — Command Methods

Add methods:

```python
def on_launch_webui_clicked(self) -> None:
    self._append_log("[webui] Launch requested by user.")
    ok = self._webui_process_manager.ensure_running()
    if ok:
        self._update_webui_state("connecting")
    else:
        self._update_webui_state("error")

def on_retry_webui_clicked(self) -> None:
    self._append_log("[webui] Retry connection requested by user.")
    ok = self._webui_process_manager.check_health()
    self._update_webui_state("connected" if ok else "error")
```

Add a helper that updates app_state + status bar:

```python
def _update_webui_state(self, state: str) -> None:
    self._app_state.set("webui_state", state)
    status_bar = self._app_state.get("status_bar_v2")
    if status_bar is not None:
        status_bar.update_webui_state(state)
```

### 3.3 `StatusBarV2` — UI for WebUI State & Buttons

- Ensure StatusBarV2 can:

  - Display `webui_state` text.
  - Optionally show a small colored indicator.
  - Show small buttons:

    - “Launch”
    - “Retry”

- Wire callback lambdas:

  ```python
  self._launch_button = ttk.Button(self, text="Launch", command=self._on_launch_clicked)
  self._retry_button = ttk.Button(self, text="Retry", command=self._on_retry_clicked)
  ```

- Hook into controller:

  ```python
  def _on_launch_clicked(self) -> None:
      controller = self._app_state.get("controller")
      if controller is not None:
          controller.on_launch_webui_clicked()

  def _on_retry_clicked(self) -> None:
      controller = self._app_state.get("controller")
      if controller is not None:
          controller.on_retry_webui_clicked()
  ```

- Use `update_webui_state(state)` to adjust labels/colors and enable/disable buttons appropriately (e.g., hide Retry when connected).

---

## 4. Validation

### 4.1 Tests

- `tests/controller/test_webui_lifecycle_ux_v2.py`:

  - Use a fake WebUIProcessManager.
  - `on_launch_webui_clicked` should call `ensure_running` and update state.
  - `on_retry_webui_clicked` should call `check_health` and update state.

- `tests/gui_v2/test_status_bar_webui_controls_v2.py`:

  - Assert Launch/Retry buttons exist.
  - Assert that clicking them calls the relevant controller methods (with mocks).

### 4.2 Manual

- Start app with WebUI not running:

  - Status bar should show `Disconnected` or similar.
  - Launch button should be enabled.

- Click Launch:

  - Observe logs indicating WebUI start attempt.
  - Once healthy, state should flip to `Connected`.

- Simulate failures (e.g., misconfigured port):

  - Retry should surface “Error” state and maintain user-visible feedback.

---

## 5. Definition of Done

This PR is complete when:

1. WebUI state is clearly visible in StatusBarV2.
2. Users can explicitly launch or retry WebUI connections via buttons.
3. These actions flow through AppController into WebUIProcessManager.
4. No V1 legacy lifecycle logic remains in active code paths; all behavior is V2-architected.
