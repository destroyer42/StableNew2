PR-CORE-016 – GUI V2 Polishing

Status: Specification
Priority: MEDIUM
Effort: MEDIUM
Phase: Post‑Unification Core Refinement
Date: 2026‑03‑29

Context & Motivation

The StableNew user interface has evolved rapidly across multiple feature additions, culminating in a complex set of tabs and controls. While functional, the GUI lacks polish and cohesion—navigation is inconsistent, some controls are duplicated across tabs, and new users find it difficult to discover key features. The 2.6 design docs note that the UI should provide a single integrated experience across pipelines, but current forms diverge from this vision. PR‑CORE‑016 aims to unify and polish the existing GUI (commonly referred to as “GUI V2”) without changing core functionality.

Goals & Non‑Goals
Goal: Create a consistent look and feel across all tabs (PromptPack, SVD, Story Planner, Gallery) by adopting shared styling and layout guidelines. This includes aligning margins, button styles, and typography.
Goal: Consolidate duplicated controls (e.g. prompt inputs or LoRA selectors) into reusable widgets. When a control appears in multiple contexts, abstract it into a common component under src/gui/widgets and reuse it.
Goal: Improve discoverability by adding tooltips or inline help for complex settings (motion bucket, interpolation, style weight). This will reference documentation where appropriate.
Goal: Ensure the GUI respects the architecture enforcement checklist—UI code must stay in the presentation layer and not leak into pipeline logic.
Non‑Goal: Introducing brand‑new features or altering the pipeline logic is outside the scope of this PR. The focus is on visual polish and usability, not functional change.
Guardrails
Maintain backward compatibility: existing jobs and workflows should run identically after UI polish. Any renamed controls or relocated buttons must preserve their underlying configuration fields.
Avoid adding blocking modals; guidance should appear inline or as tooltips so that the user’s flow is not interrupted.
Respect the separation of concerns: do not move pipeline logic into the GUI. Use callbacks to call into controllers when necessary.
Allowed Files
Files to Modify
src/gui/views/*.py – apply consistent styling (e.g. using a theme file), consolidate duplicated widgets, add tooltips, and rearrange layouts for clarity.
src/gui/widgets/ – create new reusable widgets such as PromptInput, LoraSelector, and SceneNavigator that encapsulate common UI elements.
src/gui/themes.py – define global colours, fonts, and padding constants; update existing frames to reference these constants.
src/gui/app_state_v2.py – if state management needs to expose new properties (e.g. theme settings), adjust accordingly.
Files to Create
tests/gui/test_gui_polishing.py – new tests to verify that each tab instantiates without errors and that shared widgets render correctly.
Forbidden Files
src/pipeline/ – no pipeline logic changes or configuration schema modifications. The GUI should call into existing controllers without altering their API.
Implementation Plan
Design Guidelines: Define a themes.py module specifying fonts, colours, and spacing. Base these guidelines on the style currently used in SVDTabFrameV2 and apply them uniformly across other frames.
Widget Abstraction: Identify common controls (prompt text entry, seed input, LoRA picker) used across multiple tabs. Create classes such as PromptInput(Frame) and LoraSelector(Frame) under src/gui/widgets. These should expose methods to get/set values and integrate tooltips explaining their usage.
Layout Harmonisation: Review each tab’s grid or pack layout. Align controls using consistent row/column spacing. Group related controls under LabelFrames with descriptive titles.
Discoverability Enhancements: For each advanced setting (motion bucket, interpolation level, style weight), add a small “info” icon that reveals a tooltip describing what the setting does and links to the relevant documentation. Use ttk.Tooltip or a custom tooltip implementation.
Testing: In test_gui_polishing.py, create minimal tests that instantiate each main frame (PromptPackTabFrame, SVDTabFrameV2, StoryPlannerFrame) in isolation. Assert that they initialise successfully and that the reusable widgets provide expected defaults. Consider snapshot tests for layout (using a testing library that supports Tkinter snapshotting, if available).
Documentation Updates: After implementation, update the user manual (docs or README) to reflect the new UI layout and include screenshots. Provide quick‑start instructions referencing the new tooltips.
Testing Plan
Unit Tests: Verify that each widget (e.g. PromptInput) correctly propagates values to the parent frame and that tooltips display the correct text.
GUI Smoke Tests: Launch the application in a headless testing environment and ensure that all tabs load without error. Use a Tkinter test harness to simulate user interactions (typing prompts, selecting LoRAs) and assert that no exceptions occur.
Manual Verification: Run the polished GUI in a dev environment and ensure that the visual styling is consistent. Check that tooltips appear on hover and that controls are logically grouped.
Verification Criteria
All GUI tabs adopt the same fonts, spacing, and colour scheme as defined in themes.py.
Common controls have been abstracted into reusable widgets. Duplicate code has been removed from tab frames.
Each advanced setting includes a tooltip or help description accessible via an info icon.
Unit and smoke tests pass, indicating that the refactored GUI does not break initialisation or value propagation.
User manual screenshots match the new polished interface.
Risk & Mitigation
Risk: Refactoring UI components may introduce regressions in event handling or state binding. Mitigate by implementing thorough unit and smoke tests and by performing manual testing of all major flows (prompt generation, video generation, scene planning).
Risk: Users might be temporarily disoriented by the new layout. Mitigate by providing clear documentation and tooltips that describe any relocated controls.
Dependencies
Relies on existing GUI functionality for SVD, PromptPack, and Story Planner tabs. No other PR must merge first.
Approval & Execution
Approvers: UI/UX lead, project maintainers.
Execution: After review, merge into the feature/gui-polish branch and test via CI. Perform manual QA before merging into the main development branch.
