PR-081D-6 — PipelineRunnerFakePipeline Signature Alignment (Learning Hooks + Variant Planner)

Intent
Fix all failures caused by function-signature drift between:

pipeline_runner

stage_sequencer

Learning hooks

Variant pipeline tests

FakePipeline classes used in tests

Errors include:

TypeError: FakePipeline.run_img2img_stage() got an unexpected keyword argument 'image_name'
TypeError: FakePipeline.run_upscale_stage() got multiple values for argument 'image_name'


This PR does not modify sequencing logic, only harmonizes the stage-runner signatures so the tests match the real V2 pipeline behavior.

Scope & Risk

Risk: Medium

Subsystems: Pipeline runner + test stubs only

No edits to executor (forbidden subsystem)

No edits to GUI / controller / sequencing logic

Allowed Files
src/pipeline/pipeline_runner.py   (signature alignment only)
src/pipeline/stage_sequencer.py   (if needed to align kwarg names)
tests/pipeline/*FakePipeline*.py
tests/learning/test_learning_hooks_pipeline_runner.py
tests/pipeline/test_pipeline_io_contracts.py
tests/pipeline/test_pipeline_runner_variants.py
tests/pipeline/test_stage_sequencer_runner_integration.py

Forbidden Files
src/pipeline/executor.py
src/pipeline/run_plan.py
src/gui/*
src/controller/*
src/main.py

Implementation Plan
1. Establish canonical V2 stage-runner signatures

Codify these signatures to match Stable Diffusion pipeline semantics and the Learning spec:

run_txt2img_stage(self, prompt, config, *, batch_size, image_name=None)

run_img2img_stage(self, image, *, image_name, config)

run_upscale_stage(self, image, *, image_name, config)


Rules:

image_name must always be a named kwarg

Txt2img may receive image_name but can ignore it

Img2img and Upscale must accept image_name and pass it to metadata/learning

2. Update StageSequencer to pass kwargs uniformly

Convert all calls to:

pipeline.run_img2img_stage(
    image_data,
    image_name=stage_image_name,
    config=stage_config,
)

3. Update FakePipeline implementations

Every FakePipeline used in tests must have:

def run_img2img_stage(self, image, *, image_name=None, config=None):
    self.calls.append(("img2img", image_name))
    return {"image": image}

4. Update tests expecting old positional args

Replace:

run_img2img_stage(image, config)


with named:

run_img2img_stage(image, image_name="x", config=config)

5. Ensure learning hooks receive image_name

Learning tests expect metadata with:

"image_name": "001.png"


Make sure PipelineRunner preserves these fields.

6. Variant Planner tests expecting variant counts

Fix tests assuming:

n_variants is derived from stage runner calls

FakePipeline must expose usage counts (reads by several tests)

Acceptance Criteria
✔ All pipeline-runner and stage-sequencer tests pass
✔ Learning hook tests pass
✔ Variant planner tests pass
✔ FakePipeline supports required signatures
✔ No sequencing logic modified
✔ No executor logic modified
✔ No GUI/controller tests touched
Validation Checklist

PipelineRunner stage-call signatures aligned

StageSequencer emits correct kwargs

Learning metadata preserved

FakePipeline updated in all relevant tests

Tests in tests/learning/* and tests/pipeline/* fully green

🚀 Deliverables

Updated stage-calling semantics

Updated FakePipeline test doubles