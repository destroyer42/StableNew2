<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PR-085 – Test Coverage Uplift & Triage Plan (V2.5)

Version: V2.5  
Last Updated: 2025-12-02  
Owner: StableNewV2 Test & Quality Working Group  
Status: Active Planning Document (Living Artifact)

## 1. Purpose

This document keeps the test uplift effort aligned with the realities of the V2.5 platform. It turns current test failures into actionable buckets, defines “Now/Soon/Later” priorities, and hands off named work packages that map to upcoming PRs (PR-082(x), PR-083, PR-081D(x), PR-081E, etc.). AI agents can read this to plan the next test-stability change that moves coverage toward the 55 % bar.

## 2. Current Coverage Snapshot

- **Total coverage**: 49.95% (last phase).  
- **Required threshold**: 55.0%.  
- **Gap**: –5.05%.

Gaps stem from:

1. Contract/API drift (FakePipeline signatures, DummyProcess, JobHistory result fields).  
2. Controller/GUI wiring misalignments (run_config None, status bar transitions).  
3. WebUI resource/learnings (missing ADetailer models, stage card expectations).  
4. V1/V2 hybrid artifacts (legacy entrypoints / prompt packs).  

## 3. Thematic Failure Groups

| Group | Impact | Representative Tests |
| --- | --- | --- |
| **3.1 Core Contracts & Test Harnesses** | Missing DummyProcess `.terminated`, FakePipeline stage signatures break runner/learning tests. | `tests/api/test_webui_process_manager.py`, `tests/pipeline/test_learning_hooks_pipeline_runner.py` |
| **3.2 GUI Entrypoint & Import Wiring** | Legacy `main_window` import no longer works; new GUI harness needed. | Bootstrapping parts of GUI V2 smoke/run controls |
| **3.3 Controller RunConfig Wiring** | `AppController` initial run config remains `None`. | `tests/controller/test_app_controller_config.py`, `test_app_controller_pipeline_integration.py` |
| **3.4 Job History Contract** | Results or errors not surfaced to job view models. | `tests/controller/test_job_history_service.py` |
| **3.5 WebUI Resource Refresh** | Stage cards expect ADetailer models/detectors, resources dict missing keys. | `tests/gui_v2/test_adetailer_stage_card_v2.py` |
| **3.6 Controller Lifecycle / Pipeline Flow** | Lifecycle states flake for run → stop → cancel. | `tests/controller/test_app_controller_pipeline_flow_pr0.py` |
| **3.7 GUI V2 Behavior** | Dropdown refresh & status bar tests failing; layout test has placeholder assert. | `tests/gui_v2/test_pipeline_dropdown_refresh_v2.py`, `test_status_bar_v2.py`, `test_stage_cards_layout_v2.py` |
| **3.8 Full Journey Tests (JT03–JT05 + v2_full)** | Top-level journeys fail until the above contracts are fixed. | `tests/journeys/test_jt03_*.py`, `test_jt04_*.py`, `test_jt05_*`, `test_v2_full_pipeline_journey.py` |
| **3.9 Prompt Pack Tests** | Pack selection state/outdated defaults mismatch V2 UX. | Legacy tests referencing V1 prompt packs |


## 4. Prioritized Triage

### 🔴 NOW – Critical Contracts

| Focus | Tests | Why Fix It Now |
| --- | --- | --- |
| DummyProcess contract | `test_webui_process_manager.py` | Broken process fixture halts the WebUI suite. |
| FakePipeline signatures | learning/pipeline integration tests | Contract mismatch means almost every downstream test fails. |
| Controller run_config wiring | `test_app_controller_config`, `test_app_controller_pipeline_integration` | Essential for controller logic + new coverage target. |
| Job history results | `test_job_history_service_records_result` | Jobs must persist results for histories and learning. |
| WebUI resource refresh | `test_adetailer_stage_card_v2`, resource refresher tests | ADetailer/refiner cards need consistent data. |
| GUI entrypoint imports | GUI smoke/run control tests | Legacy imports break UI bootstrapping. |

### 🟠 SOON – Behavioral & Lifecycle Coverage

