# StableNew GUI Overview

The StableNew GUI is a Tkinter-based application using a dark ASWF theme.

## 1. Architecture Overview

`StableNewGUI` (in `src/gui/main_window.py`) orchestrates:

- Theme (e.g., `src/gui/theme.py`)
- `PromptPackPanel`
- `PipelineControlsPanel`
- Randomization panel
- Advanced Prompt Editor
- Log panel
- Mediators for pack selection and configuration context

## 2. Theming Rules

- All colors should come from `src/gui/theme.py`.
- No hard-coded color constants elsewhere in the GUI.
- ASWF blacks and greys are used for backgrounds.
- ASWF gold is used for high-contrast text and accents.
- Buttons:
  - Primary: gold or green on dark background.
  - Danger: red on dark background (e.g., Stop, Exit).

## 3. Layout Rules

- Every tab must have consistent padding and background.
- Controls should be arranged with:
  - Reasonable padding (4–8 px).
  - Grid/pack weight so resizing works sensibly.
- Scrollbars are required for:
  - Randomization panel.
  - Advanced prompt editor.
  - Any panel that can overflow the window height.

- Prefer multiline wrapping over horizontal scrolling when possible.

## 4. Behavior Constraints

- Never block the Tk main thread with long-running operations.
- Configuration loads should be explicit (e.g., via buttons), not surprising side effects.
- Selecting packs should NOT silently modify editor state unless explicitly designed.
- Warn users about unsaved changes before discarding or overwriting configs.

## 5. Resilience

- Keep the GUI resilient to crashes:
  - Maintain recent log lines for post-crash inspection.
  - Include startup checks that can detect unclean shutdowns and trigger clean-up.
- Make it clear to the user when the pipeline is running vs idle.
