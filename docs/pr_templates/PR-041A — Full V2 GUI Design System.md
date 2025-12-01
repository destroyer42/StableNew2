PR-041A — Full V2 GUI Design System (Tokens, Theme, and Primitive Components)

PR-ID: PR-041A
Risk Tier: Medium (GUI-only, reachable from main, no pipeline/executor changes)
Goal (1 sentence): Establish a centralized V2 GUI design system (tokens, theme wiring, and primitive widgets) so all new and refactored UI uses consistent colors, typography, spacing, and control styles.

1. Baseline & Constraints

Baseline snapshot

Use: StableNew-snapshot-20251130-075449.zip

Use the accompanying repo_inventory.json in the project folder as the structure truth source.

Key architectural constraints

GUI must not import: pipeline, learning, api, cluster, ai.

GUI may import: controller, utils, other GUI modules.

Prefer V2 modules (*_v2.py, views/*_v2.py, stage_cards_v2/*) for all new work.

Logic stays in controllers; GUI stays thin and declarative.

2. Scope

In-scope for PR-041A

Design tokens & theme system

Define a central design token model (colors, typography, spacing, radii, elevations, sizing) for V2.

Wire these tokens into src/gui/theme_v2.py so that:

There is a single, explicit “V2 theme” entrypoint.

Tk/ttk styles are registered from these tokens.

Keep src/gui/theme.py intact (legacy), but make it clear in comments that theme_v2.py is the preferred V2 path going forward.

Primitive components / helpers

Introduce a small set of “primitive” building blocks that UI code can re-use:

Buttons (primary, secondary, destructive, ghost)

Cards/frames (stage card shells, panels, sections)

Label + input groupings (label + entry, label + slider)

Section headers / sub-headers

Keep these simple and Tk/Ttk-native; no custom drawing libraries.

Initial adoption in V2-only modules

Apply the new design system to a limited, representative set of V2 GUI modules without changing behavior:

src/gui/theme_v2.py

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/gui/views/run_control_bar_v2.py

src/gui/views/stage_cards_panel_v2.py

src/gui/stage_cards_v2/base_stage_card_v2.py

src/gui/stage_cards_v2/components.py

Existing layout and widget hierarchy should remain semantically the same; only styling/wrappers change.

Tests & safety

Expand tests/gui_v2/test_theme_v2.py to assert:

Theme initialization doesn’t crash.

Key styles (primary.TButton, Card.TFrame, etc.) exist.

Optionally add a small smoke test for one of the V2 frames (e.g., prompt_tab_frame_v2) if feasible with existing patterns.

3. Out of Scope (Explicit Non-Goals)

No changes to:

src/main.py

src/pipeline/executor.py

src/pipeline/pipeline_runner.py or other pipeline internals

No functional changes to:

Pipeline execution

Learning engine

Randomizer behavior

No rewrites of all legacy panels; adoption will continue in future PRs (e.g., PR-041B/C).

No new threading or concurrency behavior.

4. Files to Modify (Allowed List)

Core design system & theme

src/gui/theme_v2.py

src/gui/design_system_v2.py (NEW)

Primitive widgets / frames

src/gui/widgets/scrollable_frame_v2.py (only if needed to align scroll behavior with design system)

src/gui/enhanced_slider.py (only if needed to align slider look/feel; no behavior changes)

V2 views & stage cards (initial adoption)

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/gui/views/run_control_bar_v2.py

src/gui/views/stage_cards_panel_v2.py

src/gui/stage_cards_v2/base_stage_card_v2.py

src/gui/stage_cards_v2/components.py

Tests

tests/gui_v2/test_theme_v2.py

(Optional) tests/gui_v2/test_v2_frames_design_system_smoke.py (NEW)

5. Forbidden Files (For This PR)

Do not modify:

src/gui/main_window_v2.py

src/gui/main_window.py

src/gui/theme.py

src/main.py

src/pipeline/executor.py

src/pipeline/* (all)

src/learning/*

Any file under archive/

Any test outside tests/gui_v2/ unless absolutely necessary (and then call that out explicitly in the PR summary).

If you discover a required change in a forbidden file, stop and treat that as a follow-on PR (PR-041B), don’t slip it into 041A.

6. Implementation Outline
6.1 src/gui/design_system_v2.py (NEW)

Create a new module that defines:

Design token structures

Colors (semantic, not literal):

PRIMARY_BG, PRIMARY_FG

SURFACE_BG, SURFACE_ELEVATED_BG

ACCENT, ACCENT_ALT

DANGER_BG, DANGER_FG

BORDER_SUBTLE, BORDER_STRONG

Typography:

Base font family (align with existing Tk app font)

Sizes: FONT_XS, FONT_SM, FONT_MD, FONT_LG, FONT_XL

Weight variants: FONT_WEIGHT_NORMAL, FONT_WEIGHT_BOLD

Spacing:

SPACE_1 (2–4 px), SPACE_2, SPACE_3, SPACE_4, SPACE_5

Radii:

RADIUS_SM, RADIUS_MD, RADIUS_LG

Elevations:

Maybe just symbolic: ELEVATION_FLAT, ELEVATION_RAISED

Simple APIs

Functions to register styles with a ttk.Style instance:

apply_button_styles(style: ttk.Style) -> None

apply_card_styles(style: ttk.Style) -> None

apply_label_styles(style: ttk.Style) -> None

Style names to standardize on:

Buttons:

"Primary.TButton"

"Secondary.TButton"

"Ghost.TButton"

"Danger.TButton"

Frames/cards:

"Card.TFrame"

"StageCard.TFrame"

"Toolbar.TFrame"

Labels:

"Heading.TLabel"

"Subheading.TLabel"

"Body.TLabel"

"Muted.TLabel"

Primitive factory helpers (optional but encouraged)

Small helpers that wrap widget creation with the right style:

create_primary_button(parent, text, command=None, **kwargs)

create_secondary_button(...)

create_stage_card_frame(parent, **kwargs)

These should return standard ttk.Button / ttk.Frame instances configured with the correct style and padding; no new widget subclasses unless it is clearly simpler.

Keep this module pure GUI: only import tkinter, tkinter.ttk, typing, and maybe logging.

6.2 src/gui/theme_v2.py

Centralize V2 theme initialization

Add/adjust a single public entrypoint function:

def init_theme(root: tk.Tk | tk.Toplevel) -> ttk.Style:

Creates or fetches a ttk.Style.

Calls into design_system_v2.apply_* functions to register styles.

Optionally sets the base theme (e.g., 'clam') if consistent with the rest of the app.

Deprecation note for theme.py

In a top-level comment or docstring, clarify:

theme_v2.py is the preferred theme for V2 GUI.

Legacy V1 GUI still uses theme.py.

Do not import or modify theme.py here.

Align any existing constants

If theme_v2.py already defines colors/fonts, refactor them to be:

Either imported or re-expressed as tokens in design_system_v2.

Avoid duplication: prefer “single source of truth” (i.e., tokens live in design_system_v2, theme_v2 just wires them into ttk).

6.3 V2 Views & Stage Cards – Minimal Adoption

For each of:

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/gui/views/run_control_bar_v2.py

src/gui/views/stage_cards_panel_v2.py

src/gui/stage_cards_v2/base_stage_card_v2.py

src/gui/stage_cards_v2/components.py

Apply the following conservative changes:

Replace hard-coded style strings and repeated styling

Where you see things like style="TButton" or custom padding repeated, switch to the design system style names:

Primary actions → "Primary.TButton"

Secondary actions → "Secondary.TButton" or "Ghost.TButton"

Stage cards → "StageCard.TFrame" / "Card.TFrame"

Where there is repeated padding=(8, 8) or similar, centralize through factories or at least constants from design_system_v2.

Use primitives where appropriate

If you added factory helpers (e.g., create_primary_button), call those instead of raw ttk.Button(...) for the main actions:

Run / Stop buttons

“Generate”, “Apply”, etc.

For containers that visually behave like cards, use create_stage_card_frame or apply "StageCard.TFrame".

No logic changes

Do not change event handlers, controller calls, or pipeline triggers.

Signature and wiring of callbacks must remain identical.

6.4 Widgets & Sliders (Optional Minimal Touch)

In src/gui/widgets/scrollable_frame_v2.py:

Avoid any inline color constants that conflict with the new tokens; align background with SURFACE_BG or a similar token.

Ensure scrollbars visually match the theme but do not change their behavior.

In src/gui/enhanced_slider.py:

If it uses custom colors or fonts, align those with token values from design_system_v2.

Don’t change slider logic, ranges, or binding behavior.

If alignment requires more invasive changes, keep them for a follow-on PR (e.g., PR-041B) and note that in comments.

7. Done Criteria (Definition of Done)

 src/gui/design_system_v2.py exists and exports:

A coherent set of design tokens (colors, typography, spacing, radii, etc.).

Style registration helpers for buttons, cards/frames, labels.

Optional widget factory helpers for common patterns.

 src/gui/theme_v2.py:

Exposes a single init_theme(...) function used by V2 GUI.

Applies design tokens from design_system_v2 to ttk styles.

Contains a clear note that theme_v2.py is the V2 theme entrypoint.

 Selected V2 frames and stage-card modules use design-system styles or primitives instead of ad-hoc styles.

 No GUI behavior changes (callbacks, events, controller calls, pipeline trigger logic remains same).

 App still launches via main.py and displays the V2 GUI without Tk errors.

 All modified files pass linting/formatting as configured in the repo (ruff/black/mypy if applicable).

 All required tests (below) pass.

8. Tests to Run

At minimum:

# Existing GUI theme test
pytest tests/gui_v2/test_theme_v2.py -q

# Any GUI V2 entrypoint/journey smoke tests
pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q  # if present

# Broader Phase 1 suite (or current GUI subset) to ensure no regressions
pytest $(cat tests/phase1_test_suite.txt) -q


If you add tests/gui_v2/test_v2_frames_design_system_smoke.py, include it in your usual test invocation or ensure it’s picked up by default pytest.

9. Instructions to Codex/Copilot (Implementation Notes)

When implementing PR-041A:

Start with design_system_v2.py and theme_v2.py.

Get tokens and style registration stable first.

Verify test_theme_v2.py passes before touching any views.

Introduce minimal primitives.

Only add helpers you actually use in the views you’re updating in this PR.

Avoid over-engineering; short and clear beats “clever”.

Adopt styles in a limited set of V2 modules.

Focus on the main tab frames and stage card base/components.

Replace direct "TButton" and manual styling with the new styles/primitives.

Do not change widget hierarchy or layout containers.

Keep GUI thin and declarative.

No business logic or pipeline logic in the design system.

No imports from pipeline, learning, or api.

Avoid touching forbidden files.

If you think main_window_v2.py or theme.py must change, stop and mark that as a todo for a follow-on PR (e.g., PR-041B).

Run tests early and often.

After changes to theme/design system.

After updating each view group.