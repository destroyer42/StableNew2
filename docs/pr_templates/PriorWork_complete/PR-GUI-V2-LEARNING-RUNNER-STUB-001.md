# PR-GUI-V2-LEARNING-RUNNER-STUB-001 — Learning Runner Groundwork (Stub Only)

## 1. Title

GUI V2 — Introduce Learning Runner Stubs and Data Models (No Behavior Yet)

## 2. Summary

This PR introduces the **learning-mode groundwork** for StableNew V2 without changing current pipeline behavior or GUI visuals. It adds:

- A minimal **learning plan/runner/feedback** model set under `src/learning/`.
- A **controller-level hook** to access a learning runner in a safe, no-op way.
- A pair of **stub entry points in the GUI** that are not yet wired to visible buttons.
- A focused **test suite** under `tests/learning/` that validates shapes, lifecycles, and invariants.

No images are generated in learning mode yet; no actual experimentation, no LLM calls, and no config mutation behavior.

This is a pure scaffolding PR that keeps the door open for future “Learning Mode” features (including controlled sweeps and user-feedback loops) while preserving current stability.

---

## 3. Problem Statement

We want StableNew V2 to eventually support:

- Controlled, “scientific” learning runs where one variable is swept at a time.
- User feedback per variant, aggregated into a structured context for an LLM.
- Iteratively improved one-click presets and per-pack configs over time.

However, V2 currently has:

- No dedicated learning domain models.
- No clear separation of learning runs from normal pipeline runs.
- No safe way to start adding learning logic without risking regressions.

We need a **strictly bounded foundation** for learning:

- That can be tested in isolation.
- That does not affect existing pipeline runs or GUI behavior.
- That defines the **shape of data and contracts** future PRs will rely on.

---

## 4. Goals

1. Define **learning data models**:
   - `LearningPlan`
   - `LearningRunStep`
   - `LearningRunResult`
   - `UserFeedbackItem` / `FeedbackBundle`

2. Create a **LearningRunner stub**:
   - Prepares batches from a base pipeline config + learning plan.
   - Runs “learning batches” as a no-op, returning deterministic placeholders.
   - Summarizes results into a structured, testable payload.

3. Provide a **learning_adapter** helper:
   - Accepts a base config, a target stage, and a target variable to sweep.
   - Returns an empty or placeholder `LearningPlan` for now.
   - Establishes the future API surface for generation of sweeps.

4. Add **controller and GUI stubs**:
   - Controller exposes `get_learning_runner()` but does not use it yet in normal runs.
   - GUI defines internal methods to start/complete learning runs without UI wiring.

5. Add a **learning test harness**:
   - New `tests/learning/` package.
   - Pure unit tests: no Tk, no pipeline, no network.

---

## 5. Non-Goals

- No visible GUI changes (no buttons, menus, or panels).
- No real learning logic (no sweeps, no config changes, no persistence).
- No integration with randomizer, pipeline runner, or SD WebUI.
- No LLM calls, no HTTP calls, no file I/O beyond tests.
- No changes to existing pipeline behavior or config structures.

---

## 6. Allowed Files

You may modify or create only:

- `src/learning/learning_plan.py` (new)
- `src/learning/learning_runner.py` (new)
- `src/learning/learning_feedback.py` (new)
- `src/learning/learning_adapter.py` (new)

- `src/controller/pipeline_controller.py` (light integration)
- `src/gui/main_window.py` (internal stub hooks only, no UI widgets)

- `tests/learning/test_learning_plan_factory.py` (new)
- `tests/learning/test_learning_runner_stubs.py` (new)
- `tests/learning/test_learning_feedback_packaging.py` (new)
- `tests/learning/test_learning_adapter_stub.py` (new)

- Project config only if required to ensure tests run:
  - `pyproject.toml` (add `tests/learning` to testpaths if needed).

---

## 7. Forbidden Files

Do **not** modify:

