PR-WIRE-02-V2.5 – Theme & Entrypoint Contracts (11-26-2025-1916).md

Scope:

Fix Theme.apply_root (and any other minimal methods it obviously needs).

Make the “stablenewgui” entrypoint and src.main clearly target V2 GUI.

Provide a minimal implementation of wait_for_webui_ready in src.main so the bootstrap tests stop failing.

Do not tackle journey/pipeline/learning contract mismatches yet – that’ll be WIRE-03.

Below is a copy-paste Codex / Copilot MAX prompt to drive this PR.

You are acting as an implementation agent for the StableNew project.

## Context

Repository root: `StableNew-cleanHouse/`

StableNew is a Python Tk/Ttk GUI app for orchestrating Stable Diffusion. We’ve already done a minimal wiring pass (PR-WIRE-01-V2.5) so that GUI → controller → pipeline → WebUI process manager is at least partially functional.

Now we’re using pytest failures as our wiring guide.

Recent pytest run shows these key failures:

- Theme / GUI V2 structural issues:
  - Many tests fail with:
    - `AttributeError: 'Theme' object has no attribute 'apply_root'`
  - Affected tests include:
    - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_loads_initial_config`
    - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py::test_pipeline_panel_run_roundtrip`
    - `tests/gui_v2/test_gui_v2_pipeline_txt2img_validation.py::test_run_button_disabled_when_invalid`
    - `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py::*`
    - `tests/gui_v2/test_gui_v2_stage_cards_layout.py::*`
    - `tests/gui_v2/test_gui_v2_startup.py::test_gui_v2_startup`
    - `tests/gui_v2/test_entrypoint_uses_v2_gui.py::*`
    - and others that import theme/V2 layout.

- Entry / bootstrap issues:
  - `tests/app/test_bootstrap_webui_autostart.py::*` fails with:
    - `AttributeError: <module 'src.main' ...> has no attribute 'wait_for_webui_ready'`
  - `tests/gui_v2/test_entrypoint_uses_v2_gui.py::test_entrypoint_targets_v2_gui` fails with:
    - `AssertionError: assert None is <class 'src.gui.main_window.StableNewGUI'>`

- Other failures (journeys, learning, some pipeline tests) are out of scope for this PR and should remain failing for now.

Your task is to implement **PR-WIRE-02-V2.5 – Theme & Entrypoint Contracts**, which focuses ONLY on:

1. Making the V2 theme object implement the basic contract expected by GUI V2 tests.
2. Ensuring the main entrypoint clearly targets the V2 GUI.
3. Providing a minimal `wait_for_webui_ready` function in `src.main` that satisfies bootstrap tests.

Do NOT:
- Move or archive files.
- Change learning/pipeline/journey test contracts in this PR.
- Implement complex new features; stick to the minimum needed to satisfy the failing tests listed above.
- Modify the file access logger or summarizer tools.

---

## Files you MUST inspect before making changes

1. `src/gui/theme_v2.py` (or other theme-related module)
2. `src/gui/theme.py` (to see if legacy or V1 behavior informs V2)
3. `src/gui/main_window_v2.py`
4. `src/gui/layout_v2.py` and any V2 status bar / pipeline panel modules referenced in failing tests.
5. `src/main.py`
6. `tests/app/test_bootstrap_webui_autostart.py`
7. `tests/gui_v2/test_entrypoint_uses_v2_gui.py`
8. One or two representative GUI V2 tests that reference `Theme.apply_root`:
   - `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py`
   - `tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py`

Use those tests as the **source of truth** for the contracts.

---

## Step 1 – Implement a minimal Theme.apply_root contract

1. Open `src/gui/theme_v2.py` (and `src/gui/theme.py` if you need context).
2. From the failing tests, infer what the Theme object is supposed to do:
   - `apply_root` method is missing.
   - Tests likely construct a theme and call `apply_root(root)` on a Tk root window or Toplevel.
   - Some tests may also expect additional methods or attributes (e.g., `apply_to_status_bar`, color palettes, etc.).

3. Implement, at minimum:

   ```python
   class Theme:
       ...
       def apply_root(self, root) -> None:
           """
           Apply global styles to the given Tk root widget.

           This should be safe to call multiple times, and must not raise.
           It can configure ttk styles, colors, fonts, etc.
           For now, implement a minimal, non-crashing version that is
           sufficient for tests to construct the GUI.
           """
           ...


It may:

Configure ttk style / theme name.

Set some default fonts/colors.

Ensure any styles used in status bar / panels exist.

The implementation does not need to be perfect; it just needs to satisfy the tests and not break the current GUI.

If tests clearly expect more theme methods (e.g. create_status_bar_styles, apply_to_status_bar), implement minimal stubs that:

Set up required ttk style names.

Don’t crash when called.

Ensure that wherever the V2 GUI is constructed, a Theme instance from theme_v2 is used consistently:

In main_window_v2, check how theme is instantiated and applied; update if needed so apply_root is actually used.

Step 2 – Make the entrypoint clearly target V2 GUI

Inspect tests/gui_v2/test_entrypoint_uses_v2_gui.py to see exactly what it expects:

It likely references:

A “stablenewgui” entrypoint module or function.

A StableNewGUI class under src.gui.main_window or similar.

The test failure you reported:

AssertionError: assert None is <class 'src.gui.main_window.StableNewGUI'>
indicates that whatever function is supposed to return the GUI class currently returns None.

Search the repo for the entrypoint:

Look for:

stablenewgui

StableNewGUI

console_scripts entrypoints (in pyproject / setup, if present)

Also examine src/gui/main_window_v2.py and any StableNewGUI class definitions.

Make sure the V2 GUI is what the entrypoint exposes:

If there is a helper function or mapping like:

def get_main_window_class():
    return StableNewGUI


ensure that it returns the V2 StableNewGUI class (from main_window_v2), not a V1 or None.

If tests expect a symbol in src.gui.main_window but the actual class lives in main_window_v2, consider:

Re-exporting the V2 class from src/gui/main_window.py, e.g.:

# in src/gui/main_window.py
from .main_window_v2 import StableNewGUI  # type: ignore[F401]


so existing tests and callers see the V2 implementation through the legacy module path.

Update src/main.py and/or src/app_factory.py if needed so that when the app starts, it also uses this same V2 entrypoint class consistently.

Step 3 – Implement wait_for_webui_ready in src.main

Open tests/app/test_bootstrap_webui_autostart.py and see exactly what they expect from:

src.main.wait_for_webui_ready

Any other bootstrap-related functions (e.g. autostart behavior, healthcheck logic).

Implement in src/main.py a function:

def wait_for_webui_ready(
    process_manager: "WebUIProcessManager",
    healthcheck: "WebUIHealthcheck",
    timeout_seconds: float = 60.0,
    poll_interval: float = 2.0,
) -> bool:
    """
    Block until WebUI is ready or timeout elapses.

    Returns True if WebUI became healthy, False if timeout or failure.
    This is primarily used in bootstrap tests and should be
    factored for easy mocking.
    """
    ...


Use whatever WebUI process manager / healthcheck abstractions exist in:

src/api/webui_process_manager.py

src/api/healthcheck.py (or similar).

Tests will tell you exactly how they call it, including argument order and expected behavior.

Implementation guidance:

Likely behavior:

Start or ensure the WebUI process is running (if not already).

Loop:

Call the healthcheck client (healthcheck.is_healthy() or similar).

If healthy → return True.

Sleep poll_interval.

Stop after timeout_seconds.

On timeout, return False.

Must not raise unhandled exceptions in usual cases; tests may simulate failures.

Ensure wait_for_webui_ready is importable as src.main.wait_for_webui_ready.

Step 4 – Run targeted tests and adjust

After changes:

Run only the relevant tests first:

pytest tests/app/test_bootstrap_webui_autostart.py -q
pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
pytest tests/gui_v2/test_gui_v2_status_bar_progress_eta.py -q
pytest tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py -q


Fix any remaining AttributeError / import issues from these tests by adjusting the minimal contracts.

Do NOT try to fix learning/journey/pipeline contract failures in this PR.

Then run the full suite to verify you haven’t regressed elsewhere:

pytest -q


It is acceptable that journey tests and some pipeline/learning tests still fail; those will be addressed in later wiring PRs. This PR’s acceptance is about improving the GUI V2 + bootstrap side.

Acceptance criteria

Theme class (likely in src/gui/theme_v2.py) implements apply_root and any other basic methods needed so that:

All tests that previously failed with Theme lacking apply_root now at least import and construct the GUI.

No new theme-related AttributeErrors appear in GUI V2 tests.

tests/gui_v2/test_entrypoint_uses_v2_gui.py passes:

The tested entrypoint returns the V2 StableNewGUI class.

src.gui.main_window (if used as an alias) exposes the V2 GUI class.

tests/app/test_bootstrap_webui_autostart.py passes:

src.main.wait_for_webui_ready exists with the expected signature.

It interacts correctly with WebUI process manager / healthcheck according to tests.

No changes to:

Archiving/legacy behavior.

Learning or journey test fixtures.

File access logger or summarizer.

Final response format

When you are finished, reply with:

A concise summary of what you changed (theme, entrypoint, bootstrap).

The list of files you created or modified.

The public methods / functions you added (signatures and their purpose).

The result of running:

pytest tests/app/test_bootstrap_webui_autostart.py tests/gui_v2/test_entrypoint_uses_v2_gui.py -q

and then pytest -q (high-level pass/fail summary).

Any follow-up wiring opportunities you noticed (e.g., next obvious GUI V2 panels/pipeline hooks to address in PR-WIRE-03).