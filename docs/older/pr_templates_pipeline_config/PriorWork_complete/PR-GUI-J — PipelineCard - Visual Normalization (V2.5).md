PR-GUI-J — PipelineCard - Visual Normalization (V2.5).md

Discovery Reference: GUI Wishlist Group-J
Date: 2025-12-06 12:55 CST
Author: ChatGPT-5.1 (StableNew Agent)

1. Summary (Executive Abstract)

This PR unifies the Pipeline Tab card system by enforcing a single, canonical card hierarchy built on BaseStageCardV2 and the existing design tokens defined in theme_v2. Several panels in the Pipeline tab—Core Config, Stage Configs (txt2img/img2img/refiner/hires/upscale/adetailer), Randomizer, Output, and Queue/Preview attachments—currently use a mix of inconsistent card structures, header formats, padding, border treatments, expander logic, and icon usage.

The PR eliminates all non-standard card variants, replaces them with the canonical card architecture, and standardizes header composition, spacing, collapsible behavior, metadata ribbons/tags, and internal padding. Only GUI elements are affected; controllers, pipeline logic, and queue semantics remain unchanged (Tier 1 risk).

Users gain a predictable, visually clean, and well-structured Pipeline tab where every card behaves and looks consistent across all stages. The system becomes easier to maintain and provides a stable foundation for future GUI PRs in the 400-series roadmap.

2. Motivation / Problem Statement

Current issues in the Pipeline tab include:

Mixed card types (legacy V1-style frames, partial V2 cards, custom expander cards).

Inconsistent headers (different fonts, padding, icons, disclosure arrows).

Uneven spacing between cards, top/bottom margins, and nested widgets.

Non-standard collapsible behavior (some cards animate, some instantly collapse, some don’t collapse at all).

Metadata ribbons (e.g., “Enabled”, “Overrides Active”, model selection indicators) appear differently between cards.

Design system violation: some cards use hard-coded colors, old border logic, or non-tokenized padding.

These violate:

Architecture_v2.5: GUI must not create new widget subsystems that drift from the intended modular panelization model.

Governance_v2.5: GUI must follow consistent visual hierarchy, token usage, and modular patterns. No inline colors or ad-hoc card variants.

Roadmap_v2.5 Phase 1: Pipeline tab normalization is mandatory before Phase 2 learning features and Phase 3 cluster extensions.

Left unaddressed, the GUI becomes increasingly error-prone and costly to modify with every future PR.

3. Scope & Non-Goals
3.1 In-Scope

Replace all Pipeline Tab card widgets with standardized BaseStageCardV2 or BaseCardV2 patterns.

Standardize:

Card headers (icon, title, optional metadata badges).

Card borders, margin, padding.

Collapsible logic (unified expander arrow, animation optional).

Typography + spacing tokens from theme_v2.

Migrate any legacy “frame-with-border” containers to canonical card widgets.

Remove ad-hoc per-panel card implementations.

Normalize metadata ribbons/tags and place them in consistent header positions.

Update GUI tests to expect consistent card structures.

3.2 Out-of-Scope

No changes to pipeline logic, stage enabling logic, or config building.

No redesign of the Pipeline tab layout (handled by PR-GUI-H).

No addition of new stage types or behaviors.

No changes to dark/light theme (handled by PR-GUI-I).

3.3 Subsystems Affected

GUI V2 only

No controller, pipeline, queue, runner, randomizer, or learning code touched.

4. Behavioral Changes (Before → After)
4.1 User-Facing Behavior
Area	Before	After
Card hierarchy	Multiple inconsistent card patterns	All cards use unified BaseStageCardV2 structure
Headers	Different fonts, icons, padding	Standardized header across every Pipeline Tab card
Collapsible panels	Inconsistent affordances	Single expander widget with unified behavior
Metadata ribbons (e.g., Enabled, Overrides Active)	Random placement & style	Top-right standardized badge system
Internal spacing	Irregular	Tokenized spacing (consistent padding/margins)
Visual hierarchy	Hard to scan	Predictable grouping & vertical rhythm
4.2 Internal System Behavior
Subsystem	Before	After
GUI	Panels implement card logic independently	All panels rely on shared card framework
Styling	Inline or per-module styles	Centralized theme-token styling via theme_v2
Testing surface	Hard-to-test inconsistencies	Stable, predictable card DOM structure
4.3 Backward Compatibility

Fully backward-compatible.
No API, state, or mode changes—only visual/structural improvements.

5. Architectural Alignment

This PR complies with:

ARCHITECTURE_v2.5

GUI remains strictly a visual/state presentation layer.

No pipeline, controller, or job lifecycle changes.

Standardized panelization is aligned with the architectural requirement that GUI V2 be modular.

Governance_v2.5

Pure Tier 1 GUI changes, allowed without touching forbidden subsystems.

Avoids architecture drift by removing legacy widget copies.

Adheres to single-source-of-truth token system.

Roadmap_v2.5

Supports Phase 1 stabilization: GUI normalization & clarity are explicit goals.

LLM_Governance_Patch_v2.5

Avoids modifying pipeline, controller, queue, runner (forbidden).

Consolidates GUI in an architecturally safe and deterministic manner.

6. Allowed / Forbidden Files
6.1 Allowed Files (with justification)

src/gui/widgets/base_stage_card_v2.py

Extend card APIs & unify header, badges, collapsible logic.

src/gui/widgets/base_card_v2.py

General-purpose card used for non-stage panels.

