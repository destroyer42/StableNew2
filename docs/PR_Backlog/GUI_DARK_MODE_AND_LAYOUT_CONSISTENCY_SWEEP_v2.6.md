# GUI Dark Mode and Layout Consistency Sweep v2.6

Status: Proposed  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: all major GUI panels, tabs, cards, dialogs, resize behavior, dark-mode consistency, hidden-label/control prevention

## 1. Purpose

StableNew now has enough GUI surface area that visual consistency and layout
resilience need to be treated as a cross-cutting product quality effort, not as
isolated one-off fixes.

This sweep is intended to systematically address:

- dark mode inconsistencies across tabs, cards, dialogs, and secondary surfaces
- inconsistent resize behavior across GUI panels
- widgets shrinking below usable visibility
- labels or controls being hidden or crowded out
- inconsistent row/column weight behavior
- long content causing adjacent controls to disappear

## 2. Goal

Create a consistent GUI baseline where:

- all major panels render correctly in dark mode
- resize behavior is predictable and consistent
- no critical label, entry, slider, selector, or action button becomes hidden at
  normal working window sizes
- long content is handled through truncation, wrapping, or row restructuring
- a reusable layout discipline exists so future panels do not regress

## 3. Guiding Principles

- fix the system, not just individual symptoms
- define reusable layout rules and widget minimums
- preserve visibility of critical controls over dense packing
- dark mode must be complete, not partial
- prefer scrollable overflow and structured multi-row layouts over hidden controls
- help surfaces and settings descriptions should remain readable in dark mode

## 4. Sweep Strategy

The work should be done in a staged sequence rather than one giant risky PR.

### Stage A - Audit and baseline inventory

Perform a GUI-wide audit of:

- major tabs
- settings/stage cards
- prompt surfaces
- review/learning surfaces
- video panels
- popups/dialogs/inspectors
- reusable widgets

For each, capture:

- dark mode correctness
- resize behavior
- hidden/collapsed controls
- long-label/content failures
- likely shared root causes

### Stage B - Shared theming and layout rules

Define cross-cutting rules for:

- dark-mode color/token usage
- minimum widths for common control types
- row/column weight discipline
- truncation/wrapping rules
- slider + numeric-entry composite behavior where needed
- dialog/panel scrollability expectations

### Stage C - Targeted panel remediation

Apply fixes panel-by-panel using the shared rules.

### Stage D - Regression-proofing

Add targeted tests/checks and a reusable checklist so future panels stay aligned.

## 5. Recommended PR Sequence

### PR-UX-272-GUI-Audit-and-Consistency-Inventory

Status: Completed 2026-03-25

Purpose:

- perform a structured inventory of all major GUI panels and identify dark-mode,
  resizing, and hidden-control issues

Primary outcomes:

- inventory of major GUI surfaces
- issue list by panel/tab/dialog
- classification of shared root causes vs one-off defects
- prioritized remediation map

Recommended coverage:

- Pipeline
- Prompt
- Review
- Learning
- Staged Curation
- Video surfaces
- settings/stage cards
- dialogs and inspector windows

Primary file targets:

- docs/report artifact for the audit
- light code touchpoints only if tiny instrumentation is needed

Execution gate:

- there is one structured audit artifact identifying which GUI surfaces still fail
  dark-mode or layout expectations

Completion record:

- `docs/GUI_AUDIT_AND_CONSISTENCY_INVENTORY_v2.6.md`
- `docs/CompletedPR/PR-UX-272-GUI-Audit-and-Consistency-Inventory.md`

### PR-UX-273-Shared-Dark-Mode-Tokens-and-Widget-Theme-Discipline

Status: Completed 2026-03-25

Purpose:

- standardize dark-mode rendering across shared widgets and panel surfaces

Primary outcomes:

- define or consolidate shared dark-mode colors/tokens/styles
- eliminate light-theme leftovers in panels, cards, dialogs, and helper widgets
- ensure text, borders, backgrounds, and hover/help surfaces are readable in dark mode

Primary file targets:

- shared GUI theme/style helpers
- reusable widget modules
- panel modules that bypass shared theme rules

Execution gate:

- major GUI surfaces render consistently in dark mode without obvious light-theme
  leftovers or unreadable contrast

Completion record:

- `docs/CompletedPR/PR-UX-273-Shared-Dark-Mode-Tokens-and-Widget-Theme-Discipline.md`

### PR-UX-274-Shared-Layout-Minimums-and-Resize-Discipline

Purpose:

