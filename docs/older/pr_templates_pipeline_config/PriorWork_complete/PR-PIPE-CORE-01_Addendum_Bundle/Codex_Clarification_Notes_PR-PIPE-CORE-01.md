Codex Clarification Notes for PR-PIPE-CORE-01
=============================================

When you implement or modify PR-PIPE-CORE-01 in the future, apply these rules:

- Treat `src/pipeline/pipeline_runner.py` as the ONLY canonical home of:
  - `PipelineConfig`
  - `PipelineRunner`

- Treat `src/controller/pipeline_runner.py` as legacy/shim:
  - You may re-export from the pipeline layer if needed.
  - Do NOT put new implementations here.

- `AppController` must:
  - Import from `src.pipeline.pipeline_runner` (not the controller-layer shim).
  - Build a `PipelineConfig` entirely from controller state.
  - Call `PipelineRunner.run(config, cancel_token)` in the worker thread.

- `PipelineRunner` must:
  - Be constructed with `api_client` and `structured_logger`.
  - Use an internal helper/factory to build the real executor from existing pipeline modules.
  - Have NO dependencies on Tk or GUI modules.

- Before declaring success, always:
  - Run the controller lifecycle tests.
  - Run any pipeline journey/config tests that validate the adapter from `PipelineConfig` into the executor.

If you are ever unsure “where does the real pipeline live?”, search under `src/pipeline` for the executor used in the pipeline journey tests and wrap THAT from inside `src/pipeline/pipeline_runner.py`. Do not reach around it from `AppController`.
