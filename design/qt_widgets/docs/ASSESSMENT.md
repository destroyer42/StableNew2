# Bounded assessment: isolated native Qt Widgets Create prototype (v0.3)

**v0.3 adds the Output Display** (owner request): a dockable / undockable, collapsible, resizable, zoomable placeholder viewer to the right of the workspace, with Free / Lock size / Fill sizing. See "Output Display (v0.3)" below. Numbers in the v0.2 sections that changed (test count, layout measurements) are updated in place.

## Status and verdict

**RUNS ON WINDOWS; TESTED; UI QUALITY NOT YET OPERATOR-VALIDATED.** The prototype was run with the existing Windows Python 3.14.9 / PySide6 6.12.0 environment. v0.1's defects were fixed, the owner-requested blue/rounded theme was applied, and the Create workflow was extended. No physical GPU/Forge/SVD or model inference was run; no production file, branch or PR changed.

**Repository evidence cut:** remote `main` `fc644705b0d2428d1a258bc820ae7b214ffe4469` (present in the local clone). Decision mapping: see `TRACEABILITY.md`.

**Existing evidence retained:** GUI-PORT-740 showed isolated Qt Widgets construction and state/dispatcher parity within synthetic scope. GUI-PORT-742 judged a *production* Qt migration NO-GO on existing evidence. This mock UI does not reverse either finding.

## Verification performed (2026-11-08, Windows 11, 96 DPI primary display)

- Environment: `C:\Users\rob\qual\gui-port740-env` no longer exists; the same environment now lives at `C:\Users\rob\qual.__moved_to_D\gui-port740-env` and works (Python 3.14.9, PySide6 6.12.0, Qt 6.12.0).
- **129 tests pass** on the native Windows platform with Qt enabled: 87 pure (domain, features, theme, architecture, output model) + 42 Qt (15 workspace + 27 Output Display). Without Qt enabled the 42 Qt tests skip.
- Qt tests assert, on a real shown window: stylesheet parses with no Qt warnings; SVG assets load; actions and buttons stay inside the window at 1280×680; no horizontal clipping at 1280×680, 1440×900 and 960×600; the settings grid reflows with width; lock/reset/undo/redo/reset-undo flows; slot rename and duplicate guard; unfocused spin boxes ignore the wheel; combos are non-editable; shortcuts are registered.
- Theme tests assert 14 contrast pairs meet their minimums (e.g. text on background 14.2:1, muted on selected 4.7:1, primary label 11.2:1), the background is blue, radii ≥ 8px, plain widgets are transparent, and focus changes only border colour.
- Layout measured with `tools/capture.py` on the native platform, **with the Output Display docked open (380 px)**: at 1280×680 the form viewport is 409×417 (content about 2080 px high, so about five screens of scrolling) with one settings column and the footer fully visible; at 1440×900 the viewport is 537×662 with two columns. With the display collapsed to its rail, 960×600 gives a 588 px-wide form with 2 columns and no clipping. A 150% scale emulation (`QT_SCALE_FACTOR`) keeps the same layout. Screenshots: `docs/screenshots/` (`create_*`, `library_*`, `dock_*`).
- **Cost of the dock on the workspace:** the expanded display makes the minimum window width 1192 px (944 px collapsed), so 960×600 is only reachable collapsed. The Create form lost width (v0.2 at 1280×680: 690 px viewport, 4 screens; now 409 px, 5 screens). Collapse the display or use Fill/Lock deliberately when authoring.

## Output Display (v0.3)

**What it is:** a `QDockWidget` (`output_display.py`) in the right dock area of the main window, with a placeholder viewer driven by the Create draft (`output_model.py`, pure). It shows the draft's size as an aspect-correct frame with the resolved prompt, model fixture, settings, seed/batch, and a state badge: DRAFT FRAME (dashed, muted), PREVIEW BUILT (solid, green), PREVIEW STALE (dashed, yellow), SIMULATED RECEIPT (solid, green). It always says **"No image generated"**; this prototype has no runtime and the display never shows a real image. State is carried by words and line style as well as colour.

| Requirement | Implementation | Verified by |
|---|---|---|
| Right of the current window | `Qt.RightDockWidgetArea`; Left also allowed, Bottom deliberately not | placement tests |
| Dockable / undockable | Custom title bar with **Undock / Dock** buttons (tested). Dragging the title bar to float or re-dock is Qt's native dock behaviour on that bar; it was **not** exercised by the tests (no synthetic OS drag) and still needs a manual check | undock, re-dock, left-dock tests |
| Collapsible | Title-bar arrow, header **Output Display** toggle, **Ctrl+3**. Docked: a 56 px vertical rail and the workspace reclaims the width; floating: shrinks to its title bar. The previous (or locked) width is restored on expand | collapse/restore, toggle, floating-collapse tests |
| Resizable | Drag the dock edge, or resize the floating window; minimum 300 px expanded | free-mode tests |
| Lock the resizable portion | **Lock size**: docked, min = max width (the edge cannot be dragged, even programmatically); floating, fixed window size. Survives collapse/expand | lock tests |
| Dynamic fill | **Fill**: docked, takes every pixel the workspace does not need (workspace keeps ~900 px) and follows window resizes; floating, fills the screen's work area and restores the previous geometry when you leave Fill | fill tests |
| Zoom | − / + (×1.25, snaps to exactly 100%), log slider 5%–1600%, **100%**, **Fit** (re-fits on every resize; custom zoom is kept), Ctrl+wheel zooms at the pointer, drag to pan, double-click toggles Fit/100%, Ctrl+= / Ctrl+− / Ctrl+0 / Ctrl+9 while focus is in the display | 8 zoom tests, 13 pure math tests |

