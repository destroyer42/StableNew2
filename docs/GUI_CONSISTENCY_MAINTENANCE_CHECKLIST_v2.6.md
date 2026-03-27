# GUI Consistency Maintenance Checklist v2.6

Status: Active  
Updated: 2026-03-26  
Authority tier: Tier 3 (Subsystem Reference)

## 1. Purpose

This checklist turns the `PR-UX-272` through `PR-UX-279` GUI consistency sweep
into a lightweight maintenance standard for future GUI work.

Use it when adding or materially changing:

- tabs and major panels
- stage cards and panel composites
- dialogs, inspectors, and helper windows
- long-text or metadata-heavy surfaces
- workspace layouts with resize-sensitive controls

## 2. Scope

This is a maintenance checklist, not a replacement for:

- `docs/GUI_Ownership_Map_v2.6.md`
- `docs/GUI_AUDIT_AND_CONSISTENCY_INVENTORY_v2.6.md`
- active architecture and coding standards documents

Its job is narrower:

- keep dark-mode compliance complete
- preserve usable minimum widths and resize behavior
- prevent long content from hiding controls
- make secondary surfaces match the quality bar of primary tabs

## 3. Merge Checklist

Before merging GUI work, verify:

### 3.1 Dark-mode compliance

- No new panel, dialog, or helper surface ships with light-theme leftovers.
- New `Toplevel` windows use shared theming helpers such as
  `apply_toplevel_theme(...)`.
- Raw `Text`, `Canvas`, `Listbox`, or similar widgets are styled through shared
  helpers instead of hard-coded colors.
- New colors are not hard-coded in panel modules when shared tokens already
  exist.

### 3.2 Minimum widths and geometry

- Main workspaces respect shared layout minimums and column contracts.
- New dialogs/inspectors declare explicit starting geometry and a usable
  `minsize(...)`.
- Dense control rows keep critical actions, selectors, and entries visible at
  normal working widths.

### 3.3 Resize behavior

- Panels resize predictably without overlapping rows or collapsing action bands.
- Controls that must stay visible are protected by layout contracts or explicit
  row/column discipline.
- Shrinking the window does not make core actions inaccessible.

### 3.4 Long-content handling

- Long prompts, metadata, model names, and JSON payloads are handled with:
  - wrapping for label-style summaries, or
  - horizontal/vertical scrolling for inspectable raw content, or
  - structured multi-row layouts where a single row would hide controls
- Raw JSON or manifest viewers do not rely on soft wrapping alone when
  horizontal inspection matters.

### 3.5 Secondary-surface parity

- Dialogs, inspectors, compare views, and helper windows meet the same dark-mode
  and resize expectations as primary tabs.
- Secondary surfaces with tables, trees, or long text expose scrollable
  overflow where needed.

### 3.6 Test coverage

- Existing focused GUI regressions are updated when behavior changes.
- New high-value GUI surfaces add at least one targeted regression when there is
  no equivalent coverage already.
- Changes that alter layout contracts update the relevant contract or resilience
  tests in the same PR.

### 3.7 Docs housekeeping

- New active GUI standards or reference docs are added to
  `docs/DOCS_INDEX_v2.6.md` in the same PR.
- If a backlog PR becomes completed, its completion record is created in
  `docs/CompletedPR/`.

## 4. Representative Regression Anchors

These tests are the minimum regression anchors to consult before adding new GUI
layout/theme work:

- `tests/gui_v2/test_theming_dark_mode_v2.py`
- `tests/gui_v2/test_window_layout_normalization_v2.py`
- `tests/gui_v2/test_workspace_layout_resilience_v2.py`
- `tests/gui_v2/test_gui_consistency_maintenance_v2.py`

Additional surface-specific tests should still be updated when the touched UI
already has focused coverage.

## 5. Practical Rules of Thumb

- Prefer shared theme and layout helpers over local one-off fixes.
- Prefer scrollable overflow to clipped controls.
- Prefer explicit `minsize(...)` for utility windows over assuming the OS window
  manager will keep them usable.
- If a new surface needs a manual exception to the shared rules, document why in
  the PR and add a targeted test for the exception.
