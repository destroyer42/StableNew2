Script for PR-#55 – Model Manager Panel V2

Spec file:
docs/pr_templates/PR-#55-GUI-V2-ModelManagerPanel-001.md

1. Read & Summarize

Read docs/pr_templates/PR-#55-GUI-V2-ModelManagerPanel-001.md.

Reply summarizing:

What Model Manager Panel V2 should expose (model checkpoint, VAE, refresh).

How these selections flow through overrides and assembler into PipelineConfig.

Which files are allowed.

Which tests must pass.

2. Allowed vs Forbidden Files

You may modify/create:

GUI:

src/gui/model_manager_panel_v2.py (new)

src/gui/sidebar_panel_v2.py

src/gui/app_layout_v2.py

src/gui/main_window.py (wiring only)

Adapter / Assembler / Helper:

src/gui/pipeline_adapter_v2.py

src/controller/pipeline_config_assembler.py

src/gui/model_list_adapter_v2.py (new, thin wrapper over existing model listing, if needed)

src/config/app_config.py (model/vae defaults)

Tests:

tests/gui_v2/test_model_manager_panel_v2.py (new)

tests/controller/test_pipeline_config_assembler_model_fields.py (new or extend)

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

src/api/* (beyond calling existing model-list APIs through a small adapter)

3. Implementation Steps

Model list helper (if needed)

Add src/gui/model_list_adapter_v2.py:

Functions to return lists of models/VAEs using existing APIs/configs.

If equivalent helpers already exist, reuse instead of duplicating.

ModelManagerPanelV2

Create src/gui/model_manager_panel_v2.py:

ttk.Frame with:

Model dropdown.

VAE dropdown (if applicable).

“Refresh” button calling the adapter to reload lists.

Methods:

get_selections() -> dict (model_name, vae_name)

set_selections(...)

Wire into GUI V2

Integrate into sidebar_panel_v2.py / app_layout_v2.py.

Minimal wiring changes in main_window.py.

Extend GuiOverrides

In pipeline_adapter_v2.py:

Add model_name and optionally vae_name to overrides.

Populate from ModelManagerPanelV2 (fallback to app_config defaults).

Assembler mapping

In pipeline_config_assembler.py:

Accept and map model_name / vae_name into PipelineConfig.

Docs & summary

Update docs to mention GUI V2 Model Manager as the model selection path.

Append PR-55 to ROLLING_SUMMARY.md.

4. Tests to Run

Focused:

pytest tests/gui_v2/test_model_manager_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v

Suites:

pytest tests/gui_v2 -v

pytest tests/controller -v

Optionally:

pytest -v

5. Final Report Back

Include:

Changed files.

Summary of implementation.

Commands run.

Full output for:

pytest tests/gui_v2/test_model_manager_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_model_fields.py -v

pytest tests/gui_v2 -v

pytest tests/controller -v

pytest -v (if run).