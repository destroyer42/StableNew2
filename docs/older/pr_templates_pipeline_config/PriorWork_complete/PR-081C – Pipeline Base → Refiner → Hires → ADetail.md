PR-081C – Pipeline Sequencing: Base → Refiner → Hires → ADetailer
Intent

Enforce the correct SDXL operation order in the V2 pipeline, driven by the existing configuration surface (081A/081B) and the ApiClient.generate_images(...) abstraction:

Base txt2img generation (low-res, using base SDXL model).

Refiner pass as part of the txt2img diffusion (if enabled).

Hires fix upscaling + second diffusion pass using the base model (if enabled).

ADetailer pass(es) on the final, high-res image as the last stage (if enabled).

The stage runner should not need to know WebUI internals — all WebUI-specific fields are encapsulated in ApiClient.generate_images payload mapping.

Files

Core pipeline

src/pipeline/stage_sequencer.py

src/pipeline/pipeline_runner.py

src/pipeline/run_plan.py

API client

src/api/client.py (extend generate_images payload mapping for refiner/hires/adetailer-related knobs)

Tests

tests/pipeline/test_stage_sequencer.py (new or extended)

tests/pipeline/test_pipeline_runner_sdxl_refiner_hires.py (new)

Detailed Changes
1) Run plan semantics for SDXL + refiner + hires

File: src/pipeline/run_plan.py

Goal: Ensure the canonical RunConfig / StagePlan models can represent:

A single txt2img generation that may internally use:

base model + refiner (via config)

hires fix (via config)

Optional img2img stages.

Final ADetailer stages.

Concretely:

Confirm (or introduce) a StageType enum/constant set that distinguishes:

STAGE_TXT2IMG

STAGE_IMG2IMG

STAGE_UPSCALE or STAGE_HIRES

STAGE_ADETAILER

Extend StagePlan (or equivalent) to explicitly carry:

stage_type: StageType

config: RunConfig or stage-specific config (Txt2ImgConfig, HiresFixConfig)

adetailer_enabled: bool (for final stage only, if needed for clarity)

Optional: metadata dict for assertions/logging.

Example (conceptual):

@dataclass
class StagePlan:
    stage_type: StageType
    name: str
    txt2img: Optional[Txt2ImgConfig] = None
    img2img: Optional[Img2ImgConfig] = None
    hires: Optional[HiresFixConfig] = None
    adetailer_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


Document in code docstrings that:

Refiner is internal to Txt2ImgConfig (via refiner_enabled etc.) and is not modelled as its own StagePlan.

Hires fix is also carried in config (via HiresFixConfig), but the sequencer will ensure it appears in the right place in the stage order (before ADetailer).

No behavioral logic here yet; just ensure the data model supports what we need.

2) Stage sequencer: enforce ordering & inject refiner/hires semantics

File: src/pipeline/stage_sequencer.py

Goal: Given a RunConfig, produce a List[StagePlan] that is correctly ordered and normalized:

Always: base txt2img first (if pipeline includes txt2img).

Optional img2img stages next.

Hires fix/upscale before ADetailer.

ADetailer last.

Key steps:

Normalize stages:

Start from current logic that builds the stage list.

Add a normalization pass that:

Ensures only one “ADetailer” stage exists at most.

If any ADetailer stage is found at an earlier index than a “generation/upscale” stage, move it to the end.

Logging:

If reordering is needed, log a warning, e.g.:

logger.warning(
    "ADetailer stage detected before generation/hires stages; "
    "auto-moving ADetailer to final position."
)


Refiner integration:

When constructing the txt2img StagePlan:

If run_config.txt2img.refiner_enabled is True, set:

stage_plan.txt2img.refiner_enabled = True
stage_plan.txt2img.refiner_model_name = ...
stage_plan.txt2img.refiner_switch_at = ...


Do not add a separate refiner stage. Instead, this is a signal to the runner that refiner params must be folded into the same generate_images call.

Hires fix integration:

When run_config.hires_fix.enabled is True:

Do not treat hires fix as an independent “pipeline stage” distinct from txt2img; instead:

Attach the HiresFixConfig to the relevant generation stage (usually txt2img, or img2img if you’ve decided to support hires there).

Guarantee in the stage list that any “upscale” stage representing hires is before ADetailer.

The planned behavior for 081C is:

txt2img stage config includes hires fix metadata (for WebUI enable_hr, etc.).

If you currently treat upscale as a separate stage, ensure that stage is inserted before ADetailer and carries the hires config.

Final stage ordering:

The sequencer should guarantee the following effective order:

["txt2img", ("img2img" optional), ("upscale"/"hires_fix" optional), ("adetailer" optional)]

Implementation sketch:

Build an initial ordered list based on existing logic.

Partition it into:

generation_stages (txt2img/img2img/upscale)

adetailer_stages (any stage marked as ADetailer)

Reassemble:

ordered = generation_stages + adetailer_stages


Replace the original list with ordered.

Guardrails / error conditions (minimal):

If the pipeline configuration somehow produces a plan with ADetailer but no generation stages (txt2img/img2img/upscale), fail fast:

Either raise a specific error (e.g., InvalidPipelinePlanError) or log and skip that run.

For this PR, raising an error with a clear message is acceptable.

3) Pipeline runner: executing stages via ApiClient.generate_images

