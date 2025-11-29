PR-GUI-V2-PIPELINE-SIDEBAR-002: Dark-Mode Sidebar Layout + Global Negative Prompt

Timestamp: 2025-11-26

1. Summary

The Pipeline left sidebar (config panel) is partially dark-mode themed, inconsistently spaced, and still carries some redundant controls. Also, the global negative prompt behavior is not clearly represented or wired for the pipeline.

This PR will:

Apply consistent dark mode styling to the entire Pipeline sidebar (all frames, labels, dropdowns, buttons).

Compact and reorganize the sidebar layout:

Put Stages, Run Mode, and Run Scope frames in a single horizontal band (three small columns).

Arrange Model Manager, Core Config, Global Negative, and Output Settings in a 2-column grid.

Fix label–dropdown alignment within those frames.

Remove the redundant “Run Now” button from the sidebar (main yellow Run button at top remains canonical).

Turn the negative prompt section into a proper Global Negative control:

Label it “Global Negative”.

Make the text field smaller to fit the 2-column layout.

Add an Enable Global Negative checkbox.

Wire this checkbox/text so that, when enabled, the global negative string is appended to every negative prompt used in the pipeline (for all prompts/packs that run).

This makes the sidebar look like a deliberate, compact dark-mode control panel, while giving you clear global negative behavior for Journey tests.

2. Problem Statement
2.1 Visual / UX Issues

Sidebar is inconsistently themed:

Some frames use dark styles; others look default/flat.

Labels and dropdowns are not consistently bold/white on dark grey.

Layout is wasteful:

Stages, Run Mode, Run Scope are stacked vertically, even though they are narrow and could easily sit side-by-side.

Model Manager, Core Config, Negative Prompt, Output Settings are each full-width blocks, causing lots of vertical whitespace.

Many dropdowns are misaligned relative to their labels.

Sidebar still has a Run Now button that’s redundant with the global yellow Run button at the top of the window.

2.2 Functional Gap: Global Negative Prompt

Current “negative prompt” field (if present) behaves like a generic negative prompt.

There’s no clear indication that a field applies globally to all prompts in a prompt pack.

There’s no enable/disable gate for the global negative; it’s all-or-nothing by convention, not explicit control.

The pipeline executor isn’t clearly wired to append a global negative to each stage’s negative prompt payload.

3. Goals / Non-Goals
3.1 Goals

Make the sidebar fully dark-themed:

Dark grey backgrounds for all frames, with bold white text everywhere.

Dropdowns and buttons styled consistently with existing V2 theme (theme.py).

Adjust the sidebar layout to be space-efficient:

One row with 3 small frames: Stages / Run Mode / Run Scope.

2-column grid below for Model Manager / Core Config / Global Negative / Output Settings.

Correct label–dropdown alignment.

Remove the sidebar Run Now button, rely on the main toolbar Run button.

Implement a Global Negative section:

Text field + enable/disable checkbox.

When enabled, global negative is appended to per-prompt negative text during pipeline build.

3.2 Non-Goals

No change to the Prompt tab or advanced prompt editor behavior beyond how negative strings are combined.

No changes to Learning tab.

No changes to pipeline engine semantics other than adding the global negative at the string-composition layer.

No changes to Journey Test definitions beyond what is necessary to mention the Global Negative feature.

4. Files in Scope

Sidebar + layout

1. Files in scope (update)

Replace the old section with something like:

**Primary implementation files**

- src/gui/sidebar_panel_v2.py  
  - Owns the Pipeline left-side config panel.
- src/gui/views/pipeline_tab_frame.py  
  - Owns the overall Pipeline tab layout (wires sidebar, stage_cards_panel, preview panel).
- src/gui/views/stage_cards_panel.py  
  - Container for the advanced stage cards (center column).
- src/gui/preview_panel_v2.py  
  - Right-side preview/summary panel.

**Theming**

- src/gui/theme.py  
- src/gui/theme_v2.py

**Pipeline config / request builder**

