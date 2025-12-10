PR-GUI-H – Window Management & Layout Fixes (V2.5).md
1. Metadata

PR ID: PR-GUI-H – Window Management & Layout Fixes (V2.5)

Group: GUI Wishlist – Group H (Window sizing & layout fixes)

Risk Tier: Tier 1 – Light (GUI layout & containers only; no pipeline/queue logic)

Subsystems:

GUI V2 – Main window shell

GUI V2 – Pipeline tab three-column layout

GUI V2 – Stage panels & layout helpers

Related Canonical Docs / PRs:

Rewritten GUI Wishlist PR Plan (V2.5) – Group H definition

Prior layout/scroll work:

PR-021 – GUI V2 Tabs Three-Column Layout (V2-P1)

PR-036 – Pipeline Tab 3-Column Layout (V2-P1)

PR-05_Layout_and_Resizing_V2 (historical reference only)

PR-05A_Scrollable_Areas_V2 (historical reference only)

Design system & card structure:

PR-041 / PR-041A – Design System & Full V2 GUI Design System

PR-06A/06B/06C – BaseStageCardV2 + stage migrations

2. Intent / Summary

Make the StableNew main window and Pipeline tab consistently usable at first launch by fixing window sizing and column layout:

The app should open wide enough to show all three pipeline columns (Config, Preview/Queue, Job/Status) without immediate horizontal crunching.

Each of the three main pipeline columns should be structured around exactly one scrollable container, with all cards and panels nested inside that container.

Card nesting and margins should be consistent across columns, matching the V2 design system (BaseStageCardV2, design tokens).

No behavior changes to queue, pipeline execution, randomizer, or run controls—this PR is structure/layout only. Scroll behavior (focus, mousewheel routing) is explicitly left for Group L.

3. Problem Statement

Current UX issues (as observed and captured in the GUI wishlist):

Window width at startup

The app sometimes opens in a narrow or inherited size that truncates the three-column layout, forcing manual resize before the UI is usable. The “happy path” should be: launch → see all three pipeline columns without fiddling.

Inconsistent column containers

Different columns use slightly different nesting (direct packing of cards vs. nested frames vs. ad-hoc scroll regions).

Some scrollable areas are per-card instead of per-column, causing strange scrollbars and wasted vertical space.

Card nesting & margins

Cards are not always nested uniformly inside column containers, leading to misaligned shadows, padding, and inconsistent vertical rhythm vs. the design system.

This is purely a layout / container / geometry issue. The goal is to give the pipeline tab a reliable “three-column dashboard” feel on first open and during resize, using consistent structural patterns.

4. Scope
4.1 In Scope

Default window geometry & min width

Define a sensible default window geometry on app launch that reliably shows all three pipeline columns on a typical 1080p display.

Ensure the window has reasonable minsize so the user cannot resize it into a layout where columns collapse or stack in unpredictable ways.

Three-column container structure

For the Pipeline tab:

Enforce a single scrollable container per main column, with all cards/panels nested under it.

Align column grid/pack usage with PR-021/PR-036 three-column patterns (equal column weights, consistent padding).

Card nesting consistency

Ensure that stage cards (BaseStageCardV2 and friends) live inside column content containers using a uniform pattern:

Column root → scrollable frame → vertical card stack → card → panel content.

Resizing behavior (structural only)

When the user resizes horizontally:

Columns should maintain relative width balance.

When the user resizes vertically:

Scrollbars should appear in the column scroll containers, not ad-hoc inside individual cards.

4.2 Out of Scope / Non-Goals

Scroll behavior normalization (mouse wheel routing, focus, “scroll column under cursor”):

Defer to PR-GUI-L – Scroll Behavior Normalization.

Queue & Run Controls behavior:

No changes to queue execution, run modes, auto-run, or button semantics (covered by F1/F2/F3 and pipeline PRs).

Visual theming / colors:

Only adjust padding, spacing, and container selection where required for layout. Palette and typography remain governed by theming PRs (Group A, PR-041 family).

Validation field removal:

Already assigned to PR-GUI-B – Remove Empty Validation Fields; do not touch those fields here.

5. Design / Approach
5.1 Default Window Geometry

Introduce a centralized geometry helper or configuration constant used by the main window:

Define DEFAULT_MAIN_WINDOW_WIDTH and DEFAULT_MAIN_WINDOW_HEIGHT (e.g., tuned to show three columns on 1080p with room for OS chrome).

Set a minimum width (MIN_MAIN_WINDOW_WIDTH) equal to or slightly less than the default to prevent column collapse.

On first launch:

If there is no persisted last-window size, apply default geometry.

If last-window size exists (future enhancement / existing behavior), prefer that but clamp to a minimum width/height.

5.2 Column Containers & Scroll Frames

For the Pipeline tab frame:

