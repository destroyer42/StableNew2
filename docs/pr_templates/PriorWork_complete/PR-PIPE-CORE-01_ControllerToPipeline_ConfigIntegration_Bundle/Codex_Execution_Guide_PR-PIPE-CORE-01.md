Codex Execution Guide for PR-PIPE-CORE-01: Wire Controller Config into Real Pipeline Runner
==========================================================================================

Purpose
-------
You are implementing PR-PIPE-CORE-01 to:

- Replace the DummyPipelineRunner with the real PipelineRunner on the v2 path.
- Make AppController build a structured config from its own state and pass it into the pipeline runner.
- Preserve lifecycle and CancelToken behavior already tested in PR-0.

Scope
-----
You may only modify/create:

- src/controller/app_controller.py
- src/pipeline/pipeline_runner.py (or the equivalent main runner module)
- src/pipeline/config.py (if needed for a small config dataclass)
- New tests:
  - tests/controller/test_app_controller_pipeline_integration.py
  - Optionally tests/pipeline/test_pipeline_runner_config_adapter.py

You must NOT modify GUI, API, entrypoint, or legacy GUI modules.

Implementation Steps (High Level)
---------------------------------
1. Read the PR spec:
   - docs\pr_templates\PR-PIPE-CORE-01_ControllerToPipeline_ConfigIntegration.md
2. Identify or define a PipelineRunner entry point that accepts:
   - A config object (or dict) built from controller state.
   - A cancel token or equivalent.
3. Add or reuse a small PipelineConfig structure to represent:
   - model, sampler, width, height, steps, cfg_scale, and pack/preset identifiers.
4. Update AppController so that:
   - It uses a real runner (injected or default) instead of DummyPipelineRunner.
   - It builds PipelineConfig from its own state and passes it to the runner.
   - It continues to honor cancellation and lifecycle transitions exactly as before.
5. Add tests:
   - tests/controller/test_app_controller_pipeline_integration.py using a FakePipelineRunner.
   - Optional small pipeline config adapter test if helpful.
6. Run the tests described in the PR and show full output.

Key Constraints
---------------
- Do not change the external behavior of the controller lifecycle (RUNNING/STOPPING/IDLE/ERROR) beyond replacing the runner.
- Do not introduce GUI or Tk dependencies into pipeline modules.
- Do not introduce pipeline logic into AppController beyond building and passing a config object.

When done, summarize:
- What interface the controller now uses to call the pipeline.
- How the PipelineConfig is constructed from controller state.
- How your tests validate the integration.
