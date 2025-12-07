PR-041-THEME-V2-DESIGN-TOKENS-UNIFICATION-V2-P1

Centralize dark-mode theming via theme_v2.py and enforce V2-wide style usage

1. Title

PR-041-THEME-V2-DESIGN-TOKENS-UNIFICATION-V2-P1 – Centralize Dark Theme & Styles for V2 GUI

2. Summary

This PR makes src/gui/theme_v2.py the single source of truth for V2 styling:

Introduces semantic design tokens (surface background, card background, card border, body text, muted text, primary button, etc.).

Defines a small set of canonical style names (SURFACE_FRAME_STYLE, CARD_FRAME_STYLE, BODY_LABEL_STYLE, etc.).

Updates V2 GUI components to use those styles instead of hard-coded colors or default widget styles.

After this PR:

Changing a single variable (e.g., CARD_BORDER_COLOR = "#FFFFFF") updates the entire app’s frames that use the Card.TFrame style.

Global tweaks like “thin white border around all cards” or “switch to a different dark background” happen in one file (theme_v2.py) instead of dozens of panels.

3. Problem Statement

Current situation:

theme_v2.py already defines a dark palette and several ttk styles (Panel.TFrame, Card.TFrame, Dark.TLabel, etc.), and apply_theme(root) is available.

Some V2 components use these styles correctly (e.g., _SidebarCard uses Dark.TLabel and Panel.TFrame).

However, many V2 GUI modules still:

Use default TFrame / TLabel with no explicit style, or

Use hard-coded bg="#...", fg="#..." colors, or

Import raw palette constants (BACKGROUND_ELEVATED, TEXT_PRIMARY) and apply them directly per widget.

Consequences:

Changing dark-mode colors or borders requires touching multiple files, not just theme_v2.

Styles are not consistently applied, so:

Some panels look “on theme”, others don’t.

It’s difficult to do global visual updates (e.g., “thin white border around all cards”) without hunting through the codebase.

Copilot/Codex tend to introduce more ad-hoc styling because there is no enforced pattern to use centralized tokens + style names.

We need a focused PR that:

Locks in a small, consistent set of design tokens and style names in theme_v2.py.

Updates V2 GUI to use those rather than ad-hoc styling.

4. Goals

Theme tokens & style aliases in one place

Add semantic tokens in theme_v2.py for:

Surface background, card background, borders, text colors.

Fonts and base sizes.

Add exported style name constants for:

Surface frames, card frames.

Body labels, muted labels.

Primary/secondary buttons.

V2 GUI uses centralized styles

All V2 GUI panels should:

Use ttk.* widgets where possible.

Set style=... using constants from theme_v2 (e.g., CARD_FRAME_STYLE, BODY_LABEL_STYLE).

No new ad-hoc color literals (e.g., bg="#000000") in V2.

Global visual changes are one-file edits

Example: if we decide “put a thin white border around all card frames,” it should be:

A change to CARD_BORDER_COLOR / FRAME_BORDER_WIDTH_DEFAULT in theme_v2.py.

No changes to individual panels.

Preserve behavior, minimize layout disruption

This is a styling-only PR; no functional logic changes.

Existing layout (geometry managers, grid/pack structures) should remain intact.

5. Non-goals

Adding a full light/dark theme switcher or runtime theme toggling.

Redesigning layout or UX structures of tabs/panels.

Converting every remaining legacy/V1 component — scope is V2 GUI only.

Changing the text content of labels, tooltips, or button text (unless necessary for style naming/tests).

Introducing new widgets or rearranging existing containers.

6. Allowed Files

This PR is limited to V2 GUI theming and tests. Codex may modify:

Theme & core GUI entrypoints

src/gui/theme_v2.py

src/gui/main_window_v2.py

Only for:

Ensuring apply_theme(root) is called exactly once.

Replacing ad-hoc colors with style usage where trivial and safe.

V2 GUI panels / views (styling only)

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py (if present)

src/gui/panels_v2/sidebar_panel_v2.py

src/gui/panels_v2/pipeline_config_panel_v2.py

src/gui/panels_v2/status_bar_v2.py

src/gui/panels_v2/preview_panel_v2.py

src/gui/panels_v2/log_trace_panel_v2.py

