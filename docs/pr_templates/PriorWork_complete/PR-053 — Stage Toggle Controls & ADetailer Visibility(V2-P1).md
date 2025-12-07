PR-053 — Stage Toggle Controls & ADetailer Visibility Fixes (V2-P1)
Summary

Stage enablement is currently confusing and non-deterministic. Some stages disappear entirely (e.g., ADetailer), and preset application inconsistently hides cards. This PR adds a simple, predictable stage toggle mechanism and stabilizes ADetailer behavior.

Goals

Add a checkbox in each stage header that controls stage enablement.

Collapsing/expanding the card is separate from enabling/disabling the stage.

Stage visibility must remain stable; ADetailer must not disappear arbitrarily.

Presets must reflect stage enablement cleanly.

Allowed Files

src/gui/stage_cards_v2/base_stage_card_v2.py

src/gui/views/stage_cards_panel_v2.py

src/gui/app_state_v2.py

src/gui/controller.py (GUI controller only)

src/controller/pipeline_controller.py

Forbidden Files

src/pipeline/executor.py

src/main.py

Implementation Plan
1. Stage header checkbox

Add in BaseStageCardV2:

[Stage Name]   [Enabled ✔] [Collapse ▼]


self.enabled_var reflects whether the stage is “in play”.

2. Card body behavior

Collapsing hides body (no functionality change).

Unchecking enabled flag:

Sets enabled=False in AppState.

Still shows header card; body collapses automatically.

3. Preset application

When a preset loads:

stage_enabled = preset["stages"][name]["enabled"]

Header checkbox set accordingly.

Card visibility updated deterministically.

4. Pipeline config

PipelineController must include:

config["stages"][name]["enabled"] = True/False


Consumers downstream interpret this boolean.

Validation
Tests

tests/gui_v2/test_stage_toggle_enabled_flags.py

Checkbox toggles → card body reflects state.

tests/gui_v2/test_adetailer_visibility_v2.py

Preset application does not hide the ADetailer card.

Definition of Done

Each stage card has a working enable toggle.

ADetailer is always visible unless explicitly disabled.

Pipeline config receives consistent enable flags.