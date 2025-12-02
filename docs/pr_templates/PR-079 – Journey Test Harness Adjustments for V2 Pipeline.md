PR-079 – Journey Test Harness Adjustments for V2 Pipeline

Status: Draft
Owner: Rob / StableNewV2
Baseline: StableNew-snapshot-20251202-070648.zip
Files changed (current working copy vs snapshot):

pytest.ini

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_full_pipeline_journey.py

1. Intent

Tighten up the V2 journey test harness so that:

Journey / slow tests have explicit markers for easier selection/skip behavior.

The V2 upscale journey (JT-05) and the V2 full-pipeline journey tests explicitly seed a “dummy” configuration so the pipeline can run deterministically in a mocked/WebUI-less environment.

This PR does not fully fix all red journeys yet; it surfaces missing shims and config plumbing that will be handled in follow-on PRs (see §5).

2. Scope & Non-Goals
In scope

Test-infra / configuration:

Register journey and slow markers in pytest.ini.

Journey tests:

Add explicit configuration seeding in:

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_full_pipeline_journey.py

Document current failures and what they reveal about missing API shims and state accessors.

Out of scope (for this PR)

Adding the ApiClient.generate_images shim on src/api/client.ApiClient / SDWebUIClient.

Fixing AppStateV2’s missing current_config facade.

Unifying _create_root() behavior across all journey tests (JT-03, JT-04, etc.) to handle Tk/Tcl issues.

Making the entire journey suite green. That will be the job of one or more follow-on PRs.

3. Design / Behavior Changes
3.1 Test selection & markers (pytest.ini)

Problem:
Journey tests make heavy use of @pytest.mark.journey and @pytest.mark.slow, but these markers weren’t registered in pytest.ini, producing Pytest “unknown marker” warnings and making it harder to run/skip them in a controlled way.

Change:

Extend pytest.ini with explicit marker registration:

journey: end-to-end GUI/pipeline tests.

slow: tests that bring up Tk, build the V2 GUI, and potentially interact with a pipeline runner.

This is purely test-harness level; no runtime behavior of StableNew itself changes.

3.2 JT-05 upscale journey – explicit config seeding

File: tests/journeys/test_jt05_upscale_stage_run.py

Prior behavior (snapshot):

JT-05 already:

Built the V2 app (build_v2_app).

Located the pipeline_tab and toggled stages on/off (txt2img, upscale).

Mocked src.api.webui_api.WebUIAPI.upscale_image so no real WebUI was required.

It did not touch app_state.current_config at all; tests were relying on whatever the controller/state defaulted to.

New behavior:

Each JT-05 test now attempts to seed a dummy model and sampler configuration directly on the app state before executing the pipeline:

In test_jt05_standalone_upscale_stage:

app_state.current_config.model_name = "dummy-model"
app_state.current_config.sampler_name = "Euler a"
app_state.current_config.scheduler_name = "Karras"


In test_jt05_multi_stage_txt2img_upscale_pipeline:

app_state.current_config.model_name = "dummy-model"
app_state.current_config.sampler_name = "Euler a"
app_state.current_config.scheduler_name = "Karras"


In the parameter variation and metadata tests:

app_state.current_config.model_name = "dummy-model"


Intent / rationale:

The journey tests are trying to behave more like a “real” V2 run: there should always be a current model & sampler configured when a pipeline is kicked off.

Instead of relying on implicit defaults buried in the controller or state, the tests now make the configuration explicit via app_state.current_config.

Current issue exposed:

AppStateV2 (from src/gui/app_state_v2.py) does not define a current_config attribute or property.

Because of that, attempts to do:

app_state.current_config.model_name = ...


raise:

AttributeError: 'AppStateV2' object has no attribute 'current_config'


Follow-on implications:

The tests are telling us what the journey layer wants:

“There should be a simple, structured view of the ‘current config’ hanging off AppStateV2, with at least model_name, sampler_name, and scheduler_name.”

A subsequent PR will need to either:

Add a real current_config object/property to AppStateV2, or

Adjust the tests to seed configuration through the actual V2 pipeline/preset API instead of hanging it off AppStateV2.

For this PR spec, we’re simply recording that the tests have been updated to try to seed current_config, and they’re now surfacing the missing state façade as an explicit failure.

3.3 V2 full-pipeline journey – explicit config seeding