- Any legacy GUI files under `tests/gui/` or `tests/gui_v1_legacy/`.
- Randomizer implementations under `src/utils/randomizer.py`.
- Pipeline stages or runner under `src/pipeline/`.
- SD WebUI client implementations under `src/api/`.
- Logger, manifest, and file I/O modules under `src/utils/` (except learning files).
- Any Figma/layout docs, roadmap docs, or existing PR spec docs.

---

## 8. Step-by-Step Implementation

### 8.1. Add Learning Plan Models

Create `src/learning/learning_plan.py` with:

- A `LearningMode` enumeration or simple string constants:
  - e.g. `"single_variable_sweep"`, `"multi_variable_experiment"` (future).

- A `LearningPlan` dataclass with fields like:
  - `mode` (string or enum)
  - `stage` (e.g. `"txt2img"`, `"img2img"`, `"upscale"`)
  - `target_variable` (e.g. `"steps"`, `"cfg_scale"`)
  - `sweep_values` (list of numeric or string values)
  - `images_per_step` (int)
  - `metadata` (dict for free-form annotations)

- A `LearningRunStep` dataclass:
  - `index` (int)
  - `stage` (string)
  - `variable` (string)
  - `value` (scalar)
  - `images_requested` (int)
  - `config_snapshot` (dict) — pipeline config used for this step.

- A `LearningRunResult` dataclass:
  - `plan` (LearningPlan)
  - `steps` (list of LearningRunStep)
  - `artifacts` (list of dict) — placeholder stubs, no real images.
  - `summary` (dict) — placeholder summary, e.g. “not yet implemented”.

- Helper: `build_learning_plan_from_dict(payload: dict) -> LearningPlan`:
  - Validate required keys (mode, stage, target_variable).
  - Normalize `sweep_values` to a list.
  - Provide safe defaults for `images_per_step` and metadata.

### 8.2. Add Learning Feedback Models

Create `src/learning/learning_feedback.py`:

- `UserFeedbackItem` dataclass:
  - `step_index` (int)
  - `score` (numeric or categorical)
  - `notes` (optional string)
  - `selected_best` (bool)

- `FeedbackBundle` dataclass:
  - `plan` (LearningPlan)
  - `items` (list[UserFeedbackItem])

- Helper: `package_feedback_for_llm(bundle: FeedbackBundle) -> dict`:
  - Return a deterministic dictionary containing:
    - Plan metadata.
    - A list of items with step index, score, selected_best, notes.
  - No external calls, no serialization beyond building the dict.

### 8.3. Add Learning Runner Stub

Create `src/learning/learning_runner.py`:

- Class `LearningRunner` with methods:
  - `__init__(self, base_config: dict | None = None)`:
    - Store base config reference, default to empty dict.

  - `prepare_learning_batches(self, plan: LearningPlan) -> list[LearningRunStep]`:
    - Build one `LearningRunStep` per value in `plan.sweep_values`.
    - Each step stores a shallow copy of base_config plus the target variable/value.
    - No network, no pipeline runner.

  - `run_learning_batches(self, steps: list[LearningRunStep]) -> LearningRunResult`:
    - Return a `LearningRunResult` with:
      - `plan` from first step (or a placeholder).
      - `steps` passed in.
      - `artifacts` as list of deterministic placeholder dicts.
      - `summary` as a static dict indicating “unimplemented”.

  - `summarize_results(self, result: LearningRunResult) -> dict`:
    - Return a summary dict derived from result (e.g., count of steps, unique values).

Implementation must be deterministic and side-effect free besides in-memory state.

### 8.4. Add Learning Adapter Stub

Create `src/learning/learning_adapter.py`:

- Function `build_learning_plan_from_config(base_config: dict, *, stage: str, target_variable: str, sweep_values: list) -> LearningPlan`:
  - Thin wrapper around `LearningPlan` with minimal validation.

- Function `prepare_learning_run(base_config: dict, options: dict) -> tuple[LearningPlan, list[LearningRunStep]]`:
  - Options might include stage, target_variable, sweep_values, images_per_step.
  - Construct plan and use `LearningRunner` to prepare steps.
  - No execution, just plan+steps.

