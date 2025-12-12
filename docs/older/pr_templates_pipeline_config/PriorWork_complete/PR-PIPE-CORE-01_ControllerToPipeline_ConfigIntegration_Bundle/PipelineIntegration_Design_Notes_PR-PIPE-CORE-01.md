Pipeline Integration Design Notes (PR-PIPE-CORE-01)
===================================================

Intent
------
Reconnect the v2 controller to the real pipeline in a safe and testable way, using:

- A clear runner interface.
- A small config structure.
- Controller-driven lifecycle and CancelToken management.

Key Principles
--------------
- AppController is the orchestrator:
  - Owns config and pack selection.
  - Builds PipelineConfig.
  - Calls the runner.
- PipelineRunner is the worker:
  - Consumes PipelineConfig and CancelToken.
  - Encapsulates actual WebUI/pipeline interactions.
- Tests use FakePipelineRunner to validate controller behavior without invoking the real pipeline.

Future Extensions (not in this PR)
----------------------------------
- Adding more parameters to PipelineConfig (ADetailer, upscale, randomization, etc.).
- Integrating error reporting and manifest logging via StructuredLogger.
