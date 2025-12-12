# PR-03 — Create V2 App Spine (with Concrete Skeletons)

## Summary

Define and enforce a **clean application spine for V2**, so that:

- All GUI work happens through a clearly owned **V2 main window and layout**.
- **V1 / legacy GUI code is not part of the main app path** (PR-02 handles physical archival).
- Core components (AppState, layout, panels, controllers) have predictable, discoverable locations.

This PR focuses on **structure and wiring**, not on final layout polish or theming. It prepares the ground for Phase 2 (layout + theme + widget refactor).

> This assumes PR-00 (WebUI process manager) is complete and PR-02 (legacy archive) is either complete or ready to ignore most V1 GUI modules.

---

## Goals

1. Establish `src/gui/v2/` (or equivalent) as the **authoritative V2 GUI package**.
2. Provide a **single, explicit V2 entrypoint** for the GUI (e.g., `main_window_v2.run_app`).
3. Introduce a minimal but clear **AppState** class and layout skeleton that Phase 2 can fill in.
4. Ensure `src/main.py` uses only V2 GUI for normal startup.

---

## Non-Goals

- Final visual hierarchy (Phase 2 will refine layout & padding).
- Full theming implementation (PR-04).
- Widget componentization (PR-06) beyond basic placeholders.
- Learning system, distributed compute, or pack config logic (Phase 3).

---

## Target Structure

The V2 GUI should live in a structured package similar to:

```text
src/gui/
  __init__.py
  main_window_v2.py
  app_state_v2.py
  layout_v2.py
  # Panels (can be here initially; later Phase 2 might split further)
  sidebar_panel_v2.py
  pipeline_panel_v2.py
  preview_panel_v2.py
  status_bar_v2.py
  webui_controls_panel_v2.py   # from PR-00A
```

> Note: You already have many of these modules; this PR is about enforcing **how they hang together** and removing any ambiguity about entrypoints.

---

## Design Overview

### Key Concepts

- **AppStateV2**: a container for GUI state (prompt, model selection, pipeline settings, etc.). For this PR, it can be minimal with TODOs for later expansion.
- **MainWindowV2**: constructs and composes panels (sidebar, pipeline controls, preview, status bar) and wires them to `AppStateV2` and controllers.
- **LayoutV2**: a helper to enforce consistent grid configuration (root row/column weights, panel docking) without yet making final aesthetic decisions.

`src/main.py` will:

1. Build shared services (config, controllers, WebUIProcessManager).
2. Instantiate `AppStateV2`.
3. Launch `MainWindowV2` via `run_app` or similar.

---

## Implementation Plan

### Step 1 — Introduce/Normalize `AppStateV2`

Create `src/gui/app_state_v2.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any


Listener = Callable[[], None]


@dataclass
class AppStateV2:
    """Central, GUI-facing state for the V2 application.

    This is intentionally minimal in PR-03 and will be expanded in Phase 2/3.
    """

    _listeners: Dict[str, List[Listener]] = field(default_factory=dict)

    # Example core fields (expand later)
    prompt: str = ""
    negative_prompt: str = ""

    def subscribe(self, key: str, listener: Listener) -> None:
        listeners = self._listeners.setdefault(key, [])
        if listener not in listeners:
            listeners.append(listener)

    def _notify(self, key: str) -> None:
        for listener in self._listeners.get(key, []):
            listener()

    # Example setters with notification
    def set_prompt(self, value: str) -> None:
        if self.prompt != value:
            self.prompt = value
            self._notify("prompt")

    def set_negative_prompt(self, value: str) -> None:
        if self.negative_prompt != value:
            self.negative_prompt = value
            self._notify("negative_prompt")
```

> Later PRs (Phase 2/3) will extend this with model selection, pipeline config, queue state, etc.

### Step 2 — Define `layout_v2` Helpers

Create `src/gui/layout_v2.py` to hold root-level grid configuration utilities:

```python
from __future__ import annotations

import tkinter as tk


def configure_root_grid(root: tk.Tk) -> None:
    """Apply top-level grid weights so the app can scale.

    For PR-03, this is a minimal setup; Phase 2 will refine.
    """
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=0)  # sidebar
    root.columnconfigure(1, weight=3)  # main / pipeline
    root.columnconfigure(2, weight=2)  # preview / queue
```

Later PRs can add helpers for standardized padding, gaps, etc.

### Step 3 — Create/Normalize `MainWindowV2`

Create or refactor `src/gui/main_window_v2.py` into a coherent spine:

```python
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from src.api.webui_process_manager import WebUIProcessManager
from src.gui.app_state_v2 import AppStateV2
from src.gui.layout_v2 import configure_root_grid
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.pipeline_panel_v2 import PipelinePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.status_bar_v2 import StatusBarV2
from src.gui.webui_controls_panel_v2 import WebUIControlsPanel  # from PR-00A


class MainWindowV2:
    def __init__(
        self,
        root: tk.Tk,
        app_state: AppStateV2,
        webui_manager: WebUIProcessManager,
        # controllers for pipeline, jobs, learning, etc. can be added here
    ) -> None:
        self.root = root
        self.app_state = app_state
        self.webui_manager = webui_manager

        self._configure_root()
        self._build_frames()
        self._compose_layout()

    def _configure_root(self) -> None:
        self.root.title("StableNew V2")
        configure_root_grid(self.root)

    def _build_frames(self) -> None:
        self.sidebar_frame = ttk.Frame(self.root)
        self.pipeline_frame = ttk.Frame(self.root)
        self.preview_frame = ttk.Frame(self.root)
        self.status_frame = ttk.Frame(self.root)

        # Panels
        self.sidebar_panel = SidebarPanelV2(self.sidebar_frame, app_state=self.app_state)
        self.pipeline_panel = PipelinePanelV2(self.pipeline_frame, app_state=self.app_state)
        self.preview_panel = PreviewPanelV2(self.preview_frame, app_state=self.app_state)
        self.status_bar = StatusBarV2(self.status_frame)

        # WebUI controls can live inside the status bar or be attached below
        self.webui_controls = WebUIControlsPanel(
            master=self.status_frame,
            webui_manager=self.webui_manager,
        )

    def _compose_layout(self) -> None:
        # Place top-level frames
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.pipeline_frame.grid(row=0, column=1, sticky="nsew")
        self.preview_frame.grid(row=0, column=2, sticky="nsew")
        self.status_frame.grid(row=1, column=0, columnspan=3, sticky="ew")

        # Make the main row grow
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)

        # Sidebar/pipeline/preview internal layouts
        self.sidebar_panel.pack(fill="both", expand=True)
        self.pipeline_panel.pack(fill="both", expand=True)
        self.preview_panel.pack(fill="both", expand=True)

        # Status bar & WebUI controls
        self.status_bar.pack(side="left", fill="x", expand=True)
        self.webui_controls.pack(side="right")

def run_app(
    root: Optional[tk.Tk] = None,
    webui_manager: Optional[WebUIProcessManager] = None,
) -> None:
    from src.api.webui_process_manager import WebUIConfig  # local import to avoid cycles

    if root is None:
        root = tk.Tk()

    if webui_manager is None:
        config = WebUIConfig.from_env_and_defaults()
        webui_manager = WebUIProcessManager(config=config)

    app_state = AppStateV2()

    main_window = MainWindowV2(
        root=root,
        app_state=app_state,
        webui_manager=webui_manager,
    )

    root.mainloop()
```

> NOTE: The actual repo likely has richer Sidebar/Pipeline/Preview panels already.
> CODEX should **adapt this skeleton** to the existing implementations,
> not overwrite them.

### Step 4 — Wire `src/main.py` to V2 Only

Update `src/main.py` so that its GUI path always launches V2 (unless a CLI flag for headless mode is used).

Example shape:

```python
import logging
import sys
import tkinter as tk

from src.api.webui_process_manager import WebUIConfig, WebUIProcessManager
from src.gui.main_window_v2 import run_app as run_app_v2


def bootstrap_webui_manager() -> WebUIProcessManager:
    config = WebUIConfig.from_env_and_defaults()
    manager = WebUIProcessManager(config=config)
    if config.autostart:
        manager.start()
    return manager


def main() -> int:
    logging.basicConfig(level=logging.INFO)

    webui_manager = bootstrap_webui_manager()
    root = tk.Tk()
    run_app_v2(root=root, webui_manager=webui_manager)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

If the repo already has more complex CLI argument parsing (e.g., for headless operations), CODEX should ensure:

- The **default “no-args” path** uses V2 app.
- Legacy/V1 GUI entrypoints are not used for normal flows.

### Step 5 — Remove Stray V1 GUI Imports from Active Path

With PR-02 archiving and this V2 spine in place:

- Search for imports referencing V1 GUI modules in active code (e.g., `txt2img_stage_card`, `upscale_stage_card`, old center-panel layouts).
- Remove or migrate them so that V2 panels (`*_panel_v2.py`, `stage_cards_v2`, etc.) are the only GUI providers.
- Ensure `ACTIVE_MODULES.md` reflects V2-only GUI usage.

---

## Files Expected to Change / Be Added

**New (or normalized):**

- `src/gui/app_state_v2.py`
- `src/gui/layout_v2.py`
- `src/gui/main_window_v2.py` (coherent structure as above)

**Updated:**

- `src/main.py` (V2-only GUI entrypoint)  
- Existing V2 panels (`sidebar_panel_v2.py`, `pipeline_panel_v2.py`, `preview_panel_v2.py`, `status_bar_v2.py`) to accept `AppStateV2` / `WebUIProcessManager` as needed.

No changes should be made to:

- Archived V1 GUI code (`archive/gui_v1/**`)
- Pipeline/learning/queue internals beyond what is required to pass correct dependencies into panels.

---

## Tests & Validation

1. **App Startup**
   - `python -m src.main` should open the V2 window only.
   - Window title should clearly indicate V2 (“StableNew V2” or similar).

2. **Panel Presence**
   - Sidebar / Pipeline / Preview / Status / WebUI controls are all visible.
   - No traceback on startup.

3. **Basic Interaction**
   - Prompt editing (basic) works and updates `AppStateV2` (log or debug-print for now).
   - WebUI controls (from PR-00A) still work (start/stop).

4. **Tests**
   - Existing `tests/gui_v2` should be updated as needed to import `MainWindowV2` / `run_app_v2` instead of V1.
   - Any tests that depended on old main window structure should be realigned to the new app spine.

---

## Acceptance Criteria

- `src/main.py` launches the V2 GUI exclusively for default runs.
- `MainWindowV2` exists and composes panels in a predictable structure.
- `AppStateV2` and `layout_v2` exist as clear extension points.
- No V1 GUI modules remain in the active import path used by `src/main.py`.
- GUI and controller tests (`tests/gui_v2`, `tests/controller`) pass after updates.
