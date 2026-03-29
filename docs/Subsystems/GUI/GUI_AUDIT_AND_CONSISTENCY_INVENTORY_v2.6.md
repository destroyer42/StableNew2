# GUI Audit And Consistency Inventory v2.6

Status: Active audit artifact
Updated: 2026-03-25

## 1. Purpose

This document is the structured audit artifact for
`PR-UX-272-GUI-Audit-and-Consistency-Inventory`.

It inventories the active Tk GUI surfaces, identifies likely dark-mode,
resizing, and hidden-control risks, and separates shared root causes from
panel-specific defects so the follow-on GUI sweep PRs can execute in a coherent
order.

## 2. Method

This audit is based on the active runtime under `src/gui/`, the current shared
theme/layout helpers, and the existing GUI regression tests.

The audit criteria were:

- whether the surface is on the shared theme/token path
- whether it relies on shared layout/minimum-size rules or local one-off rules
- whether high-value guidance/inspection surfaces are consistently exposed
- whether dialogs and inspector windows follow the same dark-mode discipline as
  the main window
- whether current tests cover the surface as part of the active GUI contract

## 3. Shared Seams Already In Place

These seams are real strengths and should be treated as the baseline for later
consistency work, not replaced:

- `src/gui/theme_v2.py` applies the active dark theme and defines reusable
  ttk styles
- `src/gui/design_system_v2.py` and `src/gui/ui_tokens.py` provide shared color,
  spacing, and typography tokens
- `src/gui/main_window_v2.py` owns the main-window geometry floor and active tab
  shell
- `src/gui/layout_v2.py` and `src/gui/view_contracts/pipeline_layout_contract.py`
  already provide a layout-contract seam, but only for a narrow slice
- `src/gui/widgets/scrollable_frame_v2.py` is the shared scroll-container seam
- `src/gui/widgets/tab_overview_panel_v2.py` and
  `src/gui/widgets/action_explainer_panel_v2.py` are now the shared guidance
  seam on major tabs
- `src/gui/base_generation_panel_v2.py` already contains one of the clearest
  minimum-width baselines in the repo

## 4. Surface Inventory

### 4.1 Pipeline workspace

Primary files:

- `src/gui/main_window_v2.py`
- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/views/stage_cards_panel_v2.py`
- `src/gui/base_generation_panel_v2.py`

Audit state: Mostly aligned

What is already good:

- the active root window applies the shared theme
- the Pipeline tab uses shared scroll containers and shared overview guidance
- the main window has explicit default/minimum geometry handling
- the base generation panel has concrete label/control minimum widths

Findings:

- stage cards still own row/column sizing locally, which means resize behavior
  is disciplined in places but not governed by one reusable rule
- `StageCardsPanel` stacks cards consistently, but the sizing contract is still
  implemented inside each card instead of a shared helper

Primary follow-on PRs:

- `PR-UX-274`
- `PR-UX-275`

### 4.2 Prompt workspace

Primary files:

- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/advanced_prompt_editor.py`
- `src/gui/widgets/matrix_helper_widget.py`
- `src/gui/widgets/matrix_slot_picker.py`
- `src/gui/widgets/lora_keyword_dialog.py`

Audit state: Mixed, high-priority inconsistency surface

What is already good:

- the main Prompt tab uses active tokens for raw `tk.Text` and `tk.Listbox`
  controls
- prompt editing remains within the active Tk runtime rather than a parallel
  toolkit path

Findings:

- the main Prompt tab does not participate in the shared `TabOverviewPanel` or
  shared workflow/action guidance seam
- the surface relies on hand-styled raw `tk.Text` and `tk.Listbox` widgets,
  which is workable but not yet governed by a shared widget primitive
- `advanced_prompt_editor.py` bypasses `theme_v2.apply_theme()` and redefines a
  local dark-mode style system in `_apply_dark_theme()`
- the advanced editor also hard-codes geometry and direct colors such as
  `foreground="white"` and `insertbackground="white"`, creating drift from the
  active token set

Primary follow-on PRs:

- `PR-UX-273`
- `PR-UX-276`
- `PR-UX-278`

### 4.3 Review workspace

Primary files:

- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/artifact_metadata_inspector_dialog.py`

Audit state: Mostly aligned in-tab, mixed on secondary surfaces

What is already good:

- Review uses the shared overview/help seam
- Review guidance, help-mode behavior, and effective-settings inspection are now
  coherent inside the tab itself

Findings:

- the main Review tab is in better shape than the modal surfaces it launches
- the Artifact Metadata Inspector uses a modal notebook and useful structure,
  but it does not apply the shared theme and still uses raw default `tk.Text`
  panes
- inspector geometry/minimums are local and not on a reusable dialog contract

Primary follow-on PRs:

- `PR-UX-277`
- `PR-UX-278`

### 4.4 Learning and staged curation

Primary files:

- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/discovered_review_inbox_panel.py`
- `src/gui/views/discovered_review_table.py`
- `src/gui/learning_review_dialog_v2.py`

