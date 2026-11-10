# Create layout evaluation: scrolling form vs split workspace

Two designs of the same mock Create journey (same components, same session, switchable at run
time via **Layout** in the Create header or `--layout`):

- **A · Scrolling form** (`scroll`): one vertically scrolling column; the Effective settings /
  Preview / Mock result card is the last block of the form.
- **B · Split workspace** (`split`, default): authoring column on the left, a persistent
  summary + preview-state + preview + result pane on the right (own scrollbar).

Both keep the action strip (Undo, Redo, Reset, Build mock preview, Simulate admission) fixed below.

## Method

`tools/layout_audit.py` shows a real window per case and measures with `layout_probe.py`:
reachability (every required control scrolled into view and not clipped), horizontal overflow,
scroll distance and scroll actions along a fixed 6-step task path (source → prompt → model → steps →
preview → admit), what stays visible without scrolling, and the Tab chain (required controls reached,
focus never out of view, preview reached before the actions that build it). Each case is measured
**fresh** and **primed** (one manual override + a current ready preview, so Undo, Reset-unlocked and
Simulate admission are enabled).

Evidence (native Windows, Python 3.14.9 / PySide6 6.12.0): `evidence/layout_audit_native_blue-modern.{md,json}`
(1280×680, 960×600, 1440×900, 1920×1080 × dock expanded/collapsed × both layouts × both states = 32
cases), `evidence/layout_audit_native_concept-a.*` (16), and `evidence/layout_audit_SIMULATED-scale-1.5_blue-modern.*`
(16, **simulated**). Screenshots: `screenshots/qt-ds-01/`.

**Display reality.** The only display used is an ASUS VG32VQ1B, 2560×1440, devicePixelRatio 1.0,
96 DPI. Everything labelled *native* is therefore **100% scaling**. The 1.5× run uses
`QT_SCALE_FACTOR` (the audit records `devicePixelRatio 1.5` as emulated); it is **not** evidence of a
real 150% Windows display. Real per-monitor 125/150% and mixed-DPI were not run.

## Results (blue-modern, native, primed state)

| Case | Design | Form viewport | Form content (screens) | Settings cols | Summary + preview state visible without scrolling | Scroll actions on task path | Review pane |
|---|---|---|---|---|---|---|---|
| **1280×680, Output Display open** | A scroll | 656×402 | 6.77 | 3 | **no** | 2 | – |
| | B split | 407×402 | 6.05 | 1 | **yes** | 3 | 229×402 |
| 1280×680, Output Display collapsed | A | 980×427 | 6.00 | 4 | no | 2 | – |
| | B | 647×427 | 4.86 | 3 | yes | 2 | 313×427 |
| **960×600 stress, display collapsed** | A | 660×322 | 8.45 | 3 | no | 3 | – |
| | B | 411×322 | 7.56 | 1 | yes | 3 | 229×322 |
| 960×600 requested, display open | both | window clamped to 1192×600 by the minimum size (so 960 is only reachable collapsed) | | | | | |
| 1440×900, display open | A / B | 816×622 / 537×622 | 4.12 / 3.47 | 4 / 2 | no / yes | 2 / 2 | B: 259×622 |
| 1920×1080, display open | A / B | 1279×827 / 847×827 | 3.10 / 2.31 | 4 / 4 | no / yes | 2 / 2 | B: 424×827 |

Across all 64 audited cases (both themes and the simulated-scale run) there were **0 unreachable
required controls, 0 horizontal overflows, 0 required controls missing from the Tab chain, 0 focus
positions out of view**, and the preview was reached before the actions in every Tab walk; the
window's minimum size hint always fit the window. Task path in both designs is 2–3 scroll actions at
1280×680. The `concept-a` theme gave the same geometry (1280×680: 6.77 / 6.05 screens).

Shell chrome (window height minus the form viewport) is **278 px of 680 (41%)** with the Output
Display open at 1280×680 (253 px, 37%, collapsed) and **278 px of 600 (46%)** at the stress size.

## Findings

1. **Neither design is comfortable at 1280×680 with the Output Display open.** The form is 6 screens
   tall and the settings fall to one column in B. The measured cause is chrome (header, banner,
   action strip, status bar ≈ 41% of the height) plus the 380 px dock, not the form itself.
2. **B keeps the decision information in view.** Summary, preview-state chip, stale reason and result
   stay visible while authoring; in A they are below ~6 screens of form. A's advantage is width: 3–4
   settings columns instead of 1 and fewer scroll actions on the task path at some sizes.
3. **B's cost is a narrow review pane** (229 px at 1280×680 with the dock open): the preview text
   wraps heavily and the pane scrolls ~1.9 screens. This is the main open design issue for B.
4. At the **960×600 stress case** (display collapsed only) both remain reachable and unclipped, but
   the form is 7.6–8.5 screens, which is a usability warning rather than a pass for comfortable use.
5. Defects the audit caught and fixed during development (kept as regression tests): focus landing
   on controls scrolled out of view (now revealed on focus), multi-line editors trapping Tab,
   segment-button labels clipping when bold, advanced-section headers widening the form, the preview
   being out of Tab order in A, and the result of a simulated admission landing off-screen.

## Decision for QT-DS-01

Keep **B (split workspace) as the default** for further design work because it keeps the decision
surface visible, and keep A switchable as the comparison baseline. This is a **design preference from
measurements and screenshots, not an operator-validated decision**: no operator timed a task, no
task-completion or error-rate data exists, and the numbers above are on one 2560×1440 display at 100%.

Before B can be called good: reduce shell chrome, move or fold the Output Display into the review pane
(or let it share the right column) so the review pane is wider than ~230 px at 1280×680, and re-measure.
