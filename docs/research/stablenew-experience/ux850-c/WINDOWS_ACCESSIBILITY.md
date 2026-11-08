# Windows sizing, keyboard and accessibility requirements

All requirements are **PROPOSED future acceptance**, not observed outcomes. No desktop/app control, Windows scaling change or Tk test execution occurred in C. The earlier selected Tk test crash `0xc0000008` is an execution limit, not reproduced evidence of a current UI defect. Historical screenshots and the October audit do not establish present failure.

## Measurement vocabulary and representative matrix

Record physical display/work area, physical **client** rectangle, Tk-reported client width/height, OS display scale, actual process/thread DPI-awareness context, monitor DPI, `tk scaling`, font family/resolved metrics, screenshot capture awareness, theme, window state and source SHA. Do not call a 1280×680 display a 1280×680 client: window decorations/taskbar consume space. Existing geometry policy prefers minimum **1280×680**, clamped to available screen; it is not a new hard minimum. **1280×760** is a comparison cell, not replacement policy.

Logical units below are design units at 96 dpi. A 125% scale corresponds nominally to 120 dpi, 150% to 144 dpi; actual awareness/virtualization can change what Tk reports. Two matrix interpretations prevent accidentally granting larger physical windows in a high-DPI test:

| Client reference | OS scale | Nominal DPI | L: hold logical client → physical pixels | P: hold physical client → conservative logical fit |
|---|---:|---:|---|---|
| 1280×680 compatibility | 100% | 96 | 1280×680 → 1280×680 | 1280×680 → 1280×680 |
| 1280×680 compatibility | 125% | 120 | 1280×680 → 1600×850 | 1280×680 → 1024×544 |
| 1280×680 compatibility | 150% | 144 | 1280×680 → 1920×1020 | 1280×680 → 853×453 (floor) |
| 1280×760 comparison | 100% | 96 | 1280×760 → 1280×760 | 1280×760 → 1280×760 |
| 1280×760 comparison | 125% | 120 | 1280×760 → 1600×950 | 1280×760 → 1024×608 |
| 1280×760 comparison | 150% | 144 | 1280×760 → 1920×1140 | 1280×760 → 853×506 (floor) |

This declares 12 L/P design cells (the two 100% pairs coincide) for **all five workflows**, plus actual runtime-mode testing below. P cells are conservative design stresses, not a newly claimed supported minimum. A physical display must have room for chrome in addition to the declared client; if it cannot supply an L cell, mark that cell unavailable on that setup and use the correct P case, never silently shrink the record.

The living style guide records historically unaware Tk/bitmap virtualization and an artificial `tk scaling` font-growth stress. Recheck process awareness when physically testing: unaware bitmap stretching, a genuinely DPI-aware runtime and a simulated font scaling change are **different evidence**. Simulated `tk scaling` is never proof of an OS 150% result. Cross-monitor movement at unlike DPI is an additional unverified stress, not an implied production-awareness migration. C changes no DPI API or platform policy.

## Reflow specification for each declared design cell

1. Budget client height for navigation, wrapping context, persistent warning summary and action strip first; body gets remaining positive height and vertical scrolling. Prototype compact body is 117 logical pixels, baseline body 344; real header/message growth must recompute this, never overlap the strip. The matrix model also reserves a 24-pixel long-label stress allowance; every supplied cell retains a positive body.
2. Side-by-side work/inspection is allowed only when measured natural request widths plus gutters fit. SVG uses 1100 logical pixels as an **illustration breakpoint**; future Tk must measure current font/control requests (as Photo Optimize does), not copy 1100 as universal truth. Below fit, stack existing regions in one vertical flow. Compact compare labels A/B remain visible as each is inspected.
3. Body sections retain natural height in `ScrollableFrame(fill_height=True)`; no weighted row may squeeze an essential section to zero. Focus reveal applies through every containing scroll frame. Wheel at inner limit passes to outer page; pointer-focus does not move a pressed target. No essential form/action depends on horizontal scroll. Large canvas panning is permitted for media coordinates only, with visible Fit/zoom controls.
4. Action buttons retain natural font/padding height, at least proposed 32 units; measure full labels, wrap secondary actions into rows before collision. Primary and relevant refusal summary are always reachable; long diagnostics/details remain vertically available. Tiny clients outside declared cells need graceful scroll, but no unsupported-size guarantee is created.
5. Wrap labels, paths and field/value summaries. Never truncate the only warning, revision, action label or save scope. Long IDs may offer a short display only alongside accessible/copyable full detail. Advanced headers summarize active nondefault values; expanding them leaves the action strip in place and retains focused widget/value.
6. Model/profile selector, authoring, mask toolbar, Storyboard rows, assembly options, study controls and galleries obey the same grammar. Do not solve compact layout by omitting native SVD, Matrix, encoding or special-study routes. Detached windows/dialogs independently fit the owning monitor and return focus; capture their client bounds too.

## Keyboard, focus and accessibility

| Surface | Proposed keyboard/focus requirement | Evidence needed before claim |
|---|---|---|
| Shell | Preserve Ctrl+Tab / Ctrl+PageUp/PageDown and native fallback; Tab order follows visible semantic order. Selected destination has a visible cue and readable HOLD reason | Real key traversal with exact tab identity/startup behavior; no shortcut stealing from multiline prompt entry |
| Fields/disclosure | Tab/Shift+Tab reaches each enabled control; Space/Enter activates the appropriate focused control; disclosure arrow + expanded state visible | Real focus cue, reveal through nested scrollers, current values survive collapse/reflow. Disabled controls explain cause through reachable text |
| Combobox/list/grid | Native keyboard selection, readable selected value/row and separate focus; long values available in detail | Model/profile choose and cancel tested; list paging/selection does not auto-submit or load hidden media |
| Canvas/media | Reach tool chooser, Fit/100%, undo and exit via keyboard; Escape leaves tool capture. Provide an explicit manual alternative for unsupported precision keyboard painting | Physical input trial; no claim that every brush gesture already has keyboard parity. Any essential operation lacking parity is a reported gap before implementation acceptance |
| Dialogs/handoffs | Focus enters sensible non-destructive choice; Escape cancels only that dialog; Tab contained while modal, focus returns to invoker. No global Enter dispatch from text areas | Actual cancellation leaves both contexts/destination unchanged, including selection and navigation; no background focus theft |
| Pending/results | Loading/new result must not steal focus or reset browse position. Explicit validation may move focus to first invalid field with reason | Late-response, hidden-tab and shutdown tests plus real key events; no focus-state-only screenshot substitute |
| Contrast/state | Text and meaningful outlines meet [TOKENS.md](TOKENS.md) floors; words/icons supplement color. Check High Contrast/theme behavior and focus on filled controls | Rendered focused pixels, resolved system colors; static ratios alone are insufficient |
| Screen reader / UI Automation | Expose control name, value, role/state, selected/expanded and associated help/error; warning/error should announce once, status politely without repetition | Actual Windows screen-reader/UIA inspection. Existing SubmissionNotice role/accessible_text is a test contract; the living guide explicitly does **not** claim present screen-reader announcement |

No Qt migration or accessibility bridge is assumed. If native Tk cannot meet an essential named requirement, record the unmet requirement and route the resulting architecture/platform decision to Rob; do not replace the toolkit as a design implementation detail.
