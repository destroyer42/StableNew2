PR-PIPE-CORE-01: Wire Controller Config into Real Pipeline Runner
=================================================================

1. Title
--------
Replace the dummy pipeline runner with the real PipelineRunner and thread AppController config into the pipeline call (PR-PIPE-CORE-01).

2. Summary
----------
Right now, the v2 stack is stable but still uses a **DummyPipelineRunner**:

- GUI: v2 (MainWindow_v2) with Header/LeftZone/Center/Bottom wired.
- Controller: AppController with proper lifecycle, cancel token, and a stub runner.
- Pipeline: Real pipeline modules exist but are not yet used in the v2 flow.

This PR reconnects the v2 controller to the **real PipelineRunner** while respecting Architecture_v2 and the new config model:

- AppController builds a structured config object from:
  - Packs/Presets (LeftZone state, as far as it is implemented).
  - Core config (Center Config Panel state: model, sampler, resolution, steps, CFG).
- The controller passes that config into the real pipeline runner.
- CancelToken and lifecycle behavior continue to be honored (no regression from PR-0).

We will rely on unit tests with a **fake/mock pipeline runner** to validate the integration, and only lightly exercise the real runner through manual smoke tests.

3. Problem Statement
--------------------
We originally cut over to v2 by “safe-stubbing” the pipeline:

- v2 controller/GUI call a DummyPipelineRunner that simulates work but never touches the real WebUI/pipeline code.
- This eliminated hangs, but it also means:
  - v2 cannot actually generate images.
  - Changes to config (model/sampler/steps, packs) are never applied to real runs.

We now have:

- A stable controller with tests protecting lifecycle and cancellation.
- A v2 GUI with:
  - Packs wiring (PR-GUI-LEFT-01).
  - Config Panel skeleton (PR-GUI-CENTER-01).

We need to **reintroduce the real pipeline runner** in a controlled way, using TDD, without reintroducing old hangs or mixing GUI/pipeline responsibilities.

4. Goals
--------
- Introduce a clear, testable **PipelineRunner interface** (if not already present).
- Make AppController use the real pipeline runner by default, while still allowing a fake runner in tests.
- Ensure AppController builds a well-defined config structure and passes it into the runner.
- Verify via tests that:
  - Controller → runner integration happens with correct parameters.
  - CancelToken and lifecycle transitions remain correct (no deadlocks/hangs).
- Keep pipeline internals **unchanged** in this PR except for what’s strictly necessary to accept the structured config.

5. Non-goals
------------
- No feature expansion in the pipeline (no new stages, no new options).
- No changes to GUI layout or theme.
- No new WebUI parameters beyond what the pipeline already supports.
- No large refactors of the entire pipeline module; we are only introducing a clean integration point.

6. Allowed Files
----------------
This PR may modify or create only:

- `src/controller/app_controller.py` (to switch from DummyPipelineRunner to real runner and build the config object).
- `src/pipeline/pipeline_runner.py` or the equivalent module where the main pipeline runner lives.
- If a dedicated config dataclass/module exists or is appropriate:
  - `src/pipeline/config.py` (new or existing).
- New tests:
  - `tests/controller/test_app_controller_pipeline_integration.py`
  - If helpful and small in scope, a focused pipeline unit test (e.g., `tests/pipeline/test_pipeline_runner_config_adapter.py`)

7. Forbidden Files
------------------
Do **not** modify:

- `src/gui/*`
- `src/api/*`
- `src/main.py`
- Legacy GUI files
- Test configuration / CI files
- Any randomizer/matrix logic

If you discover necessary changes in those areas, stop and request a new PR design instead of expanding this one.

8. Step-by-step Implementation Plan
-----------------------------------

### Step 1 – Define/Confirm the PipelineRunner interface
In `src/pipeline/pipeline_runner.py` (or the existing pipeline module):

- Identify the main entry point used to execute the pipeline (e.g., a `PipelineRunner` class or function).
- If there is no clear “runner” abstraction, introduce a thin class or function that:
  - Accepts a structured config object (or a small dict) with:
    - model
    - sampler
    - width
    - height
    - steps
    - cfg_scale
    - pack/preset info as needed (basic string identifiers are enough for now).
  - Accepts a CancelToken (or similar) so it can honor cancellation.
  - Encapsulates the logic that previously lived in the legacy GUI controller code.

Do **not** refactor pipeline internals beyond what is needed to support this clean signature; the goal is to have a single, obvious entry point for AppController.

### Step 2 – Add a pipeline config structure (if not present)
If not already present, add a small config structure in `src/pipeline/config.py` or within the runner module:

