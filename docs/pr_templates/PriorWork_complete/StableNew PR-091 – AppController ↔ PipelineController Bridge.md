StableNew PR – AppController ↔ PipelineController Bridge.md

PR-ID: PR-090
Scope: Controller wiring / execution path
Summary: Make AppController a thin façade over the modern PipelineController / queue-backed execution path so GUI “Run” uses the real V2 pipeline instead of a legacy runner.

Snapshot / Baseline

Snapshot used: StableNew-snapshot-20251203-052644.zip

Inventory: repo_inventory.json (same timestamp)

Guardrail: No changes to forbidden files:

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/main.py

src/pipeline/executor.py

Pipeline runner core threading / executor internals (beyond existing public usage)

Problem / Intent
Current state

AppController.run_pipeline() still:

Validates pipeline settings.

Builds a PipelineConfig.

Calls a local PipelineRunner instance directly (self.pipeline_runner.run(...)).

Has bespoke logic for txt2img/img2img/upscale/adetailer wiring via _run_pipeline_from_tab and _run_pipeline_via_runner_only.

PipelineController already exists and:

Builds PipelineConfig via PipelineConfigAssembler and GUI state (StateManager, PipelineState).

Uses StageExecutionPlan / StageSequencer and PipelineRunner.

Submits work via JobExecutionController / QueueExecutionController (single-node job runner / queue).

V2 GUI (PipelineRunControlsV2 in the 3rd column) still calls AppController.start_run(), so:

User presses Run → goes through the legacy run_pipeline() path.

The modern PipelineController path is not what the user is actually exercising via the main button.

Intent

Make AppController:

a compatibility façade for:

legacy journeys/tests that call start_run() or run_pipeline(), and

the V2 GUI Run button,

but internally delegate all execution to PipelineController + StageSequencer + PipelineRunner + JobExecutionController, instead of owning its own runner logic.

Result:

GUI “Run” uses the same path as the modern controller + queue stack.

Journey tests that call AppController.start_run() automatically test the modern pipeline path.

We can safely retire legacy execution pieces later, leaving AppController as a thin bridge.

Scope
In-Scope

AppController construction and execution methods:

Instantiating / owning a PipelineController instance.

Bridging run_pipeline() and start_run() into PipelineController.start_pipeline(...) (and friends).

Wiring to StageSequencer / PipelineRunner through PipelineController (no direct PipelineRunner construction in AppController anymore).

Minimal updates to controller tests that assume “AppController → PipelineRunner wiring”:

Keep them, but make them validate the bridge instead of direct runner creation.

Out-of-Scope (for PR-090)

No GUI layout changes (buttons/controls stay as-is).

No changes to:

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/pipeline/executor.py

src/main.py

No semantics changes to:

Stage sequencing rules (already covered by prior PRs).

Queue / Job state machine (JobService / SingleNodeJobRunner).

No Learning tab / LearningRecord wiring (that will be separate).

Files to Modify (exact paths)

Controllers

src/controller/app_controller.py

src/controller/pipeline_controller.py (light additions: public entrypoints for AppController to call)

Pipeline (used via PipelineController only, not changed unless absolutely necessary)

No structural changes expected here:

src/pipeline/pipeline_runner.py

src/pipeline/run_plan.py

src/pipeline/stage_sequencer.py

Tests

tests/controller/test_app_controller_pipeline_integration.py

tests/controller/test_app_controller_config.py (if needed, for constructor changes)

tests/controller/test_stage_sequencer_controller_integration.py (if we update expectations to go through PipelineController)

Any other tests directly asserting AppController → PipelineRunner wiring.

Design / Behavior
New high-level behavior

Before PR-090

AppController.start_run() → AppController.run_pipeline() → builds PipelineConfig → calls self.pipeline_runner.run(...) directly.

PipelineController.start_pipeline() is not used in this path.

After PR-090

AppController owns a PipelineController instance configured with:

StateManager / GUI state (AppStateV2 / GUIState) from main_window.

