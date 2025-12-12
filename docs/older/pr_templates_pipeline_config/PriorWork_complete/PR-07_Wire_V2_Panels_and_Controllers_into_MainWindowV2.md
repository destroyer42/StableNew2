# PR-07 — Wire V2 Panels & Controllers into MainWindowV2

## Summary

After PR-03/04/05, StableNew now has:

- A V2 app spine (`MainWindowV2`, `AppStateV2`, `layout_v2`).
- A dark ASWF theme (`theme_v2.apply_theme`).
- A sane layout (sidebar / pipeline / preview / status) that resizes correctly.

However, much of the **actual functionality** is still disconnected:

- Packs don’t load in the V2 UI.
- Run / Stop / Preview / Settings / Help buttons don’t trigger pipelines or controllers.
- Pipeline stage UIs (stage cards) are not mounted in the main window.
- Preview / history areas do not update.

This PR’s purpose is to **pull the existing V2 work off the shelf and plug it into MainWindowV2**.  
It wires:

- V2 panels (`SidebarPanelV2`, `PipelinePanelV2`, `PreviewPanelV2`, `StatusBarV2`).
- Existing controllers and adapters (pipeline, packs, learning, status).  
- Button callbacks and status updates.

> No new features — this PR just makes the V2 GUI **actually drive the already-existing pipeline and controllers**.

---

## Goals

1. Make the V2 GUI **functionally equivalent (or better)** than the previous hybrid main window for core flows:
   - Load pack
   - Edit pack
   - Run pipeline
   - Stop / cancel
   - Preview (dry run / no output writes if supported)
2. Mount V2 panels into `MainWindowV2` so the center and right side of the app show:
   - Pipeline controls (stage cards, run settings).
   - Preview / job history / queue view.
3. Connect the bottom status bar and WebUI controls to real status events:
   - API status / WebUI status
   - Job progress (at least high-level “Running/Idle/Failed”).
4. Keep business logic in controllers/adapters — `MainWindowV2` should remain a **thin orchestration layer**, not reimplement logic.

---

## Non-Goals

- No new pipeline features or job types.  
- No refactor of controller internals.  
- No archiving of any GUI modules.  
- No deep learning/experimentation UX; that is Phase 3+.

---

## Pre-Requisites / Assumptions

- **PR-03** is implemented:
  - `src/gui/app_state_v2.py`
  - `src/gui/layout_v2.py`
  - `src/gui/main_window_v2.py`
- **PR-04** (theme engine) and **PR-05** (layout) are applied.
- V2 GUI panels already exist, including something like:
  - `src/gui/sidebar_panel_v2.py`
  - `src/gui/pipeline_panel_v2.py`
  - `src/gui/preview_panel_v2.py`
  - `src/gui/status_bar_v2.py`
  - And advanced stage cards under `src/gui/stage_cards_v2/advanced_*_stage_card_v2.py`
- Controllers/adapters already exist and are used in tests / prior main window:
  - An “app controller” (`AppController` / `AppControllerV2` / `StableNewController`).
  - A pipeline run controller (`PipelineController`, `AppController.pipeline_runner`, or similar).
  - A prompt-pack controller/service for loading/editing packs.
  - A status notifier / WebUI status hooks (through `WebUIProcessManager` and/or `StatusAdapterV2`).

CODEX should cross-check the exact class names and module paths with the repo (e.g., via `ACTIVE_MODULES.md` and `repo_inventory.json`) and adapt the skeletons below accordingly.

---

## Design Overview

### High-Level Flow

`src/main.py`:

1. Builds controllers (pipeline, packs, learning, status).  
2. Builds `WebUIProcessManager`.  
3. Creates `Tk` root + `AppStateV2`.  
4. Creates `MainWindowV2`, injecting:
   - `app_state`
   - `controllers` (or a single façade controller)
   - `webui_manager`

`MainWindowV2`:

- Composes the **header toolbar**, **sidebar**, **pipeline panel**, **preview panel**, **status bar**, and **WebUI controls**.  
- Binds toolbar buttons (`Load Pack`, `Edit Pack`, `Run`, `Stop`, `Preview`, `Settings`, `Help`) to calls on the appropriate controller methods.  
- Subscribes to controller events / callbacks to update:
  - AppStateV2
  - Status bar messages
  - Preview / job history panel

Panels:

- `SidebarPanelV2` binds pack list and pack selection to the prompt/pack services.  
- `PipelinePanelV2` exposes stage cards and run settings and forwards “run pipeline” intentions to a controller.  
- `PreviewPanelV2` shows output / history / queue via an adapter or callbacks.  
- `StatusBarV2` receives text + severity updates and renders them.

---

## Implementation Plan

### Step 1 — Extend AppStateV2 with Basic Fields

In `src/gui/app_state_v2.py`, add minimal fields and helpers that the GUI needs right now:

- Current pack name / ID  
- Boolean “pipeline is running” flag  
- Current status line text  
- Optional “last error” field

Example (adaptable to existing structure):

```python
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Optional

Listener = Callable[[], None]


@dataclass
class AppStateV2:
    _listeners: Dict[str, List[Listener]] = field(default_factory=dict)

    current_pack: Optional[str] = None
    is_running: bool = False
    status_text: str = "Idle"
    last_error: Optional[str] = None

    # subscribe/_notify already exist from PR-03

    def set_current_pack(self, value: Optional[str]) -> None:
        if self.current_pack != value:
            self.current_pack = value
            self._notify("current_pack")

    def set_running(self, value: bool) -> None:
        if self.is_running != value:
            self.is_running = value
            self._notify("is_running")

    def set_status_text(self, value: str) -> None:
        if self.status_text != value:
            self.status_text = value
            self._notify("status_text")

    def set_last_error(self, value: Optional[str]) -> None:
        if self.last_error != value:
            self.last_error = value
            self._notify("last_error")
```

Panels can subscribe to keys like `"current_pack"` and `"status_text"` to keep labels updated.

### Step 2 — Pass Controllers into MainWindowV2

Update `src/gui/main_window_v2.py` to accept controller instances (or a façade) instead of being GUI-only.

Constructor signature (example):

```python
class MainWindowV2:
    def __init__(
        self,
        root: tk.Tk,
        app_state: AppStateV2,
        webui_manager: WebUIProcessManager,
        app_controller: AppController,           # or similar
        packs_controller: PacksController,       # or service
        pipeline_controller: PipelineController, # can be part of app_controller
    ) -> None:
        self.root = root
        self.app_state = app_state
        self.webui_manager = webui_manager
        self.app_controller = app_controller
        self.packs_controller = packs_controller
        self.pipeline_controller = pipeline_controller

        apply_theme(self.root)
        self._configure_root()
        self._build_frames()
        self._compose_layout()
        self._wire_toolbar()
        self._wire_status_updates()
```

`src/main.py` should then build these controllers (using existing factory functions or direct instantiation) and pass them in.

If the repo already has a single `AppController` that exposes `load_pack`, `start_run`, etc., CODEX may pass just that and adapt the method calls accordingly.

### Step 3 — Mount V2 Panels into MainWindowV2

In `MainWindowV2._build_frames()` or `_compose_layout()`, replace placeholder content with real V2 panels:

```python
from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.pipeline_panel_v2 import PipelinePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui.status_bar_v2 import StatusBarV2
from src.gui.webui_controls_panel_v2 import WebUIControlsPanel
```

Example:

```python
def _build_frames(self) -> None:
    # ... existing frame creation (sidebar_frame, pipeline_frame, preview_frame, status_frame)

    # Panels
    self.sidebar_panel = SidebarPanelV2(
        self.sidebar_frame,
        app_state=self.app_state,
        packs_controller=self.packs_controller,
    )

    self.pipeline_panel = PipelinePanelV2(
        self.pipeline_frame,
        app_state=self.app_state,
        pipeline_controller=self.pipeline_controller,
    )

    self.preview_panel = PreviewPanelV2(
        self.preview_frame,
        app_state=self.app_state,
        pipeline_controller=self.pipeline_controller,
    )

    self.status_bar = StatusBarV2(self.status_frame, app_state=self.app_state)

    self.webui_controls = WebUIControlsPanel(
        master=self.status_frame,
        webui_manager=self.webui_manager,
    )
```

And in `_compose_layout()`:

```python
self.sidebar_panel.pack(fill="both", expand=True)
self.pipeline_panel.pack(fill="both", expand=True)
self.preview_panel.pack(fill="both", expand=True)

self.status_bar.pack(side="left", fill="x", expand=True)
self.webui_controls.pack(side="right")
```

CODEX should adapt parameter names to match actual panel constructors.

### Step 4 — Wire Header Toolbar Buttons

In `MainWindowV2`, the header toolbar row contains buttons like:

- Load Pack  
- Edit Pack  
- Run  
- Stop  
- Preview  
- Settings  
- Help  

Each should call appropriate controller methods and update `AppStateV2` and/or panels. For example:

```python
def _wire_toolbar(self) -> None:
    self.load_pack_button.config(command=self._on_load_pack_clicked)
    self.edit_pack_button.config(command=self._on_edit_pack_clicked)
    self.run_button.config(command=self._on_run_clicked)
    self.stop_button.config(command=self._on_stop_clicked)
    self.preview_button.config(command=self._on_preview_clicked)
    self.settings_button.config(command=self._on_settings_clicked)
    self.help_button.config(command=self._on_help_clicked)

def _on_load_pack_clicked(self) -> None:
    pack_name = self.packs_controller.prompt_and_load_pack(self.root)
    if pack_name is not None:
        self.app_state.set_current_pack(pack_name)
        self.app_state.set_status_text(f"Loaded pack: {pack_name}")

def _on_edit_pack_clicked(self) -> None:
    self.packs_controller.open_pack_editor(self.root)

def _on_run_clicked(self) -> None:
    self.app_state.set_running(True)
    self.app_state.set_status_text("Running pipeline...")
    self.pipeline_controller.start_run()  # or app_controller.start_run()

def _on_stop_clicked(self) -> None:
    self.pipeline_controller.stop_run()
    self.app_state.set_running(False)
    self.app_state.set_status_text("Stopped.")

def _on_preview_clicked(self) -> None:
    self.pipeline_controller.preview_run()
    self.app_state.set_status_text("Preview complete.")

def _on_settings_clicked(self) -> None:
    self.app_controller.open_settings_dialog(self.root)

def _on_help_clicked(self) -> None:
    self.app_controller.open_help_page()
```

These are examples; CODEX must map them to the actual controller API (e.g., `app_controller.load_pack_from_dialog`, `pipeline_controller.run_active_pipeline`, etc.).

### Step 5 — Connect Status Bar to AppState & Controllers

`StatusBarV2` should reflect:

- `AppStateV2.status_text`  
- API/WebUI status (online, offline, last error)  
- Possibly current pack name and pipeline activity

Implementation sketch:

In `StatusBarV2.__init__`:

```python
def __init__(self, master, app_state: AppStateV2, **kwargs):
    super().__init__(master, **kwargs)
    self.app_state = app_state

    self.status_label = ttk.Label(self, style="StatusBar.TLabel", text="Idle")
    self.status_label.pack(side="left", padx=4)

    # subscribe to state
    self.app_state.subscribe("status_text", self._on_status_changed)
    self._on_status_changed()
```

In `_on_status_changed`:

```python
def _on_status_changed(self) -> None:
    self.status_label.config(text=self.app_state.status_text)
```

`MainWindowV2` (or controllers) should call `app_state.set_status_text(...)` when significant events occur (start/stop, load pack, error, etc.).

