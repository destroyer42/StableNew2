#CANONICAL
# StableNew Coding and Testing Standards (v2.5)

---

# Executive Summary (8–10 lines)

This document defines how code must be written, structured, and tested in StableNew v2.5.  
It aligns with the canonical architecture, governance, and roadmap documents, and gives both humans and AI agents concrete rules for formatting, design patterns, test coverage, and validation workflows.  
The goal is to ensure that every change is small, reviewable, testable, and consistent with the job lifecycle and subsystem boundaries.  
All pipeline, controller, and queue changes MUST be covered by targeted tests; GUI changes SHOULD include behavior tests whenever feasible.  
These standards also define how to design pure functions, dataclasses, and adapters, and how to structure tests around ConfigMergerV2, JobBuilderV2, NormalizedJobRecord, JobService, and GUI panels.  
This file is required reading for contributors and agents generating PRs that modify code.

---

# PR-Relevant Facts (Quick Reference)

- All code changes must follow these standards.  
- Pure logic (mergers, builders, job models) MUST be in testable, GUI-independent modules.  
- Controllers must be thin orchestrators and heavily tested via integration tests.  
- GUI code must not embed pipeline or queue logic; it must call controller methods.  
- Tests MUST be written “failing first” for logic-affecting changes.  
- No PR may reduce test coverage in critical subsystems (pipeline, controller, queue).  
- Coding style emphasizes explicitness, immutability where practical, and small functions.  

---

============================================================
# 0. TLDR / BLUF — Coding & Testing Cheat Sheet
============================================================

### 0.1 Coding TLDR

- **Use dataclasses** for structured data (configs, overrides, job records).  
- **Keep logic pure** where possible (no side effects, no global state).  
- **Respect subsystem boundaries** (GUI vs controller vs pipeline vs queue vs runner).  
- **Minimal imports across boundaries** — prefer adapters and typed interfaces.  
- **No “magic paths”** that bypass ConfigMergerV2, JobBuilderV2, or NormalizedJobRecord.

### 0.2 Testing TLDR

- Pipeline changes → **unit tests + integration tests**.  
- Controller changes → **integration tests** (controller ↔ pipeline ↔ queue).  
- Queue changes → **lifecycle + ordering tests**.  
- GUI changes → **behavior tests** when feasible (panel state, callbacks, preview/queue wiring).  
- All meaningful logic must be tested **failing first**.  

### 0.3 Structure TLDR

- `src/` is for production code.  
- `tests/` mirrors the package layout (e.g., `tests/pipeline`, `tests/controller`, `tests/gui_v2`).  
- Names reflect responsibilities (e.g., `config_merger_v2.py`, `job_builder_v2.py`).  
- Test files follow `test_<module>_v2.py` or similar pattern.

---

============================================================
# 1. Purpose and Scope
============================================================

This document is the **sole canonical reference** for:

- Coding style
- Structural patterns
- Testing strategy
- CI expectations
- How to write, adapt, and test code in StableNew

It applies to:

- All new code (v2.5+)  
- All refactors of existing code  
- All AI-generated PRs  
- All manual PRs touching pipeline, controllers, queue, GUI, or tests  

It does NOT restate architecture or governance rules; it operationalizes them.

---

============================================================
# 2. Core Coding Principles
============================================================

### 2.1 Single Source of Truth

- Config and pipeline behavior must be defined once and reused.
- The job lifecycle (ConfigMergerV2 → JobBuilderV2 → NormalizedJobRecord → Queue → Runner) is the **only** valid path.
- No parallel or duplicate config systems.

### 2.2 Purity & Immutability Where Possible

- Prefer pure functions that return new objects rather than mutating inputs.
- Dataclasses representing configs should be treated as immutable from callers’ perspective, even if fields are technically mutable.

### 2.3 Explicit Over Implicit

- Avoid magic numbers, hidden state, and “doEverything()” APIs.
- Prefer explicit arguments and clearly named dataclasses.

### 2.4 Small, Composable Units

- Functions and methods should be small and focused.
- Split complex logic into helpers.
- Pipeline steps should be testable in isolation.

---

============================================================
# 3. File and Module Structure
============================================================

### 3.1 Production Code Layout

