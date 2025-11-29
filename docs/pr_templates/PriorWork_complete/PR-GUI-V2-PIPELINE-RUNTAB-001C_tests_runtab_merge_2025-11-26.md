PR-GUI-V2-PIPELINE-RUNTAB-001C_tests_runtab_merge_2025-11-26
1. Title

PR-GUI-V2-PIPELINE-RUNTAB-001C: Tests & Docs for Run→Pipeline Merge

2. Summary

This PR cements the Run→Pipeline merge with:

Updated GUI tests that treat the Pipeline tab as the sole host for advanced stage cards and execution UX.

A short docs update to the GUI V2 program/architecture docs so future work doesn’t re-introduce a Run tab.

Journey Test mapping updates so JT-03/04/05 clearly reference Pipeline as the home of stage configuration.

No functional changes — just tests and documentation.

3. Goals / Non-Goals

Goals

Ensure tests fail loudly if anyone re-introduces a Run tab or moves stage cards away from Pipeline.

Ensure tests cover:

Presence and basic wiring of txt2img / img2img / upscale cards on Pipeline.

Absence of Run tab in tab labels.

Update docs (StableNew_GUI_V2_Program_Plan, ARCHITECTURE_v2_COMBINED, and Journey Test Plan) to reflect the new single-tab model.

Non-Goals

Additional GUI refactors.

Any new functionality in Pipeline or Learning tabs.

4. Allowed / Forbidden Files

Allowed

tests/gui_v2/test_pipeline_tab_stage_cards.py (new)

tests/gui_v2/test_main_window_tabs_v2.py (new)

Any existing GUI V2 tests that reference Run tab or stage locations

ARCHITECTURE_v2_COMBINED.md

StableNew_GUI_V2_Program_Plan-11-24-2025.md

Journey_Test_Plan_*.md

Forbidden

All src/* code except minimal test helpers (if any).

Non-GUI docs unrelated to layout.

5. Implementation Steps

New GUI tests for Pipeline stage cards

Add tests/gui_v2/test_pipeline_tab_stage_cards.py:

Create main window (or test harness window).

Navigate to Pipeline tab.

Assert that:

txt2img, img2img, and upscale cards are present.

Each has expected key widgets (e.g., sampler, steps widgets exist).

Optional: toggling stage enable flags affects card state.

New GUI test for tab set

Add tests/gui_v2/test_main_window_tabs_v2.py:

Instantiate main window / notebook.

Collect visible tab labels.

Assert {"Prompt", "Pipeline", "Learning"} is the exact set (or at least that “Run” is not present).

Clean up / adapt existing tests

Update any test that:

Searches for stage cards under a Run tab frame.

Asserts that a Run tab exists.

Point them at Pipeline tab instead or retire them if redundant.

Docs updates

In ARCHITECTURE_v2_COMBINED.md, ensure the GUI layer section describes:

PipelinePanelV2 as the host of stage cards.

No mention of a separate Run tab in the V2 layout.

In StableNew_GUI_V2_Program_Plan-11-24-2025.md, update any diagrams/text that still reference a Run tab.

In Journey Test Plan:

JT-03/04/05 steps should explicitly say “configure in Pipeline tab”.

Remove references to Run tab from any journey narrative.

6. Testing & Validation

Run new tests plus existing GUI V2 suite:

Confirm all pass with no references to Run tab.

Skim docs for any remaining “Run tab” references and make sure they’re either:

Marked legacy, or

Corrected to “Pipeline tab”.