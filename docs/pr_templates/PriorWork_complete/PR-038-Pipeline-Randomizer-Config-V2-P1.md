PR-038-Pipeline-Randomizer-Config-V2-P1

Randomization controls in pipeline config, attached per pack & job

1. Title

PR-038-Pipeline-Randomizer-Config-V2-P1 — Randomization Controls at Job Creation in Pipeline Config

2. Summary

This PR gives the Pipeline tab a proper randomization configuration block:

Randomizer settings (enable, max variants, maybe seed mode, etc.) live in PipelineConfigPanelV2.

These settings are:

Loaded from pack configs when you “Load current config”.

Written back into pack configs via “Apply config to pack(s)”.

Snapshotted into PackJobEntry.config_snapshot when you “Add to Job”.

Randomization is explicitly set at job creation, not at prompt-pack assembly in the Prompt tab.

3. Problem Statement

Currently:

There are randomization concepts (random tokens, variants, etc.) scattered between:

Prompt content (Prompt tab).

Pipeline config in a vague, partial way.

But there is no stable pipeline-level randomization config that is:

editable in one place,

tied to pack configs,

and snapshotted into jobs at creation.

We need:

A dedicated Randomizer card in PipelineConfigPanelV2 that defines how randomization is applied at job creation, per pack.

A consistent way for JobDraft to know:

whether randomization is enabled,

how many variants to generate,

and the relevant knobs.

4. Goals

Randomizer UI in PipelineConfigPanelV2

Randomizer on/off toggle.

Core knobs (exact set depending on existing config model), for example:

Max variants.

Apply mode (e.g., “per pack” / “per prompt” if we already have such a field).

Maybe a flag to randomize seed or keep fixed.

Pack integration

When Load current config is used:

Randomizer settings for that pack populate the randomizer UI.

When Apply config to pack(s) is used:

Randomizer settings from UI are written to selected pack configs.

JobDraft integration

Add to Job snapshots randomizer settings into PackJobEntry.config_snapshot.

Separation of concerns

Prompt tab still owns random tokens in text.

Pipeline randomizer only controls how those tokens are realized at job creation, not what they are.

5. Non-goals

Implementing the actual expansion of random tokens at runtime.

Changing how random tokens are encoded in prompt text.

Implementing the job queue execution logic (beyond snapshotting config).

Designing a complex randomization DSL or new token syntax.

6. Allowed Files

Config & state

src/gui/app_state_v2.py

Extend config structures to include randomizer parameters (if not already).

src/utils/config.py

Ensure presets/packs include randomizer settings.

Controller

src/controller/app_controller.py

Wire load/apply/job-add randomizer fields just like LoRA strengths.

GUI

src/gui/panels_v2/pipeline_config_panel_v2.py

Add Randomizer card (checkbutton + spinbox/entry/etc.).

src/gui/views/pipeline_tab_frame_v2.py

Only if layout needs to be adjusted to place the Randomizer card within the left column stack.

Tests

tests/controller/test_pipeline_randomizer_config_v2.py

tests/gui_v2/test_pipeline_randomizer_panel_v2.py

7. Forbidden Files

src/pipeline/* (runner, sequencer, executor).

src/api/*.

Prompt tab text editing modules.

Learning/queue/cluster modules.

Legacy GUI files.

8. Step-by-step Implementation
Step 1 — Add randomizer fields to config/state

In app_state_v2.py (run/config model):

Add a randomizer section, e.g.:

run_config.randomizer_enabled: bool

run_config.max_variants: int

(Any other minimal existing fields we can expose).

In config.py:

Make sure these are persisted:

In presets.

In per-pack configs.

In default/last-run config.

Step 2 — Randomizer card in PipelineConfigPanelV2

In pipeline_config_panel_v2.py:

Add a “Randomizer” card in the left column stack:

Controls:

Checkbutton: “Enable randomization”.

Numeric input: “Max variants”.

Optional: seed strategy, if already modeled.

Methods:

load_randomizer_config(config: dict[str, Any])

get_randomizer_config() -> dict[str, Any]

Integrate with the panel’s existing config load/save methods so that:

When full config is loaded into UI, randomizer UI updates.

When full config is read back out, randomizer values are included.

Step 3 — Pack config integration

In app_controller.py:

When on_pipeline_pack_load_config(pack_id) runs:

Load pack config, including randomizer fields.

Call pipeline_config_panel.load_randomizer_config(...).

When on_pipeline_pack_apply_config(pack_ids) runs:

Read get_randomizer_config() from the panel.

Write those values into each selected pack’s config.

Ensure preset operations (in PR-040) also include these randomizer fields.

Step 4 — JobDraft snapshot integration

When on_pipeline_add_packs_to_job(pack_ids) builds PackJobEntry.config_snapshot:

Include randomizer settings from the current config.

The Job preview (built in PR-035/036) should be able to display:

Randomizer enabled/disabled per pack.

Max variants (or similar) per pack.

Step 5 — Tests

tests/controller/test_pipeline_randomizer_config_v2.py:

Verify:

on_pipeline_pack_load_config brings randomizer settings into panel.

on_pipeline_pack_apply_config writes randomizer settings back into pack configs.

on_pipeline_add_packs_to_job snapshots randomizer settings.

tests/gui_v2/test_pipeline_randomizer_panel_v2.py:

Build Pipeline tab.

Confirm:

Randomizer card exists (enable toggle, max variants).

Toggling/enabling and changing values updates the config dict returned by get_randomizer_config().

9. Acceptance Criteria

Pipeline tab left column includes a Randomizer card within PipelineConfigPanelV2.

Randomizer settings:

Load from pack configs into UI when Load current config is used.

Are written back to pack configs when Apply config to pack(s) is used.

Are included in PackJobEntry.config_snapshot when packs are added to job.

Job preview on the right can (minimally) indicate randomizer state per pack.

No change to prompt text behavior.

All new tests pass, and existing tests continue to pass.

10. Rollback Plan

Revert:

app_state_v2.py

config.py

app_controller.py

pipeline_config_panel_v2.py

pipeline_tab_frame_v2.py (if touched)

tests/controller/test_pipeline_randomizer_config_v2.py

tests/gui_v2/test_pipeline_randomizer_panel_v2.py

11. Codex Execution Constraints

No randomizer runtime logic — only config wiring.

No editing of Prompt tab behaviors.

No new dependencies.

Keep changes additive and minimal.

12. Smoke Test Checklist

python -m src.main

Open Pipeline tab.

In Randomizer card:

Enable randomization, set max variants to a non-default value.

Select a pack:

Apply config to pack(s) → no error.

Load current config → Randomizer UI shows same values.

Click Add to Job:

Job preview shows that randomization is enabled for that pack.

Repeat with a different pack having different randomizer settings:

Ensure snapshot and preview reflect per-pack differences.