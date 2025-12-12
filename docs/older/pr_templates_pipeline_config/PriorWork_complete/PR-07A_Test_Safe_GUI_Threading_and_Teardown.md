# PR-07A — Test-Safe GUI Threading & Teardown (Maximum Stability)

## Summary

After PR-03 (V2 spine), PR-04 (theme), PR-05/05A (layout/scroll), PR-06A–C (stage card componentization), and PR-07 (panel/controller wiring), the GUI is substantially more capable — but the test suite is now hitting:

- **Windows fatal exception 0x80000003** inside Tk/logging
- Crashes during threaded cleanup in `src/gui/controller.py` / `src/gui/state.py`
- Pytest aborting at ~60–70% of tests

This is a classic Tkinter + threads + teardown problem: background threads or callbacks are still touching Tk / GUI state **after** the root has been destroyed, or are doing so from a non-main thread.

This PR introduces a **comprehensive, maximum-stability layer** for GUI-thread safety and teardown, so that:

- All GUI updates happen on the main thread via a safe invoker.
- AppStateV2 notifications do not fire into destroyed widgets or from background threads.
- Controllers cleanly stop background work before GUI teardown.
- Tests can create/destroy Tk roots without triggering low-level Windows crashes.

> This PR focuses entirely on **stability** — no new UI features or layout changes.

---

## Goals

1. Ensure **all GUI operations occur on the Tk main thread** via a simple invoker abstraction.
2. Make `AppStateV2` notifications test-safe and teardown-aware.
3. Ensure controllers and background threads **stop cleanly** and do not access Tk after teardown.
4. Provide a **stable test harness** to create/destroy Tk roots without fatal exceptions.
5. Preserve all existing UX and logic — behavior should be the same, just more robust.

---

## Non-Goals

- No visual changes (no theme or layout tweaks).
- No changes to pipeline logic or WebUI integration, except what’s required to honor the new invoker/cleanup model.
- No archiving or removal of any modules.

---

## Design Overview

Core pattern:

- Introduce a lightweight `GuiInvoker` that wraps `root.after(...)` and tracks disposal.
- Inject a `GuiInvoker` into `AppStateV2` and any controller that needs to schedule UI updates.
- Route **all GUI-facing callbacks** and `AppStateV2` listener notifications through this invoker.
- Add a `cleanup()` method on `MainWindowV2` (and/or a central controller) that:
  - Stops all background threads / timers.
  - Disables further AppState notifications.
  - Disposes the invoker.
- Update tests to use a shared Tk fixture that calls `cleanup()` and then destroys the root.

This ensures no code runs Tk operations after the root is gone, and no background thread touches Tk directly.

---

## Implementation

### 1. Add a GuiInvoker Helper

Create a new module:

```text
src/gui/gui_invoker.py
```

Implementation sketch:

```python
from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Optional


class GuiInvoker:
    """Thread-safe invoker for scheduling GUI work on the Tk main thread."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._disposed = False
        self._lock = threading.Lock()

    def invoke(self, fn: Callable[[], None]) -> None:
        """Schedule `fn` to run on the Tk main loop as soon as possible."""
        with self._lock:
            if self._disposed:
                return
            try:
                self._root.after(0, fn)
            except tk.TclError:
                # Root is likely already destroyed; fail silently.
                pass

    def dispose(self) -> None:
        """Prevent any further scheduling; in-flight callbacks may still run."""
        with self._lock:
            self._disposed = True
```

Notes:

- `tk.Misc` is enough to accept `Tk` or `Toplevel`.  
- We swallow `TclError` to avoid crashes during late teardown.

This class does **not** create or own the root; it just uses the one passed in.

---

### 2. Make AppStateV2 Aware of GuiInvoker and Teardown

In `src/gui/app_state_v2.py`:

1. Add a field for the invoker and a flag for “notifications enabled”:

```python
from typing import Optional
from src.gui.gui_invoker import GuiInvoker  # new import


@dataclass
class AppStateV2:
    _listeners: Dict[str, List[Listener]] = field(default_factory=dict)

    _invoker: Optional[GuiInvoker] = None
    _notifications_enabled: bool = True

    # existing fields: current_pack, is_running, status_text, last_error, ...
```

2. Add methods to set/unset invoker and disable notifications:

```python
    def set_invoker(self, invoker: GuiInvoker) -> None:
        self._invoker = invoker

    def disable_notifications(self) -> None:
        """Stop delivering listener callbacks (e.g., during teardown)."""
        self._notifications_enabled = False
```

3. Update `_notify` to use the invoker and honor `_notifications_enabled`:

```python
    def _notify(self, key: str) -> None:
        if not self._notifications_enabled:
            return

        listeners = self._listeners.get(key, [])
        if not listeners:
            return

        if self._invoker is None:
            # Fallback: call inline (useful for tests that don't construct a full GUI)
            for listener in list(listeners):
                listener()
        else:
            for listener in list(listeners):
                self._invoker.invoke(listener)
```

