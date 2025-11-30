PR-B01-PACK-PREVIEW-STABILITY-V2-P1
1. Title

PR-B01 – Pack Preview Stability & UX Fixes (SidebarPanelV2)

2. Summary

This PR hardens the prompt pack preview behavior in SidebarPanelV2 so that:

Selecting a pack and toggling “Show Preview” never causes runaway updates or Tk “Not enough memory resources” errors.

The preview panel shows a usable, scrollable view of the first prompt block (LoRAs/embeddings included) instead of a truncated 1–2 lines.

Preview state is stable when the selection changes (0, 1, or many packs), and multi-selection does not try to render a preview.

The logic is fully covered by unit tests so regressions are caught before they crash Tk.

Scope: one bugfix PR, tightly focused on the pack preview in the pipeline sidebar.

3. Problem Statement

Current behavior in the Pipeline tab’s left sidebar (SidebarPanelV2):

Selecting a pack and enabling preview eventually produces Tk_GetPixmap / “Not enough memory resources” errors.

This strongly suggests a runaway repaint or event loop interaction that keeps redrawing the preview text widget.

The preview pane only shows a small slice of the first prompt; you can’t see the full first block or scroll it.

The logic for when to show/hide/refresh the preview is spread across:

Selection changes,

Preview toggle button,

And internal state flags,
making it hard to reason about and easy to accidentally create infinite or near-infinite update loops.

We need a stable, predictable, and test-backed pack preview behavior that does not tank Tk, while preserving the UX requirements:

Single-pack selection → preview available.

Multi-pack selection → preview disabled/hidden.

No selection → preview hidden/disabled.

Preview text shows a meaningful “first prompt block” description and is scrollable.

4. Goals

Eliminate the Tk_GetPixmap / memory-resource crashes associated with pack preview.

Make the pack preview logic in SidebarPanelV2 single-source-of-truth and easy to reason about:

Explicit rules for when preview is visible.

Explicit rules for when preview text is regenerated.

Improve the preview UX:

Show the full “first block” content (positive/negative prompts, LoRAs, etc.).

Provide a scrollable area instead of truncating at a tiny fixed height.

Add targeted tests that:

Cover single/multi selection, toggle on/off, and selection changes while visible.

Assert we don’t repeatedly regenerate preview for the same pack in a loop.

Keep the change localized to the sidebar and its tests; no changes to the main window, pipeline layout, controllers, or job queue.

5. Non-goals

No redesign of the prompt pack metadata model or file format.

No changes to how prompt packs are discovered or filtered.

No changes to the job queue, job draft, or right-hand preview panel.

No changes to pipeline execution, WebUI connection, or resource sync.

No theming overhaul; only minimal preview widget tweaks needed for usability.

6. Allowed Files

Code (implementation):

src/gui/sidebar_panel_v2.py

Primary target: stabilize preview state machine and selection handling.

(If needed) src/gui/prompt_pack_adapter_v2.py

Only if we need a helper to get a safe first-prompt summary with better guarantees (avoid huge strings).

Tests:

tests/gui_v2/test_sidebar_pack_preview_v2.py (new)

tests/gui_v2/__init__.py (only if needed to register the new test module)

Docs (optional / lightweight):

docs/BUGLOG_V2-P1.md – add a short entry describing this bugfix.

7. Forbidden Files

Do not modify in this PR:

GUI spine & layout:

src/gui/main_window_v2.py

src/gui/layout_v2.py

src/gui/panels_v2/layout_manager_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/views/prompt_tab_frame_v2.py

src/gui/views/learning_tab_frame_v2.py

Status bar & WebUI lifecycle:

src/gui/status_bar_v2.py

src/controller/webui_connection_controller.py

src/api/webui_process_manager.py

src/api/healthcheck.py

Pipeline core & executor:

src/pipeline/*

Controllers & app state (except through events already exposed):

src/controller/app_controller.py

src/gui/app_state_v2.py

Randomizer, learning, queue/cluster subsystems.

Any V1 or legacy GUI files.

If you believe a forbidden file must change, stop and treat that as a separate PR, not part of B01.

8. Step-by-step Implementation
A. Clarify and document the preview state machine

In SidebarPanelV2:

Add clear internal state fields:

self._preview_visible: bool

self._preview_current_path: Path | None – last pack path we rendered.

Add a short docstring or comment block above the preview methods describing the rules:

Preview is only valid when exactly one pack is selected.

If selection changes to 0 or >1 items, preview auto-hides and “Show Preview” is disabled.

When visible, preview text is re-generated only when the selected pack changes.

B. Harden selection change and button handlers

Still in SidebarPanelV2:

In _on_pack_selection_changed:

Keep it as the single place that reacts to listbox selection changes.

Ensure it only calls:

_update_pack_actions_state() (button enable/disable), and

not any direct preview show/hide calls beyond what _update_pack_actions_state already orchestrates.

In _update_pack_actions_state:

When single is False:

Disable preview toggle button and hide preview if currently visible.

When single is True:

Enable preview toggle button.

If self._preview_visible is True, call a single helper to refresh the text for the new selection:

self._refresh_preview_for_current_selection()

Implement _refresh_preview_for_current_selection:

Fetch summary = self._get_selected_pack_summary().

If summary is None, hide preview and return.

If summary.path == self._preview_current_path, do nothing (already showing this pack → prevents redundant updates).

Otherwise:

Call _update_preview_text(summary).

Update self._preview_current_path.

Update _toggle_pack_preview:

If no single selection → do nothing (extra guard).

When turning preview on:

Set self._preview_visible = True.

Call _refresh_preview_for_current_selection() and grid() the frame.

When turning preview off:

Call _hide_pack_preview() (sets visible flag false, clears _preview_current_path if desired, and grid_remove() the frame).

C. Make the preview widget usable but bounded

In _build_pack_selector_section where self.pack_preview_text is created, ensure:

Height is reasonable and scrollable, e.g.:

height=8–10 with wrap="word".

Attach a vertical scrollbar:

Either by:

Creating a small ttk.Scrollbar next to the Text widget and wiring yscrollcommand.

Keep all styling consistent with BACKGROUND_ELEVATED, TEXT_PRIMARY, etc.

This addresses the “preview doesn’t show full first prompt” without requiring enormous text height.

D. Guard the text update path

In _update_preview_text:

Keep the existing logic (clear → insert → disable).

Add a protection against very large strings:

e.g., max_chars = 4000 and truncate oversize previews with “… [truncated]”.

This is a belt-and-suspenders safety to avoid extremely large prompts from creating huge DIB sections.

In _describe_first_prompt / _read_first_block:

Keep the current caching behavior, but ensure:

Errors reading the file or parsing prompts are swallowed and yield a small, safe string.

No loops or callbacks should be triggered from here; this function must remain pure (no GUI calls).

Ensure _hide_pack_preview:

Clears self._preview_visible = False.

Optionally sets self._preview_current_path = None so that next preview toggling always re-evaluates the current selection.

E. Add focused tests

Create tests/gui_v2/test_sidebar_pack_preview_v2.py that uses the existing GUI test conventions (mark as gui and skip if Tk not available):

Test 1 – Single selection preview shows content:

Build a minimal SidebarPanelV2 with a fake PromptPackAdapterV2 that returns a small summary and prompt block.

Populate _prompt_summaries and _current_pack_names with one item and simulate:

Select index 0.

Click “Show Preview”.

Assert:

_preview_visible is True.

pack_preview_text.get("1.0", "end") contains the expected header text (e.g. pack name) and first block content.

Test 2 – Multi selection disables preview:

Simulate selection of 2 indices in pack_listbox.

Ensure:

Preview toggle is disabled.

If preview was visible, it is now hidden (_preview_visible is False).

Test 3 – Selection change does not loop:

Use a fake adapter that increments a counter every time _describe_first_prompt is called.

Steps:

Single selection → toggle preview on.

Change selection to another single pack.

Ensure the counter increments only once per unique pack and not unbounded in a loop.

This is a proxy for “no infinite update loop”.

Test 4 – Preview truncated but safe for huge text:

Simulate _describe_first_prompt returning a very large string (e.g. 10k characters).

Call _update_preview_text.

Assert:

The stored text length is ≤ max_chars + small_margin.

No exceptions are raised.

9. Required Tests (Failing first)

Before implementing:

Add the new tests in tests/gui_v2/test_sidebar_pack_preview_v2.py:

They should initially fail or be fragile because:

Preview truncation/scroll behavior is not yet in place.

The state machine and redundant updates aren’t constrained.

After implementation:

Run (on a machine with Tk available):

python -m pytest tests/gui_v2/test_sidebar_pack_preview_v2.py -q


Confirm existing sidebar/pipeline GUI tests still pass:

python -m pytest tests/gui_v2/test_gui_v2_workspace_tabs_v2.py -q


(If Tk isn’t available, they should skip cleanly, not crash.)

10. Acceptance Criteria

This PR is considered done when:

Manually:

Selecting a single pack and clicking “Show Preview”:

Shows a scrollable preview with pack metadata and first block content.

Selecting zero packs:

“Show Preview” is disabled, preview hidden.

Selecting multiple packs:

“Show Preview” is disabled, preview hidden.

Changing from one selected pack to another while preview is visible:

Updates the preview exactly once per selection, with no lag or hangs.

Running through these operations repeatedly does not produce Tk_GetPixmap or “Not enough memory resources” errors.

Programmatically:

All tests in tests/gui_v2/test_sidebar_pack_preview_v2.py pass.

Existing GUI workspace / pipeline tests still pass or skip gracefully.

No other parts of the GUI (tabs, pipeline cards, job preview, WebUI status) change behavior as a result of this PR.

11. Rollback Plan

If this PR introduces regressions:

Revert the changes to:

src/gui/sidebar_panel_v2.py

tests/gui_v2/test_sidebar_pack_preview_v2.py

Any documentation notes added in docs/BUGLOG_V2-P1.md

Confirm:

Application still launches.

Sidebar still shows packs and is operable, even if preview behavior regresses to current state.

Re-open the bug and capture any additional reproduction details observed.

12. Codex Execution Constraints

When Codex applies this PR:

Do not touch forbidden files (main window, layout manager, controllers, pipeline runtime).

Keep changes local and surgical:

Most logic should be confined to the existing methods and small new helpers.

Maintain type-hints and follow existing coding style.

Ensure GUI tests are marked and skipped appropriately when Tk isn’t available.

Avoid introducing new dependencies or altering project configuration.

13. Smoke Test Checklist

After implementation, manually verify on your dev machine:

python -m src.main opens MainWindowV2 normally.

Go to the Pipeline tab:

Confirm the sidebar is present with the Pack Selector card.

In the Pack Selector:

Select a single pack → click “Show Preview”.

Confirm preview appears with meaningful content and is scrollable.

Select multiple packs:

Confirm preview hides and the toggle is disabled.

Rapidly:

Select pack A, preview on.

Select pack B, pack C, back to A, toggling preview a few times.

Confirm no error dialogs and no Tk_GetPixmap / memory errors in the console.

Exit the app cleanly; no traceback at shutdown.

If all of the above checks out and tests pass, PR-B01 is ready to merge.