- For example, a `@dataclass PipelineConfig` with fields:
  - model: str
  - sampler: str
  - width: int
  - height: int
  - steps: int
  - cfg_scale: float
  - pack_name: Optional[str]
  - preset_name: Optional[str]
- It should be easy to construct from controller state and easy to test.

If such a config type already exists, reuse it rather than creating a duplicate.

### Step 3 – AppController builds and passes PipelineConfig
In `src/controller/app_controller.py`:

- Replace the DummyPipelineRunner wiring with:

  - A dependency (injected or passed) on a real runner (or runner factory), defaulting to the real pipeline runner in production.
  - Tests will still pass in a fake runner for isolation.

- In the controller’s method that starts the pipeline (e.g., in the worker thread body):

  - Gather state from:
    - Packs/Presets (LeftZone state, via existing controller fields).
    - Config Panel state (Center config, via existing `get_current_config()` or internal fields).
  - Build a `PipelineConfig` (or equivalent config object/dict).
  - Pass:
    - The config object.
    - The cancel token.
    - Any necessary logging or callbacks.
    to the real pipeline runner.

- Ensure that:

  - The CancelToken and lifecycle transitions (RUNNING → STOPPING → IDLE/ERROR) behave identically to PR-0 behavior, just with a real runner now.

### Step 4 – Tests for controller → pipeline integration
Add `tests/controller/test_app_controller_pipeline_integration.py`:

- Use a **FakePipelineRunner** that records:
  - The config object it was given.
  - The cancel token (or equivalent) it was given.
- Construct an AppController with:
  - A fake window (no real Tk).
  - The fake runner injected.
- Simulate:

  1. Starting the pipeline:
     - Verify the fake runner was called exactly once.
     - Assert that the config fields match the controller config state (model, sampler, resolution, steps, cfg, pack/preset).
  2. Cancelling the pipeline:
     - Verify that the CancelToken given to the runner is set/cancelled.
     - Verify that the controller lifecycle returns to IDLE (or ERROR if you simulate an exception from the runner).

You do **not** need to run the real pipeline in unit tests; that is a manual smoke test step.

### Step 5 – Optional small pipeline test
If useful, add a minimal pipeline test (e.g., `tests/pipeline/test_pipeline_runner_config_adapter.py`) that:

- Constructs a minimal `PipelineConfig`.
- Calls the real runner’s “adapter” layer (not the whole WebUI call chain) and asserts:
  - It builds the correct WebUI/API payload fields.

Keep this test small and deterministic; avoid real network calls.

### Step 6 – Manual smoke test
After tests are green:

1. Run `python -m src.main`.
2. Confirm:

   - Hitting Run now triggers the real pipeline runner (i.e., actual image generation through WebUI, assuming WebUI is running and configured).
   - Config changes from the Center Panel (model/resolution/etc.) appear to affect the run (as far as WebUI or logs show).
   - Pack selection (where implemented) is reflected appropriately (path or name showing up in logs or payload).
   - Cancel/Stop behaves as expected (no hangs; pipeline cancels between stages).

9. Required Tests
-----------------
- `pytest tests/controller/test_app_controller_pipeline_integration.py -v`
- The existing controller lifecycle test:
  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
- Optionally, one focused pipeline config test:
  - `pytest tests/pipeline/test_pipeline_runner_config_adapter.py -v` (if implemented)

10. Acceptance Criteria
-----------------------
- DummyPipelineRunner is no longer wired into the v2 controller in production code; instead, the real pipeline runner is used.
- AppController builds a `PipelineConfig` (or equivalent) from its own config state and pack selection and passes it into the runner.
- Controller lifecycle and cancellation behavior remain correct and are validated by tests.
- All existing tests remain green.
- No forbidden files were modified.

11. Rollback Plan
-----------------
- Revert changes to:
  - `src/controller/app_controller.py`
  - `src/pipeline/pipeline_runner.py`
  - (Optional) `src/pipeline/config.py`
  - New tests.
- Restore DummyPipelineRunner wiring if necessary as a temporary fallback.

12. Codex Execution Constraints
-------------------------------
For Codex (implementer):

- Stay strictly within the Allowed Files list.
- Do not refactor large portions of pipeline internals; introduce the smallest viable integration points.
- Preserve controller lifecycle semantics and CancelToken behavior exactly as enforced by existing tests.
- Use dependency injection for the runner in tests to avoid calling the real pipeline.
- Run all required tests and show full output before declaring the PR complete.