Use 3 top-level column containers (e.g., left_column, middle_column, right_column) with:

grid_columnconfigure weights (1, 1, 1) at the tab level.

Consistent horizontal padding/gaps between columns.

Within each column:

Replace any per-card scrollbars with a single ScrollableColumnFrame pattern:

ColumnContainer (grid/pack in tab)
→ ColumnScrollCanvas + vertical scrollbar
→ ColumnInnerFrame (actual card stack).

All stage cards, preview/log cards, and queue/run cards attach to ColumnInnerFrame using a single stacking direction (e.g., pack(side="top", fill="x", pady=… ) or equivalent).

5.3 Card Nesting Contract

Align cards with the existing BaseStageCardV2 and design system:

Every stage/section card in the pipeline tab should follow:

ColumnInnerFrame → BaseStageCardV2 (or card wrapper) → stage/panel content.

Remove any ad-hoc “card-like” frames layered inside other cards; use the canonical card for shadow/border/background.

Margins & padding:

Standardize vertical spacing between cards in a column (e.g., same pady).

Ensure left/right padding matches design system tokens so columns line up visually with other tabs.

5.4 Resizing Behavior

Horizontal resize:

Keep equal weights so columns grow/shrink together.

Avoid hardcoded widths that cause one column to starve the others.

Vertical resize:

Columns grow with the window until they hit the natural content height, then scrollbars take over.

No nested scroll regions inside single cards for basic pipeline usage (special cases like deeply nested logs/trace panels are out of scope here).

6. Files

Note: Paths inferred from repo_inventory.json and GUI docs; adjust if the snapshot differs in minor naming.

6.1 Allowed / Expected to Change

Main window / layout shell

src/gui/main_window_v2.py

Apply default geometry / minsize and hook into any existing “restore last size” logic if present.

Pipeline tab layout

src/gui/views/pipeline_tab_frame_v2.py (or current equivalent)

Enforce three consistent column containers and a scrollable column pattern.

Column/panel layout helpers

src/gui/panels_v2/layout_manager_v2.py (or similar helper if present)

If layout helpers already exist, extend them with reusable “three-column” and “scrollable column” patterns.

Any per-column container classes under src/gui/panels_v2/ that currently own the actual stack of stage cards or preview/queue cards.

Optional new helpers

New module under src/gui/panels_v2/ or src/gui/widgets/ (e.g., scrollable_column_frame_v2.py) if no suitable reusable scroll frame exists.

Tests

New or updated GUI layout tests under:

tests/gui/test_window_layout_normalization.py (new)

Or an appropriate existing GUI V2 test module if one already covers main window layout.

6.2 Allowed but Use Sparingly

src/gui/theme_v2.py

Only if strictly necessary for shared spacing constants (e.g., design-token imports). No color/palette changes.

6.3 Explicitly Out of Scope / Forbidden for This PR

Controller / pipeline / queue core:

src/controller/pipeline_controller.py

