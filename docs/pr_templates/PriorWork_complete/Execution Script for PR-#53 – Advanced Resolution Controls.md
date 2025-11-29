Execution Script for PR-#53 – Advanced Resolution Controls V2

Spec file:
docs/pr_templates/PR-#53-GUI-V2-ResolutionAdvancedControls-001.md

1. Read & Summarize

Read docs/pr_templates/PR-#53-GUI-V2-ResolutionAdvancedControls-001.md.

Reply summarizing:

What the new resolution controls should support (width/height, presets, ratios).

How resolution data should move from GUI → overrides → assembler → config.

Which files are in scope.

Which tests must pass.

2. Allowed vs Forbidden Files

You may modify/create:

GUI:

src/gui/resolution_panel_v2.py (new)

src/gui/core_config_panel_v2.py

src/gui/sidebar_panel_v2.py

src/gui/app_layout_v2.py

src/gui/main_window.py (wiring only)

Adapter / Assembler / Config:

src/gui/pipeline_adapter_v2.py

src/controller/pipeline_config_assembler.py

src/config/app_config.py (defaults for resolution/presets, if needed)

Tests:

tests/gui_v2/test_resolution_panel_v2.py (new)

tests/controller/test_pipeline_config_assembler_resolution.py (new or extend)

Docs:

docs/PIPELINE_RULES.md

docs/ARCHITECTURE_v2_COMBINED.md

docs/codex_context/ROLLING_SUMMARY.md

You must not modify:

src/pipeline/*

src/queue/*

src/cluster/*

src/learning*

src/randomizer*

src/api/*

3. Implementation Steps

ResolutionPanelV2

Create src/gui/resolution_panel_v2.py:

ttk.Frame subclass with:

Width and height fields.

Resolution preset dropdown (a handful of curated presets).

Optional ratio helper dropdown.

Optional label showing approximate megapixels.

Methods:

get_resolution() -> tuple[int, int]

set_resolution(width: int, height: int)

Embed in Core Config or Sidebar

Integrate into core_config_panel_v2.py and/or sidebar_panel_v2.py.

Ensure it’s visible in the V2 layout via app_layout_v2.py.

Extend GuiOverrides

In pipeline_adapter_v2.py:

Add width and height to overrides.

Read them from ResolutionPanelV2, fallback to defaults if not set.

Assembler mapping & clamping

In pipeline_config_assembler.py:

Read width/height from overrides.

Apply existing megapixel clamp logic.

Set final width/height on PipelineConfig.

Docs & summary

Update docs to describe the advanced resolution controls.

Add PR-53 entry to ROLLING_SUMMARY.md.

4. Tests to Run

Focused:

pytest tests/gui_v2/test_resolution_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_resolution.py -v

Suites:

pytest tests/gui_v2 -v

pytest tests/controller -v

Optionally:

pytest -v

5. Final Report Back

Include:

Files changed.

Short summary of UI + assembler behavior changes.

Commands run.

Full output for:

pytest tests/gui_v2/test_resolution_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_resolution.py -v

pytest tests/gui_v2 -v

pytest tests/controller -v

pytest -v (if run).