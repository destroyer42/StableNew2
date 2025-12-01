PR-033-PIPELINE-LEFT-PANEL-UX-V2-P1
1. Title

PR-033-PIPELINE-LEFT-PANEL-UX-V2-P1 — Normalize Pipeline Left Column Layout & Semantics

2. Summary

Clarify and simplify the Pipeline tab left column so it acts as the “Pipeline Config & Control” surface, instead of a confusing mix of three overlapping prompt-pack lists and ambiguous presets. This is a layout/UX clean-up only: no new randomization logic or preset semantics yet, just making the panel readable, consistent, and correctly wired to existing state.

3. Problem Statement

Right now the Pipeline tab’s left column is:

Showing three prompt-pack lists with overlapping but slightly different contents.

Exposing two different preset dropdowns whose scope is unclear (pack-specific? run-config? something else?).

Using labels/buttons (e.g., “Load pack”, “Apply to prompt”) whose behavior isn’t obvious and doesn’t clearly map to Prompt vs Pipeline responsibilities.

Surfacing core config (model/vae/sampler) and output settings in a partially wired card where dropdowns never populate and the refresh button appears inert.

This leads to a user experience where:

It’s unclear which control actually changes the pipeline vs just previews a prompt.

Nothing in the left column obviously explains the relationship between prompt packs, presets, and run config.

The visual structure doesn’t match the conceptual layout we agreed on (Pipeline tab = “how this run will execute”).

4. Goals

G1 – Reorganize the Pipeline tab left column into a small, coherent set of cards:

Prompt Pack Selection (read-only): which pack(s) are in play for this run.

Preset Selector (high-level): which pipeline preset is active (visual only in this PR).

Core Pipeline Config (read-only shell): model/vae/sampler/output card clearly labeled and placed, even if dropdowns are wired by later PRs.

Run Mode/Stages Preview (visual): stage toggles and run mode grouped at the bottom in a way that matches the stage cards in the center.

G2 – Remove obviously redundant controls in the left column:

Third prompt pack list that just shows the same packs as the first.

Misplaced “Edit pack” controls (move those to Prompt tab in later work).

G3 – Ensure labels and tooltips correctly describe scope:

“Load pack” makes it clear this affects the Pipeline run config, not editing the pack.

G4 – Keep wiring changes minimal and localized to GUI V2 files; no behavior changes to executor or randomizer in this PR.

5. Non-goals

Applying presets to actual run configs (that’s PR-034).

Implementing randomization or learning integration (PR-035+).

Modifying how prompt packs are created/edited (belongs to Prompt tab work).

Changing any WebUI resource fetching or backend behavior.

6. Allowed Files

GUI layout & wiring only:

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/sidebar_panel_v2.py

src/gui/views/pipeline_config_panel_v2.py (or current config panel implementation)

src/gui/views/randomizer_panel_v2.py (if used purely for grouping run mode/stages UI)

src/gui/app_state_v2.py (only if needed for field naming / simple view-model bindings)

Tests:

tests/gui_v2/test_sidebar_panel_layout_v2.py (new)

tests/gui_v2/test_pipeline_tab_layout_v2.py (new or updated)

7. Forbidden Files

Do not touch:

src/gui/main_window_v2.py

src/controller/app_controller.py (beyond renamed callbacks if absolutely required)

Any src/pipeline/* runtime modules

Any V1/legacy GUI modules (e.g., src/gui/main_window.py, src/gui/theme.py)

WebUI API modules

8. Step-by-step Implementation

Normalize the left column structure in pipeline_tab_frame_v2.py:

Declare a single left column container (e.g., left_config_column).

Add three primary frames in order:

PromptPackSelectionCard

PresetSummaryCard

PipelineConfigSummaryCard

RunModeAndStagesCard (bottom).

Refactor SidebarPanelV2:

Reduce to:

Primary prompt pack list (with clear label like “Active prompt pack”).

A single “Load pack for pipeline” action with a tooltip clarifying what it does.

Remove or hide:

Duplicate prompt pack list at the bottom that mirrors the first.

Any inline “edit pack” entry point.

Ensure the middle prompt pack list (with categories) is clearly marked as “Pack browser (read-only preview)” for now; actual semantics will be refined in later PRs.

Clarify core config card shell:

In pipeline_config_panel_v2.py, ensure:

Labels: “Model”, “VAE”, “Sampler”, “Scheduler”, “Output directory”, “Filename format”.

Fields are clearly disabled/placeholder if not yet wired.

The “Refresh” button has a tooltip like “Refresh models from WebUI (wired in later step)”.

Run mode & stages grouping:

Move run mode / queue / randomizer / stages checkboxes into a clearly labeled card, e.g., “Run Control & Stages”.

Ensure stage checkboxes visually correspond to the center stage cards but do not yet change visibility (that behavior gets tackled later).

Tooltips & labels:

Add gentle tooltips to:

Load pack

Preset dropdown

“Apply to prompt” (if still present)

Make sure the copy is consistent with the conceptual model (Prompt vs Pipeline).

Tests:

Add a GUI test that:

Builds the Pipeline tab.

Asserts only one primary prompt pack list is visible.

Confirms PresetSummaryCard and PipelineConfigSummaryCard exist (by widget class or label text).

Confirms Run Mode/Stages are grouped in a single bottom card.

9. Required Tests (Failing first)

tests/gui_v2/test_pipeline_tab_layout_v2.py

Initially fails because expected cards/labels aren’t present or counts are wrong.

tests/gui_v2/test_sidebar_panel_layout_v2.py

Initially fails because duplicate prompt pack lists or “Edit pack” buttons still exist in the Pipeline tab.

10. Acceptance Criteria

Only one primary prompt pack list is present in the Pipeline left column.

“Edit pack” entry points are removed from the Pipeline tab (Prompt tab only later).

Users can visually identify:

Active prompt pack

Active preset (even if it’s currently a label)

Core config shell

Run mode & stages section

No Tk errors when opening the Pipeline tab.

11. Rollback Plan

Revert changes to:

pipeline_tab_frame_v2.py

sidebar_panel_v2.py

pipeline_config_panel_v2.py

Any new tests

This returns the UI to the pre-PR-033 layout, even if confusing, without touching backend behavior.

12. Codex Execution Constraints

Keep diffs focused: no new files beyond small view classes and tests.

Do not introduce new controller callbacks; reuse existing ones / no-op placeholders.

Preserve current widget IDs / names where possible to avoid breaking other tests.

13. Smoke Test Checklist

Launch python -m src.main.

Open Pipeline tab:

Confirm cleaned-up left column structure.

No duplicated prompt pack blocks.

No GUI errors in the terminal logs.

Close app cleanly.