- create shared layout rules so controls do not collapse or vanish under resize

Primary outcomes:

- minimum-width standards for key widget classes
- consistent row/column weight behavior
- reusable layout helpers for common label/control rows
- shared guidance for scrollable vs compressible surfaces

Primary file targets:

- shared GUI layout helpers
- stage-card widget builders
- reusable form/row helpers

Execution gate:

- the repo has a reusable layout baseline that future panels can adopt

### PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep

Purpose:

- fix pipeline/base-config/stage-card resize issues and hidden controls

Primary outcomes:

- prevent controls like `Steps` from being crowded out
- standardize stage-card row behavior
- ensure core entries/selectors remain visible at normal working widths
- align with dark-mode and shared layout standards

Primary file targets:

- Pipeline tab
- stage-card modules
- related shared widget helpers

Execution gate:

- Pipeline/base-config/stage-card surfaces behave consistently and keep critical
  controls visible

### PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep

Purpose:

- fix prompt-tab and LoRA-row layout issues, especially long-name failures

Primary outcomes:

- long LoRA names no longer hide the slider or remove button
- slider + manual numeric entry support for exact values
- dedicated multi-row or truncation-based resilient LoRA layout
- prompt surface resize behavior becomes predictable

Primary file targets:

- Prompt tab / prompt workspace modules
- LoRA row renderer/widgets
- slider-entry composite helper if introduced

Execution gate:

- prompt/LoRA controls remain usable without over-widening the window

### PR-UX-277-Review-Learning-and-Video-Panel-Consistency-Sweep

Purpose:

- apply the same dark-mode and resize consistency rules to Review, Learning,
  Staged Curation, and Video surfaces

Primary outcomes:

- hidden/collapsing controls fixed across those panels
- panel-specific long-content issues resolved
- compare/help/metadata surfaces remain readable in dark mode

Primary file targets:

- Review tab
- Learning tab
- Staged Curation surfaces
- video-related panels
- related dialogs/inspectors

Execution gate:

- the main advanced workflow surfaces behave consistently under dark mode and resize

### PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep

Purpose:

- clean up popups, dialogs, inspectors, and secondary windows that often get missed

Primary outcomes:

- metadata inspector, compare dialogs, and helper windows fully support dark mode
- dialog content is scrollable where needed
- labels/actions do not get clipped in smaller window sizes

Primary file targets:

- dialog and popup modules
- inspector windows
- compare/secondary helper surfaces

Execution gate:

- secondary surfaces no longer lag behind primary tabs in dark-mode and layout quality

### PR-UX-279-GUI-Consistency-Regression-Checks-and-Maintenance-Checklist

Purpose:

- reduce regression risk after the sweep

Primary outcomes:

- lightweight regression checklist for new GUI panels
- targeted GUI tests/checks where practical
- documented standards for:
  - dark-mode compliance
  - minimum widths
  - resize behavior
  - long-content handling

Primary file targets:

- tests and docs/checklist artifacts
- shared GUI standards docs if introduced

Execution gate:

- future GUI work has a clear standard and lower regression risk

## 6. Recommended Order

1. `PR-UX-272-GUI-Audit-and-Consistency-Inventory` Completed 2026-03-25
2. `PR-UX-273-Shared-Dark-Mode-Tokens-and-Widget-Theme-Discipline`
3. `PR-UX-274-Shared-Layout-Minimums-and-Resize-Discipline`
4. `PR-UX-275-Pipeline-and-Stage-Card-Resilience-Sweep`
5. `PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep`
6. `PR-UX-277-Review-Learning-and-Video-Panel-Consistency-Sweep`
7. `PR-UX-278-Dialog-Inspector-and-Secondary-Surface-Consistency-Sweep`
8. `PR-UX-279-GUI-Consistency-Regression-Checks-and-Maintenance-Checklist`

## 7. Validation Expectations

At completion, validate:

- all major tabs and dialogs render correctly in dark mode
- no critical controls are hidden at normal working widths
- resizing is predictably consistent across primary panels
- long labels/content no longer destroy control access
- sliders with precision needs support exact manual entry where appropriate
- future GUI work has documented standards to follow

## 8. Recommendation

Yes, this can be done, but it should be handled as a structured sweep rather than
an ad hoc series of tiny fixes.

The right way is:

- audit everything first
- define shared theme/layout rules second
- remediate panel groups in sequence
- add regression protection last

That approach will produce a far more durable and consistent GUI than fixing one
panel at a time in isolation.
