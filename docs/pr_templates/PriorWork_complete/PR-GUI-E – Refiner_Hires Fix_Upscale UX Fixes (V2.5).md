PR-GUI-E – Refiner_Hires Fix_Upscale UX Fixes (V2.5).md

2. Summary

This PR fixes the stage-panel UX for Refiner, Hires Fix, and Upscale so that:

The Refiner and Hires Fix enable checkboxes actually show/hide their detailed options (instead of always showing a dense card).

The Hires Fix card exposes a model selector that defaults to the base model but can be overridden.

Denoise/strength sliders and upscale controls have clear numeric indicators so users aren’t guessing at values.

The Upscale panel’s final size calculation no longer shows 0x0, but correctly reflects the current base dimensions × scale.

This PR is a GUI-only UX polish for stage cards, anchored on the existing ConfigMergerV2 + JobBuilderV2 semantics and the GUI wishlist plan’s PR-GUI-E scope.

3. Problem Statement

From the GUI Wishlist:

“Enable refiner checkbox should show/hide refiner options.”

“Same issue with hires fix checkbox (needs to hide/show hires fix options).”

“Refiner slider goes all the way to the right and no numeral to show what percent the slider is at, leading to guessing at the percentage.”

“Denoise slider doesn’t show any number, so impossible to know what the amount/number is.”

“Hires fix needs to have a model selector if the user doesn’t want to use the base model…”

“Final size calculation on upscale seems broken (says 0x0 regardless of selections).”

Current symptoms:

Refiner and Hires cards feel “always-on,” visually cluttered, and don’t visually respect the enable checkboxes.

Users can’t see exact refiner/denoise values at a glance; they have to guess based on slider position.

The Upscale panel’s final-size label (0x0) is misleading and doesn’t help users understand output size.

Hires Fix cannot select a model explicitly, even though the architecture supports an override via ConfigMergerV2 and JobBuilderV2.

We need to bring the stage-panels’ behavior in line with the v2.5 architecture and GUI roadmap without re-implementing merging or job-building logic.

4. Goals

Stage toggles control visibility

Enable Refiner checkbox:

When unchecked → hide inner refiner options (strength, switch-at-step, model, etc.).

When checked → show inner options.

Enable Hires Fix checkbox:

Same behavior for Hires sub-panel.

Hires Fix model selector

Add a Hires model combobox:

Defaults to “Use base model” or the base model name.

If user selects a different model, it populates the hires override fields such that ConfigMergerV2 interprets this as an override (no new merge logic).

Numeric indicators on key sliders

Ensure the following have visible numeric values in the card, not just the slider:

Refiner strength / switch percentage (0–1 or 0–100%, depending on current representation).

Hires denoise slider.

Upscale denoise, scale, and tile size sliders/fields.

These can be small labels next to the sliders or integrated into the existing label area, consistent with PR-GUI-A theming work.

Correct Upscale final size calculation

Final size label should:

Show width x height based on current base dimensions and upscale factor.

Update live when width/height or scale change.

Uses existing config values from the Upscale panel/AppState; no new pipeline math or executor changes.

Respect existing architecture

Stage enable flags, models, denoise values, etc. must continue to flow through:

Stage cards → AppState → ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord.

No direct pipeline calls from GUI, no custom merging logic inside panels.

5. Non-Goals

No changes to ConfigMergerV2 or JobBuilderV2 behavior (those are established in the 204-series PRs).

No changes to the randomizer engine, seed behavior, or queue semantics.

No theming/dark-mode changes outside what’s necessary for slider labels to be readable (general theming covered by PR-GUI-A).

No changes to Preview/Queue layout (covered by PR-GUI-F/G/H).

No re-ordering of stages or pipeline logic.

6. Allowed Files

Stage panels only, plus minimal shared helpers:

src/gui/panels_v2/refiner_panel_v2.py

src/gui/panels_v2/hires_panel_v2.py

src/gui/panels_v2/upscale_panel_v2.py

src/gui/panels_v2/core_config_panel_v2.py (only if needed for final-size base width/height or to expose read-only getters)

src/gui/app_state_v2.py (only if a small accessor is needed to read base width/height or base model name for labels)

tests/gui_v2/test_refiner_hires_upscale_ux_v2.py (new)

7. Forbidden Files

Do not modify:

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/main.py

Any pipeline/executor core:

src/pipeline/executor.py, src/pipeline/executor_v2.py, src/pipeline/pipeline_runner_v2.py, etc.

