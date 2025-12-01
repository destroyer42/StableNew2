PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1

Make the presets dropdown actually find, list, and apply presets from presets/

1. Title

PR-033-PIPELINE-PRESETS-HOOKUP-V2-P1 – Sidebar presets discovery & application wiring

2. Summary

Right now:

You have multiple preset files in C:\Users\rob\projects\StableNew\presets.

SidebarPanelV2 exposes a presets dropdown and is supposed to use ConfigManager.list_presets() / load_preset().

But the dropdown is empty and you can’t load any presets.

PR-030’s discovery work confirmed:

ConfigManager manages presets using a relative "presets" directory.

SidebarPanelV2 is wired to a ConfigManager instance but isn’t successfully populating or applying presets.

The Pipeline tab left column (wired in PR-031) is the correct UX surface for presets + pipeline config.

This PR:

Fixes the end-to-end hookup so presets:

Are discovered from the presets/ directory,

Show up in the presets dropdown,

Can be selected and applied to the current pipeline config.

Adds tests so we don’t regress this again.

3. Problem Statement

Observed behavior

The preset dropdown on the left column of the Pipeline tab:

Shows no entries, even though presets/ contains valid files.

Selecting a preset (when it does appear) currently doesn’t visibly update the config panel or stage cards.

Likely causes (from discovery + symptoms)

Path resolution mismatch

ConfigManager may be using a base path that is:

Not the project root, or

Not the same as the python -m src.main working directory.

As a result, list_presets() may be looking at the wrong folder or silently ignoring files.

Filtering / pattern mismatch

list_presets() may be filtering on extension patterns (e.g. .json, .yaml) that don’t match the actual preset filenames.

Wiring gaps

SidebarPanelV2 may:

Call ConfigManager.list_presets() too early (before the working dir or config is finalized),

Not refresh the dropdown after the controller/state is ready,

Not call the right controller/state hooks when a preset is selected.

Application gaps

Even if a preset loads, the resulting config might not:

Be applied to AppStateV2.run_config,

Propagate down into PipelineConfigPanelV2 and the associated stage cards.

We need a focused PR to fix both discovery and application paths, without touching unrelated subsystems.

4. Goals

Presets show up properly

The presets dropdown in SidebarPanelV2 lists all valid preset files in presets/, using human-readable names.

Presets load correctly

Selecting a preset:

Loads the preset file via ConfigManager.load_preset(),

Updates the in-memory pipeline configuration (e.g., model/sampler/steps/cfg),

Logs the change for debugging.

Presets integrate with V2 pipeline config

Applied preset values:

Are reflected in AppStateV2 / RunConfig,

Propagate to PipelineConfigPanelV2 (left column config panel) and, by extension, to the stage cards / dropdowns.

Tests guard behavior

New tests prove:

ConfigManager.list_presets() locates files in presets/,

SidebarPanelV2 populates the dropdown from those values,

Selecting a preset calls into the controller/state and updates the config.

5. Non-goals

No changes to the format or schema of existing preset files.

No introduction of a new preset type (e.g., “learning presets” or “ADetailer presets”).

No changes to the underlying pipeline execution or WebUI behavior.

No new UX for creating/saving presets from the GUI (save/export can be a future PR).

No changes to the Prompt or Learning tabs; scope is Pipeline tab left column only.

6. Allowed Files

Codex may edit only these files for PR-033:

Config / presets core

src/utils/config.py

ConfigManager path resolution, list_presets(), load_preset() behavior.

GUI – sidebar & config

src/gui/panels_v2/sidebar_panel_v2.py

Preset dropdown population, event handlers, wiring to controller/state.

src/gui/panels_v2/pipeline_config_panel_v2.py

Only as needed to accept preset-applied values (e.g., apply_run_config method).

src/gui/app_state_v2.py

run_config storage/accessors used when applying presets.

src/controller/app_controller.py

on_preset_selected, apply_preset_to_run_config, or similar helper(s) that:

Use ConfigManager to load preset,

Update AppStateV2,

Request GUI refresh.

Tests

tests/utils/test_config_presets_v2.py (new)

For ConfigManager.list_presets() / load_preset().

tests/gui_v2/test_sidebar_presets_v2.py (new)

For SidebarPanelV2 dropdown population + basic “select preset” flow.

If tests/utils/test_config.py already exists and is clearly the home of ConfigManager tests, you may extend that instead of adding a new file, but keep the V2 naming consistent in test names.

7. Forbidden Files

