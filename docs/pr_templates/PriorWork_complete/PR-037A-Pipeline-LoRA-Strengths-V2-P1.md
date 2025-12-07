

PR-037A-Pipeline-LoRA-Strengths-V2-P1

Attach LoRA strength sliders to pipeline configs, packs, and jobs

1. Title

PR-037-Pipeline-LoRA-Strengths-V2-P1 — LoRA Strength Controls in Pipeline Config & JobDraft Snapshots

2. Summary

This PR:

Adds LoRA strength controls to the Pipeline tab left-column config (inside PipelineConfigPanelV2), separate from prompt editing.

Ensures LoRA strengths are:

Loaded from a pack’s config when you click “Load current config” in the Pipeline tab.

Written back into pack configs when you click “Apply config to pack(s)”.

Snapshotted into each JobDraft pack entry when you click “Add to Job”.

Leaves LoRA tokens entirely in the Prompt tab; Pipeline only controls the numeric strengths.

3. Problem Statement

Right now:

LoRA tokens live only in prompt text (correct).

LoRA strengths are not explicitly modeled or controllable in the Pipeline tab:

You can’t easily see or tweak the per-LoRA strength per pack from the config view.

Pack configs and JobDraft snapshots lack explicit LoRA strength parameters.

This makes it hard to:

Dial in “People” vs “Armor” or “Background” LoRAs.

Apply consistent strength patterns across multiple packs.

Persist strengths into jobs and history.

We need a single place where LoRA strengths are managed:
→ Pipeline tab config, wired into pack configs and JobDraft.

4. Goals

Expose LoRA strengths in PipelineConfigPanelV2

Show a set of sliders (or numeric inputs) for each active LoRA.

These strengths are part of the pipeline RunConfig / pack config.

Pack config integration

Load current config pulls LoRA strengths from the selected pack’s config into the sliders.

Apply config to pack(s) writes the current LoRA strengths back to each selected pack’s config.

JobDraft integration

When Add to Job is invoked:

LoRA strengths are included in each PackJobEntry.config_snapshot.

Keep prompt editing separate

LoRA tokens remain in the Prompt tab (no change).

Pipeline tab never modifies prompt text; it only manages numeric strengths.

5. Non-goals

Discovering LoRAs automatically from Stable Diffusion models or WebUI (we assume the list is already known or configured).

Adding or removing LoRA tokens in prompts.

Implementing any learning or auto-tuning of LoRA strengths.

UI beautification beyond necessary layout and basic styling.

6. Allowed Files

Config & state

src/gui/app_state_v2.py

Add LoRA strength mapping to the config-related structures if it’s not already present.

src/utils/config.py

Extend config serialization to include LoRA strengths (if this isn’t already there).

Controller

src/controller/app_controller.py

Only for:

Reading/writing LoRA strengths in pack configs.

Including LoRA strengths in PackJobEntry.config_snapshot.

GUI

src/gui/panels_v2/pipeline_config_panel_v2.py

New LoRA Strengths section.

src/gui/views/pipeline_tab_frame_v2.py

Only if needed to mount the LoRA section card inside the left column stack.

src/gui/panels_v2/sidebar_panel_v2.py

Only if minor wiring is required to pass pack IDs or config keys into the controller when buttons are clicked.

Tests

tests/controller/test_pipeline_lora_strengths_v2.py

tests/gui_v2/test_pipeline_lora_strength_panel_v2.py

7. Forbidden Files

Do not modify:

src/pipeline/* (runner, executor, sequencer).

src/api/*.

Any Prompt tab files that deal with text (prompt_tab_frame_v2, advanced editor, etc.).

Learning, queue, cluster modules.

Legacy GUI (non-V2).

If it seems necessary to touch those to complete this PR, stop and report instead.

8. Step-by-step Implementation
Step 1 — Extend config/state to carry LoRA strengths

In app_state_v2.py (and/or the config struct used for RunConfig):

Add a structure to hold LoRA strengths, for example:

run_config.lora_strengths: dict[str, float]

Keyed by LoRA name or ID.

Values are floats in [0.0, 2.0] (for example; range can be conservative).

In config.py:

Ensure config serialization/deserialization includes lora_strengths:

Presets.

Pack configs.

Default config.

Step 2 — LoRA Strengths section in PipelineConfigPanelV2

In pipeline_config_panel_v2.py:

Add a “LoRA Strengths” card in the left column config stack:

For each known LoRA (source can be:

A static list, or

A list from ConfigManager or AppStateV2):

Render:

Label: LoRA name.

Slider (or spinbox) for strength.

Add methods like:

load_lora_strengths(strengths: dict[str, float])

get_lora_strengths() -> dict[str, float]

Hook these into the panel’s existing “load config into UI” / “read config from UI” flow.

Step 3 — Pack config integration (controller)

In app_controller.py:

When on_pipeline_pack_load_config(pack_id) is called (from PR-035):

Load the pack’s config, including lora_strengths.

Call pipeline_config_panel.load_lora_strengths() with these values.

When on_pipeline_pack_apply_config(pack_ids: list[str]) is called:

Read current LoRA strengths via pipeline_config_panel.get_lora_strengths().

Write them into the config for each selected pack.

When preset operations run (PR-040 later):

Ensure LoRA strengths are part of what gets:

Applied to default.

Applied to packs.

Loaded into stages.

Saved into presets.

Step 4 — JobDraft snapshot integration

In app_controller.py (existing on_pipeline_add_packs_to_job logic from PR-035):

When building PackJobEntry.config_snapshot:

Include lora_strengths from the current RunConfig/pipeline config panel.

This ensures the job preview and future runs know which LoRA strengths were active at job creation.

Step 5 — Tests

tests/controller/test_pipeline_lora_strengths_v2.py:

Test that:

Loading config for a pack pulls lora_strengths into the panel.

Applying config to pack(s) persists lora_strengths back.

Adding packs to job includes lora_strengths in config_snapshot.

tests/gui_v2/test_pipeline_lora_strength_panel_v2.py:

Build Pipeline tab.

Confirm:

LoRA strengths panel renders expected sliders.

Adjusting sliders updates the internal dict from get_lora_strengths().

9. Acceptance Criteria

Pipeline tab left column shows a LoRA Strengths section in PipelineConfigPanelV2.

LoRA strengths are:

Loaded from pack configs when Load current config is used.

Written back to pack configs via Apply config to pack(s).

Included in config_snapshot when packs are added to JobDraft.

Prompt text and LoRA tokens remain in Prompt tab; Pipeline tab does not edit them.

All new tests pass, no regressions in existing tests.

10. Rollback Plan

Revert:

app_state_v2.py

config.py

app_controller.py

pipeline_config_panel_v2.py

pipeline_tab_frame_v2.py (if touched)

sidebar_panel_v2.py (if touched)

tests/controller/test_pipeline_lora_strengths_v2.py

tests/gui_v2/test_pipeline_lora_strength_panel_v2.py

This removes LoRA strength UI and config integration, returning to the prior behavior.

11. Codex Execution Constraints

Do not modify Prompt tab behavior.

Keep LoRA strength logic purely in config/state; no changes to pipeline execution.

No new external dependencies.

Avoid refactors; add focused, incremental wiring.

12. Smoke Test Checklist

Run python -m src.main.

Open Pipeline tab.

Select a pack, click “Load current config”:

LoRA sliders update (if strengths present).

Adjust a few LoRA sliders.

Click “Apply config to pack(s)”:

No errors; logs show updated config written.

Click “Add to Job”:

Job preview shows the pack listed.

Confirm via logs (or debug prints) that lora_strengths are in the job snapshot.