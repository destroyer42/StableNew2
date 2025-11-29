# PR-V2-PIPELINE-STAGE-SEQUENCER-002 — Stage Sequencer Orchestration (V2 Pipeline)

## 1. Overview

This PR introduces a **stage sequencer** for the v2 pipeline: a small, testable component that transforms configuration + stage flags into a concrete, ordered execution plan.

Today, the pipeline logic implicitly assumes a fixed order (txt2img → img2img → upscale) and relies on scattered conditionals to skip stages. As we move toward:

- Learning runs (single‑variable sweeps),
- Randomized variant plans,
- Future multi‑node “pipeline farm” execution,

we need a central place to reason about:

- Which stages should run,
- In what order,
- With which configuration snippet,
- And under what constraints (e.g., “upscale requires a base image”).

This PR adds that abstraction and wires it into the v2 runner and controller, without changing user‑visible behavior.

---

## 2. Goals / Non‑Goals

### Goals

1. **Centralize stage ordering**

   - Represent pipeline stages as structured objects rather than ad‑hoc booleans.
   - Keep the default order (txt2img → img2img → upscale) but make it explicit.

2. **Make stage plan derivation testable**

   - Build a pure function that converts `PipelineConfig` + “enabled” flags into a `StageExecutionPlan`.
   - Allow tests to verify sequences for different configurations (e.g., txt2img‑only, upscale‑only).

3. **Prepare for learning and randomizer integration**

   - Allow later PRs to attach extra metadata (learning mode, variant index, farm hints) per stage.
   - Make it trivial to compute “how many steps will this run likely take?” based on stage plan.

4. **Keep the runner/controller behavior stable**

   - Wire the sequencer into `PipelineRunner` with minimal surface changes.
   - No changes to GUI events or UX flows in this PR.

### Non‑Goals

- No new GUI controls for ordering or per‑stage toggling yet (beyond existing settings).
- No multi‑node farm distribution or scheduling.
- No LLM configuration or learning feedback integration here.
- No changes to file IO or SD WebUI API semantics.

Those will be handled in later PRs (e.g., `PR-GUI-V2-STAGE-TOGGLE-001`, `PR-AI-V2-SETTINGS-GENERATOR-001`, and farm orchestration PRs).

---

## 3. Design

### 3.1 Stage model and execution plan

**New file:** `src/pipeline/stage_sequencer.py`

Key dataclasses:

- `StageType`
  - Enum‑like (or literal) type capturing: `"txt2img"`, `"img2img"`, `"upscale"` (extensible).

- `StageConfig`
  - A minimal view of the config relevant to a particular stage:
    - `enabled: bool`
    - `model`, `vae`, `sampler`, `scheduler`, `steps`, `cfg_scale`, `width`, `height`, etc., as applicable.
    - Stage‑specific extras (e.g., `denoising_strength` for `img2img`, `upscaler`/`resize` for `upscale`).
  - Derived from `PipelineConfig` or a raw dict; no SD WebUI client dependency.

- `StageExecution`
  - Represents one stage invocation in the final plan:
    - `stage_type: StageType`
    - `config: StageConfig`
    - `order_index: int`
    - `requires_input_image: bool`
    - `produces_output_image: bool`
    - Optional fields for future use: `learning_mode`, `variant_index`, `farm_hint`.

- `StageExecutionPlan`
  - A simple container:
    - `stages: list[StageExecution]`
    - `run_id: str | None`
    - `one_click_action: str | None`
  - Read‑only view of “what will this pipeline run actually do?” for a single variant.

The intent is that **every** caller uses this plan when they want to reason about stages, not raw booleans in the config.

---

### 3.2 Plan builder

**Function:** `build_stage_execution_plan(config: PipelineConfig | dict) -> StageExecutionPlan`

Semantics:

1. Extract per‑stage enablement from `config`:
   - `config["txt2img"]["enabled"]` (or equivalent flag).
   - `config["img2img"]["enabled"]`.
   - `config["upscale"]["enabled"]`.

2. Construct the default ordering:
   - If txt2img is enabled → push a `StageExecution` with `order_index=0`.
   - If img2img is enabled → push a `StageExecution` with `order_index=1`, `requires_input_image=True`.
   - If upscale is enabled → push a `StageExecution` with `order_index=2`, `requires_input_image=True`.

3. For each stage, derive a `StageConfig` slice from the full config:
   - Only include fields that stage actually uses (e.g., `upscaler`, `upscaling_resize` for `upscale`).
   - Preserve the underlying values exactly; no defaults are invented here.

4. Build and return the `StageExecutionPlan`:
   - `run_id` and `one_click_action` are pulled from `PipelineConfig` metadata when available.
   - The plan does **not** decide variant count (that remains owned by the randomizer/learning plan).

