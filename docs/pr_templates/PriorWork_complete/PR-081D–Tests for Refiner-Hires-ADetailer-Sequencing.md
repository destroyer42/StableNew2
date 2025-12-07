PR-081D–Tests for Refiner-Hires-ADetailer-Sequencing.md
Intent

Extend the journey tests to validate the new sequencing and configuration semantics from 081A–081C:

Refiner/Hires config is correctly propagated into API payloads.

ADetailer is always the final stage.

User-visible behavior (metadata, stage order) matches expectations.

These tests sit on top of the lower-level pipeline tests from 081C and are meant to prevent regressions in real V2 app flows.

Files

Journey tests

tests/journeys/test_jt03_txt2img_pipeline_run.py

tests/journeys/test_jt04_img2img_adetailer_run.py

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_full_pipeline_journey.py

Shared helpers (optional but recommended)

tests/journeys/utils/pipeline_asserts.py
(new module for common assertions on stage order & payload content)

Detailed Changes
1) JT-03: txt2img with refiner + hires + ADetailer

File: tests/journeys/test_jt03_txt2img_pipeline_run.py

Add/extend a test variant, e.g.:

def test_jt03_txt2img_with_refiner_and_hires_and_adetailer(...):
    ...


Scenario:

Build the V2 app via build_v2_app(...).

Use the pipeline tab / app_state to configure:

Base txt2img settings (prompt, steps, etc.).

refiner_enabled=True, refiner_model_name="sdxl_refiner_xxx", refiner_switch_at=0.8.

hires_enabled=True, hires_upscale_factor=2.0, hires_upscaler_name="Latent", hires_denoise=0.3.

ADetailer enabled with at least one model (face, etc.).

Patch src.api.client.ApiClient.generate_images and capture calls.

Assertions:

Exactly two key calls happen in order (or whatever your stage count is):

First call: stage="txt2img":

Config includes:

model_name = base model

refiner_enabled=True

refiner_model_name="sdxl_refiner_xxx"

refiner_switch_at=pytest.approx(0.8)

hires_enabled=True

hires_upscale_factor=2.0

hires_upscaler_name="Latent"

hires_denoise ~ 0.3

Final call: stage="adetailer":

Config includes ADetailer settings.

Uses the output of the txt2img/hires stage as input.

No intermediate ADetailer calls are made before hires/base generation.

Optional:

Validate that returned GenerateResult.info from the final stage contains markers for both hires and ADetailer (e.g., metadata keys). You can fake these in the mock return to keep it deterministic.

2) JT-04: img2img + ADetailer with/without hires

File: tests/journeys/test_jt04_img2img_adetailer_run.py

Extend existing tests or add two new ones:

Without hires fix:

Set up img2img pipeline with ADetailer on.

hires_enabled=False.

Patch ApiClient.generate_images.

Assert:

Sequence of stages: ["img2img", "adetailer"].

No hires-related keys (enable_hr, etc.) in the img2img payload.

With hires fix (if supported for img2img):

hires_enabled=True, with some non-default settings.

Assert:

img2img payload includes hires fields (scale, upscaler, denoise).

ADetailer still runs last and sees the hires-processed output.

If img2img doesn’t support hires in your pipeline yet, you can limit the tests to:

Asserting that enabling hires on txt2img does not break the img2img + ADetailer sequence.

3) JT-05: upscale (hires-like behavior)

File: tests/journeys/test_jt05_upscale_stage_run.py

Revise or add tests to ensure:

When a “hires fix” upscaling is configured:

The upscale stage is configured with:

Correct hires_upscale_factor mapping into hr_scale (or equivalent).

Correct hires_denoise mapping into hr_denoise_strength.

The mock WebUIAPI or ApiClient.generate_images sees these values.

Concretely:

In TestJT05UpscaleStageRun.test_jt05_multi_stage_txt2img_upscale_pipeline:

After building the app and setting config:

Configure hires upscaling (factor, denoise).

Patch generate_images or WebUIAPI.

Run the pipeline.

Assert that the upscale-related call contains the matching factor/denoise values passed from the GUI-state.

In test_jt05_upscale_metadata_preservation:

Ensure that when hires fix is used, the metadata in the final image is consistent (e.g., includes upscale_factor, model).

4) Full V2 pipeline journey: end-to-end stage order

File: tests/journeys/test_v2_full_pipeline_journey.py

Extend the existing tests:

Refiner + Hires + ADetailer pipeline order

Build an end-to-end config via build_v2_app:

txt2img base config.

refiner_enabled=True.

hires_enabled=True.

ADetailer enabled.

Patch the pipeline runner or StageSequencer to expose the StagePlan list (e.g., by inspecting the runner’s internal plan or by injecting a fake FakePipelineRunner that records the plan).

Assert:

stage_types == [STAGE_TXT2IMG, ..., STAGE_ADETAILER] with ADetailer last.

Only one ADetailer stage exists.

Config propagation sanity

In the same journey, patch ApiClient.generate_images.

Assert that the combination of runs (txt2img, optional hires/upscale, adetailer) see the same keys and values as set in the GUI (refiner switch, hires scale, etc.).

5) Shared assertion helpers

File: tests/journeys/utils/pipeline_asserts.py (new)

Create reusable helpers for:

Asserting stage order:

def assert_stage_order(stages, expected_types):
    actual = [s.stage_type for s in stages]
    assert actual == expected_types


Asserting that ADetailer is last:

def assert_adetailer_last(stages):
    adetailer_indices = [i for i, s in enumerate(stages) if s.stage_type == StageType.ADETAILER]
    assert len(adetailer_indices) <= 1
    if adetailer_indices:
        assert adetailer_indices[0] == len(stages) - 1


Asserting payload contents (refiner/hires fields) on mocked generate_images calls.

Use these helpers across JT-03/04/05 and full pipeline tests to avoid duplication and keep the expected behavior centralized.

Out of Scope

No new GUI widgets or layout changes beyond what 081B already added.

No changes to low-level WebUI integration beyond what 081C’s runner/client already covers.

No new ADetailer configuration semantics; tests simply lock in “ADetailer is last, runs on final high-res image”.