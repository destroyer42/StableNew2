PR-042-PHASE1-JOURNEY-TEST-V2-P1

“Boot → WebUI READY → Dropdowns → Single Pipeline Run”

1. Title

PR-042 – Phase-1 Journey Test & Coverage Hardening (GUI V2 + Pipeline)

2. Summary

This PR introduces a single end-to-end Journey test and a few focused unit/integration tests that together:

Prove the Phase-1 “happy path” is intact:

GUI V2 can be constructed without Tk explosions.

WebUI resources are refreshed.

Core dropdowns (model/VAE/sampler/scheduler) are populated from WebUI.

A minimal pipeline job can be assembled and dispatched.

Add targeted coverage to the most fragile links:

GUI scaffolding (MainWindowV2, Pipeline tab wiring).

WebUI connection controller.

Resource + dropdown path.

The goal is to create a tripwire: any future drift that breaks the main UX path should fail tests early.

3. Problem Statement

We’ve done a lot of wiring work (PR-015, 019, 020, 028, 029, 031–033, 034, etc.), but:

There is no single “top-to-bottom” test that:

Instantiates the V2 GUI,

Simulates WebUI readiness and resource refresh,

Builds a JobDraft,

Ensures a pipeline job is emitted.

Coverage is still patchy in some high-risk files:

main_window_v2.py

pipeline_tab_frame_v2.py

webui_connection_controller.py

Codex and future PRs can inadvertently:

Break stage wiring,

Break WebUI READY → resource refresh → dropdown path,

Break job submission,
without immediate, obvious test failures.

We need a Phase-1 Journey test and a few hardening tests to lock down the core behavior before expanding into Randomizer / Learning / advanced queue behavior.

4. Goals

Add a Phase-1 Journey test that (with mocks/stubs):

Constructs the V2 app (or a minimal harness of AppController + MainWindowV2).

Simulates WebUI becoming READY.

Injects a fake WebUIResources object.

Verifies:

Pipeline dropdowns (models / VAEs / samplers / schedulers) are populated.

A JobDraft can be composed (e.g., select one pack, enable txt2img + upscale).

A “Run Now” / “Add to Queue & Run” path results in at least one job being scheduled.

Add focused tests in high-risk modules:

main_window_v2.py:

Validate that constructing MainWindowV2 with a fake controller doesn’t throw, and that tabs (Prompt, Pipeline, Learning) are present.

pipeline_tab_frame_v2.py:

Validate that the left/center/right columns instantiate correctly and bind to AppState/AppController.

webui_connection_controller.py:

Validate that READY transitions trigger callback(s) without raising, using mocks.

Avoid touching forbidden core files:

No changes to:

src/main.py

src/pipeline/executor(_v2).py

src/api/healthcheck.py

The Journey test must use existing public objects and mocked dependencies, not change prod entrypoints.

Keep the scope tight:

No test explosion.

No refactors disguised as “test prep”.

Only the minimum hooks needed to simulate the happy path.

5. Non-goals

No retry/backoff stress tests.

No negative UX paths (invalid config, WebUI offline, etc.) — those can be later PRs.

No Learning, Randomizer, or Job History assertions; only confirm that:

WebUI READY → resources refreshed → dropdowns populated.

At least one pipeline job can be started.

No GUI visual assertions; this PR is about behavior, not theme.

6. Allowed Files

Journey tests & helpers

tests/journey/test_phase1_pipeline_journey_v2.py (new)

Optional tiny test harness module:

tests/journey/helpers/app_harness_v2.py (new) if needed to avoid duplicating setup.

GUI V2 (tests only rely on these; code changes very small and test-oriented)

src/gui/main_window_v2.py

Only allow:

A minimal factory/helper for tests, e.g. create_main_window_for_test(controller) if strictly necessary.

Prefer no changes if tests can construct the window directly.

src/gui/views/pipeline_tab_frame_v2.py

Only allow:

A small, test-facilitating method/property such as:

get_core_dropdown_widgets() or

debug_get_model_dropdowns()

If we can avoid this and instead access existing public attributes, even better.

Controller & WebUI connection

src/controller/webui_connection_controller.py

Allowed changes:

Minor signature/documentation clarifications.

No behavioral changes beyond what’s needed to allow a ready_callback to be mocked in tests (this should already be present from earlier PRs).

src/controller/app_controller.py

