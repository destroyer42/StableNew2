# PR-MAR26-UI-REFRESH-001 Migration Accelerator (Non-Throwaway)

## Objective
Create a UI refresh PR that improves current UX while directly reducing PySide6 migration cost.  
This PR is architecture prep, not cosmetic Tk-specific polish.

## Why This PR Exists
A straight Tk visual reskin is mostly throwaway for Qt migration.  
This PR isolates design system and UI behavior contracts so views can be rehosted (Tk -> Qt) with minimal logic churn.

## Scope (In)
1. Introduce a UI design token system (semantic colors, spacing, typography, radius, elevation names).
2. Create toolkit-agnostic view contracts for high-reuse UI patterns.
3. Extract view logic from tab classes into controller/view-model adapters where missing.
4. Normalize state/event flow for Prompt/Pipeline/Review/Learning tabs via explicit event methods.
5. Add snapshot-style UI contract tests that assert behavior/state, not Tk widget internals.
6. Add migration notes mapping each Tk surface to future Qt equivalents.

## Scope (Out)
1. No broad theme repaint across every widget.
2. No custom Tk widget framework.
3. No PySide6 runtime integration yet.
4. No layout rewrite for aesthetics only.

## Architectural Intent
After this PR:
- UI logic is mostly outside Tk widget classes.
- Styling intent is tokenized and centrally defined.
- UI components expose stable contracts independent of Tk APIs.
- PySide6 migration can swap renderer layer while retaining controllers/contracts.

## Allowed Files
- `src/gui/theme_v2.py`
- `src/gui/ui_tokens.py` (new)
- `src/gui/views/*.py` (only targeted tabs: prompt/pipeline/review/learning)
- `src/gui/controllers/*.py` (targeted controller extraction only)
- `src/gui/view_contracts/*.py` (new)
- `tests/gui_v2/*.py` (new/updated contract tests)
- `tests/controller/*.py` (if behavior extraction needs updates)
- `docs/PR_MAR26/PR-MAR26-UI-REFRESH-001-Migration-Accelerator.md` (this file)
- `docs/ARCHITECTURE_v2.6.md` (minimal addendum section only)
- `docs/StableNew_Coding_and_Testing_v2.6.md` (testing guidance addendum)

## Forbidden Files
- Runner internals (`src/pipeline/*`, `src/queue/*`, execution path core files)
- Canonical execution contracts unrelated to UI
- WebUI process manager internals
- Legacy archive files

## Implementation Plan

### Step 1: Token Layer (Semantic, Not Toolkit-Specific)
1. Add `src/gui/ui_tokens.py`:
   - `ColorTokens`, `SpacingTokens`, `TypeTokens`, `MotionTokens` dataclasses.
   - Named semantic roles only: `surface_primary`, `surface_secondary`, `text_primary`, `text_muted`, `accent_primary`, `status_success`, etc.
2. In `theme_v2.py`, reference tokens via adapter functions.
3. Keep Tk mapping in one place; avoid spreading raw hex values in views.

### Step 2: View Contracts
1. Add `src/gui/view_contracts/` with contracts such as:
   - `status_banner_contract.py`
   - `form_section_contract.py`
   - `selection_list_contract.py`
   - `feedback_panel_contract.py`
2. Contracts define:
   - Required inputs
   - Emitted events
   - State transitions
   - Error/disabled semantics
3. Contracts must not import Tk classes.

### Step 3: Controller/View Extraction
1. For Learning and Review tabs first (highest churn risk), move non-render logic into controller methods:
   - Prompt diff computation
   - Feedback payload building
   - Batch grouping decisions
   - Undo token tracking
2. Keep view classes as render + event wiring only.
3. Add thin adapter methods where needed to preserve existing call sites.

### Step 4: Event Surface Normalization
1. Define explicit event handlers in each target tab:
   - `on_user_select_images(...)`
   - `on_user_apply_changes(...)`
   - `on_user_save_feedback(...)`
2. Remove implicit widget-driven side effects where practical.
3. Ensure each event has deterministic output and test coverage.

### Step 5: Contract Tests
1. Add tests that validate behavior contracts independent of widget implementation:
   - Token presence/validity tests.
   - Contract state machine tests.
   - Controller extraction behavior tests.
2. Avoid brittle pixel/style assertions.

### Step 6: Migration Mapping Doc Addendum
1. Add short section in `ARCHITECTURE_v2.6.md`:
   - “UI Host Abstraction Boundary”.
2. Include mapping table:
   - Tk widget/pattern -> Contract -> PySide6 target class family.

## Acceptance Criteria
1. No execution-pipeline behavior changes.
2. Targeted tabs still function with existing workflows.
3. UI tokens are central source-of-truth for style semantics.
4. Core interaction logic for Review/Learning is testable without Tk widget setup.
5. New contract tests pass.
6. Golden Path suite remains unchanged in outcomes.

## Test Plan
1. `pytest -q tests/controller/test_learning_controller_resume_state.py`
2. `pytest -q tests/controller/test_learning_controller_review_feedback_undo.py`
3. `pytest -q tests/integration/test_golden_path_suite_v2_6.py`
4. New tests introduced in this PR:
   - `tests/gui_v2/test_ui_tokens_contract.py`
   - `tests/gui_v2/test_learning_view_contracts.py`
   - `tests/gui_v2/test_review_view_contracts.py`

## Risk Assessment
1. Risk: accidental behavior drift during extraction.
   - Mitigation: keep adapter methods and add regression tests first.
2. Risk: over-abstracting too early.
   - Mitigation: only extract repeated/high-churn flows (Learning/Review first).
3. Risk: team confusion on token usage.
   - Mitigation: add strict lint/check rule or test that forbids hardcoded colors in target views.

## Rollback Plan
1. Revert only new token/contract modules and adapter usage in touched views.
2. Keep business logic in existing controllers as authoritative fallback.
3. Validate with same test plan and GP suite.

## Follow-On PRs
1. `PR-MAR26-UI-REFRESH-002`: Apply contracts/tokens to Prompt and Pipeline tabs.
2. `PR-MAR26-UI-REFRESH-003`: Introduce Qt-compatible presenter layer and parallel host adapter.
3. `PR-MAR26-UI-REFRESH-004`: PySide6 pilot for one tab (Review) behind dev flag.