For this PR, do not modify:

src/main.py

src/gui/main_window_v2.py

src/gui/layout_v2.py

src/gui/status_bar_v2.py

src/gui/log_trace_panel_v2.py

src/controller/webui_connection_controller.py

src/api/*

src/pipeline/*

Any *_v1.py or legacy GUI files

Any learning/queue/cluster/randomizer modules

Any CI or build config

If you discover that presets cannot be fixed without touching a forbidden file, stop and report instead of editing.

8. Step-by-step Implementation
Step 1 – Fix / verify ConfigManager.list_presets() and load_preset()

File: src/utils/config.py

Path root clarity

Ensure ConfigManager computes the presets directory in a deterministic way:

Prefer PROJECT_ROOT/presets where PROJECT_ROOT is based on the location of config.py (or the repo root), not on the current working directory of the interpreter if they differ.

If we already rely on cwd and it is the project root when you run python -m src.main, then just confirm that logic and document it in comments.

Add a small docstring or comment explaining:

list_presets() reads from the presets directory alongside the repository root (or relative to the executable root), not from arbitrary working directories.

List behavior

list_presets() should:

Enumerate files in the presets directory with allowed extensions (e.g., .json).

Return a stable list of preset names (e.g., filename without extension) or objects that SidebarPanelV2 can use directly.

Ensure:

Hidden files or backup files (like *.bak, .*) are ignored.

There is no silent failure if the directory exists but is empty; return [].

Load behavior

load_preset(name) should:

Resolve the name to a specific file in presets/ (e.g., name + ".json").

Load the file and return a structured config (dict/dataclass) that maps cleanly to the pipeline/run config.

If the preset name is not found:

Log a warning,

Do not crash the GUI.

Step 2 – Wire preset discovery into SidebarPanelV2

File: src/gui/panels_v2/sidebar_panel_v2.py

Initialization

Ensure the sidebar:

Constructs a ConfigManager instance with the correct base path (the same as used by ConfigManager.list_presets() above; avoid passing an incorrect base_dir).

Calls a self._populate_presets_dropdown() method that:

Calls config_manager.list_presets(),

Fills the dropdown with those names.

Refresh behavior

If there’s an existing “Refresh” or “Reload presets” button, wire it to:

def _populate_presets_dropdown(self):
    names = self.config_manager.list_presets()
    self.preset_dropdown["values"] = names or []
    # optionally, reselect last chosen preset if still present


Event handler

For preset selection (combobox <<ComboboxSelected>>):

Capture the selected name.

Call a controller method, e.g.:

self.controller.on_preset_selected(preset_name)


Do not directly call ConfigManager.load_preset from the GUI; keep that in the controller.

Step 3 – Apply presets in AppController and update AppState

File: src/controller/app_controller.py

Add on_preset_selected

Implement:

def on_preset_selected(self, preset_name: str) -> None:
    try:
        preset_config = self.config_manager.load_preset(preset_name)
    except Exception:
        self.logger.exception("Failed to load preset %s", preset_name)
        return

    self.apply_preset_to_run_config(preset_config, preset_name)


Add apply_preset_to_run_config

This method should:

Merge the preset config into the current run config / app state:

E.g., update model/sampler/steps/cfg/options that are supported by the preset.

Avoid removing settings that are not controlled by presets (keep safe defaults).

Update AppStateV2:

self.state.set_run_config(new_run_config)


Notify relevant GUI panels (e.g., PipelineConfigPanelV2) so they re-render:

Either via existing observer patterns, or via explicit apply_run_config call if one exists.

Log a concise message:

self.logger.info("Applied preset '%s' to run config", preset_name)

Step 4 – Make PipelineConfigPanelV2 react to presets

File: src/gui/panels_v2/pipeline_config_panel_v2.py

Ensure this panel has a method it can expose, something like:

def apply_run_config(self, run_config) -> None:
    # Set its widgets (model dropdown, sampler, steps, etc.) from run_config


When AppStateV2 run config changes (e.g., via set_run_config), either:

The panel is notified by the controller and calls apply_run_config, or

The panel subscribes to state changes and calls apply_run_config itself.

The important outcome: once a preset is applied, the values in the config panel visibly change to match.

Step 5 – AppStateV2: run config accessors

File: src/gui/app_state_v2.py

Ensure that:

There is a run_config field or equivalent that captures the active pipeline settings.

There are methods such as:

def set_run_config(self, run_config) -> None:
    self.run_config = run_config
    # notify listeners if any


If listeners exist (e.g., Pipeline tab), they can assume that run_config is the single source of truth for config, including presets.

Step 6 – Add / extend tests
6.1 ConfigManager presets test

File: tests/utils/test_config_presets_v2.py (or extend the existing config tests)

Arrange:

Point ConfigManager at a temporary presets directory with a small set of fake preset files (e.g., basic.json, xl_highres.json).

Act:

Call list_presets() and verify:

It returns expected names (e.g., ["basic", "xl_highres"]).

Call load_preset("basic") and ensure:

It loads and returns a dict with expected keys (e.g., "model", "sampler", etc.).

Assert:

No exceptions are thrown for valid presets.

Missing presets cause a logged warning, not a crash.

6.2 Sidebar presets GUI test

File: tests/gui_v2/test_sidebar_presets_v2.py

Mark as GUI test and skip if Tk is unavailable.

Arrange:

Create a stub AppController with:

config_manager returning a fixed set of preset names.

on_preset_selected mocked to record calls.

Build SidebarPanelV2 with this controller.

Act:

Trigger whatever method populates the presets dropdown.

Simulate selecting a preset (e.g., set the combobox variable and generate <<ComboboxSelected>>).

Assert:

The presets dropdown ["values"] contains the expected names.

controller.on_preset_selected("basic") (or equivalent) was called once.

Optionally:

If the test stack can stand it, integrate SidebarPanelV2 + AppController + ConfigManager to test an end-to-end “select preset → load file → update run_config” flow.

9. Required Tests (Failing first)

Before changes:

Run existing config and GUI tests to ensure baseline:

python -m pytest tests/utils/test_config*.py -q
python -m pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


After changes:

Run:

python -m pytest tests/utils/test_config_presets_v2.py -q    # or extended config tests
python -m pytest tests/gui_v2/test_sidebar_presets_v2.py -q
python -m pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


All must pass or skip (for GUI tests if Tk is missing).

10. Acceptance Criteria

PR-033 is done when:

Real-world behavior

Running python -m src.main from C:\Users\rob\projects\StableNew:

The Pipeline tab → left column presets dropdown shows entries corresponding to the files in presets/ (e.g., basic, xl_highres, etc.).

Selecting a preset:

Immediately updates the config values in the left-column PipelineConfigPanelV2.

Logs a message indicating which preset was applied.

Subsequent runs still see the same preset list (no need to restart the app when preset files haven’t changed).

Internal wiring

ConfigManager.list_presets() reads from the correct directory and filters appropriately.

SidebarPanelV2 calls list_presets() and populates the dropdown.

SidebarPanelV2 forwards preset selection to AppController.on_preset_selected.

AppController uses ConfigManager.load_preset() and updates AppStateV2.run_config.

PipelineConfigPanelV2 reflects the new run_config visually.

Tests

Config presets test passes.

Sidebar presets GUI test passes or skips gracefully if Tk isn’t available.

No existing tests are broken.

11. Rollback Plan

If this PR causes regressions:

Revert changes to:

src/utils/config.py

src/gui/panels_v2/sidebar_panel_v2.py

src/gui/panels_v2/pipeline_config_panel_v2.py

src/gui/app_state_v2.py

src/controller/app_controller.py

tests/utils/test_config_presets_v2.py

tests/gui_v2/test_sidebar_presets_v2.py

Re-run:

python -m pytest tests/utils/test_config*.py tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


Confirm:

The GUI still launches.

Preset dropdown returns to its previous (non-functional) state but no crashes occur.

12. Codex Execution Constraints

Keep changes minimal and clearly scoped to preset discovery and application.

Do not refactor ConfigManager beyond what is strictly necessary for presets.

Avoid introducing circular imports (e.g., GUI importing config at the wrong layer).

Do not change the preset file schema; assume existing files are correct.

All GUI tests must be marked with the existing GUI marker and skip cleanly in Tk-less environments.

13. Smoke Test Checklist

After Codex applies PR-033 and tests pass:

From the repo root:

cd C:\Users\rob\projects\StableNew
python -m src.main


Open the Pipeline tab.

Look at the left column:

Confirm the presets dropdown is populated with entries that match the presets/ directory.

Select one of your presets (e.g., the one you use most often):

Confirm:

Model, sampler, steps, cfg, etc. in PipelineConfigPanelV2 update.

The change is logged in:

Terminal,

Bottom log panel (after PR-032).

Try another preset: