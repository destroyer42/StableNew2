PR-GUI-V2-PIPELINE-RUNTAB-001B_remove_run_tab_and_legacy_buttons_2025-11-26
1. Title

PR-GUI-V2-PIPELINE-RUNTAB-001B: Remove Run Tab, Legacy Prompt Builder Button, and Duplicate Run/Stop

2. Summary

Once 001A has moved stage cards into the Pipeline tab, this PR decommissions the Run tab:

Remove the Run tab from the main notebook.

Remove the Run Pipeline and Stop buttons that lived inside the Run tab (the toolbar remains canonical).

Remove the legacy Advanced Prompt Builder button and its callback from the GUI.

Update LEGACY_CANDIDATES.md to mark the prompt builder window as legacy (future removal at code level).

3. Problem / Motivation

With the stage cards duplicated in Pipeline (001A), the Run tab becomes:

A duplicate workspace that can drift out of sync.

Source of UX confusion (two places to Run/Stop).

The only remaining entry point to an old Advanced Prompt Builder that doesn’t fit the V2 design or Prompt tab architecture.

We want a single, clear pipeline workspace (Pipeline tab) and a single Run/Stop control surface (toolbar).

4. Goals / Non-Goals

Goals

Remove the Run tab page from the main notebook.

Remove all Run-tab–local Run/Stop buttons and their callbacks.

Remove the Advanced Prompt Builder launch button from the GUI.

Mark the Advanced Prompt Builder module as legacy in docs.

Non-Goals

Removing the underlying legacy prompt builder code/module from the repo (that’s a follow-on cleanup PR).

Changing toolbar Run/Stop behavior or controller lifecycle logic (covered by lifecycle PRs).

5. Allowed / Forbidden Files

Allowed

src/gui/main_window_v2.py (tabs, toolbar wiring, but don’t redesign)

src/gui/run_tab_v2.py or equivalent Run tab frame

src/gui/api_status_panel.py only if it contains Run-tab–specific references

LEGACY_CANDIDATES.md

Any GUI tests that explicitly assert a Run tab exists

Forbidden

src/controller/*, src/pipeline/*, and all back-end layers.

Randomizer, learning, or API modules.

Non-GUI docs except LEGACY_CANDIDATES.md and this PR’s own md.

6. Implementation Steps

Remove Run tab from main notebook

In main_window_v2.py, locate notebook/tab creation.

Delete the creation of the Run tab frame and the notebook.add(..., text="Run") call.

Remove any tab-change callbacks that explicitly handle a Run tab index.

Remove Run-tab Run/Stop buttons

In the Run tab frame module:

Remove any Run and Stop buttons from the layout.

Remove their command= callbacks.

Ensure the toolbar Run/Stop remains the only active entry point.

Remove Advanced Prompt Builder button

Remove the button (and label/section) that launches the legacy Advanced Prompt Builder window.

Remove or stub out the callback, unless still needed elsewhere.

Update legacy documentation

Add an entry in LEGACY_CANDIDATES.md:

Mark the Advanced Prompt Builder window/module as unused from V2 GUI.

Indicate it is safe to remove in a future “legacy cleanout” PR once tests confirm no remaining references.

Clean up dead imports

Search for imports of the Run tab frame or Advanced Prompt Builder:

Remove any that are now unused.

Make sure there are no unused symbols causing linter/test noise.

7. Testing & Validation

Manual

Start the app:

Confirm tabs across top are now Prompt | Pipeline | Learning (no Run tab).

Confirm:

Toolbar Run/Stop still works.

No in-tab Run/Stop buttons exist.

No UI element launches the legacy Advanced Prompt Builder.

Automated

Update any tests that assumed a Run tab exists:

Either remove those tests or change them to assert the absence of a Run tab in V2.

Add a small GUI test asserting that only the three expected tabs exist.