Error handling:

- If no stages are enabled, return an empty `StageExecutionPlan` and let the caller decide whether to treat that as a validation error.
- If required stage fields are missing (e.g., an enabled stage lacks a model), the builder raises a descriptive `ValueError` with a clear message, so callers can surface it via the GUI or logs.

---

### 3.3 Runner integration

**File:** `src/pipeline/pipeline_runner.py`

We extend the runner with a small, explicit seam:

- When preparing to execute a **single variant**:
  - The runner calls `build_stage_execution_plan` with the effective config for that variant.
  - For each `StageExecution` in `plan.stages`:
    - It routes to the appropriate underlying call (txt2img, img2img, upscale), using the `StageConfig` payload.
    - It enforces `requires_input_image` / `produces_output_image` invariants:
      - img2img and upscale refuse to run if they don’t have a valid input image from a prior stage.
  - If the plan is empty, the runner raises a controlled error (“No pipeline stages enabled”) which the controller can surface.

We deliberately keep this layer **pipeline‑only**:

- No GUI imports.
- No SD WebUI URL knowledge beyond what the runner already uses.
- All stage semantics stay in one place.

This makes it much easier for future PRs to:

- Adjust stage ordering for “learning mode” (e.g., run txt2img multiple times with different steps values).
- Insert experimental stages (e.g., video, post‑processing) without touching the GUI.

---

### 3.4 Controller integration

**File:** `src/controller/pipeline_controller.py`

Controller changes are minimal:

- When building the effective config for a run, the controller:
  - Optionally calls `build_stage_execution_plan` in a dry‑run mode to validate the config before handing it to the runner.
  - Logs the plan summary (e.g., “Pipeline plan: [txt2img, img2img, upscale]”) for debugging.

- For tests, the controller exposes:
  - `get_last_stage_execution_plan_for_tests()` → returns the last plan built so GUI v2 tests can assert on it.

The actual execution remains runner‑driven; the controller is not responsible for iterating stages.

---

## 4. Tests

New tests under `tests/pipeline`:

1. `tests/pipeline/test_stage_sequencer_plan_builder.py`
   - Verifies that:
     - txt2img‑only config yields `[txt2img]`.
     - img2img‑only config yields `[img2img]` with `requires_input_image=True`.
     - txt2img+upscale yields `[txt2img, upscale]` and enforces the ordering.
   - Asserts that missing required fields raise clear `ValueError`s.

2. `tests/pipeline/test_stage_sequencer_runner_integration.py`
   - Uses a fake `SDWebUIClient` that records calls instead of hitting a real endpoint.
   - Runs the runner with small configs for:
     - txt2img‑only,
     - txt2img → upscale,
     - txt2img → img2img → upscale.
   - Asserts:
     - Calls happen in the right order.
     - Later stages see the correct input image artifact.
     - The “no stages enabled” case surfaces as a controlled error.

Controller test:

3. `tests/controller/test_stage_sequencer_controller_integration.py`
   - Asserts that `PipelineController` logs/records the last `StageExecutionPlan`.
   - Confirms `get_last_stage_execution_plan_for_tests()` returns the plan for the last run.

Regression:

- `pytest tests/pipeline/test_stage_sequencer_plan_builder.py -v`
- `pytest tests/pipeline/test_stage_sequencer_runner_integration.py -v`
- `pytest tests/controller/test_stage_sequencer_controller_integration.py -v`
- `pytest tests/pipeline -v`
- `pytest -v`

All pass, with any GUI/Tk skips unchanged.

---

## 5. Acceptance Criteria

- [ ] `src/pipeline/stage_sequencer.py` exists and defines `StageType`, `StageConfig`, `StageExecution`, `StageExecutionPlan`, and `build_stage_execution_plan`.
- [ ] `PipelineRunner` uses `StageExecutionPlan` to drive per‑variant execution without changing external behavior.
- [ ] `PipelineController` validates configs using the sequencer and exposes a test hook for the last plan.
- [ ] New pipeline/controller tests pass and are deterministic.
- [ ] Full `pytest -v` passes aside from known Tk/Tcl skips.

---

## 6. Future Work

This PR sets the stage (pun intended) for:

- **Learning mode orchestration**
  - A future PR can construct special plans where a single stage runs multiple times with controlled parameter sweeps.

- **Randomizer + stage integration**
  - Randomizer plans can decorate `StageExecutionPlan` with variant indices and per‑variant tags.

- **Farm execution**
  - A farm coordinator can take `StageExecutionPlan` + variant plans and map them onto multiple nodes, knowing exactly which stages will be executed where.

For now, `PR-V2-PIPELINE-STAGE-SEQUENCER-002` is about correctness and clarity: a single central object that explains, in plain terms, “what the pipeline is about to do.”  
