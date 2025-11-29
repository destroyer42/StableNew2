Timestamp: 2025-11-22 18:44 (UTC-06)
PR Id: PR-#39-GUI-V2-RunButtonQueueSmoke-001
Spec Path: docs/pr_templates/PR-#39-GUI-V2-RunButtonQueueSmoke-001.md

# PR-#39-GUI-V2-RunButtonQueueSmoke-001: GUI V2 Run Button Queue-Backed Smoke Test

## What’s new

- Adds a **GUI V2 smoke test** that verifies the “Run” button wiring end-to-end (at a high level) now that:
  - Pipeline execution is queue-backed (PR-#35 / PR-#36).
  - GUI learning entrypoints and config assembly are in place (PR-#34, PR-#38).
- Introduces a small, test-only **GUI harness** for StableNewGUI V2 that:
  - Constructs the main window in a headless-safe way.
  - Injects fake controller and queue/runner dependencies.
  - Simulates a user pressing the Run button.
- Confirms that pressing Run:
  - Builds or requests a `PipelineConfig` via controller.
  - Submits a job into the queue (via controller/queue integration).
  - Drives controller lifecycle transitions (IDLE → RUNNING → IDLE) as observed by the GUI.
- Adds tests that are explicitly non-flaky and do not require a real SD WebUI process, keeping with `ARCHITECTURE_v2_COMBINED.md` and `Testing_Strategy_v2`.

This PR is intentionally **test-focused**: it does not add new GUI features. It only adds the minimum shim/hooks needed to allow deterministic testing of the Run button → controller → queue path.

---

## Files touched

> Names may differ slightly in the repo; keep changes scoped to GUI V2 and tests.

### GUI V2 (minimal hooks only)

- `src/gui/main_window.py`
  - Adds limited, test-friendly hooks if not already present, for example:
    - Ability to inject a mock/fake `PipelineController` (via constructor parameter or setter).
    - A clearly named method (e.g., `_on_run_clicked()` or similar) that the test harness can call directly, mirroring the Run button callback.
  - Must **not**:
    - Change layout behavior.
    - Introduce any direct imports of queue, pipeline, or API modules (GUI continues to depend only on controllers, per `ARCHITECTURE_v2_COMBINED.md`).

- `src/gui/app_layout_v2.py` (only if needed)
  - Ensures the Run button in V2 layout is wired to the same callback entrypoint used in tests.
  - No changes to layout structure; only callback hookup clarity if necessary.

If the existing GUI V2 already exposes suitable hooks for testing, minimize or skip changes to these files.

### Test harness / support

- `tests/gui_v2/conftest.py` (new or extended)
  - Provides fixtures such as:
    - `fake_pipeline_controller`:
      - Exposes `run_pipeline(...)` or equivalent.
      - Records:
        - Whether it was called.
        - What arguments it received (e.g., config or job submission metadata).
      - Simulates job lifecycle callbacks (e.g., “pretend this job finished successfully”).
    - `stable_new_gui_v2_app`:
      - Constructs a StableNewGUI V2 instance using a mocked root (or real Tk root under a test-safe pattern used elsewhere).
      - Injects `fake_pipeline_controller`.

- `tests/gui_v2/test_run_button_queue_smoke.py` **(new)**
  - Core smoke test scenarios:
    1. **Happy path**
       - Given a StableNewGUI V2 instance with fake controller:
         - Simulate the user hitting Run.
         - Assert:
           - The controller’s “run” method is called exactly once.
           - The controller records a job submission (or equivalent).
           - GUI updates status to “Running” then “Idle/Completed” when fake controller triggers completion callback.
    2. **Disabled run conditions (optional)**
       - If the GUI supports disabled Run (e.g., while already running):
         - Verify that pressing Run while in a non-idle state does not double-submit jobs.
    3. **Error surface (optional, shallow)**
       - Simulate a controller-level failure and assert the GUI shows an error status or message.

  - These tests must not:
    - Depend on real SD WebUI.
    - Interact with actual queue/runner implementations; those are already tested in queue/controller tests.
    - Create real windows that persist beyond the test run; rely on the existing GUI test pattern for headless operation.

### Docs

- `docs/Testing_Strategy_v2.md`
  - Add a note in the GUI testing section describing:
    - The purpose of the Run-button queue-backed smoke test.
    - Its role as a regression guard for the GUI ↔ controller ↔ queue integration.
  - Clarify that:
    - Detailed pipeline behavior (API calls, learning writes) remains covered by pipeline + controller + learning tests.
    - GUI smoke tests focus on wiring and lifecycle.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Update with bullets listed in the “Rolling summary update” section.

---

## Behavioral changes

- From a user’s perspective:
  - There is **no new GUI feature** or change in behavior in this PR.
  - The Run button and status bar should behave exactly as before.

- From a testing/architecture perspective:
  - We now have an explicit, codified check that:
    - The Run button in GUI V2 is wired to the controller correctly.
    - The controller responds by initiating a queue-backed run.
    - GUI lifecycle/status updates follow controller events (IDLE ↔ RUNNING ↔ IDLE/ERROR).

- This acts as a **regression safety net** whenever:
  - Controller run semantics change (e.g., new queue behavior).
  - GUI wiring is refactored.
  - New features (like learning runs or randomizer variants) are introduced that could inadvertently break basic Run semantics.

---

## Risks / invariants

- **Invariants**
  - No GUI → pipeline or GUI → API imports; GUI must only depend on controllers and utils (`ARCHITECTURE_v2_COMBINED.md`).
  - Smoke tests must be:
    - Deterministic.
    - Non-flaky.
    - Independent of actual WebUI processes or network calls.
  - The Run button callback must:
    - Continue to use the same public controller methods.
    - Not bypass the queue- and controller-based lifecycle.

- **Risks**
  - If the test harness uses real Tk root windows incorrectly, tests could become flaky or hang on some CI environments.
  - Overly invasive changes to `main_window.py` could inadvertently affect runtime behavior.

- **Mitigations**
  - Reuse the patterns from existing `tests/gui_v2` tests for headless-safe GUI initialization.
  - Keep any modifications to `main_window.py` / `app_layout_v2.py` minimal and focused on dependency injection or accessor hooks.
  - Avoid assumptions about actual screen size or user interaction; the tests should operate purely on callbacks and state inspection.

---

## Tests

Run at minimum:

- GUI smoke test:
  - `pytest tests/gui_v2/test_run_button_queue_smoke.py -v`

- GUI regression:
  - `pytest tests/gui_v2 -v`

- Controller/queue regression (since this PR leans on their contracts):
  - `pytest tests/controller -v`
  - `pytest tests/queue -v`

- Full suite:
  - `pytest -v`

Expected results:

- The new smoke tests confirm:
  - Run button → controller call.
  - Controller call → simulated job submission.
  - Lifecycle callbacks → GUI status updates.
- Existing GUI V2, controller, queue, pipeline, and learning tests remain green.

---

## Migration / future work

This PR gives you a **baseline wiring guarantee** for GUI V2’s Run flow. Future work can expand this safety net:

- Additional GUI smoke tests:
  - Stop/Cancel button behavior:
    - Simulate cancel calls and ensure the GUI reacts correctly to controller lifecycle transitions.
  - Learning-enabled runs:
    - Confirm that toggling learning still leads to successful Run semantics (even if learning is a no-op in tests).
  - Randomizer-aware runs:
    - Ensure the GUI integration doesn’t disrupt queue job submission when randomizer is active.

- Potential new GUI panels:
  - A “Jobs / Queue” view that shows:
    - Active, queued, and completed jobs.
    - Basic job details (prompt, model, status).
  - These should build on the same controller/queue contracts verified by this smoke test.

By locking in this smoke test now, any future refactor to GUI, controller, or queue behavior will be less likely to accidentally break the core “click Run to start a job” path.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the current date heading (e.g., `## 2025-11-22`):

- Added a **GUI V2 Run-button smoke test** that verifies the end-to-end wiring from Run → controller → queue-backed execution without requiring a real SD WebUI backend.
- Introduced a small StableNewGUI V2 test harness with injectable controllers, making it easier to validate GUI lifecycle and status updates in isolation.
- Strengthened regression protection for future controller/queue/GUI refactors by codifying the expected Run-button behavior in tests.
