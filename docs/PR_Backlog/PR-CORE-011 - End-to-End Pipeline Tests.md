PR-CORE-011 – End‑to‑End Pipeline Tests

Status: Specification
Priority: MEDIUM
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026-03-29

Context & Motivation

StableNew has extensive unit tests covering individual modules (config contracts, GUI widgets, pipeline components), but lacks integration tests that exercise the entire text‑to‑video pipeline. According to the research exsum, no tests currently verify that a PromptPack can be executed from start to finish to produce a video file
newtab
. As new features are added (scene planning, character embeddings, style LoRAs), the risk of regressions increases. An end‑to‑end (E2E) test suite will provide confidence that the system works as a cohesive whole.

Goals & Non‑Goals
Goal: Create a set of automated tests that simulate a simple PromptPack or scene plan passing through the entire StableNew pipeline (builder → NJR → pipeline runner → backend → video export). The tests should verify that a video file (or sequence of frames) is produced and that key metadata (prompts, seeds, LoRAs) is preserved.
Goal: Use mocks or lightweight dummy pipelines for heavy components (diffusers/Comfy) to avoid long runtimes and GPU dependency. Focus on verifying data flow and integration logic.
Goal: Integrate these tests into the CI pipeline so they run automatically on every commit, failing fast when integration issues arise.
Non‑Goal: These tests do not measure subjective video quality; they merely assert that the pipeline completes and produces expected outputs. Visual quality evaluation is deferred to manual testing or separate evaluation scripts.
Guardrails
Tests must not rely on external network resources or GPU hardware. Use stubbed versions of diffusers pipelines and ComfyUI nodes that return dummy images or arrays.
E2E tests should be deterministic: fix random seeds and mock any time‑dependent functions to ensure repeatability.
Keep E2E tests minimal and efficient; they should run within reasonable time during CI (e.g. <30 s). Do not attempt to generate high‑resolution videos in CI.
Allowed Files
Files to Create
tests/integration/test_full_pipeline.py – the main test file orchestrating the end‑to‑end run. This script will:
Construct a minimal PromptPack (e.g. a single prompt “A fantasy landscape”).
Invoke the PromptPack builder to generate the NJR tasks.
Use a mocked runner/backend to process the tasks and produce a dummy video file.
Assert that the video file exists and that the metadata file matches expected values.
tests/integration/dummy_backend.py – a lightweight backend that simulates image generation and returns synthetic frames (e.g. colored noise arrays). This allows testing without GPU.
tests/integration/test_story_plan_integration.py – optional test verifying that a StoryPlan with multiple scenes results in multiple video outputs when passed through the compiler and runner.
Files to Modify
pytest.ini or equivalent configuration – include the integration tests in the test discovery pattern and mark them as integration tests so they can be skipped in fast unit runs if necessary.
src/pipeline/job_builder_v2.py – optionally refactor to allow dependency injection of backends (e.g. passing in dummy_backend for tests).
Forbidden Files
Do not modify production code to include test‑only logic; instead, use dependency injection or mocking frameworks.
Do not attempt to perform actual heavy inference in CI; rely on mocks.
Implementation Plan
Design dummy backend: Create dummy_backend.py with a class that mimics the interface expected by the runner (generate_frames() or similar). This dummy backend can generate a series of synthetic frames (e.g. simple numpy arrays or PIL images with random noise). It should also support LoRA and ControlNet parameters (no‑ops) so the pipeline passes these through.

Write full pipeline test: In test_full_pipeline.py, assemble a minimal config:

from src.services.prompt_pack import PromptPack
prompt_pack = PromptPack(prompts=[{"prompt":"A test landscape", "steps":5}])
# build jobs
jobs = prompt_pack.build()
# run through dummy runner
runner = DummyRunner()  # configured to use dummy backend
result = runner.run(jobs)
assert result.video_path.exists()
assert result.metadata[0]["prompt"] == "A test landscape"

Use dependency injection or patching to replace the real backend with the dummy backend. After running, check that a video file (or at least one PNG) is produced in the expected location.

Story plan integration test: If story planning (PR‑CORE‑003) is merged, write a test that loads a dummy StoryPlan with multiple scenes and verifies that the compiler and runner produce the correct number of outputs and that the prompts align with scenes.
CI integration: Ensure that the integration tests run automatically via pytest. Mark them with a custom marker (e.g. @pytest.mark.integration) so they can be skipped when running unit tests only.
Documentation: Document in the contributor guide how to run integration tests locally and how to regenerate dummy outputs if test logic changes.
Testing Plan
Unit tests: The dummy backend should have unit tests verifying that it generates a predictable sequence of frames and that metadata is recorded correctly.
Integration tests: The main test_full_pipeline.py ensures that the builder, runner, and exporter work together. It asserts presence of output files and correctness of associated metadata. Additional tests can verify that LoRA tags are passed through when a style or character is specified.
CI: Configure the CI pipeline to run integration tests. Optionally run them in a separate job so that heavy unit tests remain fast.
Verification Criteria
The integration tests pass in a fresh environment without GPU or network access. A dummy video file (e.g. a small MP4 or GIF) is produced.
Prompt metadata (prompt text, seeds, LoRAs) in the result matches the input PromptPack. The number of outputs equals the number of scenes or prompts.
The integration tests run on CI and fail if the pipeline flow breaks (e.g. a new stage fails to propagate config fields).
No performance regressions in unit tests due to the dummy backend injection.
Risk Assessment
Low risk: This PR introduces tests only. The main risk is inadvertently coupling test code with production code. Mitigate by using dependency injection or mocking frameworks instead of altering production code.
Maintenance: Integration tests require maintenance when pipeline signatures change. Keep tests simple and update them alongside pipeline changes.
Tech Debt Analysis

Implementing E2E tests addresses a major gap in test coverage. It will surface integration bugs early and serve as living documentation for how the pipeline pieces connect. Future debt may include expanding tests to cover new features (e.g. ControlNet, style LoRAs) and adding visual regression testing.

Documentation Updates

Add a section to CONTRIBUTING.md describing how to run integration tests. Explain how to use the dummy backend and how to skip integration tests in unit‑only runs. Document that all new pipeline features should be accompanied by integration tests.

Dependencies
Requires pytest and optionally pytest-mock for mocking. Ensure these are listed in development requirements.
Approval & Execution

Planner: agent
Executor: TBD
Reviewer: @qa‑team
Approval Status: Pending

Next Steps

Once integration tests are in place, gradually increase their coverage. Add tests for specific scenarios (e.g. multi‑scene story plans, LoRA application). Consider adding visual diff tests that compare output images to baselines using metrics like SSIM (Structural Similarity) when GPU resources are available.