This ensures:

- Notifications in the running app are always scheduled on the GUI thread.  
- Tests can still use AppStateV2 without a GUI (invoker stays `None`, and it behaves as before).  
- During teardown, `disable_notifications()` prevents callbacks from firing at all.

> Do not change any existing `set_*` methods except to make sure they call `_notify(key)` as they already do.

---

### 3. Inject GuiInvoker in MainWindowV2 and Wire It to AppStateV2

In `src/gui/main_window_v2.py`:

1. Import `GuiInvoker`:

```python
from src.gui.gui_invoker import GuiInvoker
```

2. In `MainWindowV2.__init__`, after `root` is assigned and before building frames, create an invoker and set it on the app state:

```python
class MainWindowV2:
    def __init__(
        self,
        root: tk.Tk,
        app_state: AppStateV2,
        webui_manager: WebUIProcessManager,
        app_controller: AppController,
        packs_controller: PacksController,
        pipeline_controller: PipelineController,
        # ... any other dependencies
    ) -> None:
        self.root = root
        self.app_state = app_state

        self._invoker = GuiInvoker(self.root)
        self.app_state.set_invoker(self._invoker)

        # existing theme/layout init
        apply_theme(self.root)
        self._configure_root()
        self._build_frames()
        self._compose_layout()
        self._wire_toolbar()
        self._wire_status_updates()
```

Now all AppStateV2 notifications triggered during normal runtime will be marshaled to the main thread.

---

### 4. Add a `cleanup()` Method to MainWindowV2

We want a centralized place to stop background work, disable notifications, and dispose the invoker.

In `MainWindowV2`:

```python
    def cleanup(self) -> None:
        """Stop background work and make GUI teardown test-safe.

        This should be called before root.destroy(), both in production shutdown and tests.
        """
        # 1) Tell app_state to stop delivering callbacks.
        self.app_state.disable_notifications()

        # 2) Dispose GUI invoker so no more GUI tasks are scheduled.
        if hasattr(self, "_invoker") and self._invoker is not None:
            self._invoker.dispose()

        # 3) Ask controllers to stop any background threads / timers.
        try:
            if hasattr(self, "pipeline_controller"):
                stop = getattr(self.pipeline_controller, "stop_all", None) or getattr(
                    self.pipeline_controller, "shutdown", None
                )
                if callable(stop):
                    stop()
        except Exception:
            # Avoid raising during shutdown; log if you have a safe logger.
            pass

        try:
            if hasattr(self, "app_controller"):
                stop = getattr(self.app_controller, "stop_all_background_work", None)
                if callable(stop):
                    stop()
        except Exception:
            pass

        try:
            if hasattr(self, "webui_manager"):
                stop = getattr(self.webui_manager, "shutdown", None) or getattr(
                    self.webui_manager, "stop", None
                )
                if callable(stop):
                    stop()
        except Exception:
            pass
```

CODEX should adapt the controller stop/shutdown method names to the actual API, but the idea is:

- No background threads should still be running when tests destroy the root.
- No future AppState notifications or invoker calls should be scheduled.

Also register this cleanup on window close:

```python
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self.cleanup()
        self.root.destroy()
```

Tests should call `mw.cleanup()` explicitly before `root.destroy()` (see test fixture below).

---

### 5. Audit Controllers for Tk Access on Non-Main Threads

In `src/gui/controller.py` and any controller that uses threads (e.g., pipeline, logging, WebUI polling), search for:

- Direct Tk widget calls (`widget.config`, `widget.insert`, etc.) in background threads.
- Direct use of `tk.StringVar`, `tk.IntVar`, etc. mutated from non-main threads.
- Logging handlers that write into Tk widgets (e.g., a `Text` widget log panel).

For each case, do **one** of the following:

#### Option A — Route via AppStateV2

If the effect is “update state, and the UI will reflect it”:

- Replace direct Tk calls with state mutations (`app_state.set_status_text(...)`, etc.).  
- AppStateV2 will route to the GUI on the main thread via `GuiInvoker`.

#### Option B — Use GuiInvoker Directly

If direct widget access is unavoidable (e.g., a logging handler writing into `LogPanel`):

- Inject the `GuiInvoker` (or a wrapper) into that code, and replace:

```python
text_widget.insert("end", message)
```

with:

```python
self._invoker.invoke(lambda: text_widget.insert("end", message))
```

The critical rule:

> **No background thread may call Tk APIs directly.**

Everything must go through:

- State changes that AppStateV2 broadcasts with the invoker, or  
- Direct `GuiInvoker.invoke(...)` calls.

---

### 6. Ensure Theme Initialization Is Safe

In `src/gui/theme_v2.py` (and `theme.py` if still used):

- Confirm that **no Tk root is created at import time**.
- Confirm `apply_theme(root)` assumes the caller has already created the root, and doesn’t re-create it internally.

If any code currently does something like `root = tk.Tk()` inside `apply_theme`, remove it. All theme configuration must operate on the provided `root` or the default style obtained from `ttk.Style()`.

This avoids weird cross-root interactions during tests.

---

### 7. Add a Tk Test Fixture for GUI Tests

Under `tests/` (likely in `tests/conftest.py` or `tests/gui_v2/conftest.py`), add a fixture that provides a shared Tk root per test or per session and ensures clean teardown using `cleanup()`:

```python
import pytest
import tkinter as tk

from src.gui.main_window_v2 import MainWindowV2
from src.gui.app_state_v2 import AppStateV2
# import whatever you need to build minimal controllers


@pytest.fixture
def tk_root():
    root = tk.Tk()
    yield root
    # No GUI left when test completes
    try:
        root.destroy()
    except tk.TclError:
        pass
```

For tests that construct `MainWindowV2`, prefer a dedicated fixture:

```python
@pytest.fixture
def main_window_v2(tk_root):
    app_state = AppStateV2()
    # Build minimal stub controllers or real ones if needed
    app_controller = ...
    packs_controller = ...
    pipeline_controller = ...
    webui_manager = ...

    mw = MainWindowV2(
        tk_root,
        app_state=app_state,
        webui_manager=webui_manager,
        app_controller=app_controller,
        packs_controller=packs_controller,
        pipeline_controller=pipeline_controller,
    )
    yield mw

    # Ensure we clean up threads and AppState callbacks before destroying root
    try:
        mw.cleanup()
    except Exception:
        pass
```

Update existing GUI tests that create Tk roots or windows to use these fixtures instead of ad-hoc `tk.Tk()` + `destroy()` logic.

---

### 8. Optional: Guard Logging Handlers on Teardown

If you have a logging handler that writes into Tk widgets (e.g., a `LogPanel`), add a simple guard:

- Set a `self._disposed = True` flag on cleanup.  
- Have the handler skip writes if `disposed` is true.  
- Optionally, detach the handler from the logger in `MainWindowV2.cleanup()`.

Example:

```python
def emit(self, record):
    if self._disposed:
        return
    msg = self.format(record)
    self._invoker.invoke(lambda: self._append_to_text_widget(msg))
```

And in cleanup:

```python
self.log_panel.dispose()  # sets handler._disposed = True
```

This avoids last-moment log writes hitting destroyed widgets.

---

## Files Expected to Change / Be Added

**New:**

- `src/gui/gui_invoker.py`

**Updated:**

- `src/gui/app_state_v2.py`
  - Add `_invoker`, `_notifications_enabled`, `set_invoker`, `disable_notifications`, `_notify` changes.

- `src/gui/main_window_v2.py`
  - Import and construct `GuiInvoker`.
  - Call `app_state.set_invoker(...)`.
  - Add `cleanup()` and `_on_close()` handling.
  - Call `cleanup()` on window close.

- `src/gui/controller.py` (and any other controllers using threads)
  - Replace direct Tk calls in background threads with state updates or `GuiInvoker.invoke(...)`.

- `src/gui/state.py` (if it manages threaded callbacks)
  - Ensure it does not directly touch Tk from non-main threads.

- `src/gui/theme_v2.py` (only if necessary)
  - Ensure no root creation; theme is applied to the provided root only.

- `tests/conftest.py` or `tests/gui_v2/conftest.py`
  - Add Tk and `MainWindowV2` fixtures as described, or update existing fixtures to call `cleanup()`.

- Any logging/LogPanel modules that directly use Tk from threads.

---

## Tests & Validation

### Manual

1. Run the app normally (`python -m src.main`) and exercise:
   - Load pack
   - Run pipeline
   - Stop/cancel
   - WebUI start/stop
   - Close window

   Confirm behavior is unchanged and shutdown is smooth (no errors in console).

2. Open/close the app repeatedly; watch for exceptions on shutdown.

### Automated

1. Run full test suite:

```bash
python -m pytest -q
```

Expected:

- No Windows fatal exception (0x80000003).
- No Tk crashes during teardown.
- All previously passing tests remain passing.

2. If any tests need to be updated for the new fixtures or constructor signatures, adapt them minimally.

---

## Acceptance Criteria

- **No more fatal Windows exceptions** (0x80000003) due to Tk/thread issues in any test runs.  
- All GUI updates originate from the main thread (enforced via `GuiInvoker`).  
- `AppStateV2` does not deliver notifications after `disable_notifications()` is called.  
- `MainWindowV2.cleanup()` is called in both production shutdown and tests, and safely stops background work.  
- The full pytest suite runs to completion, and all previously passing tests remain green.
