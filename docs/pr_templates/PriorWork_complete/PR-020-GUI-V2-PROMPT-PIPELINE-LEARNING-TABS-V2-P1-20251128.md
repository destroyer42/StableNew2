PR Spec: Reattach the Prompt / Pipeline / Learning 3-Tab Workspace

Goal: Use the existing PromptTabFrame, PipelineTabFrame, and LearningTabFrame to restore the 3-tab workspace on the center notebook, while keeping V2-only, preserving current tests, and avoiding changes to main.py or main_window_v2.py.

1. Title

PR-020-GUI-V2-PROMPT-PIPELINE-LEARNING-TABS-V2-P1-20251128

2. Summary

Reconnect the already-implemented V2 tab frames (PromptTabFrame, PipelineTabFrame, LearningTabFrame) into the running GUI so the center ttk.Notebook shows Prompt / Pipeline / Learning tabs again, instead of a bare “spine” layout.

Use LayoutManagerV2 as the single wiring point:

Create the three tab frames and add them to center_notebook.

Route existing GUI V2 panels through those tab frames.

Preserve compatibility attributes on MainWindowV2 (sidebar_panel_v2, pipeline_panel_v2, randomizer_panel_v2, preview_panel_v2, status_bar_v2, pipeline_controls_panel, run_pipeline_btn) so current tests keep working.

No architectural changes, no V1 imports.

3. Problem Statement

Right now, MainWindowV2:

Builds the spine (header row, left zone, center_notebook, right zone, bottom zone).

Instantiates LayoutManagerV2 and calls attach_panels().

But LayoutManagerV2 currently:

Directly drops SidebarPanelV2, PipelinePanelV2, RandomizerPanelV2 into those zones and notebook pages.

Ignores the existing V2 tab frames:

PromptTabFrame (src/gui/views/prompt_tab_frame_v2.py)

PipelineTabFrame (src/gui/views/pipeline_tab_frame_v2.py)

LearningTabFrame (src/gui/views/learning_tab_frame_v2.py)

Those tab frames already wire up:

Prompt workspace + prompt pack matrix helper.

Stage cards + sidebar + preview for the pipeline.

Learning controller, state, experiment design, plan table, and review panel.

So the 3-tab layout you remember is implemented, but unreachable from the current V2 entrypoint path. The result is the “hot garbage” spine you’re seeing: header, legacy-ish left panel, empty center, empty right, status bar.

4. Goals

Show Prompt / Pipeline / Learning as notebook tabs in the center area when launching the app via python -m src.main.

Use the existing V2 tab frames as the source of truth:

PromptTabFrame handles prompt workspace + packs.

PipelineTabFrame hosts sidebar, stage cards, preview.

LearningTabFrame hosts the learning workspace.

Keep V2-only and backwards-compatible:

No V1 imports, no archived modules pulled back.

Preserve current compatibility attributes on MainWindowV2 used by tests and other modules.

Add minimal tests to ensure the 3-tab layout doesn’t silently regress again.

5. Non-goals

No changes to src/main.py or entrypoint wiring.

No redesign of the visual layout beyond using the existing 3 tabs.

No changes to learning logic, pipeline execution, or randomizer behavior.

No reclassification of tests (we only add a small test file; we don’t shuffle the legacy test tree).

No work yet on WebUI launch determinism; that will be a separate PR right after this.

6. Allowed Files

Only these files may be modified in this PR:

src/gui/panels_v2/layout_manager_v2.py

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py (new)

If Codex finds it absolutely impossible to complete the wiring without touching another file, it should stop and emit a clear explanation instead of editing additional files.

7. Forbidden Files

These must not be modified in this PR:

src/main.py

src/app_factory.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

src/controller/app_controller.py

src/gui/layout_v2.py

src/pipeline/executor.py

Any file under archive/ or archive/gui_v1/

Any file under tests/legacy/ (read-only for reference)

8. Step-by-step Implementation
8.1. Update LayoutManagerV2 imports

In src/gui/panels_v2/layout_manager_v2.py:

Keep the existing imports from src.gui.panels_v2 only if still needed for compatibility.

Add imports:

from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame


These are the already-implemented V2 tab frames.

8.2. Rebuild attach_panels around tab frames

Rewrite LayoutManagerV2.attach_panels to:

Create the three tab frames and add them as notebook pages:

Pseudo-structure (Codex must match the actual __init__ signatures from each tab frame):

def attach_panels(self) -> None:
    mw = self.main_window

    # Prompt tab
    mw.prompt_tab = PromptTabFrame(
        mw.center_notebook,
        app_state=getattr(mw, "app_state", None),
        # pass any additional kwargs required by PromptTabFrame.__init__
    )
    mw.center_notebook.add(mw.prompt_tab, text="Prompt")

    # Pipeline tab
    mw.pipeline_tab = PipelineTabFrame(
        mw.center_notebook,
        app_state=getattr(mw, "app_state", None),
        prompt_workspace_state=getattr(mw, "prompt_workspace_state", None),
        pipeline_controller=getattr(mw, "pipeline_controller", None),
        # plus any other dependencies that PipelineTabFrame.__init__ expects
    )
    mw.center_notebook.add(mw.pipeline_tab, text="Pipeline")

    # Learning tab
    mw.learning_tab = LearningTabFrame(
        mw.center_notebook,
        app_state=getattr(mw, "app_state", None),
        # pass through any other required args (e.g., learning-specific config)
    )
    mw.center_notebook.add(mw.learning_tab, text="Learning")


Important: Codex must open each tab frame file and pass through the parameters they actually require (e.g., config_manager, theme, pipeline_controller, etc.), using existing attributes already present on MainWindowV2 or AppStateV2. Do not invent new attributes on MainWindowV2 in this PR.

Align notebook selection:

Optionally, ensure the initial selected tab is Pipeline (matches current “run pipelines first” workflow):

mw.center_notebook.select(mw.pipeline_tab)

8.3. Wire compatibility attributes to tab internals

To keep tests/gui_v2/test_gui_v2_layout_skeleton.py and other code happy, set the existing panel attributes on MainWindowV2 to point into the tab frames instead of creating separate, duplicate panels.

Right after creating the tab frames in attach_panels:

Sidebar, pipeline panel, preview, randomizer:

From PipelineTabFrame we know there are attributes:

self.sidebar (a SidebarPanelV2)

self.stage_cards_panel (owns txt2img/img2img/upscale cards)

self.preview_panel (a PreviewPanelV2)

Use those to set:

mw.sidebar_panel_v2 = mw.pipeline_tab.sidebar
mw.pipeline_panel_v2 = mw.pipeline_tab.stage_cards_panel
mw.preview_panel_v2 = mw.pipeline_tab.preview_panel

# Randomizer panel: if PipelineTabFrame exposes a dedicated
# randomizer panel, wire it; otherwise leave it None or derive
# from sidebar, but do NOT invent new GUI pieces in this PR.
mw.randomizer_panel_v2 = getattr(mw.pipeline_tab, "randomizer_panel", None)


Codex should inspect PipelineTabFrame to see if a randomizer_panel attribute already exists; if not, it should prefer leaving randomizer_panel_v2 as None over designing new UI.

Status bar:

Keep using the BottomZone’s status bar instance; just expose it:

mw.status_bar_v2 = getattr(mw.bottom_zone, "status_bar_v2", None)


Pipeline controls + run button:

Reuse the existing pattern from the old LayoutManagerV2:

stage_panel = mw.pipeline_panel_v2

mw.pipeline_controls_panel = getattr(stage_panel, "controls_panel", stage_panel)
mw.run_pipeline_btn = getattr(stage_panel, "run_button", None)


This keeps the tests that expect pipeline_controls_panel and run_pipeline_btn intact.

Left/right zones:

The tab frames already own the sidebar and preview layout; we do not directly pack new panels into mw.left_zone or mw.right_zone in this PR. Those zones essentially act as the structural grid parents for the notebook and other elements, which is already handled in main_window_v2.py.

8.4. Remove old direct panel instantiation from LayoutManagerV2

Delete or comment out any existing code in attach_panels that creates:

SidebarPanelV2(...) directly

PipelinePanelV2(...) directly

RandomizerPanelV2(...) directly

PreviewPanelV2(...) or StatusBarV2(...) directly

The only responsibilities of LayoutManagerV2 after this PR:

Create tab frames and add them to center_notebook.

Expose the compatibility attributes on MainWindowV2 by referencing tab frame internals and the bottom status bar.

No other GUI widgets should be instantiated here.

8.5. New test: verify workspace tabs and compatibility attributes