Queue / JobService:

src/pipeline/job_service.py, src/pipeline/job_queue_v2.py, etc.

204-series core modules:

src/pipeline/config_merger_v2.py

src/pipeline/job_builder_v2.py

src/pipeline/job_models_v2.py

If you discover a real need to change any of these, stop and spin a separate, explicitly scoped PR.

8. Step-by-Step Implementation
A. Refiner panel show/hide behavior

File: src/gui/panels_v2/refiner_panel_v2.py

Identify the existing Enable Refiner checkbox:

Likely bound to a tk.BooleanVar or similar.

Group all refiner option widgets (model selector if present, strength, switch-at, etc.) into a dedicated container frame, e.g.:

self._options_frame = ttk.Frame(self)
# existing controls re-parented into this frame


Add a helper:

def _update_refiner_visibility(self) -> None:
    enabled = bool(self._enable_refiner_var.get())
    if enabled:
        self._options_frame.grid()  # or pack/place according to existing layout
    else:
        self._options_frame.grid_remove()


Attach the helper to the checkbox:

self._enable_refiner_checkbutton.configure(command=self._update_refiner_visibility)


Ensure load_from_config() / equivalent initialization calls _update_refiner_visibility() so the panel reflects the current config on load.

Stage-enable behavior continues to be driven by whatever value is stored in AppState/config; we’re just making the UI match it.

B. Hires Fix panel show/hide behavior

File: src/gui/panels_v2/hires_panel_v2.py

Mirror the same pattern for Enable Hires Fix:

Group all Hires options (denoise slider, scale, steps, model selector) into a container frame.

Add _update_hires_visibility() that hides/shows the frame based on the enable variable.

Wire checkbox command to call _update_hires_visibility().

Call _update_hires_visibility() during initialization after loading config.

C. Hires Fix model selector

File: src/gui/panels_v2/hires_panel_v2.py (and possibly a minimal accessor in app_state_v2.py)

Add a ttk.Combobox (or existing combobox pattern) for the Hires model:

Items:

First item: “Use base model” (or actual base model name from AppState if accessible).

Additional items: from the same model list used by the txt2img model selector (reuse data source if already available in the panel).

Value semantics:

If “Use base model” selected → hires_model_override field in the panel’s config output should be None (or not set), so ConfigMergerV2 falls back to the base model.

If a different model selected → panel writes that model ID/name into the hires override section that ConfigMergerV2 already knows how to merge.

Extend panel’s to_config_dict() or equivalent mapping:

When building the dict to send to AppState:

Include hires_model or hires_model_override field only if a non-default model is chosen.

When calling load_from_config():

If the hires override model equals the base model or is missing, select “Use base model”.

Otherwise select the matching item in the combobox.

Important: do not add custom merging logic here; simply reflect the user’s choice into the existing override fields that ConfigMergerV2 already understands (as per the 204A spec).

D. Numeric indicators for Refiner & Hires sliders

Files:

src/gui/panels_v2/refiner_panel_v2.py

src/gui/panels_v2/hires_panel_v2.py

For each key slider:

Refiner strength / weight / switch percentage.

Hires denoise slider.

Implement a small ttk.Label bound to the same variable or updated on <Motion> / command callback:

def _on_refiner_strength_changed(self, value: str) -> None:
    # value typically str from Scale; convert if needed
    self._refiner_strength_label.configure(text=f"{float(value):.2f}")


Configure sliders:

self._refiner_strength_scale.configure(command=self._on_refiner_strength_changed)


On load (load_from_config()), call the handlers explicitly to ensure the numeric labels are correct when the panel first appears.

Keep formatting simple and consistent with PR-GUI-A decisions (e.g., 0.00 or %); if A chose a specific format, reuse it.

E. Numeric indicators for Upscale sliders

File: src/gui/panels_v2/upscale_panel_v2.py

For Upscale:

Denoise slider.

Scale slider (e.g., 1.0–4.0).

Tile size (if slider-based).

Potentially steps, if slider-based.

Add numeric labels and callbacks, same pattern as above.

Ensure the labels are placed in the same row as the slider or in a small right-aligned column to avoid layout breakage.

F. Fix Upscale final size calculation

Files:

src/gui/panels_v2/upscale_panel_v2.py

src/gui/panels_v2/core_config_panel_v2.py or src/gui/app_state_v2.py (only if needed for base dimensions)