File: tests/journeys/test_v2_full_pipeline_journey.py

There are two tests here:

test_v2_full_pipeline_journey_runs_once

test_v2_full_pipeline_journey_handles_runner_error

Prior behavior (snapshot):

Both tests:

Created a root Tk instance via _create_root().

Built the V2 app:

root, app_state, app_controller, window = build_v2_app(
    root=root,
    pipeline_runner=fake_runner,   # FakePipelineRunner in this file
    threaded=False,
)


Drove the GUI + lifecycle enough to:

Trigger a single run via the injected FakePipelineRunner.

Assert that the lifecycle toggles, run flags, and error handling behave correctly.

They did not touch any configuration on app_state; the focus was on wiring, not on model selection.

New behavior:

Both tests now attempt to seed a dummy model into the app state immediately after building the V2 app:

app_state.current_config.model_name = "dummy-model"


Intent / rationale:

Establish a consistent pattern across journey tests: before running any pipeline, there should be a configured model name.

Even if the tests don’t inspect the model, they keep the harness “honest” about requiring a minimal config.

Current issue exposed:

Same as JT-05: AppStateV2 doesn’t expose current_config, so this line raises:

AttributeError: 'AppStateV2' object has no attribute 'current_config'


Follow-on implications:

Any “full pipeline” runner path that assumes the presence of state.current_config is fragile today.

A future PR needs to introduce either:

A thin CurrentConfig dataclass on AppStateV2, or

A dedicated accessor (e.g., state.get_current_config() or state.get_model_selection()) that journey tests and the controller can share.

For this PR, again, we’re just making the expectation explicit and letting the tests surface the missing abstraction.

4. File-by-File Diff Summary
4.1 pytest.ini

Before:

Minimal [pytest] configuration, primarily test discovery paths.

After:

Add marker registration:

[pytest]
markers =
    journey: End-to-end UI/pipeline journey tests.
    slow: Tests that bring up Tkinter / GUI and may be long-running.


Keeps existing testpaths or other options unchanged.

Behavioral impact:

Pytest no longer warns about unknown markers.

Callers can selectively run or skip journeys with -m journey / -m "not journey" etc.

4.2 tests/journeys/test_jt05_upscale_stage_run.py

Key changes:

In all three JT-05 tests, immediately after building the app:

root, app_state, app_controller, window = build_v2_app(root=root)


we now attempt to seed:

app_state.current_config.model_name = "dummy-model"
app_state.current_config.sampler_name = "Euler a"
app_state.current_config.scheduler_name = "Karras"


(or just model_name in the metadata-focused test).

No changes to:

The Tk root creation helper (_create_root).

The mocking of WebUIAPI methods.

The actual pipeline wiring assertions.

Net effect:

The tests now document a desired contract:

“JT-05 assumes there is a current_config view on app_state, with at least model & sampler attributes.”

In the current repo state, that contract is not met, causing the AttributeError.

4.3 tests/journeys/test_v2_full_pipeline_journey.py

Key changes:

In both test_v2_full_pipeline_journey_runs_once and test_v2_full_pipeline_journey_handles_runner_error, right after building the app we now have:

app_state.current_config.model_name = "dummy-model"


No changes to:

FakePipelineRunner logic.

Lifecycle assertions (run count, failure handling).

Root creation helper logic.

Net effect:

Same as JT-05: tests now assume a current_config view exists on AppStateV2 and expose its absence.

5. Current Test Results & Follow-On Work
5.1 Current results (after this change)

From your most recent run:

JT-03 / JT-04:

Tk error on JT-03:

Failed: Tkinter unavailable for journey test: Can't find a usable init.tcl ...
This probably means that Tcl wasn't installed properly.


→ This comes from _create_root() in test_jt03_txt2img_pipeline_run.py calling pytest.fail on TclError.

API shim errors on JT-03 / JT-04:

AttributeError: <class 'src.api.client.SDWebUIClient'> does not have the attribute 'generate_images'


→ Tests use:

with patch('src.api.client.ApiClient.generate_images') as mock_generate:
    ...


but ApiClient (alias to SDWebUIClient) has no generate_images method.

JT-05 & V2 full pipeline:

All tests in test_jt05_upscale_stage_run.py and test_v2_full_pipeline_journey.py fail with:

AttributeError: 'AppStateV2' object has no attribute 'current_config'