WebUI connection controller / JobExecutionController wiring that already exists in PipelineController.

AppController.run_pipeline() becomes:

validation + logging + lifecycle management wrapper, then

calls into PipelineController.start_pipeline(...) (or a dedicated bridge method) so:

StageExecutionPlan + StageSequencer decide the stages,

PipelineRunner is invoked by PipelineController, not by AppController.

AppController.start_run() remains a simple shim for tests and legacy harnesses:

It still checks lifecycle, logs, and then calls run_pipeline().

This means existing journeys that use start_run() now drive the modern path with no change to their call sites.

Implementation Plan
1. Introduce a PipelineController instance to AppController

In src/controller/app_controller.py:

Add a private field:

from src.controller.pipeline_controller import PipelineController as CorePipelineController


In AppController.__init__:

After wiring self.main_window, self.app_state, etc., create or inject a CorePipelineController:

self._pipeline_controller: CorePipelineController | None = None
self._init_pipeline_controller()


Implement _init_pipeline_controller():

Build an appropriate StateManager / GUIState view for the existing GUI:

Use self.app_state and self.main_window as the source of truth.

If necessary, wrap them in a lightweight adapter that satisfies PipelineController’s state_manager expectations (e.g., get_pipeline_overrides, can_run, etc.).

Instantiate CorePipelineController with:

state_manager instance,

a PipelineConfigAssembler (or allow it to use its default),

WebUIConnectionController if needed (or let it create its own),

reusing JobExecutionController / QueueExecutionController as appropriate.

Ensure this controller uses the same cancel_token / JobExecutionController as the rest of the app where possible (no duplicate worker threads).

Guard: if main_window is None (headless tests), still construct a minimal state_manager wrapper so controller tests can run.

2. Refactor run_pipeline() to call into PipelineController

In AppController.run_pipeline():

Keep the existing structure:

Early exit if lifecycle is already RUNNING.

Validation step:

is_valid, message = self._validate_pipeline_config()

_set_validation_feedback(is_valid, message)

If not valid, log and return None.

Lifecycle transitions: RUNNING → IDLE or ERROR.

Replace the body that currently:

builds pipeline_config via build_pipeline_config_v2(),

decides between _run_pipeline_from_tab(...) and _run_pipeline_via_runner_only(...),

calls self.pipeline_runner.run(...) directly,

with logic that:

Delegates execution into self._pipeline_controller:

self._set_lifecycle(LifecycleState.RUNNING)

try:
    # Delegate to modern pipeline controller
    result = self._run_via_pipeline_controller()
    self._set_lifecycle(LifecycleState.IDLE)
    return result
except Exception as exc:
    self._append_log(f"[controller] Pipeline error in run_pipeline: {exc!r}")
    self._set_lifecycle(LifecycleState.ERROR, error=str(exc))
    return None


Implement _run_via_pipeline_controller():

Basic approach:

def _run_via_pipeline_controller(self) -> Any:
    if not self._pipeline_controller:
        raise RuntimeError("PipelineController not initialized")

    result_holder: dict[str, Any] = {}

    def _on_complete(payload: dict[Any, Any]) -> None:
        result_holder.update(payload)

    def _on_error(exc: Exception) -> None:
        # Optionally log or re-raise; final handling done by caller.
        self._append_log(f"[controller] PipelineController error: {exc!r}")

    ok = self._pipeline_controller.start_pipeline(
        pipeline_func=None,
        on_complete=_on_complete,
        on_error=_on_error,
    )
    if not ok:
        # Start failed (e.g., WebUI not ready, cannot run)
        return None

    # For now, assume synchronous behavior (SingleNodeJobRunner already wired)
    return result_holder or None


If async behavior is needed in future, the bridge can become a “kick off + wait” pattern, but for this PR the assumption is: existing start_pipeline(...) runs synchronously through the job controller for single-node mode (matching current behavior).

