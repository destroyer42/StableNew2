PR-081E — Full Sequencing Implementation.md (Refiner + Hires + ADetailer)
Intent

Implement the final V2.5 stage sequencing semantics for the image pipeline, integrating:

Refiner model usage

Hires fix parameters (single- or two-pass)

ADetailer as the final stage on the final high-res image

…so that:

The stage order is deterministic and enforced (no invalid combinations).

RunConfig → StagePlan → PipelineRunner → Executor all agree on how refiner/hires/ADetailer are applied.

The journey tests from PR-081D (including the refiner/hires/ADetailer sequencing tests) pass and “lock in” the behavior.

This PR is the “behavior implementation” that sits under the PR-081D test scaffolding and on top of PR-081D-1..7 and PR-081E’s own pre-journey glue.

High-Level Behavior (What “Correct” Looks Like)
Stage Order Invariants

At least one generation stage must be present

Either txt2img or img2img (or both). If neither is enabled, runner must raise an error early.

Canonical stage order (when enabled)

Conceptually:

txt2img? → img2img? → refiner?/hires (high-res synthesis) → upscale? → ADetailer?


If txt2img_enabled and img2img_enabled:

txt2img runs first, produces base images

img2img runs second, consumes txt2img outputs

If only img2img_enabled:

img2img is treated as the initial generation stage.

Refiner + hires: applied on the intermediate outputs before any explicit Upscale or ADetailer stage.

Upscale (configurable) is applied after refiner/hires (if enabled).

ADetailer is always the final stage, and always runs on the final high-res image batch (after any hires/refiner/upscale).

ADetailer invariants

If ADetailer is enabled, it:

Never runs before any generation stage.

Never runs before hires/refiner/upscale if those are enabled.

Always runs last and sees the final images.

Refiner + Hires semantics

enable_hr and related config (hr_scale, hr_upscaler, hr_second_pass_steps, hr_resize_x/y, denoising_strength, hr_sampler_name) are treated as high-res second-pass information for generation.

refiner_enabled/refiner_model_name represent using a secondary model for the high-res pass (txt2img or img2img).

When refiner is enabled:

The stage plan must ensure that the high-res pass (hires fix) uses refiner_model_name if provided.

This is visible in the payloads sent to the underlying API client (e.g., as an additional refiner_checkpoint or via two-step calls, depending on how 081C defined the runner).

Scope & Risk

Risk Level: High (Tier 3)

Subsystems:

Stage planning / sequencing

Pipeline runner

Journey harness integration

Executor only for wiring, not for deep refactor

This PR should not expand scope beyond sequencing/refiner/hires/ADetailer behavior and the minimal metadata needed to support it.

Files – Allowed to Modify
Core sequencing & runner

src/pipeline/run_plan.py

src/pipeline/stage_sequencer.py

src/pipeline/pipeline_runner.py (limit to sequencing + stage invocation wiring; no big refactor)

Refiner/Hires integration points

src/pipeline/executor.py (tiny changes only, e.g., accepting/forwarding refiner + hires metadata if not already done in 081C; avoid major restructuring)

Tests

tests/pipeline/test_stage_sequencer_runner_integration.py

tests/pipeline/test_pipeline_runner_variants.py

tests/pipeline/test_pipeline_io_contracts.py

tests/journeys/test_v2_full_pipeline_journey.py

tests/journeys/test_jt03_txt2img_pipeline_run.py

tests/journeys/test_jt04_img2img_adetailer_run.py

tests/journeys/test_jt05_upscale_stage_run.py

tests/journeys/test_v2_refiner_hires_adetailer_sequence.py (from PR-081D, remove xfail once behavior is in place)

Files – Forbidden to Modify (Unless Explicitly Unlocked)

src/main.py

src/gui/main_window_v2.py

Any Tk bootstrapping code not directly related to pipeline for journeys

Any learning core modules (beyond using existing hook points)

Cluster/queue core

Detailed Implementation Plan
1. Define a Stable StagePlan Model (run_plan.py)

Introduce (or finalize) a StagePlan / StageExecutionPlan class that can represent each stage with enough information for sequencing and testing.

Example shape:

@dataclass
class StagePlan:
    name: str  # "txt2img", "img2img", "refiner", "upscale", "adetailer"
    enabled: bool
    config: dict[str, Any]
    order: int


And a container:

@dataclass
class PipelinePlan:
    stages: list[StagePlan]


Responsibilities:

Construct a PipelinePlan from RunConfig, including:

Generation stages

Refiner/hires stage information (even if executed as part of txt2img/img2img)

Upscale

ADetailer

Ensure invariants:

Order is canonical.

Required stages exist.

If a separate StageExecutionPlan type already exists from earlier PRs, extend it rather than creating a new one.

2. Implement canonical stage ordering in StageSequencer (stage_sequencer.py)

Use PipelinePlan to build the ordered list of stages to run.

Example (pseudo):

plan = build_pipeline_plan(run_config)

# Filter to enabled stages
stages = [s for s in plan.stages if s.enabled]

# Validate invariants
if not any(s.name in ("txt2img", "img2img") for s in stages):
    raise StagePlanError("At least txt2img or img2img must be enabled")

