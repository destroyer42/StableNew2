
# PR-PIPE-DIAG-001: Upscale Hang Repro & Pipeline Telemetry

## 1. Title

**PR-PIPE-DIAG-001: Upscale Hang Repro & Pipeline Telemetry**

---

## 2. Summary

This PR is a **diagnostic and test-focused** change set targeting the intermittent **pipeline hangs around the upscale stage**, especially when multiple images appear to be “in flight” at once.

The intent is to:

- Add **deterministic tests** that reproduce the observed symptoms (long-running upscale, multiple images processed concurrently despite serial expectations, jobs piling up behind a stuck upscale).
- Add **minimal, structured telemetry and guardrails** in the pipeline execution path so that:
  - We can see *exactly* which stage is active and for which image index.
  - We can confirm that the **CancelToken is honored between images and between stages**.
  - We can assert that **only one upscale operation is active per pipeline run** (no silent “fan-out” of upscales).

This PR **does not attempt a broad refactor** of the pipeline or controller. It is narrowly scoped to **reproduce** and **observe** the existing hang behavior with tests and logging, and to add **lightweight guardrails** where necessary.

Use this PR once the repo is at the state of the ZIP:
- `StableNew-MoreSafe-11-20-2025-07-27-00-AftrerPR-PIPE-CORE01.zip`

And with the project docs:
- `docs/ARCHITECTURE_v2_Translation_Plan.md`
- `docs/StableNew_Roadmap_v1.0.md`
- `docs/Known_Bugs_And_Issues_Summary.md`
- `docs/codex/prs/PR-PIPE-014_upscale_tiling.md` (if already added)

---

## 3. Problem Statement

### 3.1 Symptoms (from Known Bugs & Observed Runs)

- On some runs, the **upscale stage stalls** for a long period (e.g., 20 minutes) on what should be a modest 2× upscale of a 1024×1024 image.
- Logs appear to show **multiple images being upscaled at once** when the intended behavior is strictly **one image at a time**.
- When a hang or stall occurs in the upscale stage, **subsequent images pile up behind it**, leading to:
  - Apparent multiple concurrent upscales.
  - The perception that the entire pipeline is hung.
- Previous work (PR-PIPE-014) added **tile size safety** and constraints, but the **queueing / lifecycle behavior** around upscale may still be fragile, especially after the more recent pipeline core changes (PR-PIPE-CORE01).

### 3.2 Likely Contributing Factors

- **Insufficient tests** around multi-image runs that include the upscale stage.
- **Insufficient telemetry** and state assertions in the pipeline execution path:
  - No clear logging for “active stage, image index, and cancel status”.
  - No explicit invariant enforcement for “single active upscale per run”.
- Possible interactions between **CancelToken**, **threading**, and **stage transitions** that are not fully covered by tests.

### 3.3 Why This PR Exists

Before attempting any deeper behavioral changes, we need:

1. **Reproduction tests** that clearly encode the hang scenario as unit/integration tests.
2. **Structured logging and invariants** to reveal what’s happening at runtime.
3. **Minimal guardrails** to prevent known-bad states (e.g., multiple active upscales in a supposedly serial pipeline).

This is strictly a **diagnostic + guardrail** PR, not a full redesign.

---

## 4. Goals

1. **Add tests that reproduce the upscale hang/queue symptoms** in a controlled way, using mocks and timeouts (no real 20-minute waits).
2. **Instrument the pipeline execution path** (especially the upscale-related stage) with structured telemetry so logs clearly show:
   - The current stage name.
   - The current image index (e.g., `image 2/5`).
   - Whether `CancelToken` is active at each stage boundary and between images.
3. **Enforce a small set of invariants** around the upscale stage, such as:
   - At most one upscale operation is active at any given time for a given pipeline run.
   - If `CancelToken` is set, the pipeline should exit promptly between images and not enqueue further upscales.
4. Keep all changes **narrowly scoped** and **compatible with Architecture v2** boundaries:
   - No GUI logic in pipeline.
   - No pipeline behavior in GUI.
   - No randomizer logic in pipeline.

---

## 5. Non-goals

- No broad refactor of the pipeline or controller.
- No change to the GUI layout or GUI-widget behavior.
- No new randomizer features, wildcard logic, or matrix logic changes.
- No change to the manifest schema or file output locations.
- No attempt to redesign how jobs are queued from the GUI; this PR only adds tests, telemetry, and localized invariants to the **existing** pipeline execution path.

---

## 6. Allowed Files

Codex may modify **only** the following files (or their direct equivalents if paths differ slightly in the current repo). If a path does not exist, ask for guidance rather than guessing.

**Pipeline & Stages**

