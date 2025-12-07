PR-090 – PipelineRunner Plan Execution & ApiClient Payloads (V2.5)

Status: Proposed
Depends on: PR-086, PR-089
Primary targets: pipeline_runner, executor, ApiClient.generate_images payload contract

1. Intent

Wire the StageExecutionPlan into the PipelineRunner so that:

The runner iterates stages in order, calling ApiClient.generate_images with a payload derived from stage_config.

Image outputs are threaded from stage to stage:

txt2img → base images

img2img → modifies those images

upscale / hires → enhances them

ADetailer → final touch-up.

Each payload includes the refiner/hires/toggle fields introduced in the docs.

2. Scope

In-scope

Extend PipelineRunner to:

Accept a StageExecutionPlan.

For each StageExecution:

Build a GenerateImagesRequest (or similar) from stage_config.

Call ApiClient.generate_images(request).

Store and pass outputs to the next stage.

Align FakePipeline / test doubles so they accept the same signature as the real runner expects (within PR-086 boundaries).

Ensure runner returns:

Final images.

Any metadata needed by learning hooks / learning tests (hooks themselves are handled in PR-086/082B where applicable).

Out-of-scope

Creating the plan (PR-089).

GUI/controller start/stop wiring (PR-087, PR-091).

Learning-record persistence details (covered by previous learning tests PRs).

3. Design
3.1 Runner input

Runner entrypoint (names approximate):

class PipelineRunner:
    def run_pipeline(self, plan: StageExecutionPlan, base_config: RunConfig, cancel_token: CancelToken | None = None) -> PipelineResult:
        ...


Behavior:

plan comes from PR-089 builder.

base_config contains general settings (prompt, seed, model, output paths).

cancel_token stops further stages if set.

3.2 Per-stage payload mapping

For each stage in plan.stages:

Start from base_config + stage.stage_config.

Build payload for ApiClient.generate_images including:

Common fields:

prompt, negative_prompt

model_name, vae_name

seed, steps, cfg_scale, etc.

input_images (for img2img/adetailer/upscale, coming from previous stage’s outputs).

Refiner fields:

refiner_enabled

refiner_model_name

refiner_switch_at

Hires fields:

hires_enabled

hires_upscale_factor

hires_denoise

hires_steps (if supported)

Stage toggles / type:

stage_type (enum/string)

Flags like txt2img_enabled, img2img_enabled, etc., as expected by the backend.

At the end of the loop:

Collect final images into PipelineResult.

Optionally expose per-stage results where tests need to assert on them.

4. Files to Touch

src/pipeline/pipeline_runner.py

src/api/client.py (if we need minor adjustments to the generate_images signature/mapping, in line with PR-086)

src/pipeline/executor.py (only if necessary to pass through plan/payload cleanly)

Tests

tests/pipeline/test_pipeline_io_contracts.py

tests/pipeline/test_pipeline_runner_variants.py

tests/learning/test_learning_hooks_pipeline_runner.py (call shape, not logic)

Possibly tests/pipeline/test_stage_sequencer_runner_integration.py for end-to-end stage-order + payload mapping.

5. Test Plan

Validate that run_pipeline():

Calls ApiClient.generate_images once per enabled stage.

Threads outputs correctly: txt2img outputs become img2img inputs, etc.

Sets refiner/hires fields on the correct stage only.