src/gui/panels_v2/*_panel_v2.py

Apply card consolidation to Core Config, Stage Config, Randomizer, Output panels.

src/gui/views/pipeline_tab_frame_v2.py

Update card references & ensure consistent widget packing.

src/gui/theme_v2.py

Add any missing spacing/badge/icon tokens needed for headers.

tests/gui_v2/test_pipeline_cards_v2.py (new)

Verify unified card hierarchy.

6.2 Forbidden Files (per governance)

src/gui/main_window_v2.py

src/main.py

Any controllers (src/controller/*)

Any pipeline modules (src/pipeline/*)

Any queue/runner modules

These cannot be touched in a Tier 1 GUI PR.

7. Step-by-Step Implementation Plan

Audit Current Card Implementations

Identify all non-standard V1 or ad-hoc card patterns.

Document required replacements.

Enhance BaseStageCardV2 & BaseCardV2

Add unified header renderer (title, icon, metadata badges).

Add standardized collapsible widget.

Add standardized body container.

Add spacing/border/padding tokens.

Introduce MetadataBadgeV2

A small reusable widget for “Enabled”, “Overrides Active”, etc.

Configurable color & label via theme tokens.

Refactor Pipeline Stage Panels

txt2img → wrap contents inside new BaseStageCardV2.

img2img → same.

Refiner / Hires / Upscale / ADetailer → migrate expander logic to canonical pattern.

Refactor Non-Stage Cards

Randomizer panel → use BaseCardV2.

Output settings panel → consolidate into canonical card.

Config summary, Quick-Actions, and Preview/Queue attachments.

Remove Legacy Card Implementations

Delete obsolete classes after refactor (if any).

Replace all imports with canonical card imports.

Apply Theme Tokenization

Replace hard-coded spacing, borders, header sizes.

Ensure dark/light mode behaves correctly.

Update Pipeline Tab Frame

Ensure vertical stacking uses consistent card spacing.

Guarantee equal spacing between cards.

Write New Tests

Verify card header exists & uses theme tokens.

Verify collapsible behavior is consistent.

Verify metadata badges appear in correct locations.

Documentation + CHANGELOG

Add updated card hierarchy section.

Update GUI design system doc (non-canonical).

8. Test Plan
8.1 New tests

tests/gui_v2/test_pipeline_cards_v2.py

Validate:

Card hierarchy consistency

Header structure

Collapsible logic

Metadata badge rendering

Theme token application

8.2 Updated Tests

Existing GUI tests may need updates where card structure changed.

Remove any tests expecting old card classes.

8.3 Scaffolding Matrix
Category	Required?	Notes
Normal-path	✔	Sanity: all cards load without error
Edge-case	✔	Collapsible open/closed states
Failure-mode	✔	Missing token → safe fallback
GUI events	✔	Click-to-expand behavior
State/restore	N/A	State logic unchanged
Randomizer tests	N/A	No functional change
Queue tests	N/A	Not impacted
9. Acceptance Criteria

All Pipeline Tab cards use BaseStageCardV2 or BaseCardV2.

Zero remaining legacy card implementations.

All headers have consistent appearance and behavior.

Collapsible functionality is uniform across all cards.

Metadata badges appear in correct standardized locations.

All GUI tests pass; no regressions.

No modifications to controllers, pipeline, or queue subsystems.

CHANGELOG updated.

10. Validation Checklist (Governance-Mandatory)

(Per Governance_v2.5)

App boots

GUI V2 loads

Dropdowns populate

Pipeline runs at least one job

Queue semantics unaffected

Runner/executor untouched

Learning system untouched

11. Documentation Impact Assessment
11.1 Documentation Questions
Question	Yes/No
Does this PR change subsystem behavior?	No
Responsibilities between layers?	No
Queue/randomizer semantics?	No
Modify GUI layout or UX?	Yes (visual hierarchy only)
Modify developer workflow/governance?	No
11.2 Required Doc Updates

GUI design system reference (non-canonical).

CHANGELOG.md entry.

11.3 CHANGELOG Entry
## [PR-GUI-J] – 2025-12-06 12:55
Summary: Consolidated Pipeline Tab cards into a unified BaseStageCardV2-based hierarchy with standardized headers, spacing, and collapsible behavior.
Files Modified:
- src/gui/widgets/base_stage_card_v2.py : header & collapsible refactor
- src/gui/panels_v2/* : card consolidation
- src/gui/theme_v2.py : additional spacing/badge tokens
Canonical Docs Updated:
- none required (GUI design system only)

12. Rollback Plan
Category	Items
Files to revert	All modified card/panel widgets
Files to delete	New MetadataBadgeV2 if introduced
Tests to revert	test_pipeline_cards_v2.py
Docs to undo	CHANGELOG
Expected outcome	GUI returns to mixed legacy cards but still functional

Rollback is straightforward since no logic or subsystems outside GUI V2 are affected.

13. Potential Pitfalls (For LLM/Codex)

Do NOT modify pipeline, controller, or queue code.

Do NOT introduce new card subclasses unless necessary—prefer composition.

Do NOT break existing event callbacks inside panels.

Do NOT change spacing tokens unless approved in PR-GUI-I or theme PRs.

Ensure collapsible widgets do not break parent scroll frames.

Ensure metadata badges never overlap the expander arrow.

14. Additional Notes / Assumptions

This PR finalizes the visual structure of the Pipeline Tab for all subsequent GUI PRs.

Forms part of the 400-series GUI wishlist implementation referenced in the canonical Roadmap.