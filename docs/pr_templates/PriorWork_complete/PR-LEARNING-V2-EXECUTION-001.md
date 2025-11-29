
# PR-LEARNING-V2-EXECUTION-001 – Learning Run Execution Pipeline

## 1. Purpose and Context

This PR turns the existing **learning groundwork** into an actual, testable **learning execution pipeline**, without introducing any new GUI dependencies or LLM calls.

We already have:

- `src/learning/learning_plan.py` – `LearningPlan`, `LearningRunStep`, `LearningRunResult`, and helpers to build plans from simple dicts.
- `src/learning/learning_runner.py` – a deterministic stub runner.
- `src/learning/learning_feedback.py` – feedback packaging.
- `src/learning/learning_adapter.py` – bridges configs to learning plans.
- `src/learning/learning_record.py`, `src/learning/run_metadata.py`, `src/learning/dataset_builder.py`, `src/learning/feedback_manager.py` – basic IO and record/dataset structures.
- Pipeline integration:
  - `PipelineRunner` and `PipelineConfig` with learning hooks and `PipelineRunResult`.
  - `StageSequencer` and per-stage execution in the runner.
  - Controller wiring for learning hooks and metadata writing.

This PR builds on that foundation by introducing a **Learning Execution layer** that can:

- Execute a `LearningPlan` as a sequence of controlled pipeline runs (per-step configs, per-stage focus).
- Stay **GUI-free and Tk-free** (pure controller/learning/pipeline integration).
- Provide a **testable, deterministic API** that future GUI work and AI settings generators can call.

No LLM integration, no distributed execution, and no UI widgets are introduced here; this is pure “under-the-hood” orchestration.

---

## 2. Goals

1. Introduce a **Learning Execution Runner** that:
   - Accepts a `LearningPlan` (and optional base config / context).
   - Produces a series of pipeline runs for each `LearningRunStep` (fan-out aware, but still local and serial).
   - Returns a structured result set that can be used for:
     - Feedback capture.
     - Dataset building.
     - Future AI-driven suggestion loops.

2. Add a **controller-level integration** so that callers (future GUI / CLI / automation) can:
   - Invoke a learning execution run via a narrow, high-level API.
   - Observe the resulting `LearningRunResult` objects.
   - Optionally attach learning metadata (e.g., which “one-click action”, which variable was being explored).

3. Ensure **tests and safety constraints**:
   - All new learning execution modules are Tk-free.
   - Learning execution stays deterministic and fast in unit tests.
   - Existing stage-sequencer and learning hooks tests continue to pass (the two known `xfail` tests in `test_upscale_hang_diag.py` remain unchanged).

---

## 3. Non‑Goals

- **No GUI changes** beyond adding controller entry points or stubs that are not visually reachable yet.
- **No LLM calls** or networked AI integration – the AI settings generator remains a separate, higher layer.
- **No distributed/cluster execution** – all runs remain local and sequential.
- **No changes to `src/pipeline/executor.py`** – that file remains untouched.

---

## 4. Design Overview

### 4.1 New Learning Execution Module

Create a new module:

- `src/learning/learning_execution.py`

Responsibilities:

- Define a **configuration layer** for learning execution:
  - A small dataclass (e.g., `LearningExecutionContext` or similar) that bundles:
    - The base pipeline config (or a `PipelineConfig` template).
    - The `LearningPlan` instance.
    - Execution limits such as:
      - `max_steps`, `max_images_per_step`.
      - Optional timeout or cancellation token.
    - Optional metadata tags (e.g., `experiment_name`, `one_click_action_id`).

- Implement a **Learning Execution Runner**:
  - Takes:
    - A `LearningPlan`.
    - A callable or adapter that can invoke the pipeline for a given config (this should be expressed **in terms of the already existing `PipelineRunner` / controller hooks**, not reinvented).
  - For each `LearningRunStep`:
    - Derive the per-step config:
      - Start from the base config.
      - Apply the step’s variable tweak (e.g., CFG scale, steps, sampler) to the appropriate stage config(s), using existing helpers and/or the learning adapter.
    - Invoke the pipeline runner/controller for that step.
    - Capture:
      - The run identifier (if present).
      - Per-step metrics (e.g., which variable, value, stage).
      - Any `LearningRunResult` fields we already have in the groundwork.

  - Return a **top-level result object** that:
    - Exposes the full `LearningPlan` (so dataset builders can reconstruct context).
    - Exposes a list of `LearningRunResult` items (one per executed step).
    - Can be serialized or fed into `dataset_builder` and `feedback_manager` without additional glue.

Constraints:

- Does **not** import Tk or GUI modules.
- Does **not** mutate the base config in place; each step uses a derived config or deltas.
- Does **not** introduce any new IO side effects beyond what the pipeline runner already performs (run metadata, records, etc.).

### 4.2 Controller Integration

Extend a controller to expose **learning execution orchestration** without binding to GUI:

- Either:
  - Extend `src/controller/pipeline_controller.py`, or
  - Introduce a dedicated `LearningExecutionController` in `src/controller/learning_execution_controller.py` that wraps an existing `PipelineController` instance.

Responsibilities:

- Provide a method such as:

  - `run_learning_plan(plan: LearningPlan, base_config: dict | PipelineConfig, metadata: dict | None = None) -> LearningRunExecutionResult`

  The exact name and signature may be adjusted to match existing controller patterns, but it should:

  - Accept a `LearningPlan` from the **learning adapter**.
  - Convert a dict-based config into a `PipelineConfig` if needed, using the existing `PipelineRunner` helpers.
  - Call the Learning Execution Runner defined in `learning_execution.py`.
  - Optionally call into the existing learning record / metadata hooks so that:
    - Each underlying pipeline run is recorded.
    - The “learning run” route is distinguishable in run metadata (e.g., `run_type="learning"`).

- Provide a narrow test hook (e.g., `get_last_learning_execution_result_for_tests()`) so the GUI V2 tests can later verify what happened without needing to re-parse files.

### 4.3 Learning Adapter Alignment

We already have:

- `learning_adapter.py` to map configs/contexts to `LearningPlan` objects.

Ensure the new execution module is **compatible with, but not tightly coupled to** this adapter:

- Execution runner should take a `LearningPlan` and base config; it does **not** construct plans itself.
- Tests for the controller should demonstrate using:
  - The adapter to build a plan.
  - The execution runner to execute that plan.
  - `dataset_builder` and `feedback_manager` to confirm that the results can later be consumed.

### 4.4 Run Metadata & Learning Records

The execution runner should:

- Reuse the existing **learning record** hooks built into `PipelineRunner` and `learning_record.py`.
- Ensure that when invoked via learning execution:
  - The per-step runs are tagged consistently (e.g., `experiment_name`, `variable_name`, `variable_value`).
  - Any optional IDs / tags for “one-click actions” are passed along **if available**, but the PR must not break existing callers that do not supply them.

This PR should **not** change the shape of the learning record on disk, but may add optional fields if they are properly defaulted and covered by tests.

---

## 5. File-by-File Instructions

### 5.1 `src/learning/learning_execution.py` (new)

Create this file with:

- A small set of dataclasses that describe the execution context and results at a coarse level.
- A `LearningExecutionRunner` (or similarly named class/function) that:
  - Accepts:
    - A `LearningPlan`.
    - A base config and/or `PipelineConfig`.
    - A callable that encapsulates “run the pipeline once with this config” and returns a `PipelineRunResult`.
  - Loops over each `LearningRunStep` and:
    - Derives the per-step config.
    - Invokes the callable.
    - Builds a `LearningRunResult` instance (or shaped dict consistent with the groundwork) for that step.
  - Returns an aggregate result bundle that includes:
    - The input `LearningPlan`.
    - The list of step results.
    - Optional summary metrics (counts, failures, etc.).

Assumptions are allowed to stay deliberately conservative – this is v1 of execution; we can extend it in later PRs.

### 5.2 `src/controller/learning_execution_controller.py` (new) or `pipeline_controller.py` (extension)

Introduce a narrow controller layer that:

- Has a method to **run a learning plan** end-to-end.
- Is careful not to import any GUI/Tk modules.
- Uses existing controllers/runners for actual pipeline calls.
- Delegates the core loop to `learning_execution.py`, rather than duplicating logic.

Add any **minimal state** necessary to support:

- Retrieving the last execution result for tests.
- Thread-safety for the typical unit-test usage (single-threaded is fine).

If you extend `pipeline_controller.py` instead of adding a new file, keep the learning-execution surface clearly separated and thoroughly documented.

### 5.3 Learning Tests – `tests/learning_v2/…`

Add new tests in `tests/learning_v2/`:

- `test_learning_execution_runner_happy_path.py`
  - Uses a **fake pipeline-run callable** (no Tk, no real executor) that records the passed configs.
  - Constructs a small `LearningPlan` with a few `LearningRunStep` entries (e.g., changing CFG and steps).
  - Verifies:
    - The number of pipeline calls matches the number of steps.
    - Each config passed into the fake runner reflects the expected per-step overrides.
    - The aggregate result object contains one result per step and preserves variable/value metadata.

- `test_learning_execution_controller_integration.py`
  - Uses a dummy controller/runner setup consistent with existing tests.
  - Demonstrates:
    - Building a plan via the existing learning adapter (if practical).
    - Running the plan through the controller’s learning-execution method.
    - Asserting that:
      - Learning records / metadata hooks were called.
      - The last execution result recalls the expected step count and tags.

### 5.4 Safety Test – `tests/safety/test_learning_execution_no_tk_imports.py`

Add a safety test that:

- Imports the new learning execution module and controller.
- Asserts that importing them does **not** pull Tk or `src.gui` modules into `sys.modules`.
- Mirrors the patterns already used for other adapter/learning safety tests.