src/pipeline/*.py (runner, job models, queue service)

Learning, randomizer, or job history code.

Any file that changes execution semantics of runs, queue jobs, or API calls.

7. Implementation Plan (Step-by-Step)

Survey existing layout

Inspect main_window_v2.py and pipeline_tab_frame_v2.py to document current:

Default geometry behavior (if any).

Column container structure and grid/pack configuration.

Existing scroll regions and where they live (per column vs per card).

Define geometry constants

Add constants (either in main_window_v2.py or a small gui/constants_v2.py module):

DEFAULT_MAIN_WINDOW_WIDTH

DEFAULT_MAIN_WINDOW_HEIGHT

MIN_MAIN_WINDOW_WIDTH

MIN_MAIN_WINDOW_HEIGHT (optional).

Use these in the main window initialization:

If last-run dimensions not available, call geometry(f"{DEFAULT_MAIN_WINDOW_WIDTH}x{DEFAULT_MAIN_WINDOW_HEIGHT}").

Apply minsize(MIN_MAIN_WINDOW_WIDTH, MIN_MAIN_WINDOW_HEIGHT).

Normalize pipeline tab three-column grid

In pipeline_tab_frame_v2.py:

Ensure there are three high-level column containers for the pipeline tab content.

Apply grid_columnconfigure with equal weights and consistent padding.

Remove any legacy layout code that conflicts (e.g., old “two-column plus sidebar” remnants).

Introduce or reuse a scrollable column widget

Check for existing reusable scroll frames (e.g., from PR-05A). If present, adapt for column usage.

Otherwise, implement ScrollableColumnFrame:

Canvas + scrollbar wrapper with an inner frame.

Expose a simple API: add_card(widget) or “expose inner frame for packing”.

Refactor each column to a single scrollable container

For each of the three columns:

Instantiate a ScrollableColumnFrame.

Move all card packing into the scrollable column’s inner frame.

Remove per-card scrollbars or nested scroll frames unless they are a special-case (e.g., deeply nested log view; call out exceptions in comments).

Align card nesting with BaseStageCardV2

Ensure all stage/section content uses the standard card contract:

Column inner frame → card → content.

Fix any ad-hoc frames that break shadows, borders, or consistent padding.

Use shared spacing constants from design system where possible (no ad-hoc magic numbers if a token exists).

Tune resizing behavior

Verify that:

Horizontal resize keeps columns aligned, without one collapsing disproportionately.

Vertical resize uses column scrollbars appropriately.

Adjust grid_rowconfigure/weight and container sticky options to reach desired behavior.

Guard against functional regressions

Confirm that all pre-existing widgets (buttons, dropdowns, labels, run controls, preview, queue) are still reachable and still in the same logical columns.

No event bindings or commands should be changed; this is a layout refactor only.

Wire tests

Add/extend GUI tests to assert:

On startup: default window size meets or exceeds MIN_MAIN_WINDOW_WIDTH.

Pipeline tab has three column containers with scroll frames.

In test harness, programmatically add enough dummy content to trigger vertical scrollbars and verify they appear on column scroll frames, not individual cards.

Documentation & changelog

Update docs and CHANGELOG as described in Section 9.

8. Testing Strategy
8.1 Automated Tests

New GUI layout test module (recommended):
tests/gui/test_window_layout_normalization.py

Scenarios:

Default geometry applied when no saved state exists

Launch GUI in a fresh test environment.

Assert the reported window width ≥ MIN_MAIN_WINDOW_WIDTH.

Assert the initial size roughly equals DEFAULT_MAIN_WINDOW_WIDTH/HEIGHT (within a small tolerance if the toolkit normalizes).

Three-column grid present

Navigate to Pipeline tab.

Assert:

Exactly three top-level column containers (or proxies) are configured.

Each column has a scrollable inner frame (verify presence of canvas + scrollbar + inner frame pattern).

Column scrollbars vs per-card scrollbars

Inject enough synthetic content into at least one column.

Verify:

Column scrollbar becomes active.

No additional scrollbars are created inside individual stage cards for that column.

Resizing behavior

Programmatically resize the main window to be larger and smaller (down to minsize).

Assert:

Columns maintain relative widths (within a tolerance).

Scrollbars continue to function.

Where direct Tkinter GUI testing is difficult in CI, use:

Existing GUI test harness or a “headless Tk” pattern established in prior PRs (e.g., PR-021/PR-051 GUI tests).

8.2 Manual / Journey Testing

Add a short checklist for manual smoke testing:

Launch StableNew → verify:

Window opens at a width that visibly shows all three pipeline columns.

Switch to Pipeline tab:

Confirm each column has a single scroll region (scrolling lists of cards).

Add extra content (e.g., expand panels, adjust advanced options) until scrolling is required:

Confirm scrollbars appear only at column level.

Resize window:

Shrink until minsize stops further shrinking; confirm columns don’t collapse into unusable layouts.

Expand to near full screen; confirm columns still visually balanced.

9. Documentation & Changelog Requirements

This PR must update documentation and the changelog:

Rewritten GUI Wishlist PR Plan (V2.5)

Mark Group H items as “covered by PR-GUI-H” in the appropriate section (or add a short status note).

GUI Architecture / Layout Docs

If there is a GUI structure section in ARCHITECTURE_v2.5.md or a related GUI/V2 doc, add:

A brief description of the three-column layout contract.

The “one scrollable container per column” rule.

Reference to ScrollableColumnFrame (or equivalent) as the canonical pattern.

CHANGELOG.md

Add an entry under the appropriate date, e.g.:

[PR-GUI-H] Window Management & Layout Fixes (V2.5) – Introduced default window geometry and normalized the Pipeline tab’s three-column layout to use a single scrollable container per column, improving first-launch usability and resize behavior.

Include file paths touched (high level) in the entry, per project rules.

10. Rollback Plan

If issues are discovered (e.g., broken layout on some displays, regressions in column visibility):

Config-level rollback

Revert geometry defaults to the previous behavior (e.g., “no explicit default size, let toolkit decide”) via a single commit that removes/neutralizes DEFAULT_MAIN_WINDOW_* usage.

Layout-level rollback

Reintroduce the prior pipeline tab layout containers and scroll behavior by:

Keeping the new scrollable column helper, but restoring old packing for the columns; or

Fully restoring the prior version of pipeline_tab_frame_v2.py from Git history.

Safe intermediate state

Ensure that, in the worst case, the app still launches and all controls remain reachable (even if layout is sub-optimal). Do not introduce a state where a broken layout prevents access to Queue/Run controls or core config.

Tests

If rollback is necessary, temporarily skip or adjust the most strict layout tests, but maintain at least a minimal “app boots and pipeline tab loads” test to avoid regressions in future work.