- `src/pipeline/executor.py`
- `src/pipeline/*upscale*.py` (e.g., `src/pipeline/upscale_stage.py` or similar, if present)
- `src/pipeline/stages/*.py` – **only** if the change is strictly:
  - Adding structured logging / telemetry, or
  - Adding a small invariant guard (e.g., single active upscale assertion).

**Controller (only for telemetry hooks, if absolutely necessary)**

- `src/controller/pipeline_controller.py` (or equivalent file that owns pipeline run lifecycle), and only for:
  - Initiating per-run telemetry contexts (e.g., run id, image count).
  - Wiring in structured logging fields.

**Tests**

- `tests/pipeline/test_upscale_*.py`
- `tests/pipeline/test_pipeline_executor*.py`
- `tests/controller/test_pipeline_controller*.py` (if needed for lifecycle tests)

**Docs**

- `docs/codex/prs/PR-PIPE-DIAG-001_upscale_hang_repro_and_telemetry.md` (this file)
- Optionally, a short note in `docs/Known_Bugs_And_Issues_Summary.md` under the relevant issue, marking “Covered by PR-PIPE-DIAG-001 tests”.

---

## 7. Forbidden Files

Do **not** touch the following in this PR:

- GUI layer:
  - `src/gui/main_window.py`
  - `src/gui/pipeline_controls_panel.py`
  - `src/gui/config_panel.py`
  - `src/gui/prompt_pack_panel.py`
  - Any other files under `src/gui/`

- Randomizer:
  - `src/utils/randomizer.py`
  - Any `randomization` / `matrix` helpers

- API client:
  - `src/api/client.py`

- Logger core / schemas:
  - `src/utils/structured_logger.py` (or equivalent)
  - `docs/schemas/` (any files)

- Any files under `tools/`, `scripts/`, or CI configuration.

If you believe a change is necessary in one of these files to fix a test or behavior, **stop and ask for a dedicated PR** instead of extending this one.

---

## 8. Step-by-step Implementation

> **Important:** Follow TDD. Write the failing tests first, then implement the minimal code to make them pass.

### 8.1 Tests – Reproduce the Upscale Hang Scenario

1. In `tests/pipeline/test_upscale_hang_diag.py` (new file) or the closest existing test module:
   - Add a test that simulates a multi-image pipeline run including an upscale stage, using mocks/stubs for the WebUI API.
   - Have one of the mocked upscale calls **intentionally block** (e.g., via a sleep or sentinel) unless a cancel signal is honored.
   - Assert that:
     - Only **one** upscale operation is active at a given time.
     - The pipeline attempts to proceed serially and that if a **CancelToken** is set, the pipeline exits without enqueuing or starting further upscales.

2. Add a second test that simulates a **long-running upscale** where:
   - The pipeline should still report progress for the correct image index.
   - Logs (or a mock logger) capture “enter upscale”, “exit upscale” events in order.

3. If feasible, add a small **timeout-based test** that ensures the pipeline does not hang indefinitely when the mock upscale call is configured to never return, but `CancelToken` is set.

### 8.2 Telemetry – Structured Logging in Pipeline Executor / Upscale Stage

4. In `src/pipeline/executor.py` (or equivalent):
   - Introduce structured log calls around each stage invocation that include, at minimum:
     - `stage_name`
     - `image_index` and `total_images`
     - `cancelled` flag (based on `CancelToken`)
   - These should be lightweight `logger.info` or `logger.debug` calls, guarded so they are safe in production.

5. In the upscale-related stage module (`src/pipeline/*upscale*.py`):
   - Add logs for:
     - “Entering upscale” with tile size, target resolution, and image index.
     - “Exiting upscale” with resulting resolution and duration (if trackable cheaply).
   - Ensure that **before starting an upscale**, the code:
     - Checks the `CancelToken` and aborts early if set.

### 8.3 Invariants – Single Active Upscale & CancelToken Enforcement

6. In the pipeline executor, introduce a small invariant mechanism, for example:
   - A counter or boolean indicating whether an upscale is currently active.
   - Assertions or defensive logging if a second upscale is requested while one is active for the same run.

7. Ensure that **between each image**, and before starting a new upscale, the executor:
   - Checks `CancelToken`.
   - If canceled, stops scheduling further images and exits gracefully.

8. Update the tests from step 8.1 to assert that:
   - These invariants hold.
   - The pipeline exits in a bounded time when cancel is set, even in the presence of a misbehaving upscale call (via mocks).

### 8.4 Clean-up & Doc Touch

9. Add or update doc comments in the modified pipeline modules to clarify:
   - Upscale is intended to be **serial** and **bounded**.
   - Cancel checks must be performed before each new upscale call.

10. Optionally add a one-line note under the relevant issue in `docs/Known_Bugs_And_Issues_Summary.md` marking it as “partially addressed by PR-PIPE-DIAG-001 (tests + telemetry + guardrails)”.

---

## 9. Required Tests (Failing First)