Audit state: Mostly aligned on main workspace, mixed on dialog support

What is already good:

- Learning uses the shared overview/help seam
- discovered review and staged-curation guidance now explain pathway choices
- staged curation has strong inspection context compared with earlier revisions

Findings:

- the main Learning tab is on the active UX-help path, but the review dialog is
  not
- `LearningReviewDialogV2` has no explicit geometry/minimum-size discipline and
  uses default ttk styling rather than the shared theme path
- the tab owns complex grid layout directly; most of it is workable, but the
  layout contract is too local to enforce consistency across later panel sweeps

Primary follow-on PRs:

- `PR-UX-274`
- `PR-UX-277`
- `PR-UX-278`

### 4.5 Video surfaces

Primary files:

- `src/gui/views/svd_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`

Audit state: Mostly aligned, medium-priority consistency cleanup

What is already good:

- all three major video surfaces use shared overviews and workflow explainers
- effective-settings summaries are present on Video Workflow and Movie Clips
- the pathway guidance between SVD, workflow-driven video, and clip assembly is
  now coherent

Findings:

- these tabs still build similar status/effective-summary strips independently
  rather than through one shared secondary-surface scaffold
- their dark-mode behavior is mostly consistent, but the layout patterns are
  still local and duplicated

Primary follow-on PRs:

- `PR-UX-274`
- `PR-UX-277`

### 4.6 Photo Optimize

Primary files:

- `src/gui/views/photo_optimize_tab_frame_v2.py`

Audit state: Mixed

What is already good:

- the tab uses shared tokens for raw listbox surfaces
- the body is on the shared scroll-container path
- the labelframe styling is already dark-mode aware

Findings:

- Photo Optimize does not yet participate in the shared overview/help seam used
  by Pipeline, Review, Learning, and the video tabs
- the tab uses many local direct `Dark.*` style choices and tokenized raw
  widgets, but there is no higher-level consistency wrapper for this surface
- this is a likely hidden-control risk under aggressive resize because the panel
  is dense and currently governed by local layout only

Primary follow-on PRs:

- `PR-UX-274`
- `PR-UX-277`

### 4.7 Settings and stage cards

Primary files:

- `src/gui/views/stage_cards_panel_v2.py`
- `src/gui/stage_cards_v2/base_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`

Audit state: Mixed, shared-root-cause heavy

What is already good:

- stage cards are already organized around a shared card container path
- base-stage-card and component modules provide a real reuse seam

Findings:

- resize behavior is still defined per card, especially in label/control rows
- the strongest minimum-width discipline exists in `base_generation_panel_v2.py`,
  not as a cross-card reusable contract
- the repo is ready for a shared layout helper, but it does not yet have one
  that all stage cards consume

Primary follow-on PRs:

- `PR-UX-274`
- `PR-UX-275`

### 4.8 Dialogs and inspector windows

Primary files:

- `src/gui/artifact_metadata_inspector_dialog.py`
- `src/gui/views/error_modal_v2.py`
- `src/gui/panels_v2/job_explanation_panel_v2.py`
- `src/gui/dialogs/multi_folder_selector.py`
- `src/gui/widgets/config_sweep_widget_v2.py`
- `src/gui/widgets/lora_keyword_dialog.py`
- `src/gui/widgets/matrix_slot_picker.py`
- `src/gui/widgets/matrix_helper_widget.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`

Audit state: Highest inconsistency concentration

What is already good:

- most of these dialogs solve real operator tasks and already expose useful
  structure
- several already define geometry or minimum size, which is better than no
  floor at all

Findings:

- dialog theming is inconsistent across the repo because `Toplevel` surfaces do
  not appear to share one mandatory `apply_theme()` path
- several dialogs use default ttk fonts, raw `tk.Text`, or explicit font tuples
  instead of shared tokens/styles
- `ErrorModalV2` is fixed-size (`resizable(False, False)`) while carrying
  variable-length message, remediation, context, and stack content, which is a
  hidden-control/readability risk
- `MultiFolderSelector` uses default colors and fonts and is not dark-mode
  aligned with the active v2 shell
- `JobExplanationPanelV2` and the metadata inspector are useful but remain only
  partially aligned with shared dark-mode and dialog-discipline rules