### 5.5 Minor Updates

If necessary and justified by the learning execution design:

- Extend `learning_contract.py` or `learning_plan.py` with **optional fields only**, keeping defaults backwards-compatible.
- Add small doc updates:
  - `docs/ROADMAP_v2.md` – mention that **Learning V2 Execution** is now available as an internal, non-GUI API.
  - `docs/CHANGELOG.md` – add an entry for `PR-LEARNING-V2-EXECUTION-001`.

Do **not**:

- Change `src/pipeline/executor.py`.
- Change GUI behavior or wiring beyond purely optional stubs.

---

## 6. Test Expectations

After implementing this PR, the following should all pass (with the existing, known `xfail`s preserved as-is):

1. `python -m pytest tests/learning_v2 -v`
2. `python -m pytest tests/learning -v`
3. `python -m pytest tests/safety/test_learning_execution_no_tk_imports.py -v`
4. `python -m pytest tests/pipeline -v`
   - Two existing `xfail`s in `tests/pipeline/test_upscale_hang_diag.py` remain unchanged.
5. `python -m pytest tests/gui_v2 -v`
6. `python -m pytest -v`

If any additional tests need to be marked `xfail` or skipped because of limitations in the environment, they must be justified in the test file with a clear reason referencing this PR or a future one.

---

## 7. CODEX Run Sheet (Drop-In Instructions)

Use the following instructions verbatim for the assistant configured as **ChatGPT Codex 5.1 max** working on this PR:

1. **Checkout and context**
   - Ensure you are on the `MoreSafe` branch (or the current feature branch for StableNew).
   - Read `docs/ROADMAP_v2.md` and `docs/CHANGELOG.md` to understand the V2 direction and prior learning groundwork.
   - Read the existing learning modules in `src/learning/` and the learning-related tests in `tests/learning/` and `tests/learning_v2/`.

2. **Design alignment**
   - Open `src/learning/learning_plan.py`, `src/learning/learning_runner.py`, `src/learning/learning_adapter.py`, and `src/pipeline/pipeline_runner.py`.
   - Ensure your design for learning execution **reuses** existing concepts:
     - `LearningPlan`, `LearningRunStep`, `LearningRunResult`.
     - `PipelineConfig` and `PipelineRunResult`.
     - The stage sequencer integration (no direct calls into the executor).

3. **Implement learning execution**
   - Create `src/learning/learning_execution.py` and implement:
     - A small execution context dataclass (name is up to you, but must be clearly documented).
     - A `LearningExecutionRunner` (class or function) that:
       - Accepts a `LearningPlan`, base config, and a pipeline-run callable.
       - Executes one pipeline run per `LearningRunStep`.
       - Returns a structured result bundle with one entry per step.

4. **Controller integration**
   - Either create `src/controller/learning_execution_controller.py` or extend `src/controller/pipeline_controller.py` with:
     - A public method that accepts a `LearningPlan` and base config, calls the `LearningExecutionRunner`, and exposes the aggregate result.
     - A test-only accessor to retrieve the last execution result.
   - Do **not** import GUI/Tk modules in the learning execution or controller integration.

5. **Tests**
   - Add:
     - `tests/learning_v2/test_learning_execution_runner_happy_path.py`
     - `tests/learning_v2/test_learning_execution_controller_integration.py`
     - `tests/safety/test_learning_execution_no_tk_imports.py`
   - Reuse existing dummy/pipeline test patterns where possible.
   - Ensure all new tests are fast, deterministic, and do not rely on actual Tk/Tcl or disk-heavy IO.

6. **Docs**
   - Append a short entry to:
     - `docs/CHANGELOG.md` under the current version, referencing `PR-LEARNING-V2-EXECUTION-001`.
     - `docs/ROADMAP_v2.md` to mark the learning execution API as “initial implementation complete (non-GUI)”.

7. **Verification**
   - Run:
     - `python -m pytest tests/learning_v2 -v`
     - `python -m pytest tests/learning -v`
     - `python -m pytest tests/safety/test_learning_execution_no_tk_imports.py -v`
     - `python -m pytest tests/pipeline -v`
     - `python -m pytest tests/gui_v2 -v`
     - `python -m pytest -v`
   - Confirm:
     - All new tests pass.
     - Existing `xfail`s in `tests/pipeline/test_upscale_hang_diag.py` remain and are not converted to failures.
     - No GUI/Tk imports leak into learning execution or its controller.

8. **Scope discipline**
   - Do **not** modify:
     - `src/pipeline/executor.py`.
     - Any GUI layout or widget behavior.
   - If you discover issues outside the scope described here, **document them in comments or TODOs**, but do not attempt to fix them in this PR.

If anything in the codebase appears to conflict with these instructions, prioritize this PR spec and leave a short comment or TODO explaining the discrepancy rather than expanding the scope.

---
