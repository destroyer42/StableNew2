PR-087 – Controller RunConfig & GUI Entrypoint Wiring (V2.5)

Version: V2.5
Status: Proposed
Owner: StableNewV2 Core / GUI & Controller WG
Related Work:

PR-085 – PR-085-Test-Coverage-Uplift-Plan-V2_5.md (Now items: controller run_config + GUI entrypoint fixes)

PR-081D-5A/B/C/D (start_run shim, PipelineTabFrameV2 wiring – specs)

PR-086 – Core Contract Repair (test harness/fakes)

1. Intent & Summary

This PR focuses on two immediate blockers called out in the coverage plan:

Controller RunConfig wiring

Fix AppController’s handling of run_config so it is always non-None, has correct defaults, and is updated in a controlled, testable way.

Repair tests that currently fail with NoneType/missing run_config on the controller/state.

GUI V2 entrypoint wiring

Ensure the CLI / GUI entrypoint resolves V2 components correctly (no stale main_window.tk import).

Make test_entrypoint_uses_v2_gui and test_gui_v2_layout_skeleton pass by aligning the entrypoint with the new main_window_v2 scaffolding.

Goal: Remove the “Now” failures in:

tests/controller/test_app_controller_config.py

tests/controller/test_app_controller_pipeline_integration.py

tests/gui_v2/test_entrypoint_uses_v2_gui.py

tests/gui_v2/test_gui_v2_layout_skeleton.py

without touching sequencing or deeper journey behavior.

2. Scope
In-Scope

RunConfig lifecycle & defaults (controller side)

Ensure AppController owns and exposes a consistent RunConfig (or equivalent config model), and that:

It is initialized on controller creation.

It can be accessed in a stable way by tests, pipeline, and GUI: e.g. controller.run_state.run_config and/or controller.get_current_config().

Updates only affect specified fields while preserving others (per tests in test_app_controller_config).

Controller ↔ Pipeline integration (minimal)

Fix failures where controller-related tests expect run_config to be present when assembling pipeline configurations:

tests/controller/test_app_controller_pipeline_integration.py

Do not change pipeline sequencing or introduce refiner/hires/ADetailer logic here; just ensure the controller can assemble a valid config snapshot.

GUI entrypoint → V2 main window wiring

Update the GUI entrypoint such that:

CLI / launcher imports main_window_v2 (or the V2 entry surface) instead of legacy main_window.tk.

Entry-level tests that check “V2 GUI is used” now pass.

Out-of-Scope

Refiner/hires/ADetailer sequencing behavior (that’s PR-081E).

Detailed journey harness behavior (JT03/04/05/v2_full) beyond what’s strictly required to keep these tests compiling/running.

Any re-layout or visual changes in the GUI; this PR is about wiring/configs, not design.

3. Target Failures & How This PR Addresses Them
3.1 Controller RunConfig Failures

Current failing tests:

tests/controller/test_app_controller_config.py::test_controller_config_defaults

tests/controller/test_app_controller_config.py::test_controller_update_config_only_updates_specified_fields

tests/controller/test_app_controller_pipeline_integration.py::test_pipeline_config_assembled_from_controller_state

tests/controller/test_app_controller_pipeline_integration.py::test_cancel_triggers_token_and_returns_to_idle

Observed errors (from your logs):

AttributeError: 'NoneType' object has no attribute 'run_config'

Interpretation:

The controller’s “run state” or app state is not being initialized with a valid config model, or tests are expecting a property that no longer exists/is wired.

This PR will:

Define/confirm the single source of truth for run config:

Identify the canonical RunConfig model (likely in src/gui/state.py, src/config/app_config.py, or similar).

Ensure AppController owns an instance such as:

self._run_state.run_config or

self.app_state.run_config

Whichever pattern the tests expect, standardize it and document in the controller docstring.

Initialize RunConfig in AppController constructor:

On AppController.__init__, construct a default RunConfig from:

Global app config defaults (e.g. AppConfig.default_run_config()), or

A dedicated helper factory.

Ensure no code path leaves this as None.

Add explicit accessor(s):

Provide a method like:

def get_current_config(self) -> RunConfig:
    return self.run_state.run_config


or equivalent, aligned with what controller/GUI tests expect.

Implement “update only specified fields” semantics:

Update the controller method used by tests (e.g. update_run_config(**overrides) or apply_config_update(new_config)):

Merge overrides into the existing RunConfig while leaving unspecified fields unchanged.

Make test_controller_update_config_only_updates_specified_fields pass by:

Using dataclasses.replace, or

Manual merge logic that respects existing values.

Pipeline integration expectations:

Ensure that the method assembling pipeline config (e.g. AppController._assemble_pipeline_config() or call into pipeline_config_assembler) consumes RunConfig correctly.

Fix test_pipeline_config_assembled_from_controller_state by:

Ensuring the assembled dict matches expected keys/values.

Using the same configuration fields as the tests assert (txt2img/img2img/upscale blocks, etc.).

Cancel + lifecycle hook:

For test_cancel_triggers_token_and_returns_to_idle:

Confirm that when cancel is invoked through the controller:

The cancellation token is set.

Lifecycle transitions from RUNNING → IDLE.

Only adjust controller logic as needed to re-instate this behavior; don’t change pipeline runner internals in this PR.