Primary follow-on PRs:

- `PR-UX-273`
- `PR-UX-274`
- `PR-UX-278`

## 5. Shared Root Causes

These are the cross-cutting problems worth fixing at the root instead of panel
by panel.

### 5.1 No mandatory Toplevel theming contract

The main window applies the active theme, but dialogs and inspector windows do
not appear to be required to call one shared theme/bootstrap helper.

Consequence:

- dark-mode quality is only as good as each dialog author's manual styling
- dialogs drift toward default ttk/Tk visuals even when the main shell is
  consistent

### 5.2 No shared primitive for raw `tk.Text` and `tk.Listbox` dark-mode surfaces

Multiple panels hand-style raw text/list widgets with tokens. That keeps them
readable, but it duplicates logic and makes consistency audits expensive.

Consequence:

- prompt, inspector, review, and utility surfaces can all drift independently

### 5.3 Layout minimums are local instead of contract-driven

The repo has good local examples, especially in `main_window_v2.py` and
`base_generation_panel_v2.py`, but no shared minimum-width/minimum-height helper
governs the full active GUI.

Consequence:

- resize resilience varies by panel
- hidden or cramped controls are likely to recur whenever a dense new surface
  is added

### 5.4 Guidance and inspectability are strong on some tabs, absent on others

Pipeline, Review, Learning, SVD, Video Workflow, and Movie Clips now use the
shared help seam. Prompt and Photo Optimize do not.

Consequence:

- the operator experience is more coherent in execution-heavy tabs than in
  editing and utility surfaces

### 5.5 Consistency regression coverage is partial

The repo has focused tests for pipeline layout, main-window geometry, help-mode,
and several major tabs, but there is no broad audit/checklist test contract for
dialogs and secondary surfaces.

Consequence:

- later consistency fixes can regress outside the best-tested workspaces without
  an immediate signal

## 6. One-Off Defects Worth Tracking Separately

These are important, but they should not be mistaken for root-cause fixes.

- `src/gui/advanced_prompt_editor.py` owns a full local dark-mode system and is
  the clearest single-file style bypass in the active GUI
- `src/gui/views/error_modal_v2.py` hard-locks a non-resizable error window even
  though its payload size is highly variable
- `src/gui/learning_review_dialog_v2.py` is functionally useful but visually and
  layout-wise under-specified compared with the rest of the active v2 shell
- `src/gui/dialogs/multi_folder_selector.py` is a practical workflow tool that
  still presents as a default Tk dialog instead of an active-product surface

## 7. Existing Regression Coverage

Current useful tests:

- `tests/gui_v2/test_gui_v2_layout_skeleton.py`
- `tests/gui_v2/test_window_layout_normalization_v2.py`
- `tests/gui_v2/test_pipeline_tab_layout_v2.py`
- `tests/gui_v2/test_action_explainer_panels_v2.py`
- `tests/gui_v2/test_tab_overview_panels_v2.py`
- `tests/gui_v2/test_main_window_smoke_v2.py`

Coverage gap summary:

- no broad dialog-consistency regression suite
- no inventory/checklist contract for dark-mode adoption across `Toplevel`
  surfaces
- no reusable audit harness that enumerates major GUI surfaces and classifies
  them against the shared theme/layout rules

## 8. Prioritized Remediation Map

### Priority 1 - `PR-UX-273`

- establish mandatory theme/token discipline for dialogs, helpers, and legacy
  editor surfaces
- extract shared dark-mode primitives for raw text/list-like widgets if needed

### Priority 2 - `PR-UX-274`

- extract shared minimum-size and resize-discipline helpers from the current
  local implementations
- define when surfaces must scroll versus compress

### Priority 3 - `PR-UX-275`

- apply the shared layout baseline to Pipeline and stage cards

### Priority 4 - `PR-UX-276`

- bring Prompt, LoRA, and matrix editing surfaces onto the same visual and
  guidance discipline as the other major workspaces

### Priority 5 - `PR-UX-277`

- normalize the remaining differences across Review, Learning, Photo Optimize,
  and the video surfaces

### Priority 6 - `PR-UX-278`

- normalize dialogs, inspector windows, and secondary utility surfaces

### Priority 7 - `PR-UX-279`

- convert this audit into durable regression checks and a maintenance checklist

## 9. Execution Gate

`PR-UX-272` is complete when this audit artifact exists and clearly identifies:

- the major GUI surfaces under the active runtime
- the shared root causes behind current inconsistency
- the one-off issues that should not be mistaken for root fixes
- the prioritized route into `PR-UX-273` through `PR-UX-279`

This document satisfies that execution gate.