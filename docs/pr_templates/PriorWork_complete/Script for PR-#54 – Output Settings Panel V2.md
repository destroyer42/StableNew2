Execution Script for PR-#54 – Output Settings Panel V2

Spec file:
docs/pr_templates/PR-#54-GUI-V2-OutputSettingsPanel-001.md

1. Read & Summarize

Read docs/pr_templates/PR-#54-GUI-V2-OutputSettingsPanel-001.md.

Reply summarizing:

Which output settings we’re exposing (directory/profile, filename pattern, batch size, format, maybe seed mode).

How they should flow into GuiOverrides and PipelineConfig.

Which files are allowed.

Which tests must pass.

2. Allowed vs Forbidden Files

You may modify/create:

GUI:

src/gui/output_settings_panel_v2.py (new)

src/gui/sidebar_panel_v2.py

src/gui/app_layout_v2.py

src/gui/main_window.py (wiring only)

Adapter / Assembler / Config:

src/gui/pipeline_adapter_v2.py

src/controller/pipeline_config_assembler.py

src/config/app_config.py

Tests:

tests/gui_v2/test_output_settings_panel_v2.py (new)

tests/controller/test_pipeline_config_assembler_output_settings.py (new)

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

Any low-level I/O that actually writes files (beyond consuming PipelineConfig).

3. Implementation Steps

OutputSettingsPanelV2

Build src/gui/output_settings_panel_v2.py:

Controls:

Output directory/profile (entry + browse or dropdown).

Filename pattern.

Batch size (image count).

Image format combo (e.g., png/jpg/webp).

Seed strategy control if it’s already modeled.

Methods:

get_output_overrides() -> dict

apply_from_overrides(...)

Wire into layout

Integrate into sidebar via sidebar_panel_v2.py and app_layout_v2.py.

main_window.py: only minimal wiring.

Extend GuiOverrides

In pipeline_adapter_v2.py:

Add fields for output_dir/profile, filename_pattern, batch_size, image_format, and optionally seed_mode.

Populate from OutputSettingsPanelV2.

Assembler mapping

In pipeline_config_assembler.py:

Map output settings from overrides into PipelineConfig fields the pipeline already expects.

Docs & summary

Update docs to include the new output configuration path.

Add PR-54 entry to ROLLING_SUMMARY.md.

4. Tests to Run

Focused:

pytest tests/gui_v2/test_output_settings_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v

Suites:

pytest tests/gui_v2 -v

pytest tests/controller -v

Optionally:

pytest -v

5. Final Report Back

Include:

Files changed.

Summary of the UI + config changes.

Commands run.

Full output for:

pytest tests/gui_v2/test_output_settings_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_output_settings.py -v

pytest tests/gui_v2 -v

pytest tests/controller -v

pytest -v (if run).
