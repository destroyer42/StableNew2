PR-052 — Stage Card Visual Cleanup & Dark Theme Alignment (V2-P1)
Summary

The Pipeline tab’s stage card visuals still contain legacy wrappers, duplicated header labels, and white-background ttk widgets that break the dark theme. This PR removes the leftover V1-style scaffolding and applies the existing design system styles consistently.

Goals

Remove redundant frame wrappers around stage cards.

Ensure each stage card has one header and one content body.

Apply existing dark theme styles everywhere.

Normalize the appearance of left panel cards and center stage cards.

Allowed Files

src/gui/views/stage_cards_panel_v2.py

src/gui/stage_cards_v2/base_stage_card_v2.py

src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py

src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py

src/gui/stage_cards_v2/adetailer_stage_card_v2.py

src/gui/panels_v2/sidebar_panel_v2.py

Forbidden Files

src/gui/theme_v2.py (no new tokens)

Any controller/pipeline code

Implementation Plan
1. Remove redundant wrappers

Many cards contain outer “wrapper frames” with a duplicate header label.

Remove these and keep a single:

+-----------------------------+
| Header (title + toggle)     |
+-----------------------------+
| Body                        |
+-----------------------------+

2. Standardize card header

Use design-system styles:

CARD_FRAME_STYLE

HEADING_LABEL_STYLE

StageHeader.TFrame

Header shows only:

Stage name (left)

Enable checkbox + collapse toggle (right)

3. Dark theme controls

Replace any default white ttk widgets with versions using:

TCombobox dark style

TEntry dark style

TSpinbox dark style

No theme changes—only widget assignments.

4. Left panel alignment

Update left panel cards to match the same card pattern as center stage cards.

Validation
Tests

Update:

tests/gui_v2/test_stage_cards_layout_v2.py
(or create if missing)

Assert:

One header per card

Body directly under header

No empty wrappers

Manual Validation

All widgets use dark styles.

All stage cards (txt2img/img2img/upscale/adetailer) look consistent.

Definition of Done

Visual consistency across all stage cards.

Dark theme fully respected.

No wrappers or duplicate headings.

No regressions in card behavior.