- `src/gui/...` — GUI V2 views, panels, widgets, AppState.  
- `src/controller/...` — AppController, PipelineControllerV2, and similar orchestrators.  
- `src/pipeline/...` — ConfigMergerV2, JobBuilderV2, job models (NormalizedJobRecord), run config structures.  
- `src/queue/` or `src/pipeline/job_service.py` — job queue, job service, lifecycle logic.  
- `src/randomizer/...` — Randomization engine and plan dataclasses.  
- `src/learning/...` — Learning System modules (Phase 2).  
- `src/cluster/...` — Cluster compute modules (Phase 3).

### 3.2 Tests Layout

- Mirror production layout:  
  - `tests/pipeline/test_config_merger_v2.py`  
  - `tests/pipeline/test_job_builder_v2.py`  
  - `tests/controller/test_pipeline_controller_v2.py`  
  - `tests/gui_v2/test_preview_panel_v2.py`  
  - `tests/gui_v2/test_queue_panel_v2.py`  

Each major module should have at least one corresponding test file.

---

============================================================
# 4. Coding Conventions
============================================================

### 4.1 Naming

- Modules: `snake_case`, with `_v2` or `_v2_5` suffix where needed to distinguish from legacy.
- Classes: `PascalCase` (`ConfigMergerV2`, `JobBuilderV2`, `NormalizedJobRecord`).
- Functions: `snake_case`, descriptive (`merge_pipeline_config`, `build_jobs`, `to_ui_summary`).
- Tests: `test_<concise_behavior_name>`.

### 4.2 Dataclasses

- Use `@dataclass` for structured data, with `frozen=True` where practical for flags and config descriptors.
- Provide default factories for lists/dicts.
- Define `to_queue_snapshot()` / `to_ui_summary()` adapters on models instead of performing transformations in controllers.

### 4.3 Imports and Dependencies

- Avoid cross-layer imports that break boundaries (e.g., GUI importing pipeline internals).
- Use type-only imports to minimize circular dependencies.
- Centralize shared types in clearly named modules (e.g., `job_models_v2.py`).

---

============================================================
# 5. Pipeline & Job Model Coding Standards
============================================================

### 5.1 ConfigMergerV2

- Must remain **pure**: no side effects, no I/O.
- Must not import GUI or controllers.
- Must handle override flags and nested stage configs deterministically.
- Tests must cover:
  - override off → base config preserved
  - override on → overrides applied
  - nested stage disable behavior
  - immutability (input configs unchanged)

### 5.2 JobBuilderV2

- Must accept:
  - MergedRunConfig
  - RandomizationPlanV2 (if present)
  - Batch and output settings
- Must emit:
  - A list of NormalizedJobRecord objects
- Must not:
  - Interact with GUI
  - Write to disk
  - Communicate with queue or runner
- Tests must cover:
  - Single-job builds
  - Variant and batch expansion
  - Seed modes
  - Correct variant/batch indices

### 5.3 NormalizedJobRecord

- Central job representation.
- Must define:
  - config snapshot
  - seed
  - variant_index, batch_index
  - output settings
  - metadata for UI and queue
- Must be convertible:
  - To queue format (`to_queue_snapshot`)
  - To UI summary (`to_ui_summary`)
- Tests must verify conversions and data integrity.

---

============================================================
# 6. Controller Coding Standards
============================================================

### 6.1 Responsibilities

Controllers must:

- Read from AppState
- Invoke ConfigMergerV2 and JobBuilderV2
- Submit jobs to JobService
- Update Preview/Queue panels with normalized jobs
- Enforce run-mode semantics (direct vs queue)
- Never embed pipeline logic directly

### 6.2 Patterns

- Use small helper methods like `_build_normalized_jobs_from_state`.
- Inject dependencies (job_builder, job_service) for testability.
- Avoid deep nesting; prefer clearly named helper methods.

### 6.3 Testing

- Use integration tests:
  - Given AppState + config + randomization plan
  - Verify correct jobs are built and passed to JobService
- Use mocks/spies for JobService to assert calls, not actual execution.

---

============================================================
# 7. GUI Coding and Testing Standards
============================================================

### 7.1 GUI Responsibilities

GUI panels must:

- Create and manage widgets.
- Reflect state from AppState.
- Forward events to controllers via callbacks.
- Render normalized job summaries in preview and queue panels.

They must NOT:

- Perform merging or building logic.
- Call JobService directly.
- Decide on pipeline sequencing.

### 7.2 Dark Mode & Styling

- Use theme tokens defined in theme_v2 (or equivalent).
- Do not hard-code colors or fonts; rely on style configuration.
- Fix known light-mode leftovers as incremental PRs with visual checks.

