Script for PR-#52 – Negative Prompt Panel V2

Spec file:
docs/pr_templates/PR-#52-GUI-V2-NegativePromptPanel-001.md

1. Read & Summarize

Read docs/pr_templates/PR-#52-GUI-V2-NegativePromptPanel-001.md.

Reply with:

What the new Negative Prompt Panel V2 should do.

How negative prompt should flow from GUI → overrides → assembler → config.

Which files you’re allowed to change.

Which tests need to pass.

No code changes until you’ve produced that summary.

2. Allowed vs Forbidden Files

You may modify/create:

GUI:

src/gui/negative_prompt_panel_v2.py (new)

src/gui/sidebar_panel_v2.py

src/gui/app_layout_v2.py

src/gui/main_window.py (wiring only)

Adapter / Assembler / Config:

src/gui/pipeline_adapter_v2.py

src/controller/pipeline_config_assembler.py

src/config/app_config.py (optional default negative prompt)

Tests:

tests/gui_v2/test_negative_prompt_panel_v2.py (new)

tests/controller/test_pipeline_config_assembler_negative_prompt.py (new)

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

If something outside that set looks necessary, stop and report.

3. Implementation Steps

NegativePromptPanelV2

Create src/gui/negative_prompt_panel_v2.py:

ttk.Frame subclass with:

A multi-line text widget.

A “Clear” button.

Optional “Reset to default” if using an app_config default.

Methods:

get_negative_prompt() -> str

set_negative_prompt(text: str) -> None

Integrate into layout

In sidebar_panel_v2.py / app_layout_v2.py:

Instantiate the panel under a “Negative Prompt” section.

In main_window.py:

Only adjust wiring as needed; no controller logic.

Extend GuiOverrides

In pipeline_adapter_v2.py:

Add a negative_prompt field to overrides.

Populate it from NegativePromptPanelV2 (or legacy field if panel is absent).

Assembler mapping

In pipeline_config_assembler.py:

Ensure build_from_gui_input reads negative_prompt from overrides and maps it into PipelineConfig (and WebUI payload if applicable).

Docs & summary

Update docs to mention NegativePromptPanelV2 as the canonical negative prompt surface for GUI V2.

Append PR-52 to ROLLING_SUMMARY.md.

4. Tests to Run

Focused:

pytest tests/gui_v2/test_negative_prompt_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v

Suites:

pytest tests/gui_v2 -v

pytest tests/controller -v

Optionally:

pytest -v

5. Final Report Back

Include:

Changed files list.

Short summary of what you implemented.

Commands run.

Full output for:

pytest tests/gui_v2/test_negative_prompt_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_negative_prompt.py -v

pytest tests/gui_v2 -v

pytest tests/controller -v

pytest -v (if run).