For WebUI status, you can either:

- Have `WebUIProcessManager` push updates to `AppStateV2` via callbacks, or  
- Have a simple periodic poll in `MainWindowV2` that updates a secondary label.

This PR can be minimal: set status to “WebUI: running” / “WebUI: stopped” when start/stop succeeds or fails.

### Step 6 — Hook Preview Panel to Job / Output Adapters

`PreviewPanelV2` should be connected to whatever adapter is already in place for job history / output.

- If there is a `JobHistoryAdapterV2` or similar, pass it into the panel at construction.  
- If the pipeline controller already emits events upon job completion, subscribe there and call a method on the preview panel (e.g., `preview_panel.show_result(job)` or `preview_panel.refresh_history()`).

The exact wiring will depend on your existing adapter design. The primary requirement of this PR is that **successful runs update the preview/history view** in the V2 GUI, mimicking the older main window behavior.

### Step 7 — Ensure Tests Still Pass (and Extend as Needed)

- Update any tests that instantiate the GUI to use the new constructor signature (with controllers).  
- Where tests only need a dummy controller, provide a simple stub object with the methods used by the GUI (e.g., `start_run`, `stop_run`).

Add or extend tests under `tests/gui_v2`:

- A smoke test that constructs `MainWindowV2` with mocked controllers and asserts that:
  - Sidebar/pipeline/preview/status widgets are created.  
  - Toolbar buttons are wired (their `command` attribute is non-null).

No behavioral tests are required yet, but they’re encouraged if easy.

---

## Files Expected to Change / Be Added

**Updated:**

- `src/gui/app_state_v2.py`
  - New fields: `current_pack`, `is_running`, `status_text`, `last_error`.
  - New setter methods with notifications.

- `src/gui/main_window_v2.py`
  - Constructor now accepts controllers.  
  - `_build_frames` creates real V2 panels.  
  - `_compose_layout` packs those panels and status bar + WebUI controls.  
  - `_wire_toolbar` binds buttons to controller methods and updates `AppStateV2`.  
  - Optional: `_wire_status_updates` to link controller events to `AppStateV2`.

- `src/main.py`
  - Builds controllers and passes them into `MainWindowV2` / `run_app_v2` instead of using the older main window interface.

- `src/gui/status_bar_v2.py`
  - Listens to `AppStateV2` and displays status text.

- `src/gui/sidebar_panel_v2.py`, `src/gui/pipeline_panel_v2.py`, `src/gui/preview_panel_v2.py`
  - Accept controller references and/or `AppStateV2` if not already.

**No new files** are strictly necessary, but small helper classes for stubbing controllers in tests are acceptable.

---

## Tests & Validation

### Manual

1. Launch the app (`python -m src.main`).  
2. Confirm:
   - Load Pack opens a dialog and loads packs into the sidebar list.  
   - Selecting a pack updates the UI appropriately.  
   - Run starts a pipeline run; status bar shows “Running…” and later “Idle” or “Completed”.  
   - Stop cancels or stops the run.  
   - Preview performs a non-destructive preview (if supported).  
   - Status bar text changes according to actions.  
   - Preview panel shows new output/history entries when runs complete.

### Automated

- Run existing tests:

  ```bash
  pytest tests/controller -v
  pytest tests/gui_v2 -v
  ```

- Update or add GUI tests to ensure `MainWindowV2` can be instantiated with stub controllers and that the layout/panels are created without error.

---

## Acceptance Criteria

- V2 GUI is no longer a shell: core flows (load pack, run, stop, preview) work end-to-end through `MainWindowV2`.  
- V2 panels (`SidebarPanelV2`, `PipelinePanelV2`, `PreviewPanelV2`, `StatusBarV2`) are visibly present and populated.  
- Status bar reflects high-level application state via `AppStateV2`.  
- WebUI controls (from PR-00A) are still functional and visible.  
- All existing controller and GUI V2 tests pass after adaptations.
