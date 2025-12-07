PR-081D-1 — Executor Cancel-Token Test Alignment & DummyClient Update

Intent
Fix the failing executor/cancel-token tests by updating test fixtures and the DummyClient contract to match the modern executor API (_generate_images() returning a dict with "images"). No changes to executor.py itself. Restore correctness for txt2img/img2img/upscale cancellation logic.

Summary of Failures Addressed

Tests failing with:

TypeError: argument of type 'Mock' is not iterable


These originate from:

tests/test_cancel_token.py

tests/pipeline/test_executor_cancellation.py

Journey tests that still patch client.txt2img instead of _generate_images.

Root Cause:
Executor now expects response to be a dict ({"images": [...]}), but tests return raw Mock objects or patch the wrong method.

Scope & Risk Level

Risk: Low/Medium

Subsystems: Pipeline tests only

No modifications to:

src/pipeline/executor.py (forbidden unless explicitly unlocked)

Any controller/GUI code

This PR only touches test fixtures, DummyClient, and patches.

Allowed Files to Modify
Tests & Fixtures
tests/test_cancel_token.py
tests/pipeline/test_executor_cancellation.py
tests/pipeline/test_stage_sequencer_runner_integration.py (if patching _generate_images here)
tests/journey/*  (only where executor mocks must be updated)
tests/conftest.py (DummyClient adjustments)

Non-test code (allowed only within fixtures)
src/api/client.py (DummyClient test subclass ONLY, not production class)

Forbidden Files

(No changes allowed)

src/pipeline/executor.py
src/pipeline/run_plan.py
src/pipeline/stage_sequencer.py
src/pipeline/pipeline_runner.py
src/gui/*
src/controller/*

Implementation Plan
1. Update DummyClient to match new executor API

Extend DummyClient used in tests to include:

def generate_images(self, kind, payload):
    return {"images": ["dummy_image"]}


Plus optional override in tests:

mock_client.generate_images = Mock(return_value={"images": [...]})

2. Update cancel-token tests to patch _generate_images instead of client.txt2img

Replace:

mock_client.txt2img = Mock(return_value=...)


with:

with patch("src.pipeline.executor.Pipeline._generate_images", return_value={"images": [...]})

3. Update side-effect tests to properly simulate looping + cancellation

For tests like:

def save_and_cancel(): ...


Ensure final behavior:

return True  # must be truthy for save loop

4. Update tests to always return a dict

Wrong:

mock_client.txt2img = Mock(return_value=Mock())


Correct:

mock_client.generate_images = Mock(return_value={"images": ["image1", "image2"]})

5. Ensure after-API cancellation tests patch _ensure_not_cancelled correctly

Example:

cancel_token.cancel()


Should be executed after the _generate_images return.

6. Confirm behavior for None → error paths

Executor uses:

if not response or "images" not in response:
    ...


Tests must satisfy dict-based expectations.

Acceptance Criteria
✔ All cancel-token tests pass:

test_cancel_after_txt2img_api_call

test_cancel_during_image_saving

test_cancel_token_passed_to_txt2img

test_full_pipeline_cancel_after_txt2img

test_full_pipeline_cancel_during_img2img_loop

✔ Pipeline tests referencing executor return values use dicts
✔ No test patches the old client.txt2img API
✔ DummyClient implements .generate_images()
✔ No changes to executor implementation
✔ No GUI/controller/journey logic changes
Validation Checklist (per StableNewV2 PR Guardrails)

App boots: NOT required (tests-only PR)

No modification of forbidden files

Executor logic untouched

All modified tests aligned with documented API

Cancel-token behavior validated through patching _generate_images

All tests in tests/test_cancel_token.py now green

No regressive changes in journey tests that perform real pipeline runs

🚀 Deliverable Output

Updated DummyClient test class

Updated cancel-token tests

Updated executor-cancellation tests