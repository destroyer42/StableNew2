
# Codex Run Sheet – Sequential PR Automation  
PR-PIPE-DIAG-001 & PR-CTRL-LC-001

This run sheet is what you (Rob) follow when driving Codex to implement the two PRs **safely and sequentially**.

---

## 0. Pre-flight

1. Ensure repo matches ZIP baseline:  
   `StableNew-MoreSafe-11-20-2025-07-27-00-AftrerPR-PIPE-CORE01.zip`
2. Confirm the following PR specs exist in the repo:
   - `docs/codex/prs/PR-PIPE-DIAG-001_upscale_hang_repro_and_telemetry.md`
   - `docs/codex/prs/PR-CTRL-LC-001_gui_lifecycle_run_stop_run_hardening.md`
3. From the repo root, you’ll run all commands as:
   ```bash
   pytest ...
   ```

---

## 1. High-level Execution Order

1. Run **PR-PIPE-DIAG-001** (pipeline upscale diagnostics & telemetry).  
2. Verify tests + manual quick sanity.  
3. Run **PR-CTRL-LC-001** (GUI/controller lifecycle hardening).  
4. Verify tests + manual quick sanity.  
5. Optionally perform combined smoke tests (Section 4).

You always finish one PR completely before starting the next.

---

## 2. Driving Codex for PR-PIPE-DIAG-001

### 2.1 Initial Message to Codex

Paste this to start PR-PIPE-DIAG-001:

> You are the Implementer.  
> Load and follow this PR specification:  
> `docs/codex/prs/PR-PIPE-DIAG-001_upscale_hang_repro_and_telemetry.md`  
> Your mission: Implement PR-PIPE-DIAG-001 exactly as written, using strict TDD.  
> - Only modify files listed under “Allowed Files”.  
> - Start by creating tests in `tests/pipeline/test_upscale_hang_diag.py`.  
> - Run ONLY those tests and paste the failing output.  
> - Then implement minimal code to make them pass.  
> - After implementation, run:  
>   - `pytest tests/pipeline -v`  
>   - `pytest -v`  
>   and paste ALL output.

### 2.2 Expected Codex Actions

Codex should:

1. Create/modify: `tests/pipeline/test_upscale_hang_diag.py`
   - Tests for:
     - Serial upscale behavior.
     - CancelToken honoring between images.
     - Logging/telemetry for stage + image index.
     - Mocked “hanging” upscale that must be interrupted by cancel.
2. Run:  
   ```bash
   pytest tests/pipeline/test_upscale_hang_diag.py -v
   ```  
   and show **failing** output.
3. Modify only allowed pipeline files (e.g. `src/pipeline/executor.py` and the upscale stage file) to satisfy tests.
4. Run:  
   ```bash
   pytest tests/pipeline -v
   pytest -v
   ```  
   and show **passing** output.

### 2.3 Your Checklist After Codex Finishes PR-PIPE-DIAG-001

- [ ] Confirm tests file exists and matches intent (no scope creep).  
- [ ] Confirm only allowed files were changed.  
- [ ] Confirm full `pytest -v` is green.  
- [ ] Optionally run a quick upscale pipeline manually:
  - 3–5 images, 2× upscale, typical resolution.
  - Ensure no obvious hangs and logs show stage/image telemetry.

If all good → proceed to PR-CTRL-LC-001.

---

## 3. Driving Codex for PR-CTRL-LC-001

### 3.1 Initial Message to Codex

Paste this to start PR-CTRL-LC-001:

> You are the Implementer.  
> Load and follow this PR specification:  
> `docs/codex/prs/PR-CTRL-LC-001_gui_lifecycle_run_stop_run_hardening.md`  
> Your mission: Implement PR-CTRL-LC-001 exactly as written, using strict TDD.  
> - Only modify files listed under “Allowed Files”.  
> - Start by creating lifecycle tests in:  
>   - `tests/controller/test_pipeline_controller_lifecycle.py`  
>   - `tests/gui/test_pipeline_controls_lifecycle.py`  
> - Run ONLY those tests and paste the failing output.  
> - Then implement minimal code to make them pass.  
> - After implementation, run:  
>   - `pytest tests/controller -v`  
>   - `pytest tests/gui -v`  
>   - `pytest -v`  
>   and paste ALL output.

### 3.2 Expected Codex Actions

Codex should:

1. Create/modify the two test files:
   - `tests/controller/test_pipeline_controller_lifecycle.py`
   - `tests/gui/test_pipeline_controls_lifecycle.py`
2. Add tests for:
   - `IDLE → RUNNING → IDLE` (normal completion).  
   - `IDLE → RUNNING → STOPPING → IDLE` (cancel).  
   - `IDLE → RUNNING → ERROR`.  
   - Rejecting a second run while RUNNING/STOPPING.  
   - GUI button/state behavior in each lifecycle state.
3. Run only those tests, get failures.
4. Implement minimal code changes **only in**:
   - `src/controller/pipeline_controller.py` (+ any controller state module).
   - `src/gui/main_window.py`
   - `src/gui/pipeline_controls_panel.py`
5. Run:  
   ```bash
   pytest tests/controller -v
   pytest tests/gui -v
   pytest -v
   ```  
   and provide full output.

### 3.3 Your Checklist After Codex Finishes PR-CTRL-LC-001

- [ ] Confirm tests exist and clearly test lifecycle (no random unrelated scenarios).  
- [ ] Confirm only controller/GUI lifecycle-related files changed.  
- [ ] Confirm `pytest -v` is green.  
- [ ] Spot check the lifecycle logic:
  - Controller states: `IDLE`, `RUNNING`, `STOPPING`, `ERROR` look sane.
  - GUI run/stop buttons wired to controller and update correctly (per tests).

---

## 4. Combined Post-PR Smoke Tests (Manual)

After both PRs are applied and tests are green, run these manual checks in the actual app.

### 4.1 Multi-image upscale with cancel

1. Configure a pipeline with txt2img + upscale (2×, 3–5 images).  
2. Start run:
   - Confirm Run button disables, Stop enables.
3. While an upscale is in progress:
   - Click Stop.
   - Confirm:
     - Run eventually re-enables.
     - Stop disables.
     - Logs show cancel being honored and no further upscales start.

### 4.2 Run → Complete → Run again

1. Run the same pipeline to completion.  
2. Immediately run it again, unchanged.  
3. Confirm:
   - No errors or crashes.
   - GUI remains responsive.
   - Logs show clear per-image and per-stage telemetry.

### 4.3 Error handling sanity

1. Intentionally break config (e.g. bad WebUI URL).  
2. Run pipeline:
   - Confirm controller goes to ERROR.
   - GUI reflects ERROR but recovers to allow new runs after you fix the config.

---

## 5. Notes for Future PRs

- Keep using this pattern: **Targeted PR spec → TDD tests → minimal changes → full test suite → manual smoke tests.**
- Always keep GUI, controller, pipeline, randomizer, and API layers in their lanes.
- If Codex ever touches non-allowed files, treat that as a regression in its behavior and correct immediately.