This module must not import any GUI modules or Tkinter.

### 8.5. Controller Hook

In `src/controller/pipeline_controller.py`:

- Add a private, lazily used helper:
  - `_get_learning_runner(self) -> LearningRunner`
    - Import `LearningRunner` inside the function to avoid circular imports.
    - Cache the instance on the controller (e.g., `_learning_runner`).

- Do not call `_get_learning_runner` from any existing methods.
- Add a simple method for tests:
  - `get_learning_runner_for_tests(self)` that returns the instance.

### 8.6. GUI Stub Hooks (No UI Changes)

In `src/gui/main_window.py`:

- Add two private methods:
  - `_start_learning_run_stub(self)`:
    - Logs or records that learning mode is not yet implemented.
    - Does not touch the pipeline, controller, or config.

  - `_collect_learning_feedback_stub(self)`:
    - Logs or records that feedback handling is not yet implemented.

They exist only for future wiring and for tests to verify they do not crash.  
Do not add new buttons or menus that invoke these methods yet.

---

## 9. Required Tests (Failing First)

Add tests under `tests/learning/`:

1. `test_learning_plan_factory.py`
   - Create dicts with different modes/stages/variables and assert that:
     - `build_learning_plan_from_dict` populates the dataclass correctly.
     - Missing fields raise or handle errors predictably.

2. `test_learning_runner_stubs.py`
   - Instantiate `LearningRunner` with a sample base_config.
   - Build a simple `LearningPlan` with a target variable and a few sweep values.
   - Assert:
     - `prepare_learning_batches` returns one step per sweep value.
     - `run_learning_batches` returns a `LearningRunResult` with:
       - Matching number of steps.
       - Deterministic placeholder artifacts.
     - `summarize_results` returns the expected summary keys.

3. `test_learning_feedback_packaging.py`
   - Build a `FeedbackBundle` with:
     - A plan.
     - A set of `UserFeedbackItem` objects.
   - Assert that `package_feedback_for_llm`:
     - Returns a dict containing plan metadata and items.
     - Preserves indices and key fields.

4. `test_learning_adapter_stub.py`
   - Use a minimal base_config and options to build a plan+steps via `prepare_learning_run`.
   - Validate:
     - Plan fields match the options.
     - Steps are consistent with sweep_values.
     - No side-effects on the original base_config.

All tests should start red, then pass once implemented.

---

## 10. Acceptance Criteria

This PR is accepted when:

1. `pytest tests/learning -v` passes locally.
2. `pytest -v` passes, and:
   - No new Tk-related skips are introduced.
   - No GUI V2 tests break.
3. Normal pipeline runs remain unchanged (manual spot check OK).
4. `src/learning/` remains free of:
   - GUI imports.
   - Pipeline runner imports.
   - Network activity.

---

## 11. Rollback Plan

If issues arise:

1. Delete the `src/learning/` directory.
2. Remove any learning-related additions from:
   - `src/controller/pipeline_controller.py`
   - `src/gui/main_window.py`
   - `tests/learning/`
3. Remove any `tests/learning` references from `pyproject.toml`.

This is a pure additive, non-invasive feature; rollback is trivial.

---

## 12. Codex Execution Constraints

- Do not modify any file not listed under **Allowed Files**.
- Do not introduce GUI widgets or visible changes.
- Do not change existing pipeline behavior.
- Do not add network calls, file I/O, or external dependencies.
- Ask for clarification before creating any new modules not explicitly listed.
- Stop after:
  - Implementing the models and stubs.
  - Implementing tests.
  - Running the requested test commands and sharing the output.

---

## 13. Smoke Test Checklist

- `python -m compileall src` succeeds (no syntax errors).
- `pytest tests/learning -v` green.
- `pytest -v` green.
- Manual import sanity from a Python shell:
  - `from src.learning.learning_plan import LearningPlan`
  - `from src.learning.learning_runner import LearningRunner`
  - `from src.learning.learning_feedback import package_feedback_for_llm`
  - `from src.learning.learning_adapter import prepare_learning_run`