### 7.3 GUI Testing

- Use GUI tests (skipped if Tk not available) to verify:
  - Panel creation does not error.
  - Callbacks are wired correctly (on_click, on_change).
  - PreviewPanel and QueuePanel update correctly given normalized jobs.
- Prefer small, focused tests over giant UI flows.

---

============================================================
# 8. Queue & Runner Testing Standards
============================================================

### 8.1 Queue Tests

- Must verify:
  - Jobs are enqueued in correct order.
  - Reordering works as expected.
  - Removal (single job, clear queue) works correctly.
  - States (pending, running, completed, failed, cancelled) transition correctly.
  - History recording tests verify JobService → JobHistoryService flows capture completed and failed jobs.
  - JobService emits `EVENT_JOB_STARTED`, `EVENT_JOB_FINISHED`, and `EVENT_JOB_FAILED` callbacks whenever those queue state transitions occur so that GUI/history listeners can sample lifecycle changes.

### 8.2 Runner Tests

- Should validate:
  - Stage ordering: txt2img → img2img → refiner → hires → upscale → adetailer.
  - Stage skipping: disabled stages are skipped.
  - Proper passing of intermediate images/metadata.

### 8.3 Integration Tests

- Controller + JobService + Runner integration tests should confirm:
  - Correct pipeline payloads.
  - Correct job metadata preserved.

---

============================================================
# 9. Randomizer & Learning Testing Standards
============================================================

### 9.1 Randomizer

- Engine must be:
  - Deterministic with fixed seed.
  - Independent of GUI and JobService.
- Tests must cover:
  - Variant combinations.
  - Seed mode behavior.
  - Max variants truncation.
  - Isolation from legacy randomizer.

### 9.2 Learning System (Phase 2)

- Must record:
  - Config snapshot
  - Seed
  - Prompt
  - Runtime metrics
  - Quality metrics (manual/auto)
- Tests:
  - Learning record schema stability.
  - No pipeline behavior changes caused by learning hooks.
  - End-to-end tests verifying learning data written correctly.

---

============================================================
# 10. Test Strategy: Failing First and CI
============================================================

### 10.1 Failing First

- Before making changes, write failing tests that capture the desired behavior.
- Then:
  - Implement code
  - Run tests
  - Validate all pass
- This enforces behavior-driven development and reduces regressions.

### 10.2 CI Expectations

- PRs must run pytest on modified test suites.
- No PR may merge with failing tests (except explicitly documented flaky tests, and even then sparingly).
- Coverage goals:
  - Pipeline and controller code: very high coverage.
  - GUI: targeted coverage for behavior-critical paths.

---

============================================================
# 11. Examples & Patterns
============================================================

### 11.1 Good Pattern: Pipeline Function

```python
def merge_and_build_jobs(
    base_config: RunConfigV2,
    overrides: StageOverridesBundle,
    randomization_plan: RandomizationPlanV2,
    batch_settings: BatchSettings,
    output_settings: OutputSettings,
    *,
    merger: ConfigMergerV2,
    builder: JobBuilderV2,
) -> list[NormalizedJobRecord]:
    merged = merger.merge_pipeline(base_config, overrides)
    jobs = builder.build_jobs(
        merged_config=merged,
        randomization_plan=randomization_plan,
        batch_settings=batch_settings,
        output_settings=output_settings,
    )
    return jobs
11.2 Good Pattern: Controller Integration Test
python
Copy code
def test_controller_builds_jobs_and_submits_to_queue(job_builder, job_service, app_state):
    controller = PipelineControllerV2(
        app_state=app_state,
        job_builder=job_builder,
        job_service=job_service,
        # other deps...
    )

    # configure app_state...

    controller.start_pipeline_v2()

    job_builder.build_jobs.assert_called_once()
    job_service.submit_jobs.assert_called_once()
============================================================

12. Deprecated Patterns (Archived)
============================================================
#ARCHIVED
(This section is informational only; do NOT use these patterns.)

Deprecated:

Logic inside GUI event handlers that modifies pipeline behavior directly.

Controllers performing manual merging instead of using ConfigMergerV2.

Direct runner invocations bypassing JobService.

Use of V1 MainWindow pipeline code.

Untested changes to critical subsystems.

Single, massive test files that combine many subsystems.

Replaced by:

Clean layering.

Merger + Builder + Normalized job model.

JobService-managed execution.

Modular, focused test files.

End of StableNew_Coding_and_Testing_v2.5.md
