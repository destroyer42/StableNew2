PR-GUI-V2-PIPELINE-STAGECARDS-001: Wire Cards-11-26-2025-0816.md

Timestamp: 2025-11-26

1. Summary

The advanced stage cards for Txt2Img, Img2Img/ADetailer, and Upscale are now visually present in the Pipeline tab center panel, but:

Many inputs are plain Entry fields with no numeric constraints or increment behavior.

Several fields are not wired into the pipeline controller / stage config model.

Some dropdowns (models, samplers, upscalers, etc.) are not populated from the real adapters.

When the window height is small, the cards shrink vertically instead of scrolling, hiding important controls.

This PR:

Fully wires all widgets in the three advanced stage cards to their underlying Tk variables and to the pipeline controller/config objects.

Replaces fragile Entry fields with proper widgets (readonly Combobox, bounded Spinbox, or EnhancedSlider) using existing helper panels and patterns.

Makes the Pipeline center column scrollable using the shared scrolling.make_scrollable helper so cards maintain a consistent height and never disappear offscreen.

After this PR:

All stage configuration happens from the Pipeline tab, with interactive, validated widgets.

The center column has a vertical scrollbar when needed instead of shrinking cards.

Stage configs can be round-tripped cleanly between GUI and pipeline state (for Journey tests and Learning integration later).

2. Problem Statement
2.1 Current Behavior

Advanced stage cards (AdvancedTxt2ImgStageCardV2, AdvancedImg2ImgStageCardV2, AdvancedUpscaleStageCardV2) are placed in the Pipeline center panel but are effectively “dead”:

Some widgets don’t propagate changes into the underlying stage config.

Some widgets are not initialized from the controller’s current config.

Certain inputs are basic Entry fields with no bounds, increments, or type safety.

The center column is a simple frame with all cards stacked vertically:

When the main window is short, Tk tries to compress the card frames vertically.

Critical controls (resolution, steps/CFG, denoise, etc.) become clipped or unreachable unless the entire app window is stretched tall.

2.2 Why This Blocks Journey Tests

To run realistic Journey tests (e.g., JT-03 Txt2Img run, JT-04 Img2Img, JT-05 Upscale), testers must:

Reliably set model, sampler, width/height, steps, CFG, denoise, upscaler, etc.

See all controls regardless of monitor size.

Confirm that changing a widget actually changes the underlying config and affects the resulting image.

Right now, we can’t do that consistently; the GUI is more of a static scaffold than a functional control surface.

3. Goals and Non-Goals
3.1 Goals

Wire every core input in the three advanced stage cards to:

An appropriate Tk variable (IntVar / DoubleVar / StringVar / BooleanVar).

The StageCard’s load_from_section() and to_config_dict() round-trip methods.

The pipeline controller / state snapshot used to build API payloads.

Use the right widget types for each field:

Read-only Combobox for enumerated options (models, samplers, VAEs, upscalers, mask modes).

Spinbox with sensible ranges and increments for dimensions, steps, CFG, tile size, etc.

EnhancedSlider for continuous 0–1 fields like denoise and confidence.

Checkbutton for booleans (enable stage, face restore, etc.).

Implement a scrolling Pipeline center panel:

Wrap the stage card stack in scrolling.make_scrollable(parent) so total height can exceed the viewport without compressing cards.

Maintain consistency with existing V2 theming (theme.py, theme_v2.py) and layout tokens.

3.2 Non-Goals

No change to back-end pipeline logic or API payload formats.

No changes to Prompt tab or Learning tab behavior.

No new randomizer or X/Y features; we only ensure existing fields are interactive and scrollable.

No removal of legacy panels; we only stop relying on them for the new V2 center cards.

4. Files In Scope

Paths relative to repo root (StableNew-newComp/).

GUI widgets / panels

src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py

src/gui/stage_cards_v2/base_stage_card_v2.py (only if shared hooks are needed)

src/gui/stage_cards_v2/components.py (reuse SamplerSection/SeedSection patterns)

src/gui/core_config_panel_v2.py (reference for spinbox ranges and controller refresh patterns).

src/gui/config_panel.py (legacy patterns for txt2img/upscale wiring).

src/gui/adetailer_config_panel.py (good example for dropdowns + sliders + set/get/validate).

src/gui/resolution_panel_v2.py (dimension presets and increments).

src/gui/enhanced_slider.py (for denoise/CFG where appropriate).

src/gui/randomizer_panel_v2.py (reference for matrix + spinbox wiring and change callbacks).

src/gui/model_manager_panel_v2.py (model/VAE combobox integration).

src/gui/scrolling.py (scrollable canvas helper).