Before implementing any code changes, create and run these tests so they fail against the current baseline (post-PR-PIPE-CORE01):

1. `tests/pipeline/test_upscale_hang_diag.py::test_multi_image_run_upscale_is_serial_and_honors_cancel`
   - Fails because current pipeline either doesn’t enforce single active upscale or doesn’t honor cancel between images.

2. `tests/pipeline/test_upscale_hang_diag.py::test_upscale_stage_logs_stage_and_image_progress`
   - Fails because current pipeline lacks structured logging / telemetry for stage + image index.

3. (Optional but recommended) `tests/pipeline/test_upscale_hang_diag.py::test_cancel_stops_long_running_upscale_in_bounded_time`
   - Fails because current pipeline doesn’t check cancel in the right places.

After tests fail, implement the minimal code to make them pass.

Also re-run a targeted subset of existing tests:

- `pytest tests/pipeline -v`
- `pytest tests/controller -v`

and ensure they remain passing or adjust the new tests if they are incompatible with existing behavior expectations.

---

## 10. Acceptance Criteria

This PR is complete when:

1. All new tests in `tests/pipeline/test_upscale_hang_diag.py` pass consistently.
2. Existing pipeline and controller tests pass unchanged.
3. Logs for a multi-image run including upscale show, for each image:
   - Stage transitions (`txt2img` → `img2img` → `upscale`, etc.) with correct `image_index`.
   - A clear “enter” and “exit” message for the upscale stage.
4. In a test scenario where an upscale call is mocked to hang but `CancelToken` is set:
   - The pipeline exits within a bounded time (test-defined timeout).
   - No additional upscales are started after cancel.
5. Manual smoke tests (see below) indicate that:
   - The GUI no longer experiences indefinite hangs at the upscale stage.
   - If an upscale does misbehave, logs clearly show where and why.

---

## 11. Rollback Plan

If this PR introduces regressions or undesirable behavior:

1. Revert the commits that:
   - Add or modify tests in `tests/pipeline/test_upscale_hang_diag.py`.
   - Add telemetry or invariants in `src/pipeline/executor.py` and related upscale stage modules.
2. Remove any added notes from `docs/Known_Bugs_And_Issues_Summary.md` referencing PR-PIPE-DIAG-001.
3. Confirm the test suite passes again with the previous behavior.

Because this PR is mostly tests and lightweight logging/invariants, rollback should be straightforward and low-risk.

---

## 12. Codex Execution Constraints

**For Codex (Implementer):**

- Open this file in the repo at:
  - `docs/codex/prs/PR-PIPE-DIAG-001_upscale_hang_repro_and_telemetry.md`
- Follow the scope exactly.

Constraints:

1. **Do not modify** any file outside the **Allowed Files** section.
2. **Do not refactor** unrelated parts of the pipeline or controller.
3. **Do not change** GUI, randomizer, API client, or manifest schemas.
4. Implement **TDD-first**:
   - Create the tests in `tests/pipeline/test_upscale_hang_diag.py`.
   - Run `pytest tests/pipeline/test_upscale_hang_diag.py -v` and capture failing output.
   - Then implement minimal code to make them pass.
5. After implementation:
   - Run:
     - `pytest tests/pipeline -v`
     - `pytest tests/controller -v`
     - `pytest -v` (full suite, if time permits)
   - Paste the **full test output** into the conversation for review.
6. If you encounter ambiguity (e.g., different existing file names/paths), **ask for clarification** instead of guessing.

---

## 13. Smoke Test Checklist

After the code changes and tests pass, perform these manual checks on Rob’s machine (or equivalent environment):

1. **Basic upscale run**
   - Launch StableNew.
   - Configure a pipeline with:
     - `txt2img` → `upscale` (2×)
     - 3–5 images
   - Run the pipeline.
   - Confirm:
     - Upscale progress appears normal.
     - No indefinite hangs.
     - Logs show clear per-image stage transitions and upscale enter/exit messages.

2. **Cancel during upscale**
   - Start the same multi-image pipeline.
   - Wait until the upscale stage is active on an image.
   - Click Stop/Cancel in the GUI.
   - Confirm:
     - The run stops in a bounded time.
     - No extra upscales start after cancel.
     - Logs show cancel state being honored.

3. **Run → Complete → Run again**
   - Run the above pipeline to completion.
   - Start a second run with the same settings.
   - Confirm:
     - No leftover upscale jobs from the previous run.
     - Stage transitions and logs look clean for the second run.

4. **Stress test with slightly larger images**
   - Repeat a multi-image pipeline using slightly larger resolutions (e.g., 896×1152) with 2× upscale.
   - Confirm no hangs and validate that the tile-size safety logic from PR-PIPE-014 still behaves as expected.

If all of the above succeed, consider this PR’s diagnostic and guardrail objectives met.