Add tests/gui_v2/test_gui_v2_workspace_tabs_v2.py:

Behavior:

Use the existing gui_app_factory fixture to create the app.

Assert that the center notebook has Prompt, Pipeline, and Learning tabs:

def test_workspace_tabs_present(gui_app_factory):
    app = gui_app_factory()
    notebook = app.center_notebook

    tab_labels = [notebook.tab(tid, "text") for tid in notebook.tabs()]
    assert "Prompt" in tab_labels
    assert "Pipeline" in tab_labels
    assert "Learning" in tab_labels


Assert that the compatibility attributes are correctly wired:

from src.gui.sidebar_panel_v2 import SidebarPanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2

def test_workspace_panels_exposed(gui_app_factory):
    app = gui_app_factory()

    assert hasattr(app, "pipeline_tab")
    assert hasattr(app, "prompt_tab")
    assert hasattr(app, "learning_tab")

    assert isinstance(app.sidebar_panel_v2, SidebarPanelV2)
    assert isinstance(app.preview_panel_v2, PreviewPanelV2)

    # Pipeline controls / run button still exist for tests
    assert app.pipeline_controls_panel.winfo_exists()
    assert app.run_pipeline_btn.winfo_exists()


Do not assert styling details; focus on structure and exposed attributes so the test is resilient.

9. Required Tests (failing first)

Codex should:

Run the new test alone and confirm it fails on the baseline snapshot:

pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


Implement the changes above.

Re-run:

pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q
pytest tests/gui_v2/test_gui_v2_layout_skeleton.py -q
pytest tests/gui_v2/test_status_bar_webui_controls_v2.py -q
pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -q


Finally, run your Phase-1 test set (whatever suite Codex has been using, e.g., tests/phase1_test_suite.txt) to ensure nothing else regressed.

10. Acceptance Criteria

When launching python -m src.main:

The central area displays a ttk.Notebook with tabs labeled Prompt, Pipeline, and Learning.

Prompt tab shows prompt workspace UI (pack/slot editor, etc.).

Pipeline tab shows the familiar sidebar + stage cards + preview layout.

Learning tab shows the learning workspace (design panel, plan table, review panel).

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py passes.

Existing GUI V2 layout tests (test_gui_v2_layout_skeleton.py, test_status_bar_webui_controls_v2.py, etc.) still pass without changes.

No forbidden files modified.

No imports from archived V1 modules are introduced.

11. Rollback Plan

If this PR introduces issues:

Revert src/gui/panels_v2/layout_manager_v2.py to its prior version in Git.

Delete tests/gui_v2/test_gui_v2_workspace_tabs_v2.py.

Re-run the Phase-1 test suite to confirm behavior matches the pre-PR snapshot (even if visually worse).

Because this PR only touches one wiring helper and a new test file, rollback is straightforward.

12. Codex Execution Constraints

When you hand this to Codex 5.1 MAX:

Explicitly list the only editable files:

src/gui/panels_v2/layout_manager_v2.py

tests/gui_v2/test_gui_v2_workspace_tabs_v2.py

Explicitly list the forbidden file list from section 7.

Instructions to Codex:

“Use the existing PromptTabFrame, PipelineTabFrame, and LearningTabFrame as the layout primitives.”

“Do not modify MainWindowV2 or any controllers.”

“Expose existing compatibility attributes (sidebar_panel_v2, pipeline_panel_v2, randomizer_panel_v2, preview_panel_v2, status_bar_v2, pipeline_controls_panel, run_pipeline_btn) by wiring them to tab frame internals.”

“Keep diffs minimal and localized; no new modules or classes.”

13. Smoke Test Checklist

After Codex completes the PR and tests are green, you can manually smoke test:

Boot the app: python -m src.main

Visual layout:

Confirm three tabs: Prompt / Pipeline / Learning.

Switch between tabs without errors.

Prompt tab:

Load a prompt pack; verify fields populate.

Use the matrix helper; confirm dialog opens and updates text.

Pipeline tab:

Toggle stages in sidebar; verify visible cards match enabled stages.

Confirm “Run pipeline” button exists and is clickable (even if pipeline execution will be tuned later).

Learning tab:

Create or select a learning plan; ensure table and review panel render.

Status bar:

Confirm status text and WebUI controls still appear in the bottom bar.

Close app: Ensure clean exit, no Tk stack traces in console.