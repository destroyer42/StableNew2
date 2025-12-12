# PR-GUI-032_gui_test_noninteractive — Make GUI tests non-interactive and resilient

## 1. Title
PR-GUI-032_gui_test_noninteractive — Make GUI tests non-interactive and resilient

## 2. Summary
The GUI test suite currently hangs or times out because certain windows and dialogs require manual user interaction:

- “There are changes that have been made that won’t apply to any packs, are you sure you want to continue?” confirmation dialog.
- Additional minimal/un-styled main windows being spawned that must be manually closed.
- A “New features have been added” window listing features that requires clicking “OK” to dismiss.

In test environments, these interactions block pytest until a human clicks through, causing harness timeouts.

This PR introduces a **non-interactive test mode** for the GUI so that:

- All confirmation dialogs and “new features” popups are automatically bypassed or suppressed under test.
- Extra main windows are not spawned (or are auto-closed) when running tests.
- Production behavior remains unchanged.

## 3. Problem Statement
Symptoms observed during `pytest tests/gui -v`:

- Tests hang on modal dialogs that ask for confirmation about unsaved or unapplied changes.
- Additional bare-bones Tk windows appear during tests and must be closed manually.
- A “new features” announcement window appears repeatedly, requiring an “OK” click.

These behaviors:

- Are appropriate for interactive users.
- Are **not** appropriate for automated test runs.
- Cause GUI test suite runs to exceed harness timeouts.

We need a way to disable or auto-resolve these dialogs and windows in test mode without affecting normal users.

## 4. Goals
1. Introduce a reliable, opt-in **GUI test mode** that can be enabled by tests (e.g., via environment variable or explicit flag).
2. When GUI test mode is active:
   - All confirmation dialogs auto-resolve with a deterministic response.
   - “New features” or first-run popups are suppressed or auto-dismissed.
   - Extra main windows are not spawned, or are auto-closed before they can block tests.
3. Ensure all GUI tests can run to completion without manual interaction and within harness time limits.
4. Keep production behavior unchanged when test mode is not active.

## 5. Non-goals
- No changes to pipeline, controller, or CancelToken logic.
- No changes to sampler/scheduler behavior.
- No functional change for end users running the GUI normally.
- No major refactors of the GUI architecture beyond what is required to inject “test mode” behavior.

## 6. Allowed Files
(Confirm exact names against REPO_SNAPSHOT.md)

- Main window / GUI bootstrap:
  - `src/gui/main_window.py` (or equivalent) where:
    - MainWindow / StableNewGUI is created.
    - “new features” dialogs are triggered.
    - the “Apply Editor → Pack(s)” and unsaved-changes prompts are implemented.
- Any small helper or config module under `src/gui/` that stores global GUI state / flags.
- Tests:
  - GUI test modules, such as:
    - `tests/gui/test_prompt_pack_editor.py`
    - Other `tests/gui/test_*.py` as needed for fixtures or new tests.

## 7. Forbidden Files
- `src/controller/...`
- `src/pipeline/...`
- Randomizer/matrix modules under `src/utils/`
- Structured logger or manifest modules
- Build/configuration files (pyproject, requirements, etc.)

If you believe changes are required outside allowed files, stop and request a new PR design.

## 8. Step-by-step Implementation

### 8.1 Define a GUI test mode switch
1. Add a small, central helper for determining whether we are in GUI test mode. For example, in a small GUI utility module or near the top of `src/gui/main_window.py`:

   Implement a function like `is_gui_test_mode()` that returns `True` when:
   - An environment variable is set (e.g., `STABLENEW_GUI_TEST_MODE=1`), or
   - A static flag on the GUI module/class is set by the tests.

   Pseudocode:

   - Read-only:

     - `is_gui_test_mode()` checks env + a module-level flag.

   - Write:

     - `enable_gui_test_mode()` sets the module-level flag to True.

2. This function must be cheap and side-effect free (beyond reading env / a module-level flag).

### 8.2 Make blocking dialogs non-interactive in test mode
3. Identify all code paths that show modal dialogs requiring user clicks. Based on observed behavior, these include at least:
   - The “There are changes that have been made that won’t apply to any packs, are you sure you want to continue?” confirmation dialog.
   - The “new features have been added” / “changelog” popup with an “OK” button.

4. Wrap these dialog calls in a conditional based on `is_gui_test_mode()`:

   - For confirmation dialogs (e.g., `messagebox.askyesno`):
     - In test mode, **do not** show the dialog. Instead, return a deterministic answer (likely “Yes”/`True` to let tests proceed).

   - For informational popups / “new features” dialogs:
     - In test mode, either skip them entirely (no window at all), or auto-close them without user input.

### 8.3 Prevent extra main windows during tests
5. Locate where the extra minimal/un-styled main windows are being created. Likely culprits:

   - `if __name__ == "__main__":` blocks that construct an additional root/window.
   - Side-effectful imports that instantiate Tk roots on module import.

6. Guard such creation with `is_gui_test_mode()`:

   - In any `__main__` block or auto-launch path, only build `Tk()` + `MainWindow` when **not** in GUI test mode.

7. If there are helper functions that create Toplevels/windows for “first run” or “tips” screens, ensure they are skipped in test mode as in 8.2.

### 8.4 Test harness: enable GUI test mode
8. In the GUI test fixtures (e.g., the `minimal_gui_app` fixture in `tests/gui/conftest.py` or similar), ensure GUI test mode is enabled before any windows are created. For example:

   - Set the environment variable for tests:

     - `STABLENEW_GUI_TEST_MODE=1`

   - Or call a programmatic hook:

     - `main_window.enable_gui_test_mode()`

9. Ensure that this is done once per test module or in a shared `conftest.py` so that **all** GUI tests run under non-interactive mode by default.

### 8.5 Add tests specifically for dialog behavior in test mode
10. Add or extend GUI tests to assert that in test mode:

    - The unsaved/unapplied-changes confirmation path auto-returns `True` and does not block.
    - The “new features” popup does not appear (or is a no-op).

    Instead of asserting window counts (which is brittle), prefer:

    - Using `monkeypatch` to assert that `messagebox.askyesno` is not called when `is_gui_test_mode()` is `True`.
    - Or using a small internal flag / log to verify that the “new features” dialog path is skipped in test mode.

## 9. Required Tests
After implementing this PR:

- Run focused GUI tests first:

  - `pytest tests/gui/test_prompt_pack_editor.py -v`
  - Any newly added tests that assert non-interactive behavior.

- Then run the full GUI suite:

  - `pytest tests/gui -v`

- Finally, run the entire test suite:

  - `pytest`

GUI tests should now complete without manual interaction and within harness time limits.

## 10. Acceptance Criteria
- GUI tests no longer hang on modal dialogs or “new features” popups.
- Extra main windows are not spawned in test mode (or do not block).
- All tests under `tests/gui` pass in a single non-interactive run.
- Production behavior (outside of test mode) is unchanged: dialogs, warnings, and feature popups still appear normally for users.

## 11. Rollback Plan
- Revert changes to:
  - `src/gui/main_window.py` (or other GUI files touched).
  - Any GUI utility / flag helpers added for test mode.
  - Any tests added or modified for this PR.
- Re-run `pytest` to confirm behavior returns to the prior state.
