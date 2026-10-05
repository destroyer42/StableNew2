# PR-GUI-100 — Responsive Workspace & Reachable Controls Foundation

Status: IMPLEMENTED / VERIFIED LOCALLY / READY FOR OWNER REVIEW (not pushed). Baseline: `main` @ `e6b6a1f`.

Scope: make the main window never demand more than the display provides, and keep the long workspaces reachable by
scrolling. This is the foundation only. It is not the visual facelift (GUI-110) and it changes no generation, queue,
backend, NJR, runtime or persistence behavior. No controller or coordinator code was touched.

## Root cause

`main_window_v2.py` enforced `DEFAULT_MAIN_WINDOW_WIDTH = int(640 * 3.1) = 1984`, a 1350 px default height and a
**minimum** of 1984 x 1110. Both exceed a 1920 x 1080 desktop, let alone a 1366 x 768 laptop, so the window opened
larger than the screen and could not be sized down. On top of that, Pipeline forced the root to at least 1400 px on its
first map (a second sizing authority), and Video Workflow, SVD Img2Vid and Review had fixed, non-scrolling bodies, so
their lower controls fell off the bottom of any window that did fit. `ScrollableFrame` registered `bind_all` /
`unbind_all` on pointer enter/leave, so one frame could replace or remove another frame's global wheel binding, and
`src/gui/scrolling.enable_mousewheel` also called `unbind_all`.

## Previous geometry behavior

Default 1984 x 1350, minimum 1984 x 1110, regardless of the screen; a saved geometry was restored only if it was at least
that large; Pipeline additionally widened the root to 1400 px on first map.

## New geometry contract

`src/gui/view_contracts/window_layout_contract.py` (pure, no Tk) is the single authority.
`compute_window_layout(screen_w, screen_h)` returns the default and minimum size, both clamped to the usable screen
(screen minus a 24 px width / 96 px height margin for window chrome and the taskbar).

| Screen | Default | Minimum |
| --- | --- | --- |
| 1366 x 768 | 1342 x 672 | 1280 x 672 |
| 1920 x 1080 | 1896 x 984 | 1280 x 680 |
| 2560 x 1440 | 1900 x 1000 | 1280 x 680 |
| 1024 x 600 | 1000 x 504 | 1000 x 504 |

`normalize_saved_geometry` keeps a valid saved geometry unchanged, clamps an oversized one to the usable screen, raises a
too-small one to the minimum, keeps the window on screen, and returns `None` (recover to the default) for malformed,
non-positive, off-screen-sentinel (`-10000`) or no-longer-visible geometries. `MainWindowV2` computes the layout from
`winfo_screenwidth/height` once, restores through the contract, and applies the layout minimum with `root.minsize`.
Maximized (`zoomed`) handling is unchanged. The preferred width is 1900 because that is the narrowest width at which every
Pipeline control fits its column (measured; see Known limits).

Pipeline's `MIN_WINDOW_WIDTH`, `_ensure_minimum_window_width` and the helper `normalize_window_geometry` were removed;
Pipeline no longer resizes the root.

## Reachable long-form tabs

Review, SVD Img2Vid and Video Workflow now build their existing bodies inside the existing `ScrollableFrame` (no tab was
rebuilt). In Review the edit/reprocess controls moved into the same scroll region as the preview so the whole workspace
scrolls together. The Review preview stays at 620 px.

## ScrollableFrame hardening

One `_WheelRouter` per Tk interpreter replaces the per-frame enter/leave `bind_all`. Frames register on creation and
unregister on destroy; the single global binding is installed with the first frame and only that binding is removed with
the last. Each wheel event goes to the nearest overflowing frame that contains the widget under the pointer, so only the
region under the pointer scrolls, hidden tabs never receive events, and Combobox / Listbox / Spinbox / Text / Treeview
keep their own wheel behavior. `scrolling.enable_mousewheel` now binds on the widget itself with `add="+"`.

## Manual Windows acceptance (non-generating)

Run on the owner's Windows 11 workstation against the real application window (`build_v2_app`, no backend generation).
The display is 2560 x 1440, so a 1366 x 768 laptop was **simulated** by sizing the window to that layout (1342 x 680 on
this display) rather than on a physical laptop panel. Wheel input was synthesized with Tk `event_generate` with real
window routing, not a physical wheel. Screenshots were reviewed for overlap.

- Review, SVD, Video Workflow and the three Pipeline scroll regions: every mapped button could be scrolled fully into its
  viewport (0 unreachable). Review, SVD and Video Workflow had 0 horizontally clipped controls at 1280, 1342 and 1760 wide.
- Wheel over a combobox did not scroll the page; wheel over plain page area did; switching tabs left the hidden tab's
  scroll position untouched and the visible tab scrolled.
- Resize: the window refuses to go below its minimum (a 900 x 500 request stayed 1280 x 680), grows again, maximizes
  (`zoomed`) and returns to the normal size.
- Observed, not a GUI-100 defect: a first-run "Operator Readiness" dialog opens over the window on first launch.
- **Cramped viewports:** at 1342 x 680 the usable scroll viewport is only 158 px (Review), 239 px (SVD) and 223 px (Video
  Workflow). Each of those tabs keeps a fixed header/guidance block above the scroll region and the app shell keeps the
  Operator Log and status bar below it. Everything is reachable, but only a few rows are visible at once.
- Saved-geometry cases (valid, oversized, below-minimum, off-screen sentinel, malformed) are covered by the contract tests,
  not exercised on a second physical display.

## Known limits (not repaired; owner decision)

- **Pipeline at laptop widths.** The three-column Pipeline workspace still needs about 1896 px. At 1342 and 1280 px wide,
  28 controls in its left-column Base Generation form (including both seed "Rand" buttons) and the stage cards are clipped
  horizontally, by up to 184 px, and there is no horizontal scroll. The baseline never rendered below 1984 px (its minimum),
  so this was previously hidden by the oversized window. A fix needs an adaptive Pipeline layout (for example a collapsible
  preview column or stacked form rows), which is a layout redesign rather than this foundation.
- **Cramped viewports** above: fixed headers and the Operator Log leave a small scroll area on a 768 px display.
- The Review preview stays 620 px and several `wraplength` values remain fixed.

## Validation

See the completion report for the exact commands and results. New automated coverage extends existing owners
(`tests/gui_v2/test_workspace_layout_resilience_v2.py`, `test_pipeline_layout_scroll_v2.py`,
`test_main_window_persistence_regressions.py`, `test_window_layout_normalization_v2.py`): screen-fit and saved-geometry
parametrized contract tests, a real-Tk reachability test per long-form tab at a laptop viewport, and a wheel-router test
covering scoping, no stealing, combobox safety and cleanup.
