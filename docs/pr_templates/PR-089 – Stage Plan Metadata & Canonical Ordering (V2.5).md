PR-089 – Stage Plan Metadata & Canonical Ordering (V2.5)

Status: Proposed
Depends on: PR-086 (Core Contract Repair), Stage_Sequencing_V2_5_V2-P1.md
Primary targets: run_plan, stage_sequencer, stage plan/metadata types

1. Intent

Make the stage plan the single source of truth for “what happens when” in the pipeline:

Each StageExecution / StageExecutionPlan carries full stage metadata including refiner, hires, upscale, and ADetailer knobs in its stage_config.

The plan builder enforces the canonical sequence:

txt2img (with optional refiner/hires metadata) → optional img2img → optional upscale/hires → optional ADetailer

and rejects invalid combinations.

This is the structural prerequisite for the runner, controller, and journeys.

2. Scope

In-scope

Extend plan types (StageExecution, StageExecutionPlan, or equivalent) so that each stage holds:

Stage type (txt2img/img2img/upscale/adetailer).

A stage_config that includes:

Refiner fields: refiner_enabled, refiner_model_name, refiner_switch_at.

Hires fields: hires_enabled, hires_upscale_factor, hires_denoise, hires_steps (if defined in docs).

Stage toggles: txt2img_enabled, img2img_enabled, upscale_enabled, adetailer_enabled (or equivalent flags used in RunConfig).

Implement a plan builder that:

Takes a validated RunConfig (from PR-086/087).

Produces an ordered list of StageExecution objects.

Enforces canonical order & invariants.

Add validation in the plan builder:

At least one generation stage (txt2img or img2img) must exist if ADetailer is requested.

ADetailer must appear last.

No “upscale before generation”.

No empty plan.

Out-of-scope

Actual execution of the plan (that’s PR-090).

GUI wiring or RunConfig creation (PR-091).

Journey and pipeline tests rework (PR-092).

3. Design
3.1 Stage metadata structure

Extend stage plan model (names approximate, adjust to the actual code):

@dataclass
class StageConfig:
    stage_type: StageType            # TXT2IMG / IMG2IMG / UPSCALE / ADETAILER
    enabled: bool = True

    # Generation toggles
    txt2img_enabled: bool = False
    img2img_enabled: bool = False
    upscale_enabled: bool = False
    adetailer_enabled: bool = False

    # Refiner
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_at: Optional[float] = None

    # Hires
    hires_enabled: bool = False
    hires_upscale_factor: Optional[float] = None
    hires_denoise: Optional[float] = None
    hires_steps: Optional[int] = None  # if supported

    # Any other documented knobs for V2.5

@dataclass
class StageExecution:
    id: str
    stage_config: StageConfig
    # plus existing fields: input source, previous stage id, etc.

3.2 Plan builder

Add/extend a function:

def build_stage_plan(run_config: RunConfig) -> StageExecutionPlan:
    """
    Inspect RunConfig and produce an ordered, validated list of StageExecution instances.
    Enforces canonical sequencing and invariants.
    """


Behavior:

Derive generation stages:

If run_config.txt2img_enabled: create a txt2img stage with its config and refiner/hires metadata.

If run_config.img2img_enabled: create an img2img stage that consumes output from txt2img (or external source if allowed).

Upscale/hires:

If run_config.upscale_enabled or hires-upscale config is present:

Append an upscale stage after the last generation stage.

ADetailer:

If run_config.adetailer_enabled:

Append an adetailer stage at the end of the list.

Validation rules:

If adetailer_enabled and no generation stage exists → raise InvalidStagePlanError.

If plan order would violate canonical sequence → reorder or raise; tests/docs should define whether we auto-repair or hard-fail.

If no enabled stages at all → raise InvalidStagePlanError.

The intent: building a correct StageExecutionPlan is deterministic and independent of the runner.

4. Files to Touch

src/pipeline/run_plan.py (or equivalent plan types)

src/pipeline/stage_sequencer.py (or wherever the builder currently lives)

Possibly src/pipeline/variant_planner.py if it needs metadata from the plan

Tests

tests/pipeline/test_stage_sequencer_runner_integration.py

Add/extend a dedicated plan-builder test module, e.g.:

tests/pipeline/test_stage_plan_builder_v2_5.py

5. Test Plan

New tests for plan builder:

txt2img only → single stage, no refiner/hires/adetailer.

txt2img + hires + refiner → one stage with both sets of metadata.

txt2img + upscale + adetailer → ordered [txt2img, upscale, adetailer].

img2img + adetailer without txt2img, if allowed → [img2img, adetailer].

Invalid: adetailer_enabled with no generation → raises.