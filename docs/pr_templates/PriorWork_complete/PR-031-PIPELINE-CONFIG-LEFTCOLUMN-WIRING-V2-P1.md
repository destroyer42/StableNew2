PR-031-PIPELINE-CONFIG-LEFTCOLUMN-WIRING-V2-P1
1. Title

Wire PipelineConfigPanelV2 into the Pipeline tab left column and connect it to AppController/AppStateV2.

2. Summary

This PR takes the read-only mapping from PR-030-DISCOVERY-PIPELINE-CONFIG-LOGGING-PRESETS-AD-V2-P1 and turns it into concrete wiring work for the Pipeline tab left column in the V2 GUI.

Right now, the left column of the Pipeline tab shows SidebarPanelV2 (presets, stage toggles, LoRA controls), but the config panel (PipelineConfigPanelV2) is not visible or connected to the controller/state. This PR:

Instantiates and embeds PipelineConfigPanelV2 in the Pipeline tab left column under/alongside SidebarPanelV2.

Wires it to AppController / AppStateV2 so it can:

Receive the current RunConfig + resource lists (models/VAEs/samplers/schedulers).

Push user edits back into the controller via explicit callbacks.

Adds a small, focused GUI test to assert the left-column shape and basic wiring.

No behavior changes are made to presets, bottom logging or ADetailer in this PR; those stay for PR-032/033/034 as mapped in PR-030.

3. Problem Statement

Observed issue

In the current V2 GUI, the Pipeline tab shows a left-hand column, but:

The configuration panel with default model/sampler/steps/etc. is not visible.

The user can’t see or edit the V2 pipeline configuration from that column.

SidebarPanelV2 is present but the rest of the intended left-column UX is missing.

Why this is a problem

The Phase-1 goal is: “it boots, it runs pipelines, dropdowns populate, payloads are correct”.

Without the config panel visible and wired, you can’t:

Sanely verify and tweak pipeline parameters from the primary UX surface.

Validate that resource lists and defaults are flowing into the UI as expected.

What PR-030 told us

From PR-030’s discovery doc:

SidebarPanelV2 is correctly integrated into Pipeline tab left column.

PipelineConfigPanelV2 exists as a V2 component but is not wired in.

The left column is the correct home for:

Presets dropdown.

Stage toggles.

Core pipeline config (default model, sampler, batch size, etc.).

We now need to convert that mapping into actual wiring.

4. Goals

Make the pipeline config panel visible

Ensure PipelineConfigPanelV2 is instantiated on the Pipeline tab and lives in the left column along with SidebarPanelV2.

Wire config panel to controller/state

Provide PipelineConfigPanelV2 with:

Access to AppStateV2 / RunConfig / resource lists (models/VAEs/samplers/schedulers).

Controller callbacks for “config changed” events (e.g., model/sampler/steps changes).

Keep wiring consistent with V2 architecture

Maintain the flow: GUI V2 ➜ AppController ➜ pipeline/runtime.

The panel should never talk directly to the WebUI or pipeline executor.

Add a minimal but real test

Validate the left-column structure and that the config panel is instantiated and bound to the shared state.

5. Non-goals

Presets behavior changes (load/save, default preset selection, etc.) – that’s PR-033.

Bottom logging behavior or appearance – that’s PR-032.

ADetailer as a separate stage or advanced wiring – that’s PR-034 and pipeline/runtime work.

Any WebUI lifecycle logic – no changes to WebUIConnectionController / WebUI process manager.

Re-layout of the entire window or tab structure – we only work within the Pipeline tab’s left column and its immediate wiring.

6. Allowed Files

Codex may edit only the following:

Pipeline tab & panels (GUI V2)

src/gui/views/pipeline_tab_frame_v2.py

To ensure the left column builds and hosts both SidebarPanelV2 and PipelineConfigPanelV2.

src/gui/panels_v2/sidebar_panel_v2.py

Only if needed to expose a clean API for interaction with the config panel / controller (e.g., callbacks or accessors).

src/gui/panels_v2/pipeline_config_panel_v2.py

Main focus: ensure it has constructor args and methods to:

Bind to AppStateV2 / RunConfig / resources lists.

Emit changes back up to AppController.

src/gui/panels_v2/__init__.py

Only if import/export of PipelineConfigPanelV2 needs to be updated.

Controller & state

src/controller/app_controller.py

To:

Provide a clean API for the config panel to:

Receive initial RunConfig / resource lists.

Notify on config changes (on_run_config_changed, etc.).

Optionally expose helper methods (get_current_run_config_for_gui, etc.) used by the panel.

src/gui/app_state_v2.py

To:

Store run_config and/or resources in a shape the config panel can consume.

Expose minimal helper methods if needed (e.g., get_resources_for_dropdowns() or set_run_config_from_ui()).

Tests

tests/gui_v2/test_pipeline_left_column_config_v2.py (new)

New file to cover:

Both SidebarPanelV2 and PipelineConfigPanelV2 existence.

Basic wiring to AppStateV2 / AppController via a lightweight stub.

If there is an existing tests/gui_v2/test_gui_v2_workspace_tabs_v2.py, Codex may only add minimal assertions to confirm the config panel is present on the Pipeline tab (no big refactor).

7. Forbidden Files

Do not touch any of the following in this PR:

src/main.py

src/controller/webui_connection_controller.py

src/api/webui_process_manager.py

src/api/webui_resource_service.py

src/api/healthcheck.py

src/pipeline/* (executor, runner, stage sequencer, etc.)

src/gui/main_window_v2.py

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

src/gui/panels_v2/log_trace_panel_v2.py

Any *_v1.py or legacy/archived GUI files

Any learning/queue/cluster/randomizer modules

Any docs, except if needed to append a short “Implementation Notes” section to the discovery doc

If updated: docs/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md may only be appended, not rewritten.

If a change seems to require touching any forbidden file, stop and return with a note instead of making the change.

8. Step-by-step Implementation
Step 1 – Confirm intended left-column structure

In pipeline_tab_frame_v2.py:

Identify how the left column for the Pipeline tab is currently built:

There should already be a SidebarPanelV2 created and packed/gridded into the left column.

Document (in comments) the intended structure:

Left column = SidebarPanelV2 (top) + PipelineConfigPanelV2 (below).

Center = stage cards.

Right = preview / status / other right-hand components.

Step 2 – Instantiate PipelineConfigPanelV2 under SidebarPanelV2

In pipeline_tab_frame_v2.py:

Import PipelineConfigPanelV2 from src.gui.panels_v2.pipeline_config_panel_v2.

Within the Pipeline tab’s left-column container:

Instantiate PipelineConfigPanelV2 with:

Parent: the same left-column frame that hosts SidebarPanelV2.

Dependencies:

app_state / controller if they are already passed into PipelineTabFrameV2 (if not, add only what’s necessary and consistent with other V2 views).

Place it below SidebarPanelV2 using the same layout mechanism (grid or pack with side=TOP).

Example intent (pseudo-code, not exact code):

left_column = ttk.Frame(self, ...)
self.sidebar_panel = SidebarPanelV2(left_column, controller=..., app_state=...)
self.config_panel = PipelineConfigPanelV2(left_column, controller=..., app_state=...)

Ensure naming is consistent with existing patterns (e.g., self.pipeline_config_panel if that’s the convention).

Step 3 – Wire PipelineConfigPanelV2 to controller/state

In pipeline_config_panel_v2.py:

Ensure the constructor supports:

def __init__(self, parent, controller, app_state, *args, **kwargs):
    ...


or the equivalent pattern used by other V2 panels.

Add or confirm the following:

A method to receive the current RunConfig and resource lists:

e.g., apply_run_config(run_config) and/or apply_resources(resources_map).

A mechanism to emit config changes:

e.g., call controller.on_run_config_changed(new_config) when the user updates a model/sampler/steps/seed in the panel.

Do not fetch resources directly from WebUI or the pipeline; only read from app_state or from data passed in by the controller.

In app_controller.py:

Confirm or add:

A helper that the GUI can call to get the current run config in a GUI-friendly shape:

e.g., get_current_run_config_for_gui() that returns a dataclass or dict.

A handler for config changes initiated in the GUI:

e.g., on_run_config_panel_changed(new_config) which:

Validates & updates AppStateV2 / internal config store.

Logs the change for debugging.

In app_state_v2.py:

Ensure there is a clearly defined home for:

Current RunConfig (or equivalent).

Resource lists (models/VAEs/samplers/schedulers) if not already present.

Add minimal helper accessors if needed so the panel doesn’t have to know internal layout details.

Step 4 – Connect AppController/AppStateV2 to the new panel

In pipeline_tab_frame_v2.py:

Once the panel is instantiated, ensure it is:

Initialised with the current run config and any known resources from AppStateV2.

Subscribed to state changes where appropriate (either via callbacks or explicit “refresh” calls from the controller).

In app_controller.py:

During Pipeline tab initialisation (or when building the workspace):

Pass app_state and controller=self into PipelineTabFrameV2 so that it can propagate them to the config panel.

After any event that changes the run config or resources (e.g., after WebUI resource refresh), call the panel’s apply_* methods where appropriate:

Note: Do not introduce new circular dependencies. If this looks risky, stop and annotate in code + comments.

Step 5 – Add tests

Create tests/gui_v2/test_pipeline_left_column_config_v2.py:

Use the same pattern as existing GUI tests (e.g., test_gui_v2_workspace_tabs_v2):

Mark it as a GUI test (pytest.mark.gui) and skip cleanly if Tk is not available.

Build a minimal AppStateV2 and AppController stub (or test doubles) sufficient to instantiate PipelineTabFrameV2.

Assertions:

Structure

The Pipeline tab’s left column contains:

An instance of SidebarPanelV2.

An instance of PipelineConfigPanelV2.

Wiring

PipelineConfigPanelV2 receives a non-None controller and app_state.

Optionally, simulate a simple change (e.g., update a combo selection) and assert the panel calls the expected controller hook (via a mocked controller).

Optionally update tests/gui_v2/test_gui_v2_workspace_tabs_v2.py:

Add a small assertion that the pipeline tab exposes a handle to pipeline_config_panel or similar, if that’s how it’s exposed.

Step 6 – Update discovery doc (optional)

If helpful, append a short “Implementation Status” section to:

docs/PIPELINE_CONFIG_LOGGING_PRESETS_ADetailer_DISCOVERY_V2-P1.md

Clarify that PR-031 has:

Instantiated PipelineConfigPanelV2 in the Pipeline tab left column.

Wired it to the controller/state.

Left presets, logging, and ADetailer for follow-on PRs.

Do not rewrite or restructure the doc – append only.

9. Required Tests (Failing first)

Before implementation, Codex should:

Run the relevant GUI tests to confirm current behavior:

python -m pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


Expect: passes or skips cleanly (depending on Tk availability).

After implementation, add and run:

python -m pytest tests/gui_v2/test_pipeline_left_column_config_v2.py -q
python -m pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


Both should pass (or skip gracefully if environment cannot load Tk).

No new non-GUI tests are required for this PR.

10. Acceptance Criteria

This PR is complete when:

GUI behavior

Launching python -m src.main and navigating to the Pipeline tab shows:

The left column containing:

The existing SidebarPanelV2 (presets, stage toggles, LoRA).

A visible PipelineConfigPanelV2 with core pipeline settings (model, sampler, steps, etc.).

Wiring

PipelineConfigPanelV2 has access to:

AppStateV2 (for current run config/resources).

AppController (to send config changes).

Changing a field in the config panel (e.g., switching the model dropdown) triggers the appropriate controller hook and logs a message (so we can trace it in the log panel later).

Tests

test_pipeline_left_column_config_v2.py passes (or is skipped in Tk-less environments).

Existing GUI tests for V2 still pass.

No regressions

No changes to WebUI lifecycle, bottom logging behavior, or presets functionality.

Other tabs (Prompt, Learning) still render and behave as before.

11. Rollback Plan

If something goes wrong:

Revert the changes to the allowed files:

pipeline_tab_frame_v2.py

pipeline_config_panel_v2.py

Any small controller/state adjustments tied to the new panel

The new test test_pipeline_left_column_config_v2.py (and any added assertions in test_gui_v2_workspace_tabs_v2.py).

Confirm:

python -m pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


still behaves as it did pre-PR.

The GUI should return to the previous state where only SidebarPanelV2 appears in the Pipeline tab’s left column.

12. Codex Execution Constraints

Do not refactor or rename classes, methods, or modules beyond what’s strictly required for this wiring.

Keep diffs small and surgical:

No broad layout rewrites.

No new architectural patterns.

Follow existing V2 patterns for:

Passing controller and app_state into views.

Handling GUI tests (pytest.mark.gui, skip on Tk errors).

Do not introduce:

New singletons.

New global state.

New cross-subsystem imports (GUI must not call pipeline or WebUI directly).

If a change appears to require touching a forbidden file, stop and emit a clear comment in the PR body instead of editing it.