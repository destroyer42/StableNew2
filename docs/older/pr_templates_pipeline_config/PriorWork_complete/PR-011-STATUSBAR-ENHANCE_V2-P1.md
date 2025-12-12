# PR-LOG-003_V2-P1 — StatusBarV2 as Status/Health Lane

**Intent:**  
Refine `StatusBarV2` to serve as the primary **status/health/progress lane**:

- Show high-level status text (Idle, starting, running stage X, error).
- Show pipeline progress and ETA.
- Show WebUI connection state in a compact form.
- Avoid flooding the user with detailed logs (those go to the trace panel later).

This PR does not yet add the detailed trace panel; that will be PR-LOG-004.

---

## 1. Scope & Subsystems

**Subsystems touched:**

- GUI V2 (status bar)
- Controller (status updates)
- Pipeline (hook for progress events)

**Files to modify:**

- `src/gui/status_bar_v2.py`
- `src/gui/main_window_v2.py`
- `src/controller/app_controller.py` or `src/controller/pipeline_controller.py`
- Potentially small updates to `src/pipeline/pipeline_runner.py` for progress hooks

> Note: Use the existing app_state / event mechanism where possible. Do not invent new global state.

---

## 2. StatusBarV2 Contract

Define a narrow, explicit contract for what `StatusBarV2` expects:

- `status_text: str` – human-readable status line.
- `status_progress: float` – 0.0–1.0 progress of current run (or None when idle).
- `status_eta: Optional[str]` – short ETA string (e.g., `"~00:45"`).
- `webui_state: Literal["disconnected", "connecting", "connected", "error"]`.

### 2.1 Update `src/gui/status_bar_v2.py`

Without changing its public class name, ensure it:

- Exposes a method (or methods) like:

  ```python
  def update_status(
      self,
      text: Optional[str] = None,
      progress: Optional[float] = None,
      eta: Optional[str] = None,
  ) -> None: ...

  def update_webui_state(self, state: str) -> None: ...
  ```

- Does **not** attempt to render raw log lines or detailed error traces; it focuses on:

  - One-line text label.
  - A determinate/indeterminate progress bar.
  - A small WebUI connection indicator (icon or text).

Example diff sketch (adapt to existing implementation):

```diff
diff --git a/src/gui/status_bar_v2.py b/src/gui/status_bar_v2.py
index 0000000..0000000 100644
--- a/src/gui/status_bar_v2.py
+++ b/src/gui/status_bar_v2.py
@@ -1,6 +1,10 @@
 class StatusBarV2(ttk.Frame):
@@
-    def __init__(self, master, app_state, *args, **kwargs):
+    def __init__(self, master, app_state, *args, **kwargs):
         super().__init__(master, *args, **kwargs)
         self._app_state = app_state
+        self._status_text_var = tk.StringVar(value="Idle")
+        self._eta_text_var = tk.StringVar(value="")
+        self._progress_var = tk.DoubleVar(value=0.0)
+        self._webui_state_var = tk.StringVar(value="disconnected")
@@
-        # existing layout code
+        # layout: status label, progress bar, WebUI state
+        # (adapt to existing widget structure)
@@
+    def update_status(
+        self,
+        text: Optional[str] = None,
+        progress: Optional[float] = None,
+        eta: Optional[str] = None,
+    ) -> None:
+        if text is not None:
+            self._status_text_var.set(text)
+        if progress is not None:
+            self._progress_var.set(max(0.0, min(1.0, progress)))
+        if eta is not None:
+            self._eta_text_var.set(eta)
+
+    def update_webui_state(self, state: str) -> None:
+        self._webui_state_var.set(state)
```

> Do **not** break existing tests that reference `StatusBarV2` attributes; extend rather than replace.

---

## 3. Wiring Status Updates from Controller / Pipeline

### 3.1 `src/controller/pipeline_controller.py`

Add helper methods to send status updates to the GUI:

- On user pressing “Run pipeline”:

  ```python
  self._status_adapter.update_status("Starting pipeline…", progress=0.0)
  ```

- On stage transitions:

  ```python
  self._status_adapter.update_status(
      f"Running {stage_name}…",
      progress=current_progress,
      eta=eta_str,
  )
  ```

- On pipeline completion / failure:

  ```python
  self._status_adapter.update_status("Pipeline completed.", progress=1.0, eta="0:00")
  # or
  self._status_adapter.update_status("Error: see details", progress=0.0)
  ```

If a dedicated `StatusAdapter` exists in V2 controllers, use/extend it instead of calling the bar directly.

### 3.2 WebUI connection state

Wherever WebUI connection state is determined (e.g., `webui_discovery` or `healthcheck` callbacks), ensure the controller:

- Calls `status_bar.update_webui_state("connecting" | "connected" | "error" | "disconnected")`.

Hook this via whatever existing observer/event mechanism you have rather than new globals.

---

## 4. Integration in `MainWindowV2`

Ensure `MainWindowV2`:

- Initializes `StatusBarV2` with a reference to `app_state` / controller.
- Exposes a simple property or method for the controller to reach it safely (or uses an adapter injected into the controller).

Example sketch (adapt to actual layout):

```diff
diff --git a/src/gui/main_window_v2.py b/src/gui/main_window_v2.py
index 0000000..0000000 100644
--- a/src/gui/main_window_v2.py
+++ b/src/gui/main_window_v2.py
@@ -1,6 +1,8 @@
 from .status_bar_v2 import StatusBarV2
@@
 class MainWindowV2(tk.Tk):
@@
-        self.status_bar_v2 = StatusBarV2(self.bottom_zone, app_state=self.app_state)
+        self.status_bar_v2 = StatusBarV2(self.bottom_zone, app_state=self.app_state)
+        # make status bar available to controllers
+        self.app_state.set("status_bar_v2", self.status_bar_v2)
```

---

## 5. Validation

1. Run GUI V2 tests:

   ```bash
   pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
   pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
   ```

2. Manual test:

   - Launch GUI.
   - Run a small pipeline.
   - Verify:
     - Status text changes as the pipeline progresses.
     - Progress bar moves (even if roughly).
     - WebUI indicator reflects connection state (connected vs error).

3. Confirm that no raw log lines are displayed in the status bar.

---

## 6. Definition of Done

This PR is complete when:

1. `StatusBarV2` reflects:
   - Human-readable status text.
   - Progress and ETA.
   - WebUI connection state.
2. Pipeline runs and WebUI state changes are visible in the bar.
3. The status bar **does not** display detailed log lines or stack traces.