Leave _run_pipeline_from_tab / _run_pipeline_via_runner_only in place for now but mark them as legacy helpers that are no longer used by run_pipeline() once the bridge is fully wired. (They can be archived in a later cleanup PR if desired.)

3. Keep start_run() as a thin shim

In AppController.start_run():

Confirm the current structure stays:

def start_run(self) -> Any:
    """Legacy-friendly entrypoint used by older harnesses."""
    if self.state.lifecycle == LifecycleState.RUNNING:
        self._append_log("[controller] start_run requested while already running.")
        return None
    self._append_log("[controller] start_run invoking run_pipeline.")
    return self.run_pipeline()


No change needed other than the fact that run_pipeline() is now the pipeline-controller bridge.

4. Adjust tests to validate the new bridge

Update tests/controller/test_app_controller_pipeline_integration.py:

Currently, it constructs AppController with a fake PipelineRunner implementation and asserts:

RecordingPipelineRunner.run(...) called with a PipelineConfig.

Cancellation, blocking behavior, etc.

After PR-090:

Replace the direct PipelineRunner injection assertions with:

Either a fake PipelineController injected into AppController (e.g., via constructor parameter or monkeypatch _init_pipeline_controller to use a test double), or

A fake underlying PipelineRunner inside PipelineController, but assertions move “one level down.”

Test ideas:

Bridge invocation test

Given an AppController configured with a fake PipelineController whose start_pipeline records calls:

When AppController.run_pipeline() is invoked,

Then start_pipeline() is called once with expected callbacks.

Lifecycle test

When run_pipeline() succeeds through the pipeline controller:

LifecycleState transitions IDLE → RUNNING → IDLE.

When start_pipeline() raises, or _run_via_pipeline_controller raises:

Lifecycle ends in ERROR and logs include the error message.

Keep tests/controller/test_app_controller_config.py happy by adjusting any constructor usage that now expects a pipeline controller / state manager wiring.

Testing Strategy
Unit / Integration

tests/controller/test_app_controller_pipeline_integration.py

Updated to validate bridge behavior rather than direct runner usage.

tests/controller/test_stage_sequencer_controller_integration.py

Optionally updated to assert that AppController → PipelineController path uses StageSequencer correctly (e.g., by asserting the StageExecutionPlan in the underlying controller).

tests/controller/test_app_controller_config.py

Ensure AppController can still be constructed in tests (with dummy main window / app_state) and that _init_pipeline_controller() doesn’t explode in headless mode.

GUI / Journey (no new tests required in this PR, but should be run)

Run existing journey tests (JT03/04/05) that call AppController.start_run() and confirm they still pass.

These now implicitly validate the modern pipeline path.

Manual checks (for you / Codex)

Launch V2 GUI.

From the Pipeline tab:

Select a simple txt2img config.

Press Run:

Confirm images are generated.

Confirm logs show PipelineController / queue-backed path (not the legacy run_txt2img_once stub).

Enable a refiner / upscale stage:

Confirm stage order / results still match StageSequencer expectations.

Risks & Mitigations

Risks

If _init_pipeline_controller() is miswired, AppController may not initialize correctly in some modes (tests, headless contexts).

test_app_controller_pipeline_integration.py may need non-trivial adjustments because it assumed direct PipelineRunner injection.

Mitigations

Keep _init_pipeline_controller() minimal and defensive:

If it fails, log and fall back to a safe “no-op controller” in tests (but prefer to make tests explicit about this).

Add a very small, dedicated test double for PipelineController in the controller tests, so we can assert the bridge logic without depending on full GUI state.

Definition of Done

AppController.run_pipeline() no longer calls self.pipeline_runner.run(...) directly.

AppController.run_pipeline() and start_run() delegate to PipelineController.start_pipeline(...) (or an equivalent single public method) via _run_via_pipeline_controller().

All existing controller + journey tests pass after updating expectations to the new bridge.

Manually running from the V2 GUI “Run” button executes the modern StageSequencer + PipelineRunner path via PipelineController.