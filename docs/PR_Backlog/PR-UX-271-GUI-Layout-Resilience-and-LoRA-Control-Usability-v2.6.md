# PR-UX-271 - GUI Layout Resilience and LoRA Control Usability v2.6

Status: Completed 2026-03-25  
Date: 2026-03-22  
Branch baseline: `feature/video-secondary-motion-pr-236`  
Applies to: Pipeline tab, base config card, Prompt tab, LoRA controls, resizing behavior, widget minimum sizing

## 1. Purpose

StableNew currently has layout-resilience problems in several operator-facing GUI
surfaces.

Observed issues include:

- controls in the Pipeline tab base config / stage-card area shrink unevenly
  when the window is not stretched wide enough
- controls on the left side of a shared row (for example `Steps`) can get crowded
  out or become effectively unreadable
- Prompt-tab LoRA rows break when a LoRA has a long name
- long LoRA names can crowd out the slider and remove (`X`) control
- some sliders are difficult to land on an exact numeric value with mouse-only
  interaction

This PR improves layout resilience, consistency, and operator usability by adding
minimum-size discipline, better row structure, truncation/wrapping rules, and
manual numeric entry for slider-backed controls.

## 2. Problem Statement

Current repo behavior creates several UX failures:

- resize behavior is inconsistent across widgets and rows
- some controls shrink below practical visibility
- important controls disappear unless the user manually widens the window
- long content (especially LoRA names) can break adjacent control access
- slider-only interaction is not precise enough for expert tuning

These are not cosmetic problems; they directly block safe and efficient use of the
product.

## 3. Goal

Create a more consistent, resilient GUI layout system so that:

- controls do not shrink below usable minimum widths
- critical controls remain visible when the window narrows
- long labels do not destroy row usability
- slider-backed values can also be entered manually
- stage cards and prompt controls behave more consistently during resize

## 4. Guardrails

- do not redesign the entire visual style in this PR
- do not change the meaning of settings or controls
- prioritize usability and resilience over dense packing
- preserve keyboard and mouse usability
- avoid hard-coding one-off fixes when a reusable widget/layout pattern is possible

## 5. Scope

### 5.1 Pipeline / base config card layout resilience

Fix resize behavior in the Pipeline tab / stage-card area so controls do not shrink
below a usable width.

Primary goals:

- define minimum widths for common widget classes used in stage cards
- ensure shared rows distribute space predictably
- prevent left-side controls from being crowded out by right-side neighbors
- standardize how labels, entries, comboboxes, and spinboxes resize

### 5.2 Prompt-tab LoRA row resilience

Fix LoRA row behavior so long LoRA names do not crowd out critical controls.

Primary goals:

- preserve visibility of:
  - remove button
  - weight slider
  - current numeric value
- prevent long LoRA names from consuming the full row width
- support a more resilient row structure

### 5.3 Manual numeric entry for slider-backed controls

Where slider precision matters, support direct numeric entry in addition to slider
movement.

Primary goals:

- allow operator to type an exact value
- keep slider and entry synchronized
- define validation/rounding behavior clearly

## 6. Recommended Design Approach

### 6.1 Reusable layout rules for stage cards

Add a small shared layout discipline for card rows, such as:

- minimum width constants per widget type
- clear column-weight rules
- helper methods for label/control row construction
- optional wrapping/truncation rules for long labels

Recommended outcome:

- all major stage-card rows behave consistently under resize

### 6.2 Dedicated LoRA row layout contract

Do **not** allow the LoRA name label to compete equally with the slider and remove
button in the same unconstrained row.

Recommended options, in order of preference:

#### Preferred option

- LoRA name on its own row
- slider + numeric entry + remove button on a dedicated second row

Benefits:

- resilient to long names
- preserves all control visibility
- clearer interaction model

#### Acceptable fallback

- truncate LoRA name with ellipsis in-row
- reserve fixed minimum width for slider / numeric entry / remove button

### 6.3 Slider + numeric-entry composite control

Introduce or reuse a composite control pattern:

- slider for coarse/fast adjustment
- entry/spinbox for exact value
- synchronized both directions
- optional small-step increment behavior

This pattern should be reusable for LoRA weights and other settings where exact
values matter.

## 7. Proposed Deliverables

### Deliverable A - stage-card minimum-width and resize pass

- audit common stage-card controls
- apply shared minimum-width rules
- standardize row/column weight handling
- prevent critical controls from collapsing out of view

### Deliverable B - LoRA row redesign

- restructure LoRA rows for long-name resilience
- preserve slider and remove-button access at normal window widths
- add truncation or dedicated-row handling for long names

### Deliverable C - exact-value entry support

- add manual numeric entry for LoRA sliders
- optionally extend the same pattern to other slider-backed settings where useful

### Deliverable D - consistency verification

- ensure resize behavior is consistent across pipeline/prompt surfaces
- add targeted tests or at least deterministic layout checks where possible

## 8. Suggested File Targets

Primary likely targets:

- stage-card GUI modules under `src/gui/`
- prompt-tab / prompt-workspace GUI modules under `src/gui/`
- shared GUI widget helpers
- tooltip/help or control composition helpers if reused

Possible files depending on repo layout:

- txt2img card / base config card modules
- prompt workspace / prompt tab modules
- LoRA row renderer or prompt-slot widget files
- shared slider/entry composite widget helpers

Tests:

- targeted GUI tests for LoRA row rendering and resize behavior
- targeted stage-card layout tests where practical

## 9. Execution Gates

This PR is complete only if:

1. base-config/stage-card controls do not collapse below practical visibility at
   normal window widths
2. left-side controls like `Steps` remain visible and usable on shared rows
3. long LoRA names no longer hide the slider or remove button
4. LoRA weights can be entered manually as exact numeric values
5. resize behavior is visibly more consistent across the affected GUI surfaces

## 10. Recommended Sequencing

This PR should be pulled forward near the front of the UX tranche because it fixes
current operator pain, not just polish.

Recommended placement:

- after `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
- before broader help/polish items like `PR-UX-269` and `PR-UX-270`

Suggested local order inside the UX tranche:

1. `PR-UX-265-Tab-Overview-Panels-and-Workflow-Explainers`
2. `PR-UX-266-Action-Buttons-and-High-Risk-Controls-Explained`
3. `PR-UX-271-GUI-Layout-Resilience-and-LoRA-Control-Usability`
4. `PR-UX-267-Stage-Card-Settings-Help-and-Config-Intent-Descriptions`
5. `PR-UX-268-Effective-Config-Summaries-and-Why-This-Value-Is-Used`
6. `PR-UX-269-Workflow-Pathway-Guidance-and-Use-Case-Recommendations`
7. `PR-UX-270-Contextual-Help-Mode-and-Inspectable-UI-Language-Polish`

## 11. Non-Goals

- do not redesign all tabs visually in this PR
- do not attempt a full responsive-design framework rewrite
- do not change backend/config semantics
- do not add unrelated workflow features here

## 12. Recommended PR Title

`PR-UX-271-GUI-Layout-Resilience-and-LoRA-Control-Usability`

## 13. Recommended Commit Message

`Improve GUI layout resilience and LoRA control usability`

## 14. Recommendation

Treat this PR as a usability/stability fix, not cosmetic polish.

The current resize and long-name behavior can hide critical controls and block
normal operation. This should be addressed early in the UX tranche.
