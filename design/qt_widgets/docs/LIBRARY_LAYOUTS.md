# Asset Library layout evaluation (QT-DS-05)

Two arrangements of the **same widgets** (`LibraryView._arrange`) were compared natively on Windows at the
five required client sizes, in both reference themes, in grid and list view, with a 148-record and a
1,528-record fixture catalog, in four states (browse, 3 selected, filters active, Organize tab open).
Each case is a real `PrototypeWindow`, resized and measured by `layout_probe.probe_library`; nothing is
submitted or written except the evidence files.

| | **A · Gallery-first** | **B · Adaptive browser** |
|---|---|---|
| Regions | scope list \| filters + grid + selection strip \| tabbed inspector (always visible) | compact top bar (search, sort) over grid + strip; filters behind a **Filters** disclosure; details in a collapsible **drawer** |
| Scope picker | persistent left column (list with counts) | compact scope combo in the top bar |
| Filters | three rows always visible | collapsed by default, one click to open |
| Inspector | tabs: Details · Actions · Organize | same tabs, in the drawer (open by default; Details ▸/◂ toggles it) |
| Narrow (< 940 px) | inspector becomes its own page; **Browse / Inspector** switch | same |

## Decision

**Default: B · Adaptive browser.** A is kept, selectable (**A · Gallery-first** in the header, or
`--library-layout gallery`), as the comparison.

Why, from the measurements (blue-modern; concept-a is identical to the pixel counts below):

- At **1280×680** (the project's working minimum) B shows **9 tiles in 3 rows** in a 724×349 media area;
  A shows **4 tiles in 2 rows** in 501×216 — the three filter rows (150 px) plus the persistent scope column
  leave A's grid short and narrow.
- At **1366×768** B shows 15 tiles (3 rows) vs 9 tiles in A; at **1440×900** 20 vs 12; at **1920×1080** both
  show 24 tiles (4 rows). A only catches up when the screen is large.
- At **960×600** both fall back to the Browse/Inspector page switch; B's grid is 269 px tall vs A's 165 px.
- B pays for it when filters are opened: with filters open B's grid at 1280×680 is 245 px (6 tiles), still
  taller than A's 216 px, so the disclosure never makes B worse than A at the same size.
- Cost of B: the scope list is a combo, not a persistent column. Operators who switch scope constantly and
  work on large displays may prefer A (at 1440×900 and above A's grid is within a row of B's).

## Measurements (native, `docs/evidence/library_native_blue-modern.md` and `…concept-a.md`)

Grid view, small catalog, browse state. "Tiles" are fully or partly visible without scrolling.

| Client size | A tiles (rows) | A media area | A filters h | B tiles (rows) | B media area | B filters h | Inspector |
|---|---|---|---|---|---|---|---|
| 960×600 | 6 (2) | 732×165 | 96 | 6 (2) | 732×269 | 0 | own page |
| 1280×680 | 4 (2) | 501×216 | 150 | 9 (3) | 724×349 | 0 | 320 px |
| 1366×768 | 9 (3) | 587×329 | 150 | 15 (3) | 810×437 | 0 | 320 px |
| 1440×900 | 12 (4) | 656×515 | 96 | 20 (4) | 879×569 | 0 | 320 px |
| 1920×1080 | 24 (4) | 1097×695 | 96 | 24 (4) | 1320×749 | 0 | 320 px |

### Audit summary

| Run | Cases | Clipped controls | Text clipped | Shrunk controls | Missing Tab stops | Actions unreachable | Max widgets | Max thumbnails decoded |
|---|---|---|---|---|---|---|---|---|
| Native `blue-modern` | 160 | 0 | 0 | 0 | 0 | 0 | 301 | 21 |
| Native `concept-a` | 160 | 0 | 0 | 0 | 0 | 0 | 301 | 21 |
| **SIMULATED** 1.5× `blue-modern` | 8 (4 clamped by the screen) | 0 | 0 | 0 | 0 | 0 | 301 | 21 |

Native timing (this machine, one run each; treat as order of magnitude): full `refresh()` median
12 ms for the 148-record catalog and 15 ms for the 1,508-record catalog
(maxima 51 / 61 ms); next-page-and-back median 13 / 15 ms.


## Reading the numbers

- **Reachability:** every control the task needs (layout switch, search, mode, sort, grid/list, paging, clear
  filters, selection Clear/Organize/Actions, all filters) stayed inside its parents at every size, and with a
  selection the Actions entry plus a way to the inspector was always visible.
- **Tab chain:** the walk from the results reached every enabled, focusable required control in every case.
- **Text clipping:** the probe compares each visible combo/button text with its width. It exists because
  an earlier layout pass showed "Any collectio" and "Any availabil" clipped; those texts were shortened and
  the count is now 0 everywhere.
- **Bounded work:** the widget count stays ≈ 300 for a 148-record and a 1,528-record catalog (the model
  holds one 24-row page and tiles are painted by a delegate); first paint decodes ≤ 21 thumbnails; hidden,
  missing and unsupported records were refused by the media gate (requests counted as blocked, never decoded; the native tests prove it with a recording decoder).
- **Responsiveness:** a full `refresh()` (scope counts, filter values, page model, selection, details) and a
  next-page-and-back flip both take tens of milliseconds on this machine (table above).

## Screenshots

`docs/screenshots/qt-ds-05/` — layouts A and B × 960×600, 1280×680, 1366×768, 1440×900, 1920×1080 (blue-modern,
browse and selected), both themes at 1280×680 and 1440×900, grid and list, the Organize tab, the negative
states (no matches, loading, read error, no favorites, blocked selection), the review, replace-unsaved-work,
Movie Clips order, Learning proposal, inspect and compare dialogs, the Edit handoff with the return button,
and the Component Library page in both themes.

## Limits of this evaluation

- Default layout was chosen from geometry (how much of the result set is visible and whether every control
  stays reachable), not from operator task timing; no operator took part.
- Fonts and DPI are this machine's (100%). The `SIMULATED-scale-1.5` file uses `QT_SCALE_FACTOR` and is not a
  real 150% display; real mixed-DPI was not run.
- Thumbnails are four packaged illustrations, so tile cost reflects layout and painting, not image decoding
  of real files.