Allowed only if:

A tiny helper is needed to build a test harness around JobDraft → queue submission.

Any structural changes to business logic are forbidden in this PR.

App state & resources

src/gui/app_state_v2.py

Only if a small helper is needed to read/test job draft + run config; no structural changes.

src/api/webui_resource_service.py

No changes unless a type alias or interface clarification is required for test fakes; avoid behavior changes.

New tests

tests/gui_v2/test_main_window_smoke_v2.py (new)

tests/gui_v2/test_pipeline_tab_wiring_v2.py (new)

tests/controller/test_webui_connection_ready_callback_v2.py (new)

7. Forbidden Files

Do not modify:

src/main.py

src/pipeline/executor.py or src/pipeline/executor_v2.py

src/api/healthcheck.py

src/api/webui_process_manager.py

Any legacy V1 files or shims

Any theme / design system files (PR-041 handles visuals)

If a change to one of these feels necessary, it should be a separate, explicitly scoped PR, not part of PR-042.

8. Step-by-step Implementation
A. Phase-1 Journey Test

Create tests/journey/test_phase1_pipeline_journey_v2.py.

In this test:

Skip gracefully if Tk is unavailable:

pytest.skip("Tk not available", allow_module_level=True)


if necessary, or use a fixture that tries to import Tk and skips on failure.

Build a fake WebUIResourceService response:

fake_resources = WebUIResources(
    models=["model_a", "model_b"],
    vae_models=["vae_a"],
    samplers=["Euler a", "DPM++ 2M"],
    schedulers=["Karras", "Normal"],
    # plus any other fields your real WebUIResources uses
)


Construct minimal controller + GUI harness:

Instantiate AppController with:

A fake or in-memory JobQueue (or mocked JobService).

A fake WebUI client that doesn’t actually call real HTTP.

Build MainWindowV2 or directly construct PipelineTabFrameV2 with:

Controller

AppStateV2

Simulate WebUI READY + resources refresh:

Call the same code path that WebUIConnectionController uses when READY:

e.g., app_controller.refresh_resources_from_webui(fake_resources) or set app_state.resources = fake_resources and invoke the existing UI update call.

Assert dropdown population:

Access pipeline tab’s core dropdowns (model / VAE / sampler / scheduler) via existing attributes or a small helper, and verify:

assert "model_a" in model_combobox["values"]
assert "vae_a" in vae_combobox["values"]
assert "Euler a" in sampler_combobox["values"]


Simulate job drafting and run:

Select one pack in the pack selector (if easily accessible in the test harness), or programmatically create a JobDraft in AppStateV2:

app_state.job_draft.add_pack("some_pack_id")


Call the same controller method that “Run Now” or “Add to Queue & Run” uses:

e.g., app_controller.on_run_job_now_clicked() or similar.

Use a mocked JobService / JobQueue:

Assert that it received at least one Job with a payload that includes:

A run config referencing the selected model.

Enabled txt2img (and optionally ADetailer/upscale if enabled by default).

Ensure the Journey test is robust but not over-fitted:

Avoid depending on exact widget text or layout.

Focus on:

“Dropdowns got values from fake resources”.

“A job was enqueued when we asked to run”.

B. GUI smoke tests: MainWindowV2 & PipelineTabFrameV2

Create tests/gui_v2/test_main_window_smoke_v2.py:

Mark as gui, skip if Tk is unavailable.

Build:

root = tk.Tk()
controller = FakeAppController()
window = MainWindowV2(root, controller=controller)


Assert:

No exception is raised.

There is a notebook with 3 tabs (Prompt, Pipeline, Learning), using labels or known IDs.

Create tests/gui_v2/test_pipeline_tab_wiring_v2.py:

Construct a PipelineTabFrameV2 with a fake app_state and fake controller.

Assert:

Left column: has pack selector + stages card + config panel frame.

Center column: stage cards panel instance exists.

Right column: preview/queue/history container exists.

Optionally verify:

Calling a public update method (e.g., update_from_run_config) doesn’t raise.

C. WebUI connection controller coverage

Create tests/controller/test_webui_connection_ready_callback_v2.py:

Instantiate WebUIConnectionController with:

Mocked API client (that pretends healthcheck is OK).

Mock ready_callback = MagicMock().

Simulate:

Starting connection logic (may be synchronous or lightly async).

