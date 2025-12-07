PR-085 – Test Coverage Uplift & Triage Plan (V2.5).md

Version: V2.5
Last Updated: 2025-12-02
Owner: StableNewV2 Test & Quality Working Group
Status: Active Planning Document (Living Artifact)

1. Purpose

The goal of this document is to provide a clear, concrete roadmap for stabilizing the StableNewV2.5 test suite, raising total coverage above the required 55% threshold, and ensuring that the highest-value tests reflect the current architecture and API contracts.

This plan transforms the raw test failures into:

Actionable categories

Priority buckets (Now / Soon / Later / Maybe-never)

Work packages for upcoming PRs

Milestones for restoring full test stability

This document will be referenced by PR-082(x), PR-083, PR-081D(x), PR-081E, and future quality-focused PRs.

2. Current Coverage Snapshot

Total Coverage: 49.95%
Required: 55.0%
Delta: –5.05%

Coverage gaps and failures stem from:

Contract/API mismatches

Controller/GUI wiring broken during V2.5 transition

Outdated test expectations

WebUI → Controller → GUI resource mismatches

FakePipeline & DummyProcess helper inconsistencies

V1/v2 hybrid remnants and test harness drift

Top-of-stack journey tests failing due to upstream issues

3. Thematic Failure Groups

All failing and erroring tests logically fall into nine categories.

3.1 Core Contracts & Test Harnesses (High Leverage)

DummyProcess missing .terminated or equivalent

FakePipeline.run_upscale_stage() signature mismatch with PipelineRunner

Multiple learning/pipeline integration tests broken due to this

3.2 V2 GUI Entrypoint & Import Wiring

ImportError around src.gui.main_window.tk

Tests expecting main_window_v2 but entrypoint imports legacy version

3.3 Controller RunConfig & Pipeline Config Wiring

controller.state.run_config is None

Affects both config and integration tests:

test_app_controller_config.py

test_app_controller_pipeline_integration.py

3.4 Job History / ViewModel Contract

JobViewModel missing .result or equivalent

Test expects returned records to expose the final job result

3.5 WebUI Resource Refresh & Stage Integration

Mismatch in resource dicts:

Models

VAEs

ADetailer detectors

ADetailer models

Tests expecting old shapes or missing keys

3.6 Controller Lifecycle & Pipeline Flow Behavior

Run → Idle

Second run after completion

Cancel → Idle

Error recovery

Affects the entire test_app_controller_pipeline_flow_pr0 suite

3.7 GUI V2 Behavior Tests

Dropdown refresh failing due to missing controller method(s)

Status bar transitions incorrect (Error: boom vs Idle)

Stage card layout test contains a placeholder assert False

3.8 Full Journey Tests (JT03/04/05 + v2_full)

Txt2Img

Img2Img + ADetailer

Upscale

Full multi-stage pipeline

Phase 1 pipeline journey

Failures are top-of-stack symptoms of earlier contract issues

3.9 Prompt Pack Tests (v1/v2 Drift)

Expected "alpha" but real packs load default SDXL packs

Selection state mismatches

User-facing messages don’t align with test expectations

4. Prioritized Triage

Tests are assigned to Now / Soon / Later / Maybe-never buckets.

🔴 NOW — Must Fix Before Any Large Refactors
Area	Representative Tests	Reason
DummyProcess contract	test_webui_process_manager.py::test_stop_handles_already_exited_process	Missing .terminated flag causes base process tests to fail
FakePipeline signature alignment	All failing test_learning_hooks_pipeline_runner, test_pipeline_runner_*, test_stage_sequencer_runner_integration	Hard contract mismatch between PipelineRunner and test FakePipeline
RunConfig wiring in controller	test_app_controller_config & test_app_controller_pipeline_integration	Controller initializes with run_config=None under V2.5
Job history result contract	test_job_history_service.py::test_history_service_records_result	JobViewModel missing .result or updated equivalent
WebUI resource refresh	Resource mismatch in test_adetailer_stage_integration_v2 and test_resource_refresh_v2	Must align with ADetailer/refiner/hires contract
GUI entrypoint import errors	Two failing tests referencing invalid import path	App bootstrap tests broken

Rationale:
These failures reflect broken contracts or invalid wiring. Downstream tests depend on these being correct.

🟠 SOON — Behavioral & Lifecycle Correctness (High Value)
Area	Tests	Reason
Controller pipeline lifecycle	All test_app_controller_pipeline_flow_pr0	Validate run/stop/cancel/recovery behavior
GUI V2 dropdown & status bar	test_pipeline_dropdown_refresh_v2, test_status_bar_v2	Must reflect accurate state transitions
Phase 1 pipeline journey	test_phase1_pipeline_journey_v2	Core e2e smoke for V2.5
Stage cards layout	test_stage_cards_layout_v2 (assert False)	Needs real assertions
🟡 LATER — Full Journey Suite & Non-Core UX
Area	Tests	Reason
JT03 Txt2Img	All in file	Blocked on FakePipeline/RunConfig fixes
JT04 Img2Img + ADetailer	All in file	Blocked on resource refresh and lifecycle fixes
JT05 Upscale	All in file	Blocked on FakePipeline, stage signatures
v2_full journey	All in file	Final integration test after fixes completed

These depend heavily on the “Now” and “Soon” layers.

⚪ MAYBE-NEVER — Potential Deprecation Candidates
Area	Reason
Phase1 journey vs JT0x suite	Redundant once JT03/04/05 and v2_full are stable
Pack controller tests	If prompt pack UX is fully redefined for V2.5
V1 remnants	Once V1 files are formally archived, remove any tests referencing them

Condition:
No tests are removed until a dedicated PR formally deprecates the corresponding feature.

5. Proposed Follow-On PR Work Packages

Below are PR-shaped work packages for future implementation.

These PRs do not correspond to existing PR numbers unless explicitly assigned later.

📦 Work Package A – Core Contracts & Harness Repair (NOW)

Intent: Fix DummyProcess, FakePipeline signatures, and related harness utilities.

Add .terminated (or equivalent) to DummyProcess.

Create/update tests/helpers/fake_pipeline.py as the canonical FakePipeline.

Align FakePipeline’s run_*_stage signatures with PipelineRunner.

Update all pipeline + learning tests to rely on this shared helper.

Dependencies: None
Unlocks: PipelineRunner tests, journeys, controller lifecycle tests.

📦 Work Package B – GUI Entrypoint Alignment (NOW)

Intent: Ensure app entrypoint imports and tests consistently target V2 GUI.

Standardize entrypoint to use main_window_v2.

Remove or alias any legacy main_window imports.

Fix tests referencing invalid main_window.tk path.

Add minimal smoke test verifying V2 GUI boot logic.

📦 Work Package C – Controller RunConfig Wiring (NOW)

Intent: Ensure AppController initializes run_config consistently.

Introduce a RunConfig factory for tests (PR-082D).

Ensure controller.run_config is non-None at bootstrap.

Make config integration tests use harnessed pipeline/tab frames.

📦 Work Package D – Resource Refresh Contract (NOW)

Intent: Align WebUI resource shape → controller → ADetailer/refiner/hires cards.

Define canonical resource dict structure (doc + tests).

Update controller refresh logic.

Update stage cards to expect the defined shape.

📦 Work Package E – Lifecycle & GUI Behavior (SOON)

Intent: Fix pipeline PR-0 flow behavior and GUI V2 dropdown/status bar.

Standardize lifecycle transitions: IDLE → RUNNING → DONE/ERROR → IDLE.

Harmonize tests around new behavior.

Fix dropdown refresh pipeline.

Fix status bar transitions.

📦 Work Package F – Journeys Restoration (LATER)

Intent: Reactivate journey suite one-by-one.

JT03 (Txt2Img)

JT04 (Img2Img + ADetailer)

JT05 (Upscale)

v2_full_pipeline_journey

Focus on verifying final V2.5 sequencing (refiner + hires + ADetailer) works correctly.

📦 Work Package G – Packs & UX Stabilization (LATER / MAYBE-NEVER)

Intent: Align or retire pack behavior tests based on V2.5 direction.

Update prompt pack load/selection logic tests to new UX contract.

Or formally deprecate if being replaced by Prompt Workspace v2.

6. Coverage Milestones
Milestone	Target	Requirements
M1: 52%	+2%	All NOW items fixed; no test errors
M2: 55%+	Coverage threshold met	All NOW + SOON items fixed; Phase1 journey green
M3: 58–60%	Healthy baseline	Re-enabled JT03/04/05 and v2_full
M4: 65%+	Stretch goal	Pack tests aligned; learning/view tables stabilized
7. Work Dependencies

A dependency graph should be maintained in tests/docs.
Simplified outline:

Core Contracts (DummyProcess, FakePipeline)
        ↓
RunConfig Wiring ↔ GUI Entrypoint
        ↓
Lifecycle Tests (PR-0 suite)
        ↓
Resource Refresh (ADetailer/Refiner/Hires)
        ↓
Phase1 Journey
        ↓
JT03 / JT04 / JT05
        ↓
v2_full journey

8. Maintenance & Updating This Document

This doc is a living artifact.

Update it whenever:

New failures appear

Coverage milestones are reached

Architectural decisions change

Deprecated features are archived

Each update should increment the version header.

9. Acceptance Criteria for PR-085

This document exists at:
docs/tests/PR-085-Test-Coverage-Uplift-Plan-V2_5.md

The content matches the structure defined above.

All failing tests identified are categorized and prioritized.

Work packages for future PRs are clearly articulated.

Coverage milestones and dependency graph included.

No code or test modifications in this PR.

Document is directly usable by Codex/Copilot for planning.

End of Document