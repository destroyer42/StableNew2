PR-PIPE-CORE-01 Addendum: PipelineRunner Location & Construction Path
=====================================================================

Context
-------
During implementation of PR-PIPE-CORE-01, there was ambiguity about:

- Where the production `PipelineRunner` should live.
- How to construct the real pipeline executor without pulling legacy GUI logic into `AppController`.

This addendum clarifies those design decisions so future implementers (and Codex) stay aligned with Architecture_v2.

1. Canonical Location of the Production Runner
----------------------------------------------
- The **canonical home** of the production runner is:

  - `src/pipeline/pipeline_runner.py`

- That module is responsible for exposing the controller-facing abstraction:

  - `PipelineConfig` — a small, typed representation of a full pipeline run.
  - `PipelineRunner` — the object that `AppController` calls.

- `src/controller/pipeline_runner.py` is considered **legacy/shim** only. New implementations MUST NOT live there.

2. Relationship to Legacy Controller Runner
-------------------------------------------
- `src/controller/pipeline_runner.py` MAY remain temporarily to support older call sites, but it should be a thin shim only, for example:

  - Re-export symbols from the pipeline layer:

    - `from src.pipeline.pipeline_runner import PipelineRunner, PipelineConfig`

- The v2 `AppController` MUST import from the pipeline layer directly, e.g.:

  - `from src.pipeline.pipeline_runner import PipelineRunner, PipelineConfig`

3. PipelineConfig Responsibilities
----------------------------------
`PipelineConfig` (defined in `src/pipeline/pipeline_runner.py` or `src/pipeline/config.py`) should:

- Represent the complete, controller-facing configuration for a single run, including at least:

  - `model: str`
  - `sampler: str`
  - `width: int`
  - `height: int`
  - `steps: int`
  - `cfg_scale: float`
  - `pack_name: Optional[str]`
  - `preset_name: Optional[str]`

- Be easy to construct from `AppController` state:

  - Pack selection / preset from LeftZone.
  - Core config (model/sampler/resolution/steps/CFG) from the Center Config Panel.

- Be easy to map into the existing pipeline executor’s config/kwargs.

4. PipelineRunner Responsibilities
----------------------------------
`PipelineRunner` must:

- Live in `src/pipeline/pipeline_runner.py`.
- Encapsulate the **production** pipeline behavior behind a small surface:

  - `__init__(self, api_client, structured_logger)`
  - `run(self, config: PipelineConfig, cancel_token) -> None`

- Internally:

  - Use a factory/helper to construct the existing multi-stage executor from the pipeline layer (whatever powers the “journey” tests).
  - Map `PipelineConfig` → the executor’s expected configuration or kwargs.
  - Call the executor’s “run full pipeline” entrypoint.
  - Respect the `cancel_token` as supported by current pipeline design.

- NOT:

  - Import or use Tk/GUI modules.
  - Depend on `AppController` or any controller-layer types.

5. AppController Responsibilities
---------------------------------
Within `src/controller/app_controller.py`:

- `AppController` should:

  - Own the lifecycle state (IDLE, RUNNING, STOPPING, ERROR).
  - Own the `CancelToken`.
  - Hold a reference to a `PipelineRunner` instance (or accept one via DI for tests).
  - Build a `PipelineConfig` from its own config + pack state.
  - Call `self._pipeline_runner.run(pipeline_config, self._cancel_token)` in the worker thread.

- `AppController` must NOT:

  - Talk directly to WebUI or low-level API routes.
  - Instantiate the underlying executor directly.
  - Know about internal pipeline stages.

6. Construction Path for the Real Pipeline
------------------------------------------
The construction path should be:

1. `src.main` (or equivalent entrypoint) constructs:
   - `ApiClient`
   - `StructuredLogger`
   - `AppController(...)`

2. `AppController.__init__` constructs a `PipelineRunner` or accepts one injected:

   - `self._pipeline_runner = PipelineRunner(api_client, structured_logger)`

3. When the user presses Run:

   - Controller snapshots its state into `PipelineConfig`.
   - Worker thread calls `PipelineRunner.run(config, cancel_token)`.

4. Inside `PipelineRunner.run`:

   - A small helper/factory (within `src/pipeline/pipeline_runner.py`) constructs the existing pipeline/executor.
   - The executor runs the multi-stage journey using WebUI via `ApiClient`.
   - `StructuredLogger` records manifests as currently designed.

Any new code that instantiates the underlying executor MUST live in the pipeline layer, not in controller or GUI.

7. Testing Expectations
-----------------------
- Controller tests:

  - Use a **FakePipelineRunner** to validate that:
    - `PipelineConfig` is constructed correctly from controller state.
    - `run(config, cancel_token)` is called with expected arguments.
    - Lifecycle and cancellation behavior remain correct.

- Pipeline tests:

  - Validate that the adapter from `PipelineConfig` to the executor’s internal config works as expected.
  - Avoid real network calls; use mocked `ApiClient` where necessary.

8. Migration Notes
------------------
- Existing code paths that import `PipelineRunner` from `src/controller/pipeline_runner.py` should be migrated gradually to the pipeline-layer import.
- The shim file can be removed once all call sites have been updated and tests are green.

This addendum is now part of PR-PIPE-CORE-01 and should be read alongside the main PR document before any future changes to controller–pipeline wiring.
