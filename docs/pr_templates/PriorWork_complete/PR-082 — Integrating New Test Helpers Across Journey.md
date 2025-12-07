PR-082 — Integrating New Test Helpers Across Journey + Pipeline + GUI
Intent

Unify and centralize the test helper code for:

Journey tests

Pipeline/runner tests

GUI V2 harness tests

…so that:

Common patterns (FakePipeline, DummyAppController, RunConfig factory, GUI harness bootstrapping) are defined once and reused.

New tests from PR-081D/081E hook into the same helpers.

Future PRs can add tests with less duplication and fewer subtle inconsistencies.

This PR is tests & helpers only, with minimal or no changes to production code.

Scope & Risk

Risk: Low / Medium

Subsystems: Test utilities only

No functional behavior change in runtime code

Intended to stabilize tests and reduce flakiness.

Allowed Files
New / consolidated helpers (examples)

tests/helpers/__init__.py

tests/helpers/factories.py (RunConfig, AppState, simple config fixtures)

tests/helpers/pipeline_fakes.py (FakePipeline, FakeRunner)

tests/helpers/gui_harness.py (GUI V2 bootstrap, Dummy controllers)

tests/helpers/webui_mocks.py (WebUI process/client stubs)

Tests to refactor to use helpers

tests/journeys/*.py

tests/pipeline/*.py

tests/gui_v2/*.py

tests/controller/*.py (where they use FakePipeline or AppController test doubles)

Forbidden Files

Any non-test production code unless a tiny adapter is required:

src/main.py

src/gui/main_window_v2.py

src/pipeline/executor.py

src/controller/app_controller.py

src/pipeline/pipeline_runner.py

src/pipeline/stage_sequencer.py

Implementation Plan
1. Introduce a shared RunConfig factory

Create factory helpers, e.g.:

def make_run_config(
    *,
    txt2img_enabled=True,
    img2img_enabled=False,
    refiner_enabled=False,
    adetailer_enabled=False,
    upscale_enabled=False,
    overrides=None,
) -> RunConfig:
    # Build RunConfig with sensible defaults + overrides


Use this in:

Journey tests (JT03/04/05, full pipeline)

Pipeline runner tests

GUI tests that require a consistent config.

2. Centralize FakePipeline implementations

Create tests/helpers/pipeline_fakes.py with a canonical FakePipeline:

Implements:

run_txt2img_stage(...)

run_img2img_stage(...)

run_upscale_stage(...)

run_adetailer_stage(...)

Uses the canonical signatures from PR-081D-6.

Tracks:

Call order

Arguments (including image_name)

“Images” as simple strings or dicts for assertions.

Refactor:

test_pipeline_runner_variants.py

test_stage_sequencer_runner_integration.py

test_pipeline_io_contracts.py

Learning hook tests that previously defined their own FakePipeline.

3. Centralize GUI V2 harness helpers

Create tests/helpers/gui_harness.py:

Simple helper to bootstrap a GUI V2 instance:

Creates AppController test-double or uses real controller in a safe harness.

Constructs MainWindowV2 or PipelineTabFrameV2 with dummy dependencies.

Provides utility methods:

open_pipeline_tab()

get_stage_card("txt2img")

get_run_controls()

Refactor:

test_main_window_smoke_v2.py

test_pipeline_tab_wiring_v2.py

test_pipeline_stage_cards_v2.py

Other GUI tests that currently do custom bootstrap.

4. Shared WebUI / process mocks

Create tests/helpers/webui_mocks.py with:

DummyProcess (Popen-like; from PR-081D-3)

DummyWebUIClient with .generate_images() and resource accessors.

Refactor:

test_webui_process_manager.py

test_webui_resources.py

Any controller tests using a WebUI client stub.

5. Update journey tests to use shared helpers

Replace bespoke setup code with:

from tests.helpers.factories import make_run_config
from tests.helpers.gui_harness import make_gui_with_controller
from tests.helpers.pipeline_fakes import FakePipeline


Clean up any duplicated FakePipeline definitions.

6. Keep imports stable and explicit

Helpers must be imported via tests.helpers.*

Avoid relative “from ..foo import” clutter that can break when tests are reorganized.

Acceptance Criteria

Common helpers used in:

All journey tests

All pipeline runner/StageSequencer tests

All GUI V2 harness tests that previously hand-rolled the same logic.

No remaining duplicate FakePipeline implementations.

No remaining ad-hoc DummyProcess/RunConfig factories that diverge in behavior.

All tests still pass (or are in expected xfail states defined by previous PRs).

No changes to runtime behavior.

Validation Checklist

 tests/helpers contains well-documented helper modules.

 Journey, pipeline, GUI, and controller tests import helpers from tests.helpers.

 CI/pytest runs show no regressions.

 Tests are simpler and more uniform (fewer lines changed for future behavior PRs).

🚀 Deliverables

New tests/helpers/ package

Refactored tests using shared helpers

Cleaner, more maintainable test suite