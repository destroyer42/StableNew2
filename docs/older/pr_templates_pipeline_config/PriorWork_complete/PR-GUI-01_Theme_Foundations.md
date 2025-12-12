PR-GUI-01: Theme Foundations for MainWindow_v2
==============================================

1. Title
--------
Introduce a modern Tk/Ttk theme layer and apply it to the v2 GUI header and status bar (PR-GUI-01: Theme Foundations).

2. Summary
----------
StableNew V2 has successfully moved its runtime entrypoint to the Architecture_v2 GUI/controller stack (MainWindow_v2 + AppController). However, the current v2 GUI is intentionally bare-bones and visually dated.

This PR introduces a **centralized theme module** for Tk/Ttk and applies it to the **HeaderZone** and **BottomZone** of `MainWindow_v2`. It lays the foundation for a modern, consistent UI without changing functionality:

- Define color, spacing, and font tokens in a dedicated `theme.py` module.
- Configure a `ttk.Style` instance with named styles (e.g., `Primary.TButton`, `Danger.TButton`, `Status.TLabel`).
- Apply these styles to:
  - Run / Stop / Preview / Settings / Help buttons in the header.
  - Status and API labels in the bottom/status zone.
- Keep behavior 100% unchanged; this is **visual-only**, with minimal and reversible changes.

3. Problem Statement
--------------------
Right now:

- `MainWindow_v2` presents a skeleton layout with default Tk/Ttk styling.
- The previous legacy GUI looked cluttered and dated; we do not want to carry that forward.
- Architecture_v2 mandates Tk/Ttk, but does **not** mandate a dated look.

We need a **centralized theming strategy** so that:

- The GUI can look modern and cohesive.
- Future panels (Packs, Config, Matrix, Preview) can plug into the same theme tokens.
- Visual changes can be made in one place (`theme.py`) instead of scattered inline options.

4. Goals
--------
- Add a theme module that encapsulates:
  - Color palette (dark-ish, with a clear primary/secondary/neutral scheme).
  - Spacing constants (for paddings/margins).
  - Typography choices (heading vs body fonts).
  - Named ttk styles for:
    - Primary buttons (Run).
    - Danger buttons (Stop).
    - Secondary/ghost buttons (Preview, Settings, Help).
    - Status bar labels.
- Wire `MainWindow_v2` to initialize and use this theme:
  - At startup, call `theme.configure_style(root)` or equivalent.
  - Apply appropriate styles to existing header and bottom widgets.
- Do *not* change any pipeline logic, controller logic, or widget behavior.

5. Non-goals
------------
- No layout redesign of the entire GUI.
- No addition or removal of widgets.
- No new panels or zones beyond what `MainWindow_v2` already defines.
- No changes to controller or pipeline code.
- No new dependencies outside the standard library (Tk/Ttk).

6. Allowed Files
----------------
This PR may modify or create only the following files:

- `src/gui/theme.py` (new)
- `src/gui/main_window_v2.py` (minimal adjustments to hook up and use the theme)

7. Forbidden Files
------------------
Do **not** modify any of the following in this PR:

- Any files under `src/controller/`
- Any files under `src/pipeline/`
- Any files under `src/api/`
- Any tests
- `src/main.py`
- Any legacy GUI modules (e.g., `src/gui/main_window.py`)

If a change to any forbidden file seems necessary, STOP and request a new PR design instead of expanding PR-GUI-01.

8. Step-by-step Implementation Plan
-----------------------------------

### Step 1 – Create `src/gui/theme.py`
Create a new module with:

- **Color tokens** (constants), for example:

  - `COLOR_BG = "#18181b"`  (window background)
  - `COLOR_SURFACE = "#27272f"`
  - `COLOR_ACCENT = "#facc15"` (primary accent, e.g., ASWF gold-like)
  - `COLOR_ACCENT_DANGER = "#ef4444"`
  - `COLOR_TEXT = "#f9fafb"`
  - `COLOR_TEXT_MUTED = "#9ca3af"`
  - `COLOR_BORDER_SUBTLE = "#3f3f46"`

- **Spacing tokens:**

  - `PADDING_XS = 2`
  - `PADDING_SM = 4`
  - `PADDING_MD = 8`
  - `PADDING_LG = 12`

- **Font names:**

  - `FONT_FAMILY_BASE = "Segoe UI"` (or similar cross-platform sans)
  - `FONT_FAMILY_MONO = "Consolas"` or `"Courier New"`

- A function to configure the theme, for example:

  ```python
  import tkinter as tk
  from tkinter import ttk

  def configure_style(root: tk.Tk) -> ttk.Style:
      style = ttk.Style(root)
      # Set overall theme base (using 'clam' or 'alt')
      style.theme_use("clam")

      # Configure global settings
      root.configure(bg=COLOR_BG)

      # Button styles
      style.configure(
          "Primary.TButton",
          padding=(PADDING_MD, PADDING_SM),
          background=COLOR_ACCENT,
          foreground="#000000",
          borderwidth=0,
          focusthickness=0,
      )
      style.map(
          "Primary.TButton",
          background=[("active", "#fde047")],
      )

      style.configure(
          "Danger.TButton",
          padding=(PADDING_MD, PADDING_SM),
          background=COLOR_ACCENT_DANGER,
          foreground="#000000",
          borderwidth=0,
          focusthickness=0,
      )
      style.map(
          "Danger.TButton",
          background=[("active", "#f97373")],
      )

      style.configure(
          "Ghost.TButton",
          padding=(PADDING_MD, PADDING_SM),
          background=COLOR_SURFACE,
          foreground=COLOR_TEXT,
          borderwidth=0,
      )
      style.map(
          "Ghost.TButton",
          background=[("active", "#3f3f46")],
      )

      # Status labels
      style.configure(
          "Status.TLabel",
          background=COLOR_BG,
          foreground=COLOR_TEXT_MUTED,
      )

      style.configure(
          "StatusStrong.TLabel",
          background=COLOR_BG,
          foreground=COLOR_TEXT,
      )

      return style
  ```

This is a template; the actual code Codex writes should follow these ideas but can tweak specifics as long as the responsibilities remain the same.

### Step 2 – Wire theme initialization into `MainWindow_v2`
In `src/gui/main_window_v2.py`:

- Import the theme module at the top:

  - `from src.gui import theme`  
    or
  - `from . import theme`

- In the `MainWindow` initialisation (e.g., in `__init__`), after creating the root window and before building child widgets:

  - Call `theme.configure_style(root)` (where `root` is the Tk master).

- Ensure that the main window background uses `theme.COLOR_BG` (or equivalent), e.g.:

  - `self.root.configure(bg=theme.COLOR_BG)`

### Step 3 – Apply styles to HeaderZone buttons
Where the header buttons are created in `MainWindow_v2` (or its header zone class), update them to be ttk Buttons with named styles:

- Run button:
  - Use `"Primary.TButton"`
- Stop button:
  - Use `"Danger.TButton"`
- Preview / Settings / Help buttons:
  - Use `"Ghost.TButton"`

For example (conceptual):

```python
self.run_button = ttk.Button(header_frame, text="Run", style="Primary.TButton")
self.stop_button = ttk.Button(header_frame, text="Stop", style="Danger.TButton")
self.preview_button = ttk.Button(header_frame, text="Preview", style="Ghost.TButton")
self.settings_button = ttk.Button(header_frame, text="Settings", style="Ghost.TButton")
self.help_button = ttk.Button(header_frame, text="Help", style="Ghost.TButton")
```

Do not change their command callbacks; wiring to `AppController` remains as-is.

### Step 4 – Apply styles to BottomZone status labels
In the bottom/status zone of `MainWindow_v2`:

- Identify labels used for status and API connection text (e.g., `status_label`, `api_status_label`).
- Convert them to `ttk.Label` if they are not already.
- Apply appropriate styles:

  - Status text: `"Status.TLabel"` or `"StatusStrong.TLabel"`
  - API status: also `"Status.TLabel"` unless you want a stronger emphasis.

Example:

```python
self.status_label = ttk.Label(bottom_frame, text="Status: Idle", style="StatusStrong.TLabel")
self.api_status_label = ttk.Label(bottom_frame, text="API: Unknown", style="Status.TLabel")
```

### Step 5 – Ensure background frames use theme colors
For `MainWindow_v2` container frames (header, left, center, right, bottom):

- Ensure their background color aligns with theme:

  - `frame.configure(bg=theme.COLOR_BG)`
  - or `bg=theme.COLOR_SURFACE` for inner surfaces.

Avoid hard-coded color literals; route everything through `theme.py`.

### Step 6 – Manual visual smoke test
After implementing the theme:

1. Run `python -m src.main` to launch StableNew.
2. Confirm visually that:
   - The overall background uses the new dark-ish theme.
   - Run is a primary/bright button.
   - Stop is a danger-colored button.
   - Other header buttons use the ghost style.
   - Status bar looks cohesive with the rest of the window.
3. Press Run / Stop to ensure styling does not affect behavior.

No automated tests are required for this PR; it is strictly visual, and existing tests for controller and pipeline should remain unaffected.

9. Required Tests
-----------------
No new tests are required for PR-GUI-01, provided that:

- Existing tests continue to pass, especially:
  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`

This PR must not break any test.

10. Acceptance Criteria
-----------------------
PR-GUI-01 is accepted when:

- `src/gui/theme.py` exists and encapsulates theme tokens + ttk style configuration.
- `MainWindow_v2` uses the theme module to configure Ttk styles at startup.
- Header buttons and bottom status labels visibly reflect the new theme.
- No controller, pipeline, or behavior logic changed.
- All pre-existing tests pass without modification.

11. Rollback Plan
-----------------
To revert PR-GUI-01:

- Remove `src/gui/theme.py`.
- Restore prior version of `src/gui/main_window_v2.py` from git history.
- Since this PR does not change behavior, rollback is purely visual and code-level.

12. Codex Execution Constraints
-------------------------------
For Codex (implementer):

- Do **not** modify any files outside `src/gui/theme.py` and `src/gui/main_window_v2.py`.
- Do **not** add or touch any controller, pipeline, or API code.
- Do **not** alter widget commands or AppController wiring.
- Do **not** introduce new dependencies beyond Tk/Ttk.
- Keep the diff as small and focused as possible; this PR is about theming foundations only.

13. Smoke Test Checklist
------------------------
After implementation, the human or implementer should:

1. Run existing tests (at least controller tests) to verify nothing broke.
2. Launch StableNew via `python -m src.main`.
3. Visually confirm the new theme in the header and status bar.
4. Click Run and Stop to ensure styling did not affect functionality.
