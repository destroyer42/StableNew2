# Motion Storyboard layout alternatives and measurements

Two arrangements of the **same** widgets over the **same** `MotionSession` are compared. Switching
between them (header selector *A · Shot strip* / *B · Timeline*) rebuilds only the Storyboard panel; the
selected shot, review status and every draft value survive (`test_layout_b_keeps_the_same_state_and_actions`).

| | **A · Shot strip (primary)** | **B · Timeline inspector** |
|---|---|---|
| Top | Tool row, then **thumbnail shot cards** (wrapping), then a thin duration timeline | Tool row, then viewer + inspector side by side |
| Middle | Viewer (left) + inspector tabs (right) | Detailed duration timeline with dependency labels |
| Bottom | – | Compact (thumbnail-less) shot cards |
| Strength | Cards carry thumbnail, identity, frames, basis and validity; the selection sits directly above its inspector | Relative durations and dependencies are legible |
| Cost | Taller card row | ≈ 170 px of height for timeline + cards |

**Primary: A.** It needs half the page scrolling at the smallest supported size and shows more per shot.
B is kept selectable (`--motion-layout timeline`) as the comparison and for timeline-focused review.

## Method

`python tools/layout_audit.py --motion-layouts strip timeline --motion-states quick story movie
--sizes 960x600 1280x680 1366x768 1440x900 1920x1080 --theme <theme>` on the **native Windows Qt
platform** (not offscreen), Python 3.14.9, PySide6 6.12.0, primary screen DPR 1.0. The probe measures,
per size: actual client size (never clamped), viewer and inspector sizes, how many of six shot cards are
fully visible without scrolling, persistent controls clipped by any non-page-scroll ancestor, vertical
page scroll needed, **horizontal overflow of every scroll area**, controls shrunk below their minimum size
hint, and the Tab chain (every enabled, visible control reachable, none missing).

Evidence: [`evidence/motion_native_blue-modern.md`](evidence/motion_native_blue-modern.md),
[`evidence/motion_native_concept-a.md`](evidence/motion_native_concept-a.md) (+ `.json`) and a
**simulated** 1.5× run
[`evidence/motion_SIMULATED-scale-1.5_blue-modern.md`](evidence/motion_SIMULATED-scale-1.5_blue-modern.md).

## Results (Storyboard, six shots, blue-modern; concept-a is identical to the pixel counts)

| Size | Layout | Viewer | Inspector | Cards fully visible | Page scroll | Horizontal overflow | Shrunk controls | Clipped persistent controls |
|---|---|---|---|---|---|---|---|---|
| 960×600 | A | 341×200 | 383×200 | 6/6 | 42 px | none | 0 | none |
| 960×600 | B | 341×200 | 383×200 | 6/6 | 84 px | none | 0 | none |
| 1280×680 | A | 497×228 | 559×228 | 6/6 | 0 | none | 0 | none |
| 1280×680 | B | 497×246 | 559×246 | 6/6 | 0 | none | 0 | none |
| 1366×768 | A | 537×316 | 605×316 | 6/6 | 0 | none | 0 | none |
| 1366×768 | B | 537×334 | 605×334 | 6/6 | 0 | none | 0 | none |
| 1440×900 | A | 570×448 | 641×448 | 6/6 | 0 | none | 0 | none |
| 1440×900 | B | 570×466 | 641×466 | 6/6 | 0 | none | 0 | none |
| 1920×1080 | A | 772×628 | 868×628 | 6/6 | 0 | none | 0 | none |
| 1920×1080 | B | 772×646 | 868×646 | 6/6 | 0 | none | 0 | none |

Quick Clip and Movie Clips (one layout each) have no horizontal overflow, no shrunk or clipped controls and a
complete Tab chain at all five sizes in both themes; at 960×600 each needs 79 px of page scrolling.
Both Storyboard layouts have 33 tab stops, none missing. With eight shots at 1366×768, A wraps to two
rows (31 px page scroll) and all eight cards stay fully visible.

## What changed because of the measurements

- Chrome at 960×600 consumes ~250 px, so the workspace sits in **one vertical scroller**; the persistent
  action strip stays outside it and always visible. Horizontal scrolling is never used.
- The context card is one row when wide and two when narrow; long values elide with a tooltip.
- Shot-card labels elide instead of wrapping so the strip height is exact; the strip is sized to its
  wrapped rows rather than clipped (found because the first strip showed only cut-off thumbnails).
- Minimum viewer height (200 px) keeps the playback controls from overlapping the frame.
- Tool buttons use short labels with full tooltips and wrap in a `ResponsiveGrid`.
- A *Disclosure* title was shortened after the probe reported 12 px of Quick Clip overflow; the
  assembly buttons moved to a `ResponsiveGrid` after 7 px of Movie Clips overflow.
- Fonts and control heights were **not** reduced anywhere: the `shrunk_controls` column is 0.

## Screenshots

`screenshots/qt-ds-04/motion_<theme>_story_<strip|timeline>_<size>.png` for the five sizes in both themes,
plus `motion_<theme>_quick_<size>.png` and `motion_<theme>_movie_<size>.png` at 960×600 and 1366×768.
Representative: [A at 1366×768](screenshots/qt-ds-04/motion_blue-modern_story_strip_1366x768.png),
[B at 1280×680](screenshots/qt-ds-04/motion_concept-a_story_timeline_1280x680.png),
[A at 960×600](screenshots/qt-ds-04/motion_blue-modern_story_strip_960x600.png).

## Scaling

The audit host reports DPR 1.0. The 1.5× run sets `QT_SCALE_FACTOR` and is **simulated**; it shows no
overflow at 1280×680 and 1366×768 but is not evidence of real Windows 125 %/150 % scaling, which remains
**unverified** until a suitable display is available.