if any(s.name == "adetailer" for s in stages[:-1]):
    raise StagePlanError("ADetailer must be the final stage")


Ensure:

If enable_hr or refiner_enabled are set, they influence the appropriate stage’s config (i.e., generation stage’s high-res config).

Upscale stage is always before ADetailer if both enabled.

Tests will assert:

The stage list order ([s.name for s in stages]) matches expectations for different RunConfig combinations.

ADetailer index is always len(stages) - 1 when enabled.

3. Integrate PipelineRunner with StagePlan (pipeline_runner.py)

Update PipelineRunner to:

Build a PipelinePlan from RunConfig.

Ask StageSequencer for the ordered execution list.

Execute each stage in order, passing along the current image batch.

Rough flow:

plan = build_pipeline_plan(run_config)
ordered_stages = StageSequencer(plan).get_ordered_stages()

images = None
for stage in ordered_stages:
    if stage.name in ("txt2img", "img2img"):
        images = pipeline.run_generation_stage(stage, images)
    elif stage.name == "refiner":
        images = pipeline.run_refiner_stage(stage, images)
    elif stage.name == "upscale":
        images = pipeline.run_upscale_stage(stage, images)
    elif stage.name == "adetailer":
        images = pipeline.run_adetailer_stage(stage, images)


Key behaviors:

Generation functions incorporate hires + refiner config:

For txt2img/img2img, incorporate enable_hr, hr_* fields, and refiner_model_name into the payload or into a two-step internal plan (depending on 081C’s design).

ADetailer always receives images from the last previous stage.

4. Wire Refiner + Hires into Executor Contract (executor.py, minimally)

If not already done in earlier PRs:

Ensure run_txt2img and run_img2img accept and pass through:

enable_hr

hr_scale

hr_upscaler

hr_second_pass_steps

hr_resize_x, hr_resize_y

denoising_strength

hr_sampler_name

refiner_model_name (if the WebUI API expects a refiner checkpoint or other field)

This is likely already partially implemented from your earlier snippet; this step is to confirm all fields needed by the PR-081D tests are honored.

The tests from PR-081D–Tests for Refiner-Hires-ADetailer-Sequencing.md will:

Patch generate_images / WebUI API.

Assert that payloads for hires/refiner calls reflect GUI-state config.

5. Ensure ADetailer Runs on Final High-Res Images

Add dedicated run_adetailer_stage() into your FakePipeline and real pipeline:

Self-documenting that ADetailer is a separate stage.

Accepts final image batch and runs ADetailer on each image.

If ADetailer is implemented inside executor, StageSequencer/PipelineRunner should nonetheless treat it as a final stage conceptually to keep tests coherent.

Journey tests will assert:

ADetailer calls are made after all other stages.

ADetailer patches run on the last images (e.g., using image naming/metadata checks).

6. Update and Un-XFail the Sequencing Tests (tests)

Using the PR-081D test plan:

Stage ordering tests:

Different RunConfig setups (txt2img-only, txt2img+img2img, img2img+upscale+ADetailer, etc.).

Assert stage names and indices.

Payload propagation tests:

Refiner:

When refiner_enabled and refiner_model_name set, assert that final high-res generation call uses that model.

Hires:

When hires is enabled, payload includes correct hr_* parameters.

ADetailer:

Assert ADetailer call happens after hires/refiner/upscale.

Journey tests:

JT03/04/05 and full pipeline journeys should:

Run the pipeline end-to-end with mocks.

Assert stage order + integration behavior is correct.

Sequencing-specific tests from test_v2_refiner_hires_adetailer_sequence.py:

Remove xfail and ensure they pass.

Acceptance Criteria

Stage ordering

For every RunConfig combination covered in tests:

Stage sequences match the expected canonical ordering.

ADetailer is always the last stage when enabled.

Refiner/Hires behavior

Refiner/hires config from RunConfig is visible in:

StagePlan.

Runner stage configs.

Final executor payloads.

ADetailer behavior

ADetailer runs only once per pipeline execution.

Always operates on the final high-res images.

Test suite

All sequencing-related pipeline tests pass:

test_stage_sequencer_runner_integration.py

test_pipeline_runner_variants.py

test_pipeline_io_contracts.py

All relevant journey tests pass:

test_v2_full_pipeline_journey.py

test_jt03_txt2img_pipeline_run.py

test_jt04_img2img_adetailer_run.py

test_jt05_upscale_stage_run.py

test_v2_refiner_hires_adetailer_sequence.py (no longer xfail)

No regressions

Existing non-sequencing behavior (basic txt2img/img2img/upscale runs) remains correct.

Learning hooks (covered under PR-081D-6) continue to function.

Validation Checklist

 StagePlan / PipelinePlan definitions reviewed and consistent with previous PRs.

 StageSequencer enforces invariants and raises clear errors for invalid configs.

 PipelineRunner executes stages in correct order and passes appropriate configs.

 Executor payloads contain the expected hires/refiner fields.

 ADetailer runs last and uses the final image batch.

 All old journey tests green; new sequencing tests green.

 No unexpected changes to main entrypoint, GUI boot, or learning core.