| Focus | Tests | Reason |
| --- | --- | --- |
| Controller lifecycle | `tests/controller/test_app_controller_pipeline_flow_pr0.py` | Validates run/stop/cancel/recover transitions. |
| Status bar / dropdowns | `test_pipeline_dropdown_refresh_v2`, `test_status_bar_v2` | Must reflect real-time status/progress. |
| Phase 1 journey stability | `tests/journeys/test_phase1_pipeline_journey_v2.py` | Benchmark for future JT01–JT05 flows. |
| Stage layout assertions | `test_stage_cards_layout_v2.py` | Replace placeholder assert False with real checks. |

### 🟡 LATER – Journey Suite & UX

| Focus | Tests | Notes |
| --- | --- | --- |
| JT03/Txt2Img | `tests/journeys/test_jt03_*` | Blocked until harness/contracts stabilise. |
| JT04/Img2Img + ADetailer | `tests/journeys/test_jt04_*` | Needs resource & lifecycle fixes. |
| JT05/Upscale | `tests/journeys/test_jt05_*` | Depends on sequencing + FakePipeline improvements. |
| v2_full journey | `tests/journeys/test_v2_full_pipeline_journey.py` | Last to re-enable once the contract stack is solid. |

### ⚪ MAYBE-NEVER (Deprecated Paths)

| Focus | Level | Justification |
| --- | --- | --- |
| Phase1 journey | Legacy | Superseded by JT03–JT05 once stabilized. |
| Prompt pack tests | Potential archive | Rework or remove once packs align with V2.5 UX. |
| V1 artifacts | Low value | Remove once V1 is formally archived. |

## 5. Proposed Work Packages

### 📦 Package A – Core Contracts & Harness Repair (NOW)

- Fix DummyProcess (`terminated`, `.pid`, `.wait()`) in `tests/helpers/webui_mocks.py`.
- Align `tests/helpers/pipeline_fakes.py` with `PipelineRunner` stage signatures.
- Update pipeline/learning tests and journeys to import the shared helper.

### 📦 Package B – GUI Entry & RunConfig Alignment (NOW)

- Standardize entrypoint to `main_window_v2`, use shared `GuiV2Harness`.
- Ensure `AppController` initializes `run_config` (use `make_run_config()`).
- Use helper factories in controller config/integration tests.

### 📦 Package C – Resource Refresh Contract (NOW)

- Define canonical `resources` dict (models, vaes, adetailer models/detectors, upscalers).
- Update `StageCards` & controller refresh logic to consume it.
- Assert the shape in tests.

### 📦 Package D – Lifecycle & GUI Behavior (SOON)

- IDLE → RUNNING → COMPLETED/ERROR flow tests.
- Status bar/run controls display the right text.
- Dropdown refresh & stage card layout tests no longer skip.

### 📦 Package E – Journeys & Full Sequencing (LATER)

- Run JT03, JT04, JT05, v2_full using shared harness + start_run.
- Document coverage expectations for each journey (map to doc).

### 📦 Package F – Prompt-Pack UX (LATER/MAYBE)

- Align or archive prompt pack tests once the UI is rewritten.
- Ensure history/packs handle new config payloads.

## 6. Coverage Milestones

| Milestone | Target | Requirements |
| --- | --- | --- |
| **M1** | 52% | Fix all NOW/critical contract tests. |
| **M2** | 55% | NOW + SOON suites pass; phase‑1 journey smoke green. |
| **M3** | 58–60% | Re-enable JT03/04/05 + v2_full journeys. |
| **M4** | 65%+ | Pack/ux tests aligned; documentation/tests reference stage sequencing. |

## 7. Dependency Graph

Core Contracts (DummyProcess / FakePipeline)  
→ RunConfig + GUI Entry  
→ Lifecycle Tests  
→ Resource Refresh  
→ Phase1 Journey  
→ JT03 / JT04 / JT05  
→ v2_full Journey  

Each link must remain green before the next layer is unparked.

## 8. Maintenance

Update this living doc whenever:

- Coverage numbers change.
- New failing tests appear.
- Architecture decisions (sequencing, entrypoint, queue) shift.
- A feature is removed/archived.

Always increment the version header when updating.

## 9. Acceptance

This plan lives at `docs/tests/PR-085-Test-Coverage-Uplift-Plan-V2_5.md`.  
It defines the Now/Soon/Later buckets, work packages, coverage milestones, and the dependency graph.  
It should be referenced by PR-082(x), PR-083, PR-081D(x), PR-081E, and any upcoming quality deliverables.  
No code/test modifications are required in this doc-only PR.