3.2 GUI EntryPoint / V2 Wiring Failures

Current failing tests:

tests/gui_v2/test_entrypoint_uses_v2_gui.py::test_stablenewgui_exposes_v2_components

tests/gui_v2/test_gui_v2_layout_skeleton.py::test_gui_v2_layout_skeleton

Observed errors:

ImportError: import error in src.gui.main_window.tk: No module named 'src.gui.main_window.tk'; 'src.gui.main_window' is not a package

Interpretation:

The entrypoint or tests still reference an old path like src.gui.main_window.tk (likely from the archived V1 era), but main_window.py is now a simple module, and the real entrypoint is in main_window_v2.py.

This PR will:

Standardize the main GUI entry module:

Confirm src/gui/main_window_v2.py is the canonical V2 entrypoint.

Add a small, explicit API surface, e.g.:

# src/gui/main_window_v2.py
def create_app(): ...
def run_app(): ...


or a top-level class like StableNewGUIV2.

Fix CLI / launcher wiring:

Update the CLI entrypoint module (likely src/main.py or src/cli.py) so:

stablenewgui (or equivalent console script) imports main_window_v2.

It does not import main_window.tk or other legacy modules.

If tests look for a symbol like StableNewGUI, provide it (or alias V2’s main window to that name):

# src/gui/main_window.py
# Thin compatibility shim if necessary:
from .main_window_v2 import StableNewGUIV2 as StableNewGUI


Only if tests explicitly expect src.gui.main_window.StableNewGUI.

Make layout skeleton expectations pass:

In test_gui_v2_layout_skeleton, tests likely assert that:

The entrypoint returns a window/frame with specific top-level zones (status bar, pipeline tab, sidebar, etc.).

Ensure main_window_v2 constructs the layout using the V2 panels (pipeline tab, sidebar, preview, etc.) already implemented, and:

Exposes the expected attributes or accessors the test uses, e.g. app.pipeline_tab, app.sidebar_panel.

If the test currently imports src.gui.main_window.tk, adjust the test (or, if not allowed in this PR, provide a compat shim in main_window.py) so that:

tk import is no longer required; only V2 layout modules are referenced.

Minimal shim, not a redesign:

This PR does not re-architect the GUI.

It only:

Wires the entrypoint correctly.

Ensures the layout skeleton exists and is accessible per tests.

4. Files to Touch

Exact list may vary slightly; Codex should check the snapshot.

Controller & config:

src/controller/app_controller.py

src/config/app_config.py (if this owns default RunConfig builder)

src/gui/state.py or src/gui/app_state_v2.py (where RunConfig/run state lives)

GUI entrypoint & CLI:

src/gui/main_window_v2.py

src/gui/main_window.py (optional: shim only; avoid heavy logic here)

src/main.py and/or src/cli.py (where stablenewgui is wired)

Tests (only as needed to align expectations):

tests/controller/test_app_controller_config.py

tests/controller/test_app_controller_pipeline_integration.py

tests/gui_v2/test_entrypoint_uses_v2_gui.py

tests/gui_v2/test_gui_v2_layout_skeleton.py

5. Behavioral Expectations

After PR-087:

Controller run_config:

AppController always has a valid run_config accessible via a well-defined property or getter.

Default values in tests of test_controller_config_defaults match the new RunConfig defaults.

Updating run config via the controller only overrides specified fields.

Pipeline integration:

test_pipeline_config_assembled_from_controller_state sees a correctly assembled pipeline config derived from run_config.

test_cancel_triggers_token_and_returns_to_idle confirms cancellation returns lifecycle to IDLE and interacts correctly with the cancellation token.

GUI V2 entrypoint:

CLI/entrypoint launches the V2 main window without ImportErrors.

test_stablenewgui_exposes_v2_components confirms:

Entry uses V2 components (main_window_v2, layout_v2, pipeline_tab_v2, etc.).

test_gui_v2_layout_skeleton confirms:

Expected V2 layout zones exist and are wired from the entrypoint.

6. Test Plan
6.1 Focused Tests

Run and fix:

pytest tests/controller/test_app_controller_config.py
pytest tests/controller/test_app_controller_pipeline_integration.py
pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py
pytest tests/gui_v2/test_gui_v2_layout_skeleton.py

6.2 Regression Check

Then run a slightly broader subset:

pytest tests/controller/ tests/gui_v2/test_main_window_smoke_v2.py


Finally, re-check coverage:

pytest --maxfail=1 --disable-warnings --cov=src --cov-report=term-missing


Confirm that:

The target tests now pass.

No new controller/GUI regressions are introduced.

7. Acceptance Criteria

PR-087 is accepted when:

All four target tests pass with no xfails:

test_controller_config_defaults

test_controller_update_config_only_updates_specified_fields

test_pipeline_config_assembled_from_controller_state

test_cancel_triggers_token_and_returns_to_idle

test_stablenewgui_exposes_v2_components

test_gui_v2_layout_skeleton

No new test failures introduced in tests/controller/ or tests/gui_v2/.

RunConfig contract is documented at the controller level (brief docstring/comments describing where the canonical config lives and how it’s updated).

EntryPoint contract is clear:

It’s unambiguous which module represents the V2 GUI entrypoint (and how CLI loads it).

Legacy main_window imports are either removed or shimmed cleanly without reintroducing Tk/V1 dependencies.