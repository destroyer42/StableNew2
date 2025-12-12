Codex Execution Guide for PR-GUI-01: Theme Foundations
======================================================

Purpose
-------
You are implementing PR-GUI-01, which introduces a centralized Tk/Ttk theme for the v2 GUI (`MainWindow_v2`) and applies it to the header and status bar.

Your mission:
- Create `src/gui/theme.py` with theme tokens and ttk style configuration.
- Update `src/gui/main_window_v2.py` to initialize and use these styles.
- Do NOT change behavior or logic, only visuals.

High-level Rules
----------------
1. Only touch:
   - `src/gui/theme.py` (new)
   - `src/gui/main_window_v2.py` (minimal edits)
2. Do not modify controller, pipeline, or API modules.
3. Do not change button commands or controller wiring.
4. Keep the diff as small and self-contained as possible.

Step-by-step Instructions
-------------------------

Step 1 – Read the PR spec
- Open `PR-GUI-01_Theme_Foundations.md`.
- Understand the responsibilities of `theme.py` and how `MainWindow_v2` should consume it.

Step 2 – Create `src/gui/theme.py`
- Implement theme tokens:
  - Color constants like `COLOR_BG`, `COLOR_SURFACE`, `COLOR_ACCENT`, `COLOR_ACCENT_DANGER`, `COLOR_TEXT`, `COLOR_TEXT_MUTED`, `COLOR_BORDER_SUBTLE`.
  - Spacing constants like `PADDING_XS`, `PADDING_SM`, `PADDING_MD`, `PADDING_LG`.
  - Optional font family constants for base and mono fonts.
- Implement a function:

  ```python
  def configure_style(root: tk.Tk) -> ttk.Style:
      ...
  ```

  that:
  - Creates a `ttk.Style` bound to `root`.
  - Uses a sensible base theme (e.g., `"clam"`).
  - Configures styles:
    - `"Primary.TButton"` (for Run)
    - `"Danger.TButton"` (for Stop)
    - `"Ghost.TButton"` (for Preview/Settings/Help)
    - `"Status.TLabel"` and `"StatusStrong.TLabel"`
  - Sets the root background to `COLOR_BG`.
  - Returns the `Style` instance.

Step 3 – Wire theme into `MainWindow_v2`
- In `src/gui/main_window_v2.py`, import the theme module:

  ```python
  from . import theme
  ```

  or an equivalent relative import consistent with the existing package structure.

- In the `MainWindow` initializer (or wherever the Tk root is first available), call:

  ```python
  self.style = theme.configure_style(self.root)
  ```

  where `self.root` is the Tk master.

- Ensure that the main containers (e.g., top-level frame) use theme background colors instead of hard-coded values, when reasonable.

Step 4 – Apply styles to header buttons
- Locate the header zone in `MainWindow_v2` (or its sub-class).
- Ensure header buttons are `ttk.Button` (convert from `tk.Button` if needed).
- Assign styles:
  - Run button: `style="Primary.TButton"`
  - Stop button: `style="Danger.TButton"`
  - Preview, Settings, Help: `style="Ghost.TButton"`

- Do not alter their `.configure(command=...)` wiring; commands must still point to AppController methods.

Step 5 – Apply styles to bottom/status labels
- Locate the bottom/status zone (e.g., a frame containing `status_label`, `api_status_label`).
- Use `ttk.Label` for these labels.
- Assign styles:
  - Status label: `style="StatusStrong.TLabel"` (for main status text).
  - API label: `style="Status.TLabel"` (muted text).

Step 6 – Ensure frames respect theme colors
- For the main containers (e.g., header frame, bottom frame), set their `background` to `theme.COLOR_BG` or `theme.COLOR_SURFACE` as appropriate.
- Avoid introducing new hard-coded color literals; reuse theme constants.

Step 7 – Run tests
- Run the existing controller tests to make sure nothing broke logically:

  ```bash
  pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v
  ```

- Show the full output.

Step 8 – Manual visual check (human task)
- Inform the human that implementation is complete and suggest:

  - Run `python -m src.main`.
  - Confirm that:
    - Run/Stop/Preview/Settings/Help buttons use new styles.
    - Status bar uses new label styles.
    - Behavior (clicking Run/Stop) is unchanged.

What You Must NOT Do
--------------------
- Do not modify:
  - Any controller modules (e.g., `src/controller/app_controller.py`).
  - Any pipeline modules (`src/pipeline/*`).
  - Any API modules (`src/api/*`).
  - Any test files.
  - `src/main.py`.
- Do not:
  - Change the text or commands of buttons.
  - Add new UI widgets.
  - Introduce new packages or dependencies.

Completion Checklist
--------------------
You are done when:

- `src/gui/theme.py` exists and configures a coherent dark-ish theme with named ttk styles.
- `MainWindow_v2` calls into `theme.configure_style(...)` and uses the named styles on header buttons and status labels.
- All existing tests remain green.
- The human confirms that the GUI looks more modern in the header and status bar, and that behavior is unchanged.
