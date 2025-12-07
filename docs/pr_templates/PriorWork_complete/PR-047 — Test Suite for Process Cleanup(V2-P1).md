PR-047 — Test Suite for Process Cleanup + Shutdown Journey (V2-P1)

PR-ID: PR-047
Risk Tier: Medium (tests + light wiring, no new core behavior)
Goal: Add automated tests that validate the new shutdown behavior from PR-046, including WebUI process cleanup and a GUI-level “start–close–repeat” journey to catch regressions and zombie processes.

1. Baseline & Dependencies

Depends on PR-046 being implemented (or at least the contracts existing):

AppController.shutdown_app(...)

webui_process_manager.stop_webui(...)

Same snapshot and architecture constraints as PR-046.

2. Scope

In-scope:

Unit tests for WebUI stop behavior

Validate that stop_webui(...):

Returns True when no process is tracked.

Attempts graceful shutdown when a fake process is attached.

Calls “kill” when the process stays alive after the grace period.

Is idempotent (multiple calls safe).

Controller-level shutdown tests

Validate that AppController.shutdown_app(...):

Invokes WebUI shutdown exactly once.

Calls job cancellation / queue pause methods if a job is active.

Protects against multiple calls (second call is a no-op).

GUI-/journey-level shutdown tests

A “mini journey” that:

Constructs an AppController with mocked WebUI process manager and job service.

Simulates GUI open and close via the same handler used by WM_DELETE_WINDOW.

Repeats startup/shutdown multiple times in a single test run to ensure no compounding resources.

Out-of-scope:

Spawning real WebUI processes in CI (use mocks/fakes instead).

OS-level process enumeration (we won’t depend on psutil or similar here).

Any changes to executor internals.

3. Allowed Files

New / updated test files:

tests/api/test_webui_process_manager_shutdown_v2.py (NEW)

tests/controller/test_app_controller_shutdown_v2.py (NEW)

tests/gui_v2/test_shutdown_journey_v2.py (NEW or extended if a similar file exists)

Optional test wiring:

Update:

tests/phase1_test_suite.txt (if present) to include the new tests.

Implementation helpers (light only):

If needed for test harness only (no production imports from these), you may add tiny helper functions in:

src/app_factory.py only if required to construct a minimal AppController for tests without spinning a full GUI.

Any test-only fixtures/modules under tests/ (e.g., tests/conftest.py).

4. Forbidden Files

Do not modify:

src/main.py

src/pipeline/executor.py

src/api/webui_process_manager.py behavior semantics (those were modified in PR-046; here we only test them)

Any GUI layout or theme files (main_window_v2.py, layout_v2.py, theme_v2.py, etc.)

Any non-GUI/non-lifecycle modules unrelated to shutdown.

If you need an additional hook in production code to make testing easier, that belongs in a separate PR (e.g., PR-048 — test harness hooks).

5. Implementation Outline
5.1 WebUI stop tests

File: tests/api/test_webui_process_manager_shutdown_v2.py

Use unittest.mock or pytest fixtures to simulate a WebUI process object with:

poll() returning None (running) or exit codes.

wait(timeout=...) behavior to simulate graceful vs stubborn shutdown.

kill() call to simulate forced termination.

Test cases:

No process tracked

Ensure calling stop_webui() returns True and does not raise.

Graceful shutdown path

Configure fake process so that wait() returns before timeout.

Assert that kill() is not called.

Assert state is cleared (subsequent stop_webui() returns True with no extra calls).

Forced kill path

Configure fake process so that wait() always times out.

Assert that kill() is called once.

Assert state is cleared and function returns True.

Idempotency

Call stop_webui() twice in a row on the same setup and ensure:

First call performs work.

Second call effectively no-ops.

5.2 AppController shutdown tests

File: tests/controller/test_app_controller_shutdown_v2.py

Build an AppController instance with injected test doubles / mocks:

Mock job service / queue runner with methods like cancel_all() or whichever APIs PR-046 uses.

Mock WebUI shutdown entry point (e.g., patch webui_process_manager.stop_webui or webui_connection_controller.shutdown).

Optional: mock learning hooks if they are explicitly called.

Test cases:

Calls components in the right order

Given:

An in-progress job.

Mock job service with cancel_all (or equivalent).

When:

controller.shutdown_app("test") is called.

Then:

Job cancellation is called once.

Learning hooks (if any) are called once.

WebUI shutdown is called once.

Idempotency

Call shutdown_app("first") then shutdown_app("second").

Verify:

Each subordinate helper (cancel_all, stop_webui, etc.) is called only once in total.

Exception safety

Make one of the helpers raise (e.g., job cancellation).

Verify:

shutdown_app catches and logs but continues to attempt WebUI shutdown.

The method returns without raising.

5.3 GUI-level shutdown / journey test

File: tests/gui_v2/test_shutdown_journey_v2.py

Mark tests with appropriate GUI markers (e.g. @pytest.mark.gui).

Use a minimal Tk harness pattern already present in GUI V2 tests so we don’t create new patterns.

Sketch:

Build a minimal Tk root and AppController (or a thin wrapper returned from factory).

Bind WM_DELETE_WINDOW to the real close handler used in production (on_app_close from PR-046).

Monkeypatch:

AppController.shutdown_app to an instrumented mock that:

Tracks how many times it’s called.

Simulate:

Triggering the close handler (e.g., call it directly or via root.event_generate if the test harness supports it).

Assert:

shutdown_app is called exactly once.

root.destroy() (or equivalent) is invoked (depending on how the harness exposes that; you may assert that the test doesn’t hang and the window is closed).

Extended journey:

Optionally, create a parametrized test that:

Creates and closes the “app” 3–5 times in a loop using the same pattern.

Ensures that:

No exceptions are raised.

No double-shutdown attempts occur.

This won’t literally detect OS-level zombie processes but will surface Python-level reference leaks and double-callback issues.

5.4 Add tests to Phase 1 suite (if applicable)

If tests/phase1_test_suite.txt or equivalent exists:

Append the new tests:

tests/api/test_webui_process_manager_shutdown_v2.py
tests/controller/test_app_controller_shutdown_v2.py
tests/gui_v2/test_shutdown_journey_v2.py

6. Definition of Done

PR-047 is complete when:

All three new test files exist and pass.

Tests cover:

WebUI process stop behavior (graceful + forced + idempotent).

AppController shutdown orchestration and idempotency.

A GUI-level close journey that exercises the real shutdown handler.

New tests are integrated into the standard GUI/Phase 1 test selection (if such a suite file is used).

Running the test suite:

Does not leave orphaned test processes behind (no hanging tests).

Does not flake due to timing issues; any waits are bounded and use mocks where possible.

7. Tests to Run (for PR-047)

At minimum:

pytest tests/api/test_webui_process_manager_shutdown_v2.py -q
pytest tests/controller/test_app_controller_shutdown_v2.py -q
pytest tests/gui_v2/test_shutdown_journey_v2.py -q


And then the broader GUI Phase 1 subset as usual (if defined):

pytest $(cat tests/phase1_test_suite.txt) -q
