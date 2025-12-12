PR-086 – Core Contract Repair (Implementation, V2.5)

Version: V2.5
Status: Proposed
Owner: StableNewV2 Core / Test Harness WG
Related Docs:

docs/tests/PR-085-Test-Coverage-Uplift-Plan-V2_5.md

PR-081D-6 (PipelineRunner/FakePipeline alignment – spec)

PR-082B/082C/082D/082E (test helpers suite – specs)

1. Intent & Summary

This PR implements the core contract repairs required to stabilize the test harness and unblock higher-layer tests (pipeline, learning, journeys):

Fix the DummyProcess / process harness contract for WebUI process manager tests.

Introduce a canonical FakePipeline helper and align it with PipelineRunner stage signatures.

Update affected pipeline/learning tests to consume the canonical FakePipeline and the repaired contracts.

Goal:

Eliminate current core contract failures (DummyProcess, FakePipeline signature mismatches).

Restore green or meaningful behavior for tests/pipeline/* and tests/learning/* that depend on these helpers.

Increase total coverage and remove “TypeError/AttributeError from test harness” as a failure mode.

Non-goal:

No changes to business logic in production pipeline execution.

No refactor of journey tests or controller/GUI behavior beyond what is strictly necessary for harness alignment.

No changes to refiner/hires/ADetailer sequencing (that is PR-081E’s domain).

2. Scope
In-Scope

DummyProcess contract repair

Fix missing attributes/methods required by webui_process_manager tests:

.terminated or equivalent behavior.

Any minimal attributes needed to simulate a subprocess-like object in tests.

Canonical FakePipeline helper

Create/standardize one FakePipeline implementation in tests/helpers/ (or a similar shared location).

Ensure its stage methods match PipelineRunner’s call contract:

run_txt2img_stage(...)

run_img2img_stage(...)

run_upscale_stage(...)

(and any additional stages we currently call in tests)

Ensure the helper returns structures compatible with:

Learning hooks

Pipeline IO contracts

Variant-planning tests, where applicable.

Update tests to use canonical helpers

Fix tests in:

tests/learning/test_learning_hooks_pipeline_runner.py

tests/pipeline/test_pipeline_io_contracts.py

tests/pipeline/test_pipeline_runner_variants.py

tests/pipeline/test_stage_sequencer_runner_integration.py

tests/api/test_webui_process_manager.py (DummyProcess usage)

Remove ad-hoc FakePipeline / DummyProcess implementations in individual tests where replaced by shared helpers.

Out-of-Scope

GUI V2 entrypoint/entry tests (handled by a different PR).

Controller lifecycle and run_config wiring (separate PRs).

Journey test suite re-alignment (JT03/04/05/v2_full) beyond updating their imports if they use the new helper.

Refiner/hires/ADetailer sequencing logic.

3. Target Files & Changes

Note: File paths and naming are indicative; Codex should adjust based on actual structure in the snapshot.

3.1 New/Updated Test Helpers

New (or consolidated) helper module (canonical location):

tests/helpers/fake_pipeline.py

Define FakePipeline (and any supporting structures) as the single source of truth for pipeline test doubles.

Responsibilities:

Represent the pipeline interface expected by:

pipeline_runner.PipelineRunner

Learning hooks in tests/learning/*

Variant runner tests in tests/pipeline/*

Provide methods with signatures aligned to PipelineRunner calls:

class FakePipeline:
    def __init__(self):
        self.calls = []
        self.configs = []
        self.results = []

    def run_txt2img_stage(
        self,
        config: dict,
        *,
        variant_id: str | None = None,
        variant_meta: dict | None = None,
    ) -> dict:
        # record calls, return stub result

    def run_img2img_stage(
        self,
        config: dict,
        image_name: str,
        *,
        variant_id: str | None = None,
        variant_meta: dict | None = None,
    ) -> dict:
        # record calls, return stub result

    def run_upscale_stage(
        self,
        config: dict,
        image_name: str,
        *,
        variant_id: str | None = None,
        variant_meta: dict | None = None,
    ) -> dict:
        # record calls, return stub result


Provide minimal “fake results” including:

image_name or equivalent output identifier.

learning_record or stub metadata where tests expect it.

If a shared helper already exists in tests/helpers/, this PR will promote and standardize that implementation rather than creating a new duplicate.

3.2 DummyProcess Contract Repair

Likely location:

tests/api/test_webui_process_manager.py
or a dedicated helper module such as:

tests/helpers/dummy_process.py

Changes:

Ensure DummyProcess exposes attributes/methods used by process manager tests:

class DummyProcess:
    def __init__(self, pid: int = 1234, return_code: int | None = None):
        self.pid = pid
        self._returncode = return_code
        self.terminated = False

    @property
    def returncode(self):
        return self._returncode

    def poll(self):
        # return current returncode

    def terminate(self):
        self.terminated = True
        self._returncode = 0

    def wait(self, timeout=None):
        # no-op or set returncode if needed


Update tests that reference DummyProcess to:

Use the shared helper if moved to tests/helpers/.

Assert on .terminated or other attributes in a way that reflects real subprocess.Popen-like behavior.

3.3 Update Affected Tests to Use Shared Helpers

Tests to align:

tests/learning/test_learning_hooks_pipeline_runner.py

Replace any inline FakePipeline definitions with the shared FakePipeline.

Adjust expectations to:

Check calls to run_txt2img_stage / run_img2img_stage / run_upscale_stage.

Assert that learning hook calls are triggered from the proper stage results.

tests/pipeline/test_pipeline_io_contracts.py

Use FakePipeline to validate that PipelineRunner:

Produces return values with expected metadata.

Calls stages with expected arguments (config, image_name, variant data).

tests/pipeline/test_pipeline_runner_variants.py

Use FakePipeline and ensure:

Correct variant IDs are passed through.

Variant count is reported accurately.

tests/pipeline/test_stage_sequencer_runner_integration.py

Align the FakePipeline usage to ensure:

Stage sequencer executes txt2img → (img2img?) → upscale with correct call signatures.

Fix the “got multiple values for argument 'image_name'” error by matching method signatures exactly.

tests/api/test_webui_process_manager.py

Ensure:

DummyProcess now satisfies attributes expected by WebUIProcessManager.

test_stop_handles_already_exited_process passes with the updated harness.

Implementation Pattern:

Import FakePipeline from tests.helpers.fake_pipeline instead of redefining it:

from tests.helpers.fake_pipeline import FakePipeline


For each test:

Replace local fake definitions.

Update assertions to use FakePipeline.calls or similar tracking structures where appropriate.

4. Behavioral Expectations

After this PR:

PipelineRunner tests will:

No longer fail with TypeError due to signature mismatches.

Confirm that stages are called with correct arguments (including image_name and variant metadata).

Learning hook tests will:

Verify learning records are emitted correctly when the runner completes relevant stages.

Stage-sequencer integration tests will:

Verify that sequencer runs txt2img → upscale in the expected order, using the canonical FakePipeline.

WebUI process manager tests will:

Use DummyProcess to simulate an already-exited process without raising attribute errors.

Correctly assert whether stop() handles already-exited processes gracefully.

5. Risks & Mitigations
5.1 Risk: Over-fitting FakePipeline to current tests

Risk: FakePipeline might be tailored too closely to existing tests, making it fragile for future changes.

Mitigations:

Document the intended contract in tests/helpers/fake_pipeline.py docstring.

Keep signatures minimal but explicit:

For each method, explicitly document input params and output shape.

Avoid embedding business logic; keep it as a traceable, simple stub.

5.2 Risk: Divergence from real Pipeline implementation

Risk: FakePipeline may drift from real Pipeline class.

Mitigations:

Limit FakePipeline’s API to the subset used by PipelineRunner.

Add one sanity test that compares inspect.signature of FakePipeline methods vs expected call patterns (from PipelineRunner) to catch drift.

6. Test Plan
6.1 Directly Affected Tests

Ensure the following tests pass:

pytest tests/api/test_webui_process_manager.py::test_stop_handles_already_exited_process

pytest tests/learning/test_learning_hooks_pipeline_runner.py

pytest tests/pipeline/test_pipeline_io_contracts.py

pytest tests/pipeline/test_pipeline_runner_variants.py

pytest tests/pipeline/test_stage_sequencer_runner_integration.py

6.2 Focused Subset Runs

Run a broader, but still focused, subset:

pytest tests/pipeline/ tests/learning/ tests/api/test_webui_process_manager.py

6.3 Coverage Check

After changes, re-run coverage:

pytest --maxfail=1 --disable-warnings --cov=src --cov-report=term-missing


Acceptance for PR-086:

No new failing tests introduced.

All previously harness-related failures in these files removed.

Overall coverage increases (even marginally) and/or moves us closer to the 52% “M1” milestone from PR-085.

7. Acceptance Criteria

For PR-086 to be accepted:

Canonical helpers exist and are used:

tests/helpers/fake_pipeline.py provides a single FakePipeline used by all affected tests.

DummyProcess is either centralized or consistently used across relevant tests.

Contract errors resolved:

No more TypeError due to extra image_name or Mock signature issues in the targeted tests.

No more attribute errors for DummyProcess in WebUI tests.

No business logic regressions:

No code paths in src/pipeline/executor.py or src/pipeline/pipeline_runner.py are changed beyond what’s strictly necessary for tests (ideally none).

Tests & coverage:

All tests listed in Section 6.1 pass.

Coverage moves in a positive direction vs. the baseline reported in PR-085.