Triggering the code path that calls ready_callback.

Assert:

ready_callback was called exactly once with expected arguments (e.g., base URL or resource summary).

No exceptions are thrown.

You can use fake timeouts or synchronous code paths as long as you stay within existing public/protected method semantics.

D. Optional tiny helpers (only if strictly necessary)

If accessing specific dropdowns or components is impossible without reflection:

In pipeline_tab_frame_v2.py, optionally add a very small “debug/test accessor” method, e.g.:

def _debug_get_core_dropdowns(self) -> CoreDropdowns:
    return CoreDropdowns(
        model=self._core_config_panel.model_combobox,
        vae=self._core_config_panel.vae_combobox,
        sampler=self._core_config_panel.sampler_combobox,
        scheduler=self._core_config_panel.scheduler_combobox,
    )


Use a lightweight namedtuple or dataclass inside the test module to make assertions simpler.

Avoid any behavior changes or layout changes in production code solely for tests.

9. Required Tests (Failing first)

Before implementation, the following tests will fail or not exist:

tests/journey/test_phase1_pipeline_journey_v2.py

tests/gui_v2/test_main_window_smoke_v2.py

tests/gui_v2/test_pipeline_tab_wiring_v2.py

tests/controller/test_webui_connection_ready_callback_v2.py

After implementation:

All of the above must pass:

python -m pytest tests/journey/test_phase1_pipeline_journey_v2.py -q
python -m pytest tests/gui_v2/test_main_window_smoke_v2.py -q
python -m pytest tests/gui_v2/test_pipeline_tab_wiring_v2.py -q
python -m pytest tests/controller/test_webui_connection_ready_callback_v2.py -q


Plus the existing suite must remain green (aside from known Tk skip markers).

10. Acceptance Criteria

PR-042 is complete when:

Journey test:

Demonstrates:

WebUI READY → fake resources → populated dropdowns.

A job can be created and submitted via controller paths.

Uses only mocks/fakes; no real HTTP, no real WebUI process.

MainWindowV2 smoke test:

Instantiates MainWindowV2 without Tk exceptions.

Confirms Prompt/Pipeline/Learning tabs exist.

Pipeline tab wiring test:

Confirms left/center/right panel creation and base wiring.

No exceptions when invoking key update methods.

WebUI connection controller test:

Confirms READY callback is invoked correctly.

No spurious exceptions on healthcheck success.

No forbidden files changed:

main.py, executor, healthcheck, and V1 files all untouched.

App still boots and runs manually:

python -m src.main still launches the GUI and uses the real WebUI + pipeline as before.

11. Rollback Plan

If PR-042 causes regressions:

Revert new tests and any small helper additions:

tests/journey/test_phase1_pipeline_journey_v2.py

tests/gui_v2/test_main_window_smoke_v2.py

tests/gui_v2/test_pipeline_tab_wiring_v2.py

tests/controller/test_webui_connection_ready_callback_v2.py

Any helper methods added in pipeline_tab_frame_v2.py or others.

Confirm:

Existing test suite returns to previous state.

CLI launch (python -m src.main) still works as before.

12. Codex Execution Constraints

Do not modify:

main.py

Executor modules

Healthcheck logic

Any V1/legacy GUI

Use mocks/stubs/fakes for:

WebUI resources

Job queue / Job service

Keep Journey test minimal but meaningful:

One clear path: READY → dropdowns → job submission.

If a helper method is required in a GUI file, it must be:

Clearly marked as test/debug utility (e.g., _debug_*).

Non-disruptive to runtime behavior.

13. Smoke Test Checklist

After Codex applies PR-042:

Run the new tests:

python -m pytest tests/journey/test_phase1_pipeline_journey_v2.py -q
python -m pytest tests/gui_v2/test_main_window_smoke_v2.py -q
python -m pytest tests/gui_v2/test_pipeline_tab_wiring_v2.py -q
python -m pytest tests/controller/test_webui_connection_ready_callback_v2.py -q


Launch the app:

python -m src.main


Manually validate:

GUI shows Prompt / Pipeline / Learning tabs.

WebUI launches / connects as before.

Pipeline tab dropdowns still populate.

A basic job (one pack, small batch) still runs end-to-end.

If all of this passes and you’re happy with the behavior, PR-042 is ready to merge and we can use it as the guardrail for the next wave (Randomizer, Learning, etc.).