#CANONICAL
PR-### — Title of Change (V2.5)

Discovery Reference: D-##
Date: YYYY-MM-DD HH:MM (local time)
Author: <Name or AI Agent>

1. Summary (Executive Abstract)

Provide a concise, high-level description (4–7 sentences):

What the PR does

Why it exists

Which subsystems it affects

What changes for the user and/or system

What risks or considerations exist

This must be a standalone EXSUM.

2. Motivation / Problem Statement

Describe:

The current behavior

Why it is incorrect or insufficient

Evidence (errors, UX issues, architectural violations, failing tests)

Consequences of not fixing

Why solving this now matters in the roadmap

Do not propose the solution here—state the pain, not the fix.

3. Scope & Non-Goals
3.1 In-Scope

List the exact behaviors, features, structures, or UI elements affected.

3.2 Out-of-Scope

List anything intentionally not addressed.

3.3 Subsystems Affected

Choose from:

GUI V2

Controller

Pipeline Runtime

Queue System

Randomizer Engine

Learning System

WebUI Client

Docs

4. Behavioral Changes (Before → After)

Provide a clear table of all changes.

4.1 User-Facing Behavior
Area	Before	After
Example	Run controls confusing	Now unified under Queue panel
4.2 Internal System Behavior
Subsystem	Before	After
4.3 Backward Compatibility

Fully compatible?

Partially compatible?

Breaking change?
Provide justification.

5. Architectural Alignment

Explicitly reference canonical docs:

ARCHITECTURE_v2.5.md

GOVERNANCE_v2.5.md

ROADMAP_v2.5.md

Module specs (Randomizer, Learning, Cluster) as applicable

Confirm:

Architectural boundaries respected

No GUI → Pipeline direct calls

Controller remains single source of truth

Pipeline semantics unchanged unless explicitly intended

Queue semantics follow roadmap direction

6. Allowed / Forbidden Files
6.1 Allowed Files

List each allowed file AND justify it:

src/controller/pipeline_controller.py  
  - Needed to wire send-job semantics into queue flow
src/gui/panels_v2/queue_panel_v2.py  
  - UI element hosting new control

6.2 Forbidden Files

Confirm none of these will be modified unless explicitly unlocked:

src/gui/main_window_v2.py  
src/gui/theme_v2.py  
src/main.py  
src/pipeline/executor.py  
pipeline runner core  
healthcheck core

7. Step-by-Step Implementation Plan

This must be explicit and atomic.

Example:

Add new field send_job_requested to QueuePanelV2.

Add controller callback on_send_job() in PipelineController.

Update JobService to support manual dispatch when queue is paused.

Update UI wiring in pipeline_tab_frame_v2.

Add new tests validating send-job dispatch rules.

Update architecture docs accordingly.

Each item must be testable and deterministic.

8. Test Plan
8.1 New Tests

List new test files and exactly what they cover.

8.2 Updated Tests

List tests that must be modified.

8.3 Test Scaffolding Matrix (Required)
Category	Required?	Notes
Normal-path tests	✔	
Edge-case tests	✔	
Failure-mode tests	✔	
GUI event tests	If GUI PR	
State/restore tests	If state touched	
Randomizer tests	If variants touched	
Queue ordering tests	If queue touched	

All PRs must meet category requirements.

9. Acceptance Criteria

Checklist of binary pass/fail requirements.

Example:

 GUI renders new control without Tk errors

 Queue dispatch behaves as designed

 All new tests pass

 All existing tests remain green

 Documentation updated (CHANGELOG + canonical docs)

 No architectural boundary violations

10. Validation Checklist (Mandatory)

Based on Governance_v2.5:

 App boots

 GUI V2 loads

 Dropdowns populate

 Pipeline runs at least one stage

 Queue semantics unaffected except where designed

 Executor untouched unless explicitly part of PR

 Learning system untouched unless explicitly part of PR

11. Documentation Impact Assessment (MANDATORY)

Every PR must evaluate documentation impact.

11.1 Documentation Impact Questions

Answer YES/NO:

Does this PR change a subsystem's behavior?

Does it change responsibilities between layers?

Does it alter queue, randomizer, or controller semantics?

Does it modify run modes or job lifecycle?

Does it update UX or GUI layout?

Does it modify developer workflow, PR flow, or governance?

11.2 Mapping to Required Docs
If Yes In…	Update:
Subsystem behavior	ARCHITECTURE_v2.5.md
Responsibilities	ARCHITECTURE_v2.5.md
Queue / Randomizer / Job lifecycle	Module specs (randomizer, learning, cluster)
UX / GUI	ROADMAP_v2.5.md
Development workflow	GOVERNANCE_v2.5.md
11.3 CHANGELOG.md Entry (Required)

Each PR must append:

## [PR-###] - YYYY-MM-DD HH:MM
Summary: <short EXSUM>
Files Modified:
- <file> : <short desc>
- <file> : <short desc>
Canonical Docs Updated:
- ARCHITECTURE_v2.5.md (section 3.2 updated)
- ROADMAP_v2.5.md (queue plan clarified)
Notes:
<optional>

12. Rollback Plan
12.1 Rollback Specification Matrix
Category	Items
Files to revert	…
Files to delete	…
Tests to revert	…
Tests to delete	…
Doc updates to undo	…
Expected behavior after rollback	…
13. Potential Pitfalls (LLM Guidance)

List foreseeable mistakes the LLM/Copilot must avoid.

Example:

Do not add new cross-layer imports

Do not modify forbidden files

Do not alter default run modes unless required

Do not create circular imports

Do not change pipeline-builder semantics unless explicitly stated

14. Additional Notes / Assumptions

Optional free-form notes.

✔ End of PR Template (Canonical V2.5)