File: src/pipeline/pipeline_runner.py

Goal: the runner should:

Iterate the ordered StagePlan list from the sequencer.

For each plan, assemble a config dict for ApiClient.generate_images(...).

For ADetailer, ensure it runs on the latest image output as the final step.

Key behaviors:

Refine txt2img execution:

When encountering the txt2img stage:

Build a config payload including:

Base model:

model_name, sampler_name, scheduler_name, steps, cfg_scale, etc.

Refiner-related fields if enabled:

refiner_enabled

refiner_model_name → mapped to appropriate WebUI fields (e.g., sdxl_refiner_checkpoint)

refiner_switch_at → convert ratio to steps if needed (e.g., refiner_switch_at * steps → refiner_switch_step).

Hires fix fields if enabled:

enable_hr

hr_scale / hr_resize_x/y (derived from upscale_factor)

hr_upscaler

hr_second_pass_steps (from hires_steps or default)

hr_denoise_strength (from hires_denoise)

Call:

result = api_client.generate_images(
    stage="txt2img",
    config=txt2img_payload,
)


Capture the output images and metadata into the runner’s context so later stages (e.g., ADetailer) can consume them.

Hires fix in runner:

There are two valid patterns; for 081C we align with the description:

Pattern chosen: treat hires fix as part of the same txt2img call:

The payload for generate_images includes both base and hires fields.

The base model remains the hires model (use_base_model_for_hires=True).

The refiner does not run during hires; its work is done during the base/low-res part.

If you also have a separate “upscale” stage, ensure:

It uses the output from the txt2img call (refined low-res image).

Its config is consistent with the hires config in RunConfig.

It runs before ADetailer.

ADetailer as final stage:

When encountering an ADetailer stage:

Ensure there is at least one previous stage that produced images; otherwise, error out clearly.

Invoke generate_images (or a specialized run_adetailer invocation, if you have one) with:

The current image.

ADetailer parameters from config.

Stage label "adetailer" for logging/metrics.

Ensure that:

No subsequent stage modifies the image.

The runner returns the image output from ADetailer as the final result.

Error handling & GenerateResult:

If 079E/079G are already implemented:

Use GenerateResult as the return type for generate_images.

Propagate structured errors upwards (e.g., WebUIUnreachable, InvalidModel, ADetailerConfigError).

Ensure the runner either:

Stops on a fatal error and surfaces a meaningful message, or

Marks the stage as failed and records the error in the result metadata.

4) ApiClient.generate_images payload mapping

File: src/api/client.py

Goal: extend generate_images so it can accept a richer config dict and map it to the WebUI payload fields for SDXL refiner, hires fix, and (optionally) ADetailer metadata.

Signature (conceptual):

class ApiClient:
    def generate_images(
        self,
        stage: str,
        config: dict[str, Any],
    ) -> GenerateResult:
        ...


Mapping rules:

From config keys (coming from runner) to WebUI payload fields:

Refiner:

config["refiner_enabled"] → If true:

payload["sdxl_refiner_checkpoint"] = config["refiner_model_name"]

payload["sdxl_refiner_switch_at"] = config["refiner_switch_at"] (or derived step count).

Hires fix:

config["hires_enabled"] → payload["enable_hr"]

config["hires_upscale_factor"] → payload["hr_scale"]

config["hires_upscaler_name"] → payload["hr_upscaler"]

config["hires_steps"] → payload["hr_second_pass_steps"] (if not None)

config["hires_denoise"] → payload["hr_denoise_strength"]

ADetailer (metadata only, if actual call flows through a different endpoint):

config["adetailer_enabled"] / config["adetailer_models"] → embed as payload["adetailer"] block if needed or store in metadata for a separate call.

Backwards-compatibility:

If refiner/hires keys are absent, the mapping must not break existing calls.

Defaults: only set the extra WebUI fields when the corresponding config flags are enabled.

Tests
1) tests/pipeline/test_stage_sequencer.py

Add tests that:

Given a RunConfig with:

refiner_enabled=True, hires_fix.enabled=True, adetailer_enabled=True,

the sequencer returns a StagePlan list whose stage_types are:

[STAGE_TXT2IMG, STAGE_ADETAILER]


(or [TXT2IMG, UPSCALE, ADETAILER] if you model hires as a separate stage).

A config where an ADetailer stage is mistakenly first produces:

A reordered list where ADetailer is last.

A warning log entry (captured with caplog).

A config with ADetailer but no generation stages raises a clear error.

2) tests/pipeline/test_pipeline_runner_sdxl_refiner_hires.py

Mock ApiClient.generate_images and assert:

For txt2img with refiner_enabled=True and hires_enabled=True:

Runner calls generate_images once for txt2img with a config that includes:

refiner_model_name, refiner_switch_at

hires_enabled=True, hires_upscale_factor, hires_upscaler_name, hires_denoise, etc.

For a pipeline with ADetailer enabled:

generate_images (or ADetailer equivalent) is called last.

The input images to ADetailer come from the previous stage’s result.

Error cases:

If generate_images raises a WebUIUnreachable error, the runner surfaces that error and stops.

Out of Scope

No GUI changes (handled by 081B).

No new ADetailer UI or config semantics beyond respecting “ADetailer is last”.

No additional error taxonomy changes beyond using what 079G already defines.