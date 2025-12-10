PR-GUI-K — CollapsiblePersistence & Behavior Normalization (V2.5).md

Discovery Reference: GUI Wishlist Group-K
Date: 2025-12-06
Author: ChatGPT-5.1 (StableNew Agent)

1. Summary (Executive Abstract)

This PR standardizes and persistently stores the open/closed state of all collapsible cards on the Pipeline Tab. Currently, collapsible behavior varies by panel—some cards remember state during a GUI session, some reset on tab-switch, and some do not collapse at all. This causes user-confusion and forces repetitive re-opening of frequently used sections (e.g., txt2img, Randomizer fields, Output settings).

The PR introduces a centralized CollapseStateManagerV2 attached to AppStateV2, ensuring that every card (stage cards, config cards, Randomizer, Output, etc.) has predictable and persistent open/closed behavior within a session. It also unifies the actual collapse/expand mechanism so that all cards behave identically with a consistent animation/instant-collapse mode, per design.

Users benefit from a predictable browsing workflow: cards stay open or collapsed according to their last interaction. The system benefits from eliminating drift across panels. There is no change to pipeline logic, controller logic, or queue semantics—purely GUI behavior (Tier 1 risk).

2. Motivation / Problem Statement

Problems observed in the Pipeline tab:

State is inconsistent:

Some cards reopen automatically on navigation.

Some collapse state is lost on “Reload/Reset UI state.”

Some stage cards collapse correctly; others use legacy expander logic.

User workflow suffers:
Users switching between cards repeatedly have to reopen important sections (txt2img, refiner, Randomizer) every time.

Not aligned with canonical design:

Architecture_v2.5 mandates modular GUI with predictable state separation (no internal widget state that cannot be serialized).

Governance_v2.5 requires consistent UX patterns and discourages one-off widget systems.

Roadmap_v2.5 Phase 1 includes Pipeline Tab normalization and UI/UX standardization.

Without consolidation, each new GUI PR increases drift and inconsistent UX.

3. Scope & Non-Goals
3.1 In-Scope

Add a centralized CollapseStateManagerV2 in GUI/AppState.

Register all collapsible cards with unique keys (e.g., "card_txt2img_main", "card_randomizer_settings").

When user toggles a card:

Persist open/closed state into AppState (session-only).

On GUI startup or Pipeline Tab open:

Apply the saved state to all cards.

Unify collapsible behavior across cards (animation optional; consistency required).

Normalize expander icon states (arrow down/up or +/- semantics).

Update GUI tests to verify persistence.

3.2 Out-of-Scope

Saving state across application restarts (future PR if desired).

Changing default collapsed/open settings from design kit.

Changing layout or column structure (PR-GUI-H).

Changing card visuals (PR-GUI-I/J).

Modifying pipeline, controller, randomizer, or queue behavior.

3.3 Subsystems Affected

GUI V2 only

4. Behavioral Changes (Before → After)
4.1 User-Facing Behavior
Area	Before	After
Collapse persistence	Random/inconsistent	All cards persist open/closed state within a session
Expander icons	Vary by card, inconsistent	Unified arrow or +/- icon from design tokens
Collapse behavior	Some animate, some jump	Uniform collapse/expand with shared mechanism
Navigation	Cards reopen unexpectedly	Cards remain in last user-defined state
UX predictability	Low	High—consistent across all panels
4.2 Internal System Behavior
Component	Before	After
Card state	Stored inside widgets inconsistently	Stored in AppStateV2.collapse_states
Card initialization	Each panel sets defaults independently	Delegated to centralized state manager
Expander handling	Multiple implementations	Single ExpanderV2 + card mix-in
4.3 Backward Compatibility

Fully backward compatible.
No API changes for controllers or pipeline.

5. Architectural Alignment
ARCHITECTURE_v2.5

GUI state now stored in AppStateV2, consistent with canonical state flow.

No pipeline, controller, queue changes occur.


Governance_v2.5

Tier 1 GUI PR allowed.

Eliminates drift and inconsistent local widget logic.


Roadmap_v2.5

Supports Phase 1 stabilization and GUI normalization objectives.


LLM_Governance_Patch_v2.5

No subsystem boundary violations.

Follows GUI-only behavior modifications.


6. Allowed / Forbidden Files
6.1 Allowed Files (with justification)

src/gui/app_state_v2.py

Add collapse_states: dict[str, bool].

Add API for get/set collapse state.

src/gui/widgets/base_stage_card_v2.py

Integrate CollapseStateManager calls.

Unify expander-powered collapse logic.

src/gui/widgets/base_card_v2.py

Same as above (non-stage cards).

src/gui/widgets/expander_v2.py (new or extended)

Standard expander widget.