Any other src/gui/panels_v2/*_v2.py files that:

Are clearly V2 components, and

Currently use hard-coded colors or default TFrame / TLabel where we want theme consistency.

Tests

tests/gui_v2/test_theme_v2.py (new or updated)

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py (only if assertions depend on style names)

7. Forbidden Files

Do not modify:

Pipeline / backend / API

src/pipeline/*

src/api/*

src/controller/app_controller.py

src/controller/webui_connection_controller.py

Non-V2 / legacy GUI

src/gui/main_window.py

src/gui/theme.py

Any *_v1.py or non-V2 GUI file.

Learning / queue / cluster systems

src/learning/*

src/queue/*

src/cluster/*

CI, build scripts, and config files.

If a required style change appears to require touching a forbidden file, stop and report instead of editing.

8. Step-by-step Implementation
Step 1 – Harden design tokens & style aliases in theme_v2.py

Add semantic tokens at the top of theme_v2.py, mapping to your existing palette:

# Semantic design tokens for V2 GUI
SURFACE_BG = BACKGROUND_DARK
CARD_BG = BACKGROUND_ELEVATED

CARD_BORDER_COLOR = BORDER_SUBTLE
CARD_BORDER_WIDTH = 1

BODY_TEXT_COLOR = TEXT_PRIMARY
MUTED_TEXT_COLOR = TEXT_MUTED
DISABLED_TEXT_COLOR = TEXT_DISABLED

PRIMARY_ACCENT_COLOR = ACCENT_GOLD
PRIMARY_ACCENT_HOVER = ACCENT_GOLD_HOVER


Define style name constants for re-use across all GUI components:

# Canonical style names
SURFACE_FRAME_STYLE = "Surface.TFrame"
CARD_FRAME_STYLE = "Card.TFrame"
BODY_LABEL_STYLE = "Body.TLabel"
MUTED_LABEL_STYLE = "Muted.TLabel"
PRIMARY_BUTTON_STYLE = "Primary.TButton"
SECONDARY_BUTTON_STYLE = "Secondary.TButton"


Update _configure_*_styles to use tokens and populate those style names:

Frames:

style.configure(
    SURFACE_FRAME_STYLE,
    background=SURFACE_BG,
)
style.configure(
    CARD_FRAME_STYLE,
    background=CARD_BG,
    borderwidth=CARD_BORDER_WIDTH,
    relief="solid",
    bordercolor=CARD_BORDER_COLOR,
)


Labels:

style.configure(
    BODY_LABEL_STYLE,
    foreground=BODY_TEXT_COLOR,
    background=SURFACE_BG,
)
style.configure(
    MUTED_LABEL_STYLE,
    foreground=MUTED_TEXT_COLOR,
    background=SURFACE_BG,
)


Buttons:

style.configure(
    PRIMARY_BUTTON_STYLE,
    background=PRIMARY_ACCENT_COLOR,
    foreground=BODY_TEXT_COLOR,
)
# etc., ensuring ttk theme supports these attributes


Ensure apply_theme(root):

Still sets base fonts/global options.

Still sets root.configure(bg=SURFACE_BG) or equivalent.

Step 2 – Ensure apply_theme is applied once in main_window_v2.py

Confirm that MainWindowV2 (or the bootstrap) calls:

from src.gui.theme_v2 import apply_theme

root = tk.Tk()
apply_theme(root)


Remove any redundant or conflicting manual root.configure(bg="#...") calls that duplicate what apply_theme already does, unless they align with SURFACE_BG.

Step 3 – Adopt style constants in V2 panels

For each allowed V2 GUI file:

Import style constants from theme_v2.py:

from src.gui.theme_v2 import (
    CARD_FRAME_STYLE,
    SURFACE_FRAME_STYLE,
    BODY_LABEL_STYLE,
    MUTED_LABEL_STYLE,
    PRIMARY_BUTTON_STYLE,
)


Replace default frames with styled frames:

Before:

self.card = ttk.Frame(parent, padding=8)


After:

self.card = ttk.Frame(parent, padding=8, style=CARD_FRAME_STYLE)


Update labels to use BODY_LABEL_STYLE / MUTED_LABEL_STYLE:

Before:

header_label = ttk.Label(header_frame, text=title)


After:

header_label = ttk.Label(header_frame, text=title, style=BODY_LABEL_STYLE)


Buttons:

For primary action buttons (e.g., “Run pipeline”, “Launch WebUI”):

run_button = ttk.Button(parent, text="Run", style=PRIMARY_BUTTON_STYLE)


For secondary / less-prominent buttons, keep default or set SECONDARY_BUTTON_STYLE.

Remove direct color literals:

Replace bg="#000000", fg="#ffffff" in V2 GUI with either:

Style usage (preferred), or

SURFACE_BG, BODY_TEXT_COLOR constants if direct color assignment is absolutely necessary (e.g., canvas drawing).

Avoid raw tk.Frame where not strictly needed:

Where feasible, use ttk.Frame with styles so theme updates apply uniformly.

Keep tk.* only where ttk does not support required functionality.

Step 4 – Introduce / update a theme test

New or updated tests/gui_v2/test_theme_v2.py:

Build a minimal root, call apply_theme(root).

Use ttk.Style() to assert that:

style = ttk.Style()
assert CARD_FRAME_STYLE in style.layout() or style.configure(CARD_FRAME_STYLE) is not None
assert BODY_LABEL_STYLE in style.configure()


Optionally:

Build a MainWindowV2 and assert that key containers use CARD_FRAME_STYLE or SURFACE_FRAME_STYLE (by accessing cget("style") for known frames).

Make sure GUI tests skip gracefully if Tk is unavailable (same pattern as existing GUI tests).

9. Required Tests (Failing first)

Before implementation, add/adjust tests so they initially fail:

tests/gui_v2/test_theme_v2.py

Fails because it expects style names like Card.TFrame, Body.TLabel exposed via constants and configured by apply_theme.

(Optional) Update of tests/gui_v2/test_gui_v2_workspace_tabs_v2.py

If we assert certain containers use specific styles, this will also initially fail until the styles are applied.

10. Acceptance Criteria

PR-041 is complete when:

Theme centralization

theme_v2.py exposes semantic design tokens and style name constants:

SURFACE_BG, CARD_BG, CARD_BORDER_COLOR, BODY_TEXT_COLOR, etc.

SURFACE_FRAME_STYLE, CARD_FRAME_STYLE, BODY_LABEL_STYLE, PRIMARY_BUTTON_STYLE, etc.

V2 GUI usage

All V2 panels in src/gui/panels_v2/ and V2 tab frames (prompt_tab_frame_v2, pipeline_tab_frame_v2, etc.):

Use ttk.* with style=... referencing theme_v2 constants.

Do not introduce new hard-coded color literals for backgrounds/text.

Primary action buttons and core frames follow the centralized styles.

Behavior unchanged

The app launches, all tabs render.

No functional behaviors are altered (no new errors in logs).

Visual differences are limited to consistent theme application (colors/borders may look more uniform).

Tests

tests/gui_v2/test_theme_v2.py passes.

Existing GUI tests continue to pass or skip as before.

11. Rollback Plan

If this PR introduces regressions:

Revert changes to:

src/gui/theme_v2.py

src/gui/main_window_v2.py (styling-related changes)

All modified src/gui/views/*_v2.py

All modified src/gui/panels_v2/*_v2.py

tests/gui_v2/test_theme_v2.py and any updated GUI tests

Re-run:

python -m pytest tests/gui_v2 -q


Confirm the GUI returns to its previous appearance and behavior (even if theming is less centralized).

12. Codex Execution Constraints

No behavior changes: only styling and style wiring.

No new dependencies: use only tkinter/ttk, no external theme packages.

Minimal edits per file: refactor only what’s necessary to attach styles; don’t restructure layout or logic.

V2-only: do not alter V1 or legacy GUI modules.

Avoid overfitting tests:

Tests should assert the existence and use of styles, not pixel-perfect colors.

13. Smoke Test Checklist

After Codex applies this PR and tests pass:

From repo root:

python -m src.main


Visually inspect:

Main window background:

Dark and consistent across tabs.

Cards / panels:

All primary panels use uniform card styling (same background, border width/color).

Text:

Labels and body text consistently use the same font/color in each context.

Buttons:

Primary actions share the same visual style.

Perform basic actions:

Switch between Prompt / Pipeline / Learning tabs.

Trigger WebUI status panel, open any dialogs that rely on theme.