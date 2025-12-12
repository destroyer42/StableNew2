Full PR-GUI-A (Theming & Control Polish) Spec.md

(As requested: fully generated, full-detail, Codex-ready PR)

This PR includes only “pure theming/styling/value-visibility fixes,” per the roadmap.
It does not include layout moves, queue controls, or behavior changes.

This correlates with:


PR-GUI-A — Theming & Control Polish (V2.5)

Risk Tier: Low (UI-only, zero logic changes)

1. Summary

This PR fixes all remaining dark-mode inconsistencies, control-styling gaps, slider value visibility problems, and mislabeled elements in the Pipeline Tab.
No layout or behavior changes occur here.
This PR is strictly visual polish.

2. Problem Statement

Despite the v2.5 GUI overhaul, several controls still render with light-mode popups, invisible spinner borders, or missing slider value labels, breaking UX coherence.

These issues span across Core, Refiner, Hires Fix, and Upscale panels.

Users cannot reliably understand values like:

Refiner strength

Hires Denoise amount

Upscale Denoise / Steps / Scale / Tile Size / Face Restore level

Additionally, some labels (e.g., SDXL Refiner) still use light-mode colors.

3. Goals

Achieve full dark-mode compliance across every widget in the Pipeline tab.

Add numeric indicators for all sliders (value displayed next to the slider).

Apply consistent styling to:

Spinboxes

Dropdown/combo popups

Slider labels

Ensure all text and borders match theme_v2 color tokens.

4. Non-Goals

No widget is moved.

No wiring or pipeline behavior is changed.

No queue or preview changes occur here.

No config logic is modified—only how values are visibly represented.

5. Scope – Allowed Files

All changes confined to GUI V2 visual layer:

src/gui/theme_v2.py  
src/gui/panels_v2/core_config_panel_v2.py  
src/gui/panels_v2/refiner_panel_v2.py  
src/gui/panels_v2/hires_panel_v2.py  
src/gui/panels_v2/upscale_panel_v2.py  
src/gui/widgets_v2/* (if shared widgets need style updates)

6. Forbidden Files

Absolutely no changes allowed to:

src/pipeline/*
src/controller/*
src/pipeline_controller.py  
src/pipeline/job_builder_v2.py  
src/pipeline/config_merger_v2.py  
src/pipeline/randomizer_engine_v2.py  
src/main.py  
src/gui/main_window_v2.py (layout forbidden)  


Theme-only PR → zero logic.

7. Step-by-Step Implementation Plan
A. Fix dark-mode on Spinboxes (Steps/CFG/etc.)

Update theme_v2 to supply dark-mode ttk style for:

TSpinbox

TEntry fallback if needed

Apply updated style in CoreConfigPanelV2.

B. Fix dark-mode dropdowns

Tk combobox popups must apply a dark listbox background + dark hover color.

Override ttk.Combobox popup styling in theme_v2 using:

TComboboxPopdownFrame

TComboboxListbox

Apply consistently across:

CoreConfig

Refiner

Hires

Upscale

C. Add numeric labels for ALL sliders

Each slider gets a small right-aligned ttk.Label showing its current value:

Refiner strength (0–1 float → show percent)

Hires denoise

Upscale:

Steps

Denoise

Scale

Tile size

Face restore intensity (if slider exists)

Implementation pattern:

Slider.on_change → update label text

Labels inherit dark-mode foreground/background from theme_v2 tokens.

D. Fix SDXL Refiner label color

In refiner_panel_v2.py:

Ensure label uses theme_v2 label_fg, label_bg

If base theme class doesn't support text color override, add style in theme_v2.

E. Apply theme fixes to upscale controls

Upscale panel currently shows several controls in light mode:

Create reusable dark-mode style for:

Numeric entries

Dropdowns

Sliders

Apply to all controls using shared widget wrapper classes in widgets_v2 if available.

8. Tests Required

GUI tests (skip when Tk unavailable):

Test 1 — Spinboxes use dark style

Instantiate CoreConfigPanel

Verify spinbox widget style name includes theme_v2 dark class

Test 2 — Dropdown popup background is dark

Trigger combobox popup event

Inspect listbox color via tk widget introspection

Test 3 — Slider value labels update

Set slider.value programmatically

Assert label displays new numeric value

Test 4 — Refiner label color

Assert label foreground/background match theme tokens

Test 5 — Upscale controls dark-mode compliance

Each widget style asserted to match dark-mode style

No behavioral assertions allowed.

9. Acceptance Criteria

All widgets use theme_v2 dark palette.

All sliders show numeric values.

No panel displays light-mode elements.

Tests all pass.

No logic diff appears in pipeline/controller layers.

10. Rollback Plan

Revert the following:

src/gui/theme_v2.py  
src/gui/panels_v2/core_config_panel_v2.py  
src/gui/panels_v2/refiner_panel_v2.py  
src/gui/panels_v2/hires_panel_v2.py  
src/gui/panels_v2/upscale_panel_v2.py  
src/gui/widgets_v2/* (if modified)
tests/gui_v2/test_theming*.py


Restores previous theme without altering behavior.

11. Potential Pitfalls (Guidance for Copilot/Codex)

Do NOT move widgets or change flow

A common LLM error is “fixing the UI” by rearranging controls.

Absolutely forbidden in PR-GUI-A.

Do NOT alter slider default values or ranges

Only add numeric display, not new behavior.

Do NOT modify controller/pipeline files

Some models mistakenly add tooltip logic or validation into controller classes.

This PR touches only theme + panel widget styling.