src/gui/theme.py / src/gui/theme_v2.py (styles & frame styles).

Pipeline layout

src/gui/app_layout_v2.py or src/gui/center_panel.py / src/gui/pipeline_panel_v2.py (where the Pipeline center column is defined and the stage cards are added).

Tests

tests/gui_v2/test_pipeline_stage_cards_v2.py (create/update as needed)

tests/gui_v2/test_scrollable_pipeline_panel_v2.py (new)

Any existing tests that already reference advanced stage card classes.

5. Detailed Design & Field Mapping
5.1 Txt2Img Stage Card (AdvancedTxt2ImgStageCardV2)

Goal: Use proper widgets with expected ranges, and ensure they map cleanly to the "txt2img" section in the pipeline config.

Widgets & Mapping

Sampler section

Already uses SamplerSection (which has sampler_var, steps_var, cfg_var).

Ensure these vars are:

Linked to class attributes (self.sampler_var, self.steps_var, self.cfg_var).

Populated from controller config via load_from_section().

Included in to_config_dict() (sampler_name, steps, cfg_scale).

Model / VAE / Scheduler / Clip Skip

Replace plain Entry model and VAE fields with readonly Combobox populated from ModelManagerPanelV2 adapter lists (get_model_names(), get_vae_names()) when available.

Keep scheduler and clip skip as Entry or Spinbox:

scheduler_var: simple Entry (free text is fine).

clip_skip_var: Spinbox from 1–8, increment 1.

Width / Height

Either:

Integrate a ResolutionPanelV2 instance into the Txt2Img card body, or

Replace the current plain Entry fields with Spinbox:

from_=64, to=4096, increment=64.

On FocusOut or spinbox command, clamp to valid range.

Ensure to_config_dict() emits ints for width and height.

Seed

Seed is already exposed via SeedSection.

Confirm it is included in to_config_dict() if needed by the API, or explicitly note that seed is handled at a higher level (and skip here).

Controller integration

Add refresh_from_config(section: dict[str, Any]) method or reuse load_from_section():

Set model_var, vae_var, sampler_var, steps_var, cfg_var, width_var, height_var, clip_skip_var, etc. from the incoming "txt2img" config.

Ensure the Pipeline controller:

Calls stage_card.load_from_section(config["txt2img"]) when loading a pipeline config.

Uses update_config_with(stage_card.to_config_dict()) (or equivalent merge) before executing.

5.2 Img2Img Stage Card (AdvancedImg2ImgStageCardV2)

Widgets & Mapping

Sampler, Steps, CFG

Same pattern as Txt2Img:

Use SamplerSection for sampler/steps/CFG.

Bind values to sampler_var, steps_var, cfg_var.

Denoise

Replace free Entry with EnhancedSlider:

from_=0.0, to=1.0, resolution=0.01, default 0.40.

Keep an underlying DoubleVar (denoise_var).

Add an optional value display (0.00–1.00) in the slider widget.

Mask mode

Replace Entry with Combobox where possible:

Values: ("none", "keep", "discard", "auto") or reuse a list from legacy img2img config panel if present.

Backwards-compatible: still store as string in config.

Width / Height

Same as Txt2Img:

Spinboxes with from_=64, to=4096, increment=64.

Round-trip through "img2img" config section.

Controller integration

Add load_from_section(section: dict[str, Any]) and to_config_dict() mapping:

"img2img": {
    "sampler_name": ...,
    "steps": ...,
    "cfg_scale": ...,
    "denoise": ...,
    "mask_mode": ...,
    "width": ...,
    "height": ...,
}


Ensure the Pipeline controller uses these for building the img2img stage request.

5.3 Upscale Stage Card (AdvancedUpscaleStageCardV2)

Widgets & Mapping

Upscaler

Use a readonly Combobox populated either from:

A dedicated upscaler list in the controller, or

ConfigPanel’s upscale_vars["upscaler"] pattern for legacy compatibility.

Upscale factor

Replace Entry with:

Either Spinbox from_=1, to=8, increment=0.1, or

EnhancedSlider from_=1.0, to=4.0, resolution=0.1.

Store in factor_var and emit as int/float as required by existing API payload.

Tile size

Use Spinbox from_=0, to=4096, increment=16.

When 0, treat as “auto tile size”.

Face restore

Use Checkbutton bound to face_restore_var (BooleanVar).

Equivalent semantics to ADetailer or legacy upscale: when true, pipeline includes face-restoration parameters.

Controller integration

Ensure load_from_section(section: dict[str, Any]) sets upscaler, factor, tile size, and face_restore.

to_config_dict() should return:

"upscale": {
    "upscaler": ...,
    "upscaling_resize": ...,
    "tile_size": ...,
    "face_restore": ...,
}


Pipeline controller merges this into the outgoing upscale request.

6. Scrollable Pipeline Center Panel

Goal: The stage cards should keep a clear, readable height. When they don’t fit vertically, a scrollbar appears instead of shrinking cards.

Implementation

In the Pipeline layout file (app_layout_v2.py / pipeline_panel_v2.py / center_panel.py):

Identify the center column frame that currently holds the three stage cards directly.

Replace the direct frame with a scrollable container built via scrolling.make_scrollable(parent, style="Dark.TFrame").

Example pattern:

from src.gui import scrolling

self.center_canvas, self.center_frame = scrolling.make_scrollable(center_parent, style="Dark.TFrame")
# Then create stage cards inside self.center_frame
self.txt2img_card = AdvancedTxt2ImgStageCardV2(self.center_frame, controller=..., theme=...)
self.img2img_card = AdvancedImg2ImgStageCardV2(self.center_frame, controller=..., theme=...)
self.upscale_card = AdvancedUpscaleStageCardV2(self.center_frame, controller=..., theme=...)


Grid them vertically in self.center_frame with sticky="ew" and padx/pady consistent with theme.PADDING_MD.

Configure row/column weights:

self.center_frame.columnconfigure(0, weight=1) so cards stretch horizontally with the window.

Ensure mouse wheel scrolling is enabled:

enable_mousewheel(canvas) is already called inside make_scrollable().

Remove any pack_propagate(False) or manual height forcing that conflicts with scroll.

7. Wiring to Controller / App State

Contract

Stage cards should not reach into global state directly; they should receive either:

A controller with get_stage_config(stage_name) / update_stage_config(stage_name, dict) methods, or

A shared AppStateV2 / PipelineState object passed in from the center panel.

Implementation Steps

Add a small adapter in the Pipeline panel:

txt_cfg = controller.get_stage_config("txt2img")
self.txt2img_card.load_from_section(txt_cfg)

def _apply_stage_configs():
    cfg = {}
    cfg.update(self.txt2img_card.to_config_dict())
    cfg.update(self.img2img_card.to_config_dict())
    cfg.update(self.upscale_card.to_config_dict())
    controller.update_pipeline_config(cfg)


Optionally:

Hook _apply_stage_configs to:

A “Apply” button in the Pipeline tab header, and/or

Stage card “changed” callbacks if those exist.

Ensure that when a pipeline is run:

The controller uses the latest merged config (including user edits from the Pipeline tab).

8. Testing Plan
8.1 Manual Smoke Tests

Txt2Img Config Round-Trip

Open Pipeline tab.

Select model/sampler, set width/height, steps, CFG, scheduler, clip skip.

Run a txt2img job; confirm generated image matches chosen resolution and steps.

Restart app; confirm stage card reflects stored defaults / last config as applicable.

Img2Img Denoise & Resolution

Configure Img2Img stage; move Denoise slider and verify numeric value changes.

Confirm API payload shows updated denoise value by checking controller logs or preview.

Adjust width/height and verify they clamp correctly.

Upscale Settings

Set Upscaler, factor, tile size, and face restore.

Run an upscale-only pipeline; verify output size and tile behavior.

Scrolling

Resize the app so the main window height is relatively small.

Confirm the Pipeline center panel shows a vertical scrollbar and that:

All three cards remain at normal height.

Scrolling exposes all controls.

8.2 Automated Tests

Stage Card Config Tests (tests/gui_v2/test_pipeline_stage_cards_v2.py)

Instantiate each advanced stage card in isolation with a dummy parent.

Call load_from_section() with a sample config dict; assert matching widget values.

Modify widgets; call to_config_dict(); assert that the resulting dict matches edited values.

Scrollable Panel Test (tests/gui_v2/test_scrollable_pipeline_panel_v2.py)

Build a minimal Pipeline panel instance.

Assert:

Center column contains a tk.Canvas and a child frame.

Stage cards are children of the scrollable frame.

The canvas has a _vertical_scrollbar attribute (exposed from make_scrollable).

Denoise & Slider Tests

Instantiate Img2Img card.

Programmatically set denoise slider; assert denoise_var.get() matches expected rounded values.

9. Risks & Mitigations

Risk: Mis-mapping field names in to_config_dict() could break existing pipeline behavior.

Mitigation: Use existing ConfigPanel and ADetailer config as reference for field names; add tests validating payload keys.

Risk: Scrollable canvas could interfere with other layouts if placed incorrectly.

Mitigation: Only wrap the Pipeline center column; keep left/right panels unchanged and verify notebook/tab behavior remains stable.