# StableNew GUI v2 Status – 2025-11-19

This document captures the current state of the **StableNew v2 GUI** as of 2025-11-19, based on the `StableNew-MoreSafe` snapshot plus PR-0, PR-0.1, PR-GUI-01, and the first LeftZone wiring.

It’s meant as a quick architectural snapshot you can drop into `docs/gui/` to keep Codex and humans aligned.

---

## 1. Runtime Path

**Entrypoint:** `src/main.py`

- Sets up logging and single-instance lock (unchanged behavior).
- Creates a Tk root and launches the **v2 GUI stack**:
  - `MainWindow` from `src.gui.main_window_v2`
  - `AppController` from `src.controller.app_controller` with `threaded=True`
- Uses a **DummyPipelineRunner** / stub pipeline runner for now.

Behavior confirmed from runtime logs:

- Run button triggers:
  - `[controller] Run clicked – gathering config (stub).`
  - `[pipeline] DummyPipelineRunner starting (stub).`
  - Three stub “working” steps.
  - `[controller] Pipeline completed successfully (stub).`
- Hitting Run a second time behaves identically with **no GUI hang**.

**Legacy GUI (`StableNewGUI`, `src/gui/main_window.py`)** is still present in the repo but is **no longer used** by `src/main.py`.

---

## 2. Visual Snapshot (what the window looks like)

The current v2 GUI window (as of the screenshot on 2025-11-19):

- Opens as a **narrow, relatively short** window centered on the screen.
- Background is a dark neutral (theme-based).
- Top header bar has:
  - Left-aligned app icon & title (“StableNew” via window decoration).
  - Buttons: **Run**, **Stop**, **Preview**, **Settings**, **Help**.

- Left side has a stacked “card” containing:
  - `Load Pack` button.
  - `Edit Pack` button.
  - A blank list area (planned Pack list placeholder).
  - A `Preset` label above a combobox.

- Bottom area has:
  - `Status: Idle` line.
  - `API: Unknown` line.
  - A dark log panel showing controller stub messages (e.g., “Load Pack clicked (stub)”, “Edit Pack clicked (stub)”, etc.).

The UI is structurally simple but now **theme-coherent** and clearly separated into zones.

---

## 3. Zone-by-Zone Status

### 3.1 Header Zone

**What exists now**

- Buttons:
  - **Run** – styled via `Primary.TButton` (gold/yellow background, black text).
  - **Stop** – styled via `Danger.TButton` (red background).
  - **Preview**, **Settings**, **Help** – styled via `Ghost.TButton` (dark surface background, lighter hover state).

- All buttons are wired into `AppController` callback methods (Run/Stop/Preview/Settings/Help).

**Status**

- Functionally correct – actions hit the v2 controller with stubbed behavior.
- Visually much improved vs stock Tk; ghost buttons look like real controls, though they remain deliberately lower emphasis than Run/Stop.

### 3.2 Left Zone (Packs / Presets)

**What exists now**

- A LeftZone “card” frame that contains:
  - `Load Pack` / `Edit Pack` buttons.
  - An empty list area (pack list placeholder).
  - A `Preset` label above a combobox.

- Clicking `Load Pack` / `Edit Pack` logs stub messages:
  - `[controller] Load Pack clicked (stub).`
  - `[controller] Edit Pack clicked (stub).`

**Status**

- Layout issues from earlier (label overlapping combobox) have been corrected; the Preset row is now clean.
- Functional behavior for packs/presets is still **stubbed**; no real pack loading logic has been ported from the legacy GUI yet.
- This card is ready to host the future **Packs/Presets Panel** once it’s migrated from legacy code.

### 3.3 Center Zone (Config / Randomizer)

**Intended (per Architecture_v2 and GUI layout docs)**

- Model / VAE / Checkpoint selection.
- Sampler + Scheduler controls.
- Resolution/steps/CFG sliders or inputs.
- Randomizer controls and advanced toggles.

**Current state**

- Center Zone is present as a structural area but is effectively **empty or skeletal** in the running GUI.
- No live controls for model/sampler/config have been ported; they remain in the legacy GUI and in pipeline configuration code.

### 3.4 Right Zone (Preview / Output)

**Intended**

- Image preview area for the last generation.
- Possibly matrix preview and/or a scrollable list of thumbnails.

**Current state**

- Right Zone is essentially a placeholder; no active preview panel is wired in yet.
- All preview/thumbnail behavior still lives in the legacy world or is not yet implemented.

### 3.5 Bottom Zone (Status Bar & Log)

**What exists now**

- Status bar labels:
  - `Status: Idle` – main status line using `StatusStrong.TLabel` style.
  - `API: Unknown` – secondary status line using `Status.TLabel` (muted gray).

- Below the status bar is a log panel:
  - Dark surface background.
  - Displays controller and pipeline stub log messages.

**Status**

- Functionally correct; status text updates and the log shows controller activity.
- The visual hierarchy (strong vs muted label) is now more aligned with the design:
  - `Status:` is readable but not overpowering.
  - `API:` reads as secondary information.

---

## 4. Theme & Window Behavior

- Theme is centralized in `src/gui/theme.py`:
  - Defines color tokens (background, surface, accent, danger, text, muted text, subtle borders).
  - Spacing tokens (XS–LG) for consistent paddings.
  - Ttk styles for buttons and labels (`Primary.TButton`, `Danger.TButton`, `Ghost.TButton`, `Status.TLabel`, `StatusStrong.TLabel`).

- The window currently opens at a modest default size:
  - Width and height are enough to show header, LeftZone card, status bar, and log.
  - It’s visually “narrow and short” compared to a full desktop, but it is resizable.

Future improvements may include:
- Slightly larger default size aligned with Figma layout.
- Smarter min-size/resize rules once Center/Right panels exist.

---

## 5. Legacy vs v2 GUI – Practical View

- **Legacy GUI**:
  - Features: more surface controls (packs + full config + misc options).
  - Problems: brittle wiring, hangs, and entangled responsibilities.

- **v2 GUI**:
  - Features: fewer visible controls right now, but:
    - Clean separation of GUI/controller/pipeline.
    - Centralized theming.
    - Proven non-hanging controller/threading.
  - This is the **active runtime path** used by `python -m src.main`.

You have consciously accepted a **minimal but structurally correct** interface as the base to rebuild from, instead of trying to patch the legacy GUI.

---

## 6. Recommended Next Steps (GUI-focused)

With v2 runtime stable and themed, the priority GUI tasks are:

1. **Finish Packs/Presets Panel in LeftZone**
   - Port real pack loading/editing logic from legacy GUI into a new, dedicated module or service.
   - Bind LeftZone buttons and list/combobox to that logic.

2. **Introduce a minimal Config Panel in Center Zone**
   - Start with core SDXL configuration (model, sampler, resolution, steps).
   - Defer randomizer/advanced options to later PRs.

3. **Add a simple Preview Panel in Right Zone**
   - Display at least the last generated image.
   - Expand to matrix/thumbnail view later.

4. **Polish Window Sizing & Resizing**
   - Once the three main zones (Left/Center/Right) are populated, adjust default geometry and `row/columnconfigure` weights for a better out-of-the-box layout.

Each of these should be handled as its own PR, following the existing pattern:

- One concern per PR.
- Clear Allowed/Forbidden files.
- Tests (where applicable) before behavior changes.
- No mixing GUI refactors with pipeline changes.