Identify where the “final size” label is created (currently shows 0x0):

It likely uses some width, height, and scale values but isn’t wired correctly.

Introduce a helper in Upscale panel:

def _update_final_size_label(self) -> None:
    base_width = self._get_base_width()
    base_height = self._get_base_height()
    scale = float(self._scale_var.get() or 1.0)

    if base_width and base_height:
        final_w = int(base_width * scale)
        final_h = int(base_height * scale)
    else:
        final_w = final_h = 0

    self._final_size_label.configure(text=f"{final_w} x {final_h}")


Implement _get_base_width() / _get_base_height() to read from:

Either the Upscale panel’s own width/height controls (if present), or

A simple accessor on AppState/core config panel that exposes current base width/height (read-only).

Wire _update_final_size_label() to:

Scale slider change.

Any base width/height spinbox changes (if present in Upscale or Core config panels).

Initial load of the panel.

If base width/height are unknown, keep 0 x 0 but prefer to grey out or indicate “Unknown (no base size)” rather than misleading; however, do not add new theming—just text.

9. Required Tests

New test file:

tests/gui_v2/test_refiner_hires_upscale_ux_v2.py

Suggested tests (Tk-dependent; mark with skip if Tk unavailable):

Refiner visibility toggles with checkbox

Instantiate RefinerPanelV2 with a fake config (enabled=True).

Verify _options_frame (or equivalent) is mapped (visible).

Set checkbox var to False, call its command; assert frame is hidden (winfo_ismapped() == 0).

Toggle back to True, assert visible again.

Hires visibility toggles with checkbox

Same pattern for HiresPanelV2.

Hires model selector semantics

Load base config where hires model override is absent or equals base model → combobox shows “Use base model”.

Load config with override model m_custom → combobox shows m_custom.

Change selection from “Use base model” to m_other: assert to_config_dict() includes hires model override with m_other.

Change back to “Use base model”: assert override is None/absent.

Refiner slider numeric label updates

Set refiner strength slider to 0.35; fire callback; assert label text is "0.35" (or relevant format).

After load_from_config(strength=0.5), assert label shows the config value.

Hires denoise slider numeric label updates

Similar to refiner, for hires denoise.

Upscale slider numeric label updates

Set scale slider to 2.0; assert numeric label updates accordingly.

Set denoise/tile size; assert labels updated.

Upscale final size calculation works

Provide base width/height (e.g., 1024x1024) via fake config or AppState accessor.

Set scale=2.0; call _update_final_size_label(); assert label text "2048 x 2048".

Change scale to 1.5; assert label "1536 x 1536" (or rounded appropriately).

All existing tests (including 204A/B/C/D and other GUI tests) must remain green aside from known pre-existing failures.

10. Acceptance Criteria

PR-GUI-E is complete when:

Refiner / Hires visibility

The Refiner and Hires Fix cards hide their inner options when disabled and show them when enabled.

Loading a config with refiner/hires disabled starts with the options collapsed.

Hires model selector

Hires panel exposes a model selector with a “Use base model” default.

Selecting a specific model sets the appropriate hires override field used by ConfigMergerV2.

Using “Use base model” results in no override (or None), so the base model is used.

Numeric indicators

Refiner strength and Hires denoise sliders show numeric values.

Upscale sliders (scale, denoise, tile size, etc.) show numeric values.

These remain readable in dark mode (with PR-GUI-A).

Upscale final size

Final size label reflects base_width x base_height times scale.

Updating width/height or scale updates the label.

The previous 0x0 bug is no longer present for normal use.

Architectural alignment

No changes to ConfigMergerV2, JobBuilderV2, or pipeline/queue core.

Stage enable flags, models, and values still flow through the established config/merger/jobbuilder path.

11. Rollback Plan

If this PR introduces regressions (e.g., panels disappearing, wrong models applied, incorrect sizes):

Revert:

src/gui/panels_v2/refiner_panel_v2.py

src/gui/panels_v2/hires_panel_v2.py

src/gui/panels_v2/upscale_panel_v2.py

Any small change in src/gui/app_state_v2.py or core_config_panel_v2.py made for base dimension access.

tests/gui_v2/test_refiner_hires_upscale_ux_v2.py.

Run tests:

python -m pytest tests/gui_v2/test_refiner_hires_upscale_ux_v2.py -q

python -m pytest -q

Confirm:

Panels are back to the previous visual behavior (even if less polished).

No change to pipeline behavior