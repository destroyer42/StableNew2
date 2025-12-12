docs/pr_templates/PR-#51-GUI-V2-CoreConfigPanel-001.md

1. Read & Summarize

Open and read the spec file:
docs/pr_templates/PR-#51-GUI-V2-CoreConfigPanel-001.md

In your first reply, summarize in your own words:

What new GUI elements you need to add.

How GuiOverrides and PipelineConfigAssembler should be extended/used.

Which files you’re allowed to touch.

Which tests must pass for this PR to be “done”.

Do not change any code until you’ve written that summary and I’ve acknowledged it.

2. Allowed vs Forbidden Files

You may modify or create only:

GUI:

src/gui/core_config_panel_v2.py (new)

src/gui/sidebar_panel_v2.py

src/gui/app_layout_v2.py

src/gui/main_window.py (wiring only)

Adapter / Assembler / Config:

src/gui/pipeline_adapter_v2.py

src/controller/pipeline_config_assembler.py

src/config/app_config.py

Tests:

tests/gui_v2/test_core_config_panel_v2.py (new)

tests/controller/test_pipeline_config_assembler_core_fields.py (new or extend existing)

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

Any legacy GUI files unless it’s a minimal import fix you explicitly call out.

If you believe a forbidden file must change, stop and tell me instead of editing it.

3. Implementation Steps

Do this in small, clear steps:

app_config core fields

In src/config/app_config.py, add safe getters/setters/defaults for:

model/checkpoint

sampler

steps

cfg scale

resolution preset (e.g., "512x512" etc.)

Do not break existing config; keep changes additive.

CoreConfigPanelV2

Create src/gui/core_config_panel_v2.py:

A ttk.Frame subclass with controls for:

Model

Sampler

Steps

CFG

Resolution preset

Public methods:

get_overrides() → returns a simple dict or small dataclass.

apply_from_overrides(...) for tests / future state restore.

Initialize from app_config defaults where reasonable.

Wire into layout

In sidebar_panel_v2.py / app_layout_v2.py:

Instantiate CoreConfigPanelV2 and add it to an appropriate section.

main_window.py:

Only adjust wiring to pass any needed references; no controller logic here.

Extend GuiOverrides & adapter

In pipeline_adapter_v2.py:

Ensure GuiOverrides (or equivalent) has fields for the core config inputs.

When building overrides, read from CoreConfigPanelV2 first, then fall back to defaults.

Assembler mapping

In pipeline_config_assembler.py:

Make sure build_from_gui_input reads the core config fields from overrides and maps them into PipelineConfig.

Preserve any existing megapixel/resolution logic.

Docs

Update PIPELINE_RULES.md and ARCHITECTURE_v2_COMBINED.md minimally to note:

Core config is driven via GUI V2 → GuiOverrides → assembler.

Append a short PR-51 block to docs/codex_context/ROLLING_SUMMARY.md.

4. Tests to Run

Run these, in this order:

Focused new tests:

pytest tests/gui_v2/test_core_config_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v

Suites:

pytest tests/gui_v2 -v

pytest tests/controller -v

If time is okay:

pytest -v

It’s okay if some GUI tests are skipped because Tk is unavailable, but do not add new skips.

5. Final Report Back

In your final response for this PR, include:

A short list of files you actually changed.

A 3–5 sentence summary of what you implemented.

The exact commands you ran.

The full textual output of:

pytest tests/gui_v2/test_core_config_panel_v2.py -v

pytest tests/controller/test_pipeline_config_assembler_core_fields.py -v

pytest tests/gui_v2 -v

pytest tests/controller -v

And pytest -v if you ran it.

Any follow-up issues or TODOs you think we should handle in later PRs.