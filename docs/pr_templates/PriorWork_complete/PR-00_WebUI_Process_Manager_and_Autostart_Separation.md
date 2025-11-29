# PR-00 — WebUI Process Manager & Autostart Separation

## Summary

Introduce a small, dedicated **WebUI process manager/launcher** that the GUI talks to, instead of having `main_window.py` directly start and own the WebUI process.

This decouples:

- **Startup policy** (autostart, manual start, restart, health checks)  
from
- **UI lifecycle** (Tk window creation/destruction, layout, user interactions)

and creates a cleaner seam for future controller/agent integrations.

> This is an **interim PR** that can land before or alongside Phase 1/2 work. It focuses only on **how WebUI is started and managed**, not on layout, theming, or broader V2 features.

---

## Problem Statement

Currently:

- The **WebUI process** is launched directly from `main_window.py` (or equivalent GUI code).  
- This couples WebUI startup and lifetime to the GUI’s lifecycle.  
- It makes it harder to:
  - Change autostart policy without editing GUI code.  
  - Restart or recover WebUI if it crashes while the GUI is still running.  
  - Headlessly start WebUI without bringing up the GUI.  
  - Plug in an external controller/agent that wants to manage WebUI independently.

We want:

- A **single place** that owns WebUI process management.  
- A simple **API surface** (Python calls or a small IPC layer) that the GUI can talk to.  
- Clear configuration for:
  - `autostart: true/false`  
  - `auto_restart_on_crash: true/false` (optional)  
  - WebUI executable/script path and arguments.

---

## Goals

1. **Remove direct WebUI process management from `main_window.py`.**  
2. **Create a small, self-contained WebUI process manager module** that is responsible for starting, stopping, and querying the status of WebUI.  
3. Provide **configurable autostart policy**:
   - Autostart off by default (or off in dev, on in “power user” mode, depending on a config flag).  
4. Make it easy for future code (CLI, controller, or agents) to use the same process manager without depending on the GUI.

---

## Non-Goals

- Rewriting WebUI itself.  
- Implementing a full microservice or network daemon.  
- Changing the GUI layout or theming (those are handled in later PRs).  
- Implementing complex IPC beyond what is needed for start/stop/status in this PR.

---

## Design Overview

Introduce a **WebUIProcessManager** class in a new module, and update `main_window.py` (and/or the new V2 main window) to use it instead of spawning WebUI directly.

### New Module

For example:

```text
src/
  webui/
    __init__.py
    process_manager.py   # NEW
```

`process_manager.py` will define:

```python
class WebUIProcessManager:
    def __init__(self, config):
        ...

    def start(self, *, force: bool = False) -> None:
        """Start WebUI if not running. If `force` is True, restart."""

    def stop(self) -> None:
        """Stop WebUI if running."""

    def is_running(self) -> bool:
        """Return True if the underlying process is alive."""

    def get_status(self) -> dict:
        """Return status info: pid, cmd, start_time, last_exit_code, etc."""
```

Under the hood, it uses `subprocess.Popen` (or equivalent) and keeps a handle to the process. It **must not** block the GUI main thread.

### Configuration Object

Define a simple config structure, either via:

- A dedicated class: `WebUIConfig`  
- Or a dictionary loaded from YAML/TOML/JSON (e.g. `config/webui.yaml`)

Config options might include:

- `enabled` (bool) — whether WebUI is even managed by this app.  
- `autostart` (bool) — start WebUI automatically on app startup.  
- `auto_restart_on_crash` (bool, optional) — if true, manager may attempt to restart WebUI if it unexpectedly exits.  
- `executable`/`script_path` — how to launch WebUI (e.g. python entrypoint or shell script).  
- `args` — additional CLI args to pass to WebUI.  
- `working_dir` — base directory for the process.

Example minimal config (YAML):

```yaml
enabled: true
autostart: false
auto_restart_on_crash: false
executable: "python"
script_path: "path/to/webui/launch.py"
args:
  - "--listen"
working_dir: "path/to/webui"
```

---

## Changes in GUI (main_window.py or V2 main window)

### Before

- GUI code calls `subprocess.Popen(...)` directly to spawn WebUI.  
- Autostart decisions are embedded in the GUI initialization logic.

### After

