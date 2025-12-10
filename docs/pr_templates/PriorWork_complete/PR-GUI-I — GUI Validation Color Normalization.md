PR-GUI-I — GUI Validation Color Normalization & Prompt/Config Panel Recolor (V2.5)

(GUI Wishlist Group I)

Discovery Reference: GUI-WISHLIST-I
Date: 2025-12-06
Author: ChatGPT (StableNew Agent)

1. Summary (Executive Abstract)

This PR standardizes the color validation states across all GUI V2 panels and unifies the prompt, preset/config, and randomizer panels under the official StableNew theme tokens.
It removes inconsistent leftover V1 color logic, consolidates light-vs-dark adjustments, and ensures that all validation feedback (empty fields, invalid values, mismatch states) uses canonical color tokens instead of literal RGB/hex values.
The work touches GUI V2 panels only, with no impact on controllers, pipeline, queue, or job lifecycle, consistent with Governance V2.5 boundaries .
Users will see consistent color behavior, readable dark-mode fields, unified borders, and corrected label/link styling.
Risk is Tier 1 (visual/UI only). No behavioral changes to job construction or execution flow (as required by Architecture_v2.5 ).

2. Motivation / Problem Statement

Current GUI styling suffers from several inconsistencies:

Validation colors are inconsistent or invisible
Some fields incorrectly use hardcoded RGB values optimized for V1 light mode.
Others use Tk default red/yellow, which is unreadable in dark mode.

Prompt & preset/config panels use mismatched colors
Some backgrounds are near-black; some labels adopt inconsistent contrast; entry fields do not follow theme_v2 tokens.

Dark mode regressions
When theme toggles, several fields render with low contrast or identical background/foreground values.

No centralized color/semantic mapping
Validation states (OK, WARNING, ERROR) are not standardized.

Consequences:

Users cannot reliably interpret validation feedback.

Accessibility suffers due to poor contrast ratios.

GUI panels break the V2.5 theme consistency policy required by Governance_v2.5 and Roadmap_v2.5 (Phase 1 GUI normalization) .

Tests may fail due to unstable widget attributes.

3. Scope & Non-Goals
3.1 In-Scope

Standardize color tokens for:

Entry validation states (normal / warning / error / disabled)

Prompt panel widgets

Preset/config panels

Randomizer panel fields requiring validation

Replace hardcoded hex colors with theme_v2 lookups.

Normalize border styles, highlightthickness, and padding where inconsistent.

Ensure dark-mode correctness for all touched widgets.

3.2 Out-of-Scope

No changes to controllers, pipeline, queue, or job lifecycle.

No logic changes to how validation is determined — only how it is displayed.

No redesign of panel layout or structural hierarchy (covered by other GUI Wishlist PRs).

No stage-card styling changes outside prompt/config fields.

3.3 Subsystems Affected

GUI V2 (panels & widgets)

Theme subsystem (theme_v2)

Docs (Style/UX notes)

4. Behavioral Changes (Before → After)
4.1 User-Facing Behavior
Area	Before	After
Field validation	Inconsistent colors, mostly hardcoded	Unified colors from theme tokens: normal, warn, error
Prompt panel	Bad dark-mode contrast, mismatched borders	Consistent style with design tokens
Config/preset panels	Mixed light/dark artifacts, random border logic	Standard border, spacing, and highlight rules
Randomizer fields	Some unreadable numeric-entry fields in dark mode	Readable, contrast-corrected theme-based rendering
4.2 Internal System Behavior
Subsystem	Before	After
GUI	Used inline literal colors; styling ad-hoc	Uses theme_v2 semantic tokens only
Theme	Did not define validation semantic palette	Gains semantic token mapping (VALID, WARN, ERROR)
Controllers / Pipeline	No interaction	Unchanged
4.3 Backward Compatibility

Fully backwards compatible.

No config, model, queue, or job metadata changes.

No breakage to saved presets.

Only visual styling updated.

5. Architectural Alignment

Respects GUI ↔ Controller boundary — no pipeline or queue logic added to GUI. (Governance_v2.5 §5.1)

Does not touch ConfigMergerV2, RandomizerEngineV2, or JobBuilderV2, preserving pipeline purity rules. (Architecture_v2.5)

GUI may update colors & styles; this is allowed Tier-1 work (Governance risk tier table).

No new subsystem responsibilities introduced.

No changes to job lifecycle or run modes (Architecture_v2.5 canonical flow).