Vector scene: the frame, grid and text are drawn as scene items with cosmetic pens, so they stay sharp at every zoom (no raster is scaled).

**Known limits of the Output Display**

1. **Expanded dock narrows the workspace** (see the cost note above). Locking a wide dock also raises the window's minimum width by the locked width.
2. **Fill is reasserted on window resize and mode change**, not continuously: dragging the dock edge in Fill moves it until the next window resize. It is not a separate "pinned" state.
3. **Floating Fill uses the screen the dock is on**; multi-monitor behaviour and moving a Fill window between monitors were not tested.
4. **No persistence** (the app promises NO WRITES): dock area, width, mode and zoom reset on restart.
5. **Accessibility:** controls have accessible names and the title-bar buttons are keyboard reachable, but Narrator/NVDA output and the dock's keyboard-driven float/resize were not verified. Qt's native dock drag has no keyboard equivalent besides the Undock/Dock button.
6. The floating dock is a Qt tool window; its rounded corners are stylesheet-drawn and the OS window shadow is the platform's.
7. This is a UI shell for an eventual output surface. It does not read artifacts, History or the filesystem and implies nothing about the production Artifacts/History path.

## Defects from the first Windows run — status

| # | v0.1 defect | v0.2 |
|---|---|---|
| 1 | Dark rectangles behind labels/containers in cards | Fixed: plain widgets transparent (tested) |
| 2 | Unreadable spin-box arrows | Fixed: SVG arrows; verified in screenshots |
| 3 | Lock checkbox nearly invisible | Fixed: bordered indicator, accent when checked |
| 4 | Change explanation vanished after any edit | Fixed: persistent change log with revisions |
| 5 | Manual overrides permanent | Fixed: ↺ per setting, reset-unlocked, auto-release when equal to recommendation |
| 6 | Editable sampler combo gave empty/partial values | Fixed: closed lists plus validation errors |
| 7 | Weak layout test | Replaced by measuring Qt tests |
| 8 | Unnamed prompt editors | Accessible names added; announcement by a screen reader **not** verified |

## Found and fixed during this iteration

- v0.3: the new layout test caught the review panel being squeezed 9 px below its content at 1280×680 (fixed with an explicit minimum width), and the footer strip clipping its bold primary label and squeezing its status text at the narrower workspace (the status now moves above the buttons when space is short; buttons have a minimum width).
- A 20 px horizontal clip at the 960×600 minimum window (size-preset row plus a wide button) was caught by the new Qt test and fixed by making that row a `ResponsiveGrid`.
- Navigation item text was elided at 960 px; the sidebar minimum width was raised.

## Remaining risk and evidence gaps

1. **Operator validation:** nothing here shows the workflow is better for the owner than the current Tk Create screen; GUI-PORT-742's NO-GO stands.
2. **Scroll length:** about five screens of form at 1280×680 with the display open. A section outline or a two-pane form may be warranted.
3. **DPI:** only a 150% scale emulation was run; true per-monitor 100/125/150% on Windows was not.
4. **Accessibility:** tab order was walked in code and names were added; no screen-reader (Narrator/NVDA) or high-contrast-mode run. The popup list of combo boxes uses square OS-level corners.
5. **Rounded corners** are stylesheet-drawn; the native Windows title bar and popups are unchanged.
6. **Learning-informed** values (steps 32, CFG 6.5; Flux steps 10) are invented fixtures, not evidence of any profile.
7. **Source ownership:** tokens are local design fixtures, not a second production theme.
8. Canonical `tools/ci/run_pr_gate.py`: **not run** (this is not a StableNew checkout).

## Next gates

1. Owner reviews the screenshots and a live run; record usability changes.
2. Run at true 100/125/150% display scaling and with Narrator.
3. Review against Concept A and the UX-850-C wireframe; the blue theme deliberately departs from Concept A.
4. Only after owner acceptance, adapt into a new short-lived repository branch and satisfy the local canonical gate and Windows CI; evaluate productivity benefit and Qt runtime cost as a separate evidence-backed decision.

No publication, protected action or physical runtime authorization was inferred.