src/gui/panels_v2/*_panel_v2.py

Register cards with unique collapse IDs.

src/gui/theme_v2.py

Ensure expander icons come from theme tokens.

Tests

tests/gui_v2/test_collapse_state_persistence.py (new).

6.2 Forbidden Files

(Per governance; cannot be touched.)

src/main.py

src/gui/main_window_v2.py

Any controller module

Any pipeline normalization or execution code

JobService / queue / runner / executor

7. Step-By-Step Implementation Plan

Add CollapseStateManagerV2

In app_state_v2.py, add a dict field:
collapse_states: dict[str, bool] = field(default_factory=dict)

Add:

get_collapse_state(key: str) -> bool | None

set_collapse_state(key: str, is_open: bool) -> None

Define Collapse Keys

For each card or panel, define a stable unique key:
"card_txt2img", "card_refiner", "card_randomizer", "card_output_settings", etc.

Modify BaseStageCardV2 / BaseCardV2

On creation, read collapse state from AppState → apply initial open/closed state.

When user clicks expander: update collapse state in AppState.

Standardize the internal body container (body_frame) and collapse animation (if used).

Standardize Expander Widget

Implement ExpanderV2 with:

theme_v2 tokens for icons

callbacks to card collapse/expand

synchronized arrow state (rotated arrow or +/-)

Refactor All Pipeline Tab Panels

Every card must:

Use canonical collapse API

Supply its collapse key

Remove any internal state caching, replacing with AppState persistence.

Remove Legacy Behaviors

Delete unused expander logic from cards.

Remove one-off expand/collapse code.

Update GUI Tests

Add tests confirming:

Collapse state persists through tab switches

Cards apply collapse state at initialization

Expander icons match expected state

Documentation + CHANGELOG

Update GUI behavior notes.

Add CHANGELOG entry.

8. Test Plan
8.1 New Tests

tests/gui_v2/test_collapse_state_persistence.py

Should verify:

Setting state → opening Pipeline tab → state applied

Toggling a card updates AppState correctly

All cards share identical collapse behavior

Expander icon matches open/closed state

8.2 Updated Tests

Any test that inspects card internal structure now expects standardized collapse container.

8.3 Mandatory Scaffolding Matrix
Category	Required	Notes
Normal-path	✔	Cards correctly restore session state
Edge-case	✔	Unknown key defaults to design default
Failure-mode	✔	Missing tokens fall back gracefully
GUI event tests	✔	Expander clicking updates AppState
State tests	✔	State round-trip validation
Randomizer/Queue tests	N/A	No functional interaction
9. Acceptance Criteria

All collapsible cards store/restore state using AppStateV2.

All expander widgets use unified ExpanderV2 logic.

No card uses legacy collapse logic.

Collapse/expand works identically across all cards.

State persists across tab re-renders during a session.

ZERO controller/pipeline/queue changes.

All GUI tests pass.

CHANGELOG updated.

10. Validation Checklist (Governance-Required)

(Per Governance v2.5)

App boots

GUI V2 loads

Dropdowns populate

Pipeline runs at least one stage

Queue semantics unaffected

Runner/executor untouched

Learning system untouched

11. Documentation Impact Assessment
11.1 Questions
Question	Yes/No
Subsystem behavior changed?	No
Layer responsibilities modified?	No
Queue/Randomizer/Learning?	No
UX/GUI changed?	Yes
Governance/workflow changed?	No
11.2 Required Updates

GUI behavior documentation (non-canonical).

Update CHANGELOG.md.

11.3 CHANGELOG Entry
## [PR-GUI-K] – 2025-12-06
Summary: Added CollapseStateManagerV2 and unified collapsible behavior across all Pipeline Tab cards. Cards now persist open/closed state within a session.
Files Modified:
- src/gui/app_state_v2.py : collapse state store
- src/gui/widgets/base_stage_card_v2.py : unified collapsible card logic
- src/gui/widgets/base_card_v2.py : added collapse support
- src/gui/widgets/expander_v2.py : new unified expander widget
- src/gui/panels_v2/*_panel_v2.py : collapse state registration
Canonical Docs Updated:
- none required
Notes:
- No logic, controller, pipeline, or queue changes.

12. Rollback Plan
Category	Items
Revert files	All collapse-related GUI changes
Delete	expander_v2.py if newly created
Revert tests	test_collapse_state_persistence.py
Docs	Remove CHANGELOG entry
Result	GUI returns to inconsistent collapse behavior but remains functional

Rollback safe since contained entirely within GUI.

13. Potential Pitfalls (LLM/Codex)

Do NOT store collapse state anywhere except AppStateV2.

Do NOT modify controller or pipeline logic.

Do NOT break scrollable column layout (PR-GUI-H).

Ensure unique collapse keys per card.

Ensure no cyclic imports when connecting cards to AppState.

Do not introduce new mandatory runtime dependencies.

14. Additional Notes / Assumptions

Collapse state persistence is session-only (in-memory), not persistent across restarts.

Completes part of the 400-series GUI wishlist (Phase 1).