6. Allowed / Forbidden Files
6.1 Allowed Files (with justification)
File	Reason
src/gui/theme_v2.py	Define semantic validation color tokens
src/gui/panels_v2/prompt_panel_v2.py	Apply theme tokens to fields
src/gui/panels_v2/preset_panel_v2.py	Normalize field and label colors
src/gui/panels_v2/randomizer_panel_v2.py	Apply consistent validation colors
src/gui/panels_v2/* minor edits	As needed to remove hardcoded colors
tests/gui_v2/test_color_validation.py (new)	Validate token usage and widget state
6.2 Forbidden Files

Per Governance_v2.5 and Architecture_v2.5 rules, do NOT modify:

Forbidden File	Reason
src/gui/main_window_v2.py	Forbidden by StableNew governance
src/main.py	Core entrypoint; cannot modify for styling PR
src/pipeline/*	Contains pipeline logic; out of scope
src/controller/*	Styling PR must not alter pipeline/queue wiring
src/pipeline/executor.py	High-risk Tier-3 subsystem
Runner / queue core	Not permitted for GUI PRs
7. Step-by-Step Implementation Plan

Add semantic color tokens to theme_v2

VALID_BG, VALID_FG

WARN_BG, WARN_FG

ERROR_BG, ERROR_FG

Add dark/light variants if theme system expects dynamic switching.

Add a helper API

apply_validation_style(widget, state: Literal["normal","warn","error"])

Audit all panels for inline colors:

Prompt panel

Preset/config panel

Randomizer panel

Remove hardcoded hex/RGB entries.

Replace direct color assignments

Map all previous states to new theme tokens.

Ensure entry background/foreground/border highlight match color token rules.

Fix dark mode regressions

Validate that fields meet minimum WCAG contrast.

Adjust light/dark theme palettes accordingly.

Normalize border and highlight behavior

All entry widgets must use consistent highlightthickness and borderwidth.

Remove stray per-widget border logic.

Add small test suite

Tests verify that a widget receives theme-defined colors for each validation state.

Tests verify that no panel imports hardcoded literal color values.

Documentation updates

Update GUI styling notes in canonical docs as necessary.

Add reference to the new validation palette.

Changelog entry

Add full PR entry per Governance v2.5 documentation rules.

8. Test Plan
8.1 New Tests

File: tests/gui_v2/test_color_validation.py

Covers:

Validation helper functions apply correct tokens.

Prompt/preset/randomizer entries respond correctly to simulated validation states.

Dark mode renders contrasting colors.

8.2 Updated Tests

Minor snapshot updates for GUI tests that check widget attributes.

8.3 Test Scaffolding Matrix
Category	Required?	Notes
Normal-path tests	✔	Semantic colors applied correctly
Edge-case tests	✔	Empty fields, invalid inputs
Failure-mode tests	✔	Ensure no crashes when theme missing fields
GUI event tests	✔	Validate widget color updates dynamically
State/restore tests	N/A	Styling only
Randomizer tests	N/A	No logic changes
Queue tests	N/A	Not touched
9. Acceptance Criteria

All GUI V2 fields use theme tokens instead of hardcoded colors.

Prompt / preset / randomizer panels render correctly in light and dark mode.

All validation states use consistent visual language.

No controller/pipeline/queue code modified.

All new tests pass; existing GUI tests remain green.

CHANGELOG updated.

No architectural boundary violations (verified through Governance checklist).

10. Validation Checklist (Mandatory)

(From Governance_v2.5)

App boots → ✔ unchanged

GUI V2 loads → ✔

Dropdowns populate → ✔ unaffected

Pipeline runs a stage → ✔ unchanged

Queue semantics unaffected → ✔

Executor untouched → ✔

Learning system untouched → ✔

11. Documentation Impact Assessment
11.1 Documentation Impact Questions
Question	Yes/No
Changes subsystem behavior?	NO
Changes responsibilities between layers?	NO
Alters queue, randomizer, controller semantics?	NO
Modifies run modes?	NO
Updates UX / GUI layout?	YES (styling only)
Updates dev workflow or governance?	NO
11.2 Required Docs to Update

Since UX styling changes are made:

Update Roadmap_v2.5.md GUI normalization reference (minor note)

Optionally update ARCHITECTURE_v2.5.md GUI section to reflect new validation styling expectations (editorial note; no behavioral change)

11.3 CHANGELOG Entry
## [PR-GUI-I] - 2025-12-06
Summary: Standardized color validation + prompt/config panel recolor.
Files Modified:
- theme_v2.py — added semantic validation tokens
- prompt_panel_v2.py — applied new tokens
- preset_panel_v2.py — removed hardcoded colors
- randomizer_panel_v2.py — fixed dark mode visibility
Canonical Docs Updated:
- Roadmap_v2.5.md (GUI normalization note)
Notes: No pipeline/controller changes.

12. Rollback Plan

Files to revert:

Revert changes in theme_v2.py, all GUI panel files touched.

Tests to revert:

Remove new validation color tests.

Docs to undo:

Remove roadmap note additions.

Expected post-rollback behavior:

GUI returns to pre-PR styling.

No pipeline/queue behavior affected.

13. Potential Pitfalls (LLM Guidance)

Do NOT introduce hardcoded colors anywhere.

Do NOT modify pipeline, queue, or controller imports.

Avoid breaking layout spacing when changing border widths.

Do NOT rename theme fields without updating all references.

Do NOT add new runtime logic to GUI.

Avoid state bleed-through: make validation purely visual.

Do NOT touch main_window_v2.py (forbidden file).

14. Additional Notes

This PR is intentionally modular — future PRs (e.g., GUI-J/K/L) may extend token usage.

Semantic color design adheres to StableNew design-system goals and Phase-1 GUI normalization from Roadmap_v2.5.

Color tokens will support expansion into WCAG accessibility PRs if added later.