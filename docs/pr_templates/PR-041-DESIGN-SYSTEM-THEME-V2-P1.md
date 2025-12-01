PR-041-DESIGN-SYSTEM-THEME-V2-P1

Unified Dark Theme, Card Hierarchy, and Design Contract for GUI V2

1. Title

PR-041 – GUI V2 Design System & Dark Theme Unification (Tokens, Cards, & Patterns)

2. Summary

This PR turns theme_v2.py and related GUI V2 components into a full design toolkit:

A tokenized dark theme (colors, typography, spacing) that covers:

All widget types: combos, radio buttons, checkboxes, sliders, spinboxes, toggles, listboxes, text areas, headers, labels, etc.

A consistent dark background (grey/black), with high-contrast white/light text, by default.

A standardized card hierarchy:

A shared BaseCard pattern (one visual contract) used everywhere:

Center panel stage cards (currently using BaseStageCard).

Left pipeline cards (currently using _SidebarCard / “side panel card”).

Right-hand preview & job/queue/history cards.

A design contract document for Codex/Copilot:

Formal rules on how cards, widgets, padding, and layout must be constructed.

“Do/Don’t” patterns and examples.

Clear requirement that all future GUI work uses theme tokens and card patterns unless explicitly told otherwise.

Goal: after PR-041, the entire GUI V2 will look consistent and be easy to evolve — changing a single token can restyle everything.

3. Problem Statement

Right now:

Theme usage is inconsistent:

Some panels use theme_v2, some hard-code bg colors, some rely on ttk defaults.

Dark mode has lots of white/grey gaps, inconsistent label colors, and mismatched controls.

Widget types are not covered uniformly:

Comboboxes, radio buttons, sliders, entries, etc. don’t all share the same background/text colors.

Card hierarchy is fractured:

Center panel uses a BaseStageCard class.

Left pipeline panel uses its own _SidebarCard/“SidePanelCard” pattern, with wrappers inside wrappers.

Right panels (preview, logging, job history) use ad hoc frames.

This makes it hard to:

Keep visual consistency across Prompt / Pipeline / Learning tabs.

Add new panels without guessing styles.

Ask Codex/Copilot to “make a new card” without them re-inventing styling.

We want a single design language for GUI V2 so every new piece slots in automatically.

4. Goals

Theme tokens for everything

theme_v2.py defines:

Dark palette (greys/blacks surfaces, white/light text, ASWF gold accent).

Semantic tokens for:

Backgrounds (root, surfaces, elevated surfaces).

Text (primary, muted, accent).

Borders (subtle, strong).

Controls (primary/secondary buttons, inputs, toggles).

State (success, warning, error).

All widgets in V2 use these tokens (no literal hex codes).

Unified card hierarchy

Introduce a BaseCardV2 component for generic “card” layout:

Standard padding, border, corner radius, header/body layout.

Make:

BaseStageCard extend or compose BaseCardV2.

_SidebarCard (or side panel card equivalent) extend/compose BaseCardV2.

Job preview/history/log cards also use BaseCardV2.

Result: left, center, right columns all share the same visual and structural card contract.

Widget pattern coverage

Standard styles for:

Buttons (primary/secondary/ghost).

Comboboxes.

Entries.

Checkbuttons / Radiobuttons.

Scales/sliders.

Spinboxes.

Listboxes.

Text areas / ScrolledText.

Tab headers.

Each gets a named style (e.g., "Primary.TButton", "Config.TCombobox", "Dark.TRadiobutton") that uses tokens.

Design contract document

docs/GUI_V2_Design_System_V2-P1.md:

Palette & token reference.

Card patterns (BaseCard/StageCard/SidebarCard).

Layout rules (padding, spacing, alignment).

Widget rules (which styles to use where).

Codex/Copilot “must follow these rules unless explicitly overridden” statement.

Zero behavior change

All wiring, logic, and behavior remain intact.

This is a visual & structural consistency PR, not a functionality change.

5. Non-goals

No Light theme implementation (we just make a dark theme that could be swapped later).

No layout changes beyond standardizing card wrappers (no new tabs, no new panels).

No changes to pipeline, queue, WebUI, or learning logic.

No changes to V1 GUI or legacy theme files.

6. Allowed Files

Theme / Design System

src/gui/theme_v2.py

src/gui/components/card_base_v2.py (new, for BaseCardV2 & card helpers)

Card-based GUI components

Center column / stage cards:

src/gui/stage_cards_v2/base_stage_card_v2.py (or the equivalent base class file)

src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

src/gui/stage_cards_v2/upscale_stage_card_v2.py

Left column:

src/gui/panels_v2/sidebar_panel_v2.py (for _SidebarCard / side panel card patterns)

src/gui/panels_v2/pipeline_config_panel_v2.py

Any other left-column cards (Global Negative, Randomizer, LoRA, etc.)

Right column:

src/gui/preview_panel_v2.py

src/gui/job_history_panel_v2.py

src/gui/panels_v2/log_trace_panel_v2.py (log bottom panel, if present)

Tab / Shell components (for style, not logic)

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/gui/main_window_v2.py (style-only, no wiring changes)

Docs & Tests

docs/GUI_V2_Design_System_V2-P1.md (new)

tests/gui_v2/test_theme_v2_design_contract_v2.py (new)

Small updates to existing gui_v2 tests as needed for style name changes (no behavior changes).

7. Forbidden Files

Do not modify:

src/main.py

src/pipeline/*

src/api/*

src/controller/app_controller.py (except at most a one-liner to initialize theme if absolutely required)

Any V1 GUI or theme.py

Queue/runner/learning/randomizer logic modules

If it feels like one of these must change, it should be a separate PR, not folded into 041.

8. Step-by-step Implementation
A. Promote theme_v2 into a full token system

Define palette & tokens in theme_v2.py

Dark palette with black/grey backgrounds & white-ish text:

PALETTE_DARK = {
    "bg_root": "#101015",
    "bg_surface": "#181821",
    "bg_surface_elevated": "#202030",
    "bg_panel": "#181821",
    "text_primary": "#F5F5F8",
    "text_muted": "#A2A2B5",
    "text_accent": "#FFC805",  # gold
    "border_subtle": "#29293A",
    "border_strong": "#FFFFFF",
    "accent_primary": "#FFC805",
    "accent_danger": "#FF4B5C",
    "accent_success": "#4CAF50",
    "input_bg": "#1E1E2A",
    "input_border": "#3A3A4A",
}


Semantic tokens (so we never hardcode palette keys in components):

BG_ROOT = PALETTE_DARK["bg_root"]
BG_SURFACE = PALETTE_DARK["bg_surface"]
BG_CARD = PALETTE_DARK["bg_surface_elevated"]
TEXT_PRIMARY = PALETTE_DARK["text_primary"]
TEXT_MUTED = PALETTE_DARK["text_muted"]
TEXT_ACCENT = PALETTE_DARK["text_accent"]
BORDER_SUBTLE = PALETTE_DARK["border_subtle"]
BORDER_STRONG = PALETTE_DARK["border_strong"]
ACCENT_PRIMARY = PALETTE_DARK["accent_primary"]


Register ttk styles for all widget families

In init_theme(root) or similar:

Frames/Cards:

"Card.TFrame", "Card.Section.TFrame", "Card.Header.TFrame"

Labels:

"Heading.TLabel", "Subheading.TLabel", "Muted.TLabel", "Value.TLabel"

Buttons:

"Primary.TButton", "Secondary.TButton", "Ghost.TButton", "Danger.TButton"

Inputs:

"Input.TEntry", "Input.TCombobox", "Input.TSpinbox"

Toggles:

"Toggle.TCheckbutton", "Toggle.TRadiobutton"

Sliders:

"Range.TScale"

Notebook/tabs:

"Dark.TNotebook", "Dark.TNotebook.Tab"

All of these use the dark backgrounds and white/light text by default.

Expose helper APIs & a “design contract” section

In theme_v2.py define:

def style_card(frame: ttk.Frame) -> None: ...
def style_section_header(label: ttk.Label) -> None: ...
def style_primary_button(btn: ttk.Button) -> None: ...
def style_secondary_button(btn: ttk.Button) -> None: ...
def style_input(widget: ttk.Widget) -> None: ...
def style_toggle(widget: ttk.Widget) -> None: ...
def style_slider(scale: ttk.Scale) -> None: ...
def style_textarea(text: tk.Text | ScrolledText) -> None: ...


These functions encapsulate how to attach styles and tokens so Codex doesn’t re-invent.

B. Centralize the card hierarchy (BaseCardV2)

Create card_base_v2.py

Add BaseCardV2(ttk.Frame):

Responsibilities:

Apply "Card.TFrame" style and padding.

Optionally create:

self.header_frame

self.body_frame

Provide:

add_header_title(text: str) helper (applies heading style).

add_header_actions(frame: ttk.Frame) hook for buttons.

Accept variant: Literal["primary", "secondary", "subtle"] to support slight visual differences via style suffixes (e.g., "Card.Primary.TFrame").

Refactor BaseStageCard to use BaseCardV2

In base_stage_card_v2.py (or equivalent):

Change it to either:

Inherit from BaseCardV2, or

Compose a BaseCardV2 and expose its body_frame.

Remove any ad hoc bg, relief, borderwidth that conflict with BaseCardV2.

Refactor _SidebarCard to use BaseCardV2

In sidebar_panel_v2.py:

Replace the internal _SidebarCard implementation with a thin wrapper class that:

Inherits from BaseCardV2 with variant="secondary" (or similar).

Accepts title and build_child callback like it does today.

Remove extra wrapper frames where they’re only being used for faux visual grouping; rely on BaseCardV2.

Apply BaseCardV2 to right-hand cards

In preview_panel_v2.py, job_history_panel_v2.py, log_trace_panel_v2.py:

Wrap each logical “card” (Job Draft, Queue, History, Logs) in a BaseCardV2.

Replace ad hoc styling with theme helpers.

Result: all three columns (left / center / right, across all tabs) use a consistent card structure.

C. Apply style tokens to all widget categories

Buttons

Across all V2 GUI files:

For primary actions (e.g., “Run Pipeline”, “Add to Job”, “Launch WebUI”):

Call style_primary_button(btn) or set style="Primary.TButton".

For secondary/utility actions (e.g., “Load config”, “Apply config”, “Show Preview”):

Call style_secondary_button(btn) or style="Secondary.TButton".

Comboboxes & Entries

All ttk Combobox / Entry in V2:

Call style_input(widget) or assign "Input.TCombobox" / "Input.TEntry".

Radio / Checkbuttons / Toggles

Style all toggles using "Toggle.TCheckbutton"/"Toggle.TRadiobutton" via style_toggle.

This guarantees:

Dark background.

White/light label text.

Sliders & Spinboxes

Use "Range.TScale" and "Input.TSpinbox".

Call style_slider(scale) / style_input(spin).

Text areas & Log panels

Wrap each Text/ScrolledText with style_textarea:

Dark inner background.

Light text.

Muted scrollbars.

Tab headers & labels

Tab titles: use Heading.TLabel in tab content.

Section labels: Subheading.TLabel / Muted.TLabel.

At the end of this pass, every widget in V2 interacts with the theme via styles/tokens — no stray default white backgrounds.

D. Design Contract Document

Add docs/GUI_V2_Design_System_V2-P1.md:

Contents:

Palette & Tokens:

List all semantic tokens from theme_v2.py.

Card Patterns:

BaseCardV2 contract: header/body, padding, border, shadow.

StageCard: extends BaseCardV2, intended for center-panel stage forms.

SidebarCard: extends BaseCardV2, intended for left-panel controls.

Example diagrams: left/center/right layout per tab.

Widget Patterns:

Which styles to use for:

Actions vs destructive actions.

Config vs navigation vs toggles.

Grid & Spacing Rules:

Default padding between cards.

Default padding inside cards.

Alignment conventions (labels left, inputs right, etc.).

Codex/Copilot Rules:

“When creating a new GUI component, you must:”

Use BaseCardV2 for any new card-type container.

Use theme_v2 helpers for any buttons, inputs, toggles, sliders, and text areas.

Not introduce raw hex colors or bare ttk default styles unless explicitly requested.

This doc becomes the authoritative design contract for all future GUI work.

E. Tests for the design contract

Add tests/gui_v2/test_theme_v2_design_contract_v2.py:

Mark as gui, skip if Tk unavailable.

Build a minimal selection of V2 components:

One BaseStageCard.

One SidebarCard.

One preview panel card.

Assert:

Card root frames have style "Card.*" (or use BaseCardV2).

Buttons use "Primary.TButton" or "Secondary.TButton".

A sample Combobox uses "Input.TCombobox".

A sample Checkbutton uses "Toggle.TCheckbutton".

Add a simple static string check (optional, not bulletproof) to ensure:

No literal color hex (e.g., "#fff", "#ffffff") appears in V2 GUI files except theme_v2.py.

9. Required Tests (Failing First)

Initially, test_theme_v2_design_contract_v2.py will fail because:

Styles/tokens/helpers are not fully present.

Some GUI components don’t use the new card/widgets styles.

After implementation:

python -m pytest tests/gui_v2/test_theme_v2_design_contract_v2.py -q should pass.

Other gui_v2 tests should continue to pass or require only minor updates to expected style names.

10. Acceptance Criteria

This PR is done when:

Visual Consistency

All tabs (Prompt / Pipeline / Learning) share:

Dark backgrounds.

White/light text.

Consistent cards with clear borders.

Card Hierarchy

BaseCardV2 is the basis for:

Stage cards.

Sidebar cards.

Preview/history/log cards.

No more ad hoc “special” panel wrappers for visuals.

Widget Coverage

Every combobox, entry, radio, checkbox, slider, spinbox, button, text area in V2 uses theme styles (no default white controls).

Design Contract in place

docs/GUI_V2_Design_System_V2-P1.md exists and is coherent enough that you (and Codex/Copilot) can follow it and generate consistent UIs.

No Behavior Regression

App boots.

All existing functionality (WebUI launch, dropdowns, job draft, etc.) still works.

No Tk errors introduced by theming.

11. Rollback Plan

If the theme/design changes cause regressions:

Revert:

theme_v2.py

card_base_v2.py

The style-only changes in V2 GUI components.

GUI_V2_Design_System_V2-P1.md

test_theme_v2_design_contract_v2.py

Confirm:

GUI returns to the previous (less consistent) look but remains functional.

12. Codex Execution Constraints

Treat this as style + structure only:

No changes to controller logic or data flow.

Make changes incrementally:

Introduce theme tokens first.

Introduce BaseCardV2.

Refactor cards per area (left/center/right) in small, reviewable steps.

Don’t introduce new dependencies or change how Tk is initialized.

When in doubt, prefer composition (BaseCardV2 inside existing classes) over mega inheritance refactors.