- GUI will **receive a WebUIProcessManager instance**, typically constructed at app startup.  
- The GUI can:
  - Call `manager.start()` if a user toggles “Start WebUI” in the UI.  
  - Call `manager.stop()` on “Stop WebUI”.  
  - Poll `manager.is_running()` or `manager.get_status()` to update indicators.  
- If `autostart` is true in config, the **app-level bootstrap code** (not the GUI layout itself) will call `manager.start()` after initialization.

Example integration sketch:

```python
# somewhere near app startup
from webui.process_manager import WebUIProcessManager, load_webui_config

config = load_webui_config()
webui_manager = WebUIProcessManager(config=config)

if config.autostart:
    webui_manager.start()

# pass the manager into the GUI:
run_app(webui_manager=webui_manager)
```

Inside the GUI:

```python
class MainWindow:
    def __init__(self, root, webui_manager):
        self.root = root
        self.webui_manager = webui_manager
        # bind buttons:
        #  - start/stop webui
        #  - show status indicator
```

This keeps **policy (autostart, config)** in the bootstrap layer and **interaction** (buttons, menus) in the GUI.

---

## Implementation Steps

1. **Add `webui/process_manager.py`**  
   - Implement `WebUIProcessManager` with:
     - `__init__(config)` storing config and internal process handle.  
     - `start()`, `stop()`, `is_running()`, `get_status()`.  
   - Use non-blocking process startup and basic logging.

2. **Add config loader**  
   - Either in the same module or a small companion module (`config/webui.py`):  
     - `load_webui_config()` that returns a config object/dict.  
   - Default behaviour should be sane even if no config file exists (e.g. WebUI management disabled, or autostart false).

3. **Update app bootstrap**  
   - Identify where `main_window.py` (or V2 entrypoint) is created.  
   - Before creating the GUI, construct `webui_manager` and, if configured, call `start()`.  
   - Pass `webui_manager` into the GUI constructor or `run_app` function.

4. **Remove direct WebUI process launching from GUI**  
   - Find any calls to `subprocess.Popen` or similar for WebUI inside GUI modules.  
   - Replace them with calls to `webui_manager.start()` / `webui_manager.stop()`.  
   - Ensure no GUI code holds direct references to the process object.

5. **Add simple UI affordances (minimal)**  
   - A status indicator (e.g., label or icon) showing WebUI: “Running” / “Stopped” / “Error”.  
   - Buttons or menu items:
     - “Start WebUI”  
     - “Stop WebUI”  
   - These are thin wrappers around the manager methods.

6. **Logging & Error Handling**  
   - Log process start/stop events and exit codes.  
   - Handle cases where start is called while process is already running (no-op or restart based on `force` flag).  
   - Handle failures to spawn WebUI gracefully (surface a message to the user, do not crash the GUI).

---

## Files Expected to Change / Be Added

**New:**

- `src/webui/__init__.py`  
- `src/webui/process_manager.py`  
- (Optional) `src/config/webui_config.py` or `config/webui.yaml`

**Updated:**

- `src/main.py` (or equivalent entrypoint): construct and wire `WebUIProcessManager`.  
- `src/gui/main_window.py` (or V2 main window): remove direct process spawning, accept `webui_manager` arg, add start/stop/status bindings.

No changes should be made to WebUI itself in this PR.

---

## Tests & Validation

- **Manual tests:**
  - Start app with `enabled: true`, `autostart: false`:
    - GUI loads without starting WebUI.  
    - Clicking “Start WebUI” starts it.  
    - Clicking “Stop WebUI” stops it.  
  - Start app with `enabled: true`, `autostart: true`:
    - GUI loads and WebUI is started automatically.  
  - Close GUI while WebUI is running:
    - Confirm that process manager is allowed to shut down WebUI cleanly (or leave it running, depending on desired policy).

- **Automated tests (lightweight):**
  - Unit test for `WebUIProcessManager` using a dummy command (e.g., `python -c "import time; time.sleep(2)"`) to verify:
    - `start()` sets `is_running()` to true.  
    - `stop()` terminates the process.  
    - `get_status()` returns sensible information.

---

## Acceptance Criteria

- `main_window.py` (or its V2 replacement) no longer directly spawns the WebUI process.  
- WebUI is started and stopped via `WebUIProcessManager`.  
- Autostart behaviour is controlled via a config object/file and **not hard-coded** in GUI initialization.  
- Future work (controllers, agents, or a non-GUI launcher) can reuse `WebUIProcessManager` without modification.