- The module that composes negative prompts for SD WebUI requests (e.g. src/pipeline/*_builder_v2.py) — only the part that concatenates negative prompt strings.


And then explicitly add:

**Legacy (do NOT modify in this PR)**

- src/gui/pipeline_panel_v2.py  
- src/gui/app_layout_v2.py  
- src/gui/layout_manager_v2.py  (only used by older entry points)


So Codex doesn’t wander into those.

2. Anywhere it says “PipelinePanelV2”

If the PR text says things like:

“In pipeline_panel_v2.py, adjust layout so left/center/right start at the top…”

Change that to:

“In views/pipeline_tab_frame.py, adjust the Pipeline tab layout so left/center/right start at the top…”

And where it talks about “Pipeline center panel”, you can optionally name:

“the center StageCardsPanel in views/stage_cards_panel.py”

just so it’s crystal clear.
Tests / docs

tests/gui_v2/test_sidebar_panel_v2_layout_and_theme.py (new)

tests/pipeline/test_global_negative_prompt.py (new)

Documentation:

docs/ARCHITECTURE_v2_COMBINED.md (GUI + pipeline config section)

docs/StableNew_GUI_V2_Program_Plan-*.md

docs/testing/Journey_Test_Plan_*.md (JT references to global negative, optional)

5. Detailed Design
5.1 Sidebar Layout: Top Row (Stages / Run Mode / Run Scope)

In sidebar_panel_v2.py:

Create a row container frame at the top of the sidebar, something like:

self.top_controls_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
self.top_controls_frame.grid(row=0, column=0, sticky="ew", padx=PADDING_MD, pady=(PADDING_MD, PADDING_SM))
self.top_controls_frame.columnconfigure(0, weight=1)
self.top_controls_frame.columnconfigure(1, weight=1)
self.top_controls_frame.columnconfigure(2, weight=1)


Inside this frame, add three small sub-frames:

Stages frame (column 0)

Run Mode frame (column 1)

Run Scope frame (column 2)

Each sub-frame uses a dark style (e.g., SURFACE_FRAME_STYLE) and contains:

Stages: three checkboxes: Txt2Img, Img2Img, Upscale

Run Mode: radio buttons or a combobox for Direct vs Queue

Run Scope: radio/combobox for scope, e.g., All enabled, Single stage only (whatever is already used)

Ensure each frame’s labels and checkboxes use the dark theme label/checkbutton styles (bold white text).

Result: Three small “tiles” across the top rather than a tall stack.

5.2 Sidebar Layout: 2-Column Control Grid

Below the top row, create a 2-column grid for:

Model Manager

Core Config

Global Negative (new version)

Output Settings

Add a container frame, e.g.:

self.settings_grid_frame = ttk.Frame(self, style=SURFACE_FRAME_STYLE)
self.settings_grid_frame.grid(row=1, column=0, sticky="nsew", padx=PADDING_MD, pady=(0, PADDING_MD))
self.settings_grid_frame.columnconfigure(0, weight=1)
self.settings_grid_frame.columnconfigure(1, weight=1)


Place the sections:

Row 0:

Column 0: Model Manager

Column 1: Core Config

Row 1:

Column 0: Global Negative (new)

Column 1: Output Settings

If any of these sections already exist as sub-panels or frames, re-parent them into this grid with grid(row=..., column=...) and remove the old single-column layout.

Fix label–dropdown alignment:

Inside each section, ensure a simple 2-column layout:

Column 0: ttk.Label (style: dark label)

Column 1: corresponding widget (combobox, spinbox, etc.)

Avoid layouts where labels and dropdowns are on different rows or separated by large padding.

5.3 Remove Sidebar “Run Now” Button

In sidebar_panel_v2.py:

Identify the Run Now button in the sidebar.

Remove its creation and layout.

Ensure no code calls its callback.

Keep the main yellow Run button at the top of the main window as the only Run action (no changes there).

If any tests reference the sidebar Run button, update or remove them accordingly.

5.4 Global Negative Prompt: UI

In sidebar_panel_v2.py:

Create the Global Negative section in the settings grid (row 1, col 0):

A small header label: “Global Negative” (bold white text).

A Checkbutton labeled “Enable”, bound to self.global_negative_enabled_var (BooleanVar).

A ttk.Entry or small tk.Text widget for the global negative string, bound to self.global_negative_text_var (StringVar if Entry).

Example:

self.global_negative_enabled_var = tk.BooleanVar(value=False)
self.global_negative_text_var = tk.StringVar(value="")

self.global_negative_frame = ttk.Frame(self.settings_grid_frame, style=SURFACE_FRAME_STYLE)
self.global_negative_frame.grid(row=1, column=0, sticky="nsew", padx=PADDING_SM, pady=PADDING_SM)

header = ttk.Label(self.global_negative_frame, text="Global Negative", style=STATUS_STRONG_LABEL_STYLE)
header.grid(row=0, column=0, columnspan=2, sticky="w")

enable_cb = ttk.Checkbutton(
    self.global_negative_frame,
    text="Enable",
    variable=self.global_negative_enabled_var,
    style="Dark.TCheckbutton",  # or sidebar-specific style
)
enable_cb.grid(row=1, column=0, sticky="w")

entry = ttk.Entry(
    self.global_negative_frame,
    textvariable=self.global_negative_text_var,
    width=30,  # reasonably small to fit 2-column layout
)
entry.grid(row=2, column=0, columnspan=2, sticky="ew")
self.global_negative_frame.columnconfigure(0, weight=1)
self.global_negative_frame.columnconfigure(1, weight=1)


The text field should be moderate width (we’re not expecting a paragraph), so it fits naturally into the column.

Apply dark-mode styles to frame and labels.

5.5 Global Negative Prompt: Wiring

You’ll need a single pipeline config field for global negative, accessible from both the GUI and the request builder.

Sidebar → Pipeline State

In sidebar_panel_v2.py (or the pipeline controller):

Add a method:

def get_global_negative_config(self) -> dict[str, Any]:
    return {
        "enabled": bool(self.global_negative_enabled_var.get()),
        "text": self.global_negative_text_var.get().strip(),
    }


When pipeline config is assembled (the place where we already use stage configs and run modes), include the global negative config into the pipeline state, e.g.:

pipeline_config["global_negative"] = self.get_global_negative_config()


Request Builder: Append Global Negative

In the request builder / pipeline builder (where negative prompts are assembled per prompt or per stage):

Fetch global negative config once:

global_neg = pipeline_config.get("global_negative", {})
global_enabled = bool(global_neg.get("enabled", False))
global_text = (global_neg.get("text") or "").strip()


When constructing each negative prompt string:

negative = base_negative_prompt_from_stage_or_prompt_pack  # existing logic

if global_enabled and global_text:
    if negative:
        negative = f"{negative}, {global_text}"
    else:
        negative = global_text


Do not break any existing behavior for stages that have explicit negative prompts; you’re just appending.

Ensure this logic is used for all relevant stages (txt2img, img2img, upscale stages that support negative prompts).

5.6 Dark Mode Styling

In theme.py:

Reuse existing V2 constants and styles:

Palette values already defined: ASWF_BLACK, ASWF_DARK_GREY, ASWF_MED_GREY, etc.

Style names: SURFACE_FRAME_STYLE, HEADER_FRAME_STYLE, PRIMARY_BUTTON_STYLE, STATUS_LABEL_STYLE, STATUS_STRONG_LABEL_STYLE, etc.

The configure_style function already sets up many dark styles.

For the sidebar, either:

Reuse SURFACE_FRAME_STYLE for all frames, or

Create sidebar-specific styles (e.g., "Sidebar.TFrame", "Sidebar.TLabel", "Sidebar.TCheckbutton"), but align them with the existing palette.

Apply styles in sidebar_panel_v2.py:

Root sidebar frame uses SURFACE_FRAME_STYLE / HEADER_FRAME_STYLE as appropriate.

All labels use a dark label style (white bold text).

All dropdowns (Combobox) use dark field/background and white text.

Buttons (if any remain) use PRIMARY_BUTTON_STYLE or a dark-ghost style.

Result: The entire sidebar reads as a cohesive dark-themed block, with minimal white gaps.

6. Testing
6.1 Manual Checks

Open the app, go to Pipeline tab.

Confirm:

No “Run Now” button in the sidebar.

Stages / Run Mode / Run Scope appear in a single top row (three small frames).

Model Manager / Core Config / Global Negative / Output Settings appear as a compact 2×2 grid.

All elements in the sidebar are dark grey with bold white text.

Set Global Negative enabled with a simple string (e.g., nsfw, blurry).

Run a pipeline:

Confirm that each stage’s negative prompt in the logs or WebUI input includes the global negative text appended.

6.2 Automated Tests

tests/gui_v2/test_sidebar_panel_v2_layout_and_theme.py:

Instantiate the sidebar.

Ensure:

Top row container exists and has 3 children: stages, mode, scope.

Settings grid frame has 2 columns and contains Model Manager, Core Config, Global Negative, Output Settings.

Sidebar Run Now button is absent.

tests/pipeline/test_global_negative_prompt.py:

Build a small pipeline config with:

A base negative prompt per stage.

global_negative = {"enabled": True, "text": "test_global"}.

Assert that the resulting API request’s negative prompt has "test_global" appended (with a comma if the base negative was non-empty).