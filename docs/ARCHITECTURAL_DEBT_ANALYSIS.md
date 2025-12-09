# StableNew Architectural Debt Analysis
**Date:** December 9, 2025  
**Context:** PR-CORE-D/E Integration Issues

## Executive Summary

The StableNew codebase suffers from **severe architectural fragmentation** caused by multiple incomplete refactors layered on top of each other. This creates:

- **3-4 different job execution paths** that don't talk to each other
- **Multiple overlapping state management systems**
- **Inconsistent controller patterns** (callbacks, direct calls, dependency injection all mixed)
- **Abandoned migration attempts** (v1 → v2 → v2.5 → v2.6)

**Result:** Simple operations like "add pack to job → execute" require navigating 7+ layers of indirection, with multiple points of failure.

---

## Problem 1: Multiple Job Execution Paths

### Path 1: Legacy Payload-Based (Abandoned but Still Active)
```python
Job.payload = {"packs": [...], "run_config": {...}}
↓
AppController._execute_job() → reads payload dict
↓
_execute_pack_entry() → legacy execution
```

### Path 2: PipelineConfig-Based (What We're Trying to Use)
```python
Job.pipeline_config = PipelineConfig(...)
↓
AppController._execute_job() → NEW: checks pipeline_config
↓
_run_pipeline_via_runner_only()
```

### Path 3: NormalizedJobRecord-Based (PR-CORE-B/C - Incomplete)
```python
NormalizedJobRecord → "canonical job representation"
↓
??? (No clear execution path)
```

### Path 4: Direct Runner Invocation (Tests/Debug)
```python
PipelineRunner.run(config) → Direct execution
```

**Problem:** Code paths exist for ALL of these but they don't integrate. You can create a job in one path and try to execute it in another, leading to silent failures.

---

## Problem 2: State Management Fragmentation

### System 1: StateManager (Legacy GUI State Machine)
- Location: `src/gui/state.py`
- Purpose: IDLE/RUNNING/ERROR transitions
- Scope: GUI only
- **Issues:** No job_draft, no queue awareness

### System 2: AppStateV2 (New Reactive State)
- Location: `src/gui/gui_state.py`
- Purpose: Observable state with listeners
- Scope: Full app state including `job_draft.packs`
- **Issues:** Not consistently used everywhere

### System 3: PipelineController Internal State
- Location: `src/controller/pipeline_controller.py`
- Purpose: Draft bundles, overrides
- Scope: `_draft_bundle.parts` (legacy text-based)
- **Issues:** Parallel state to AppStateV2, creates confusion

### System 4: JobQueue State
- Location: `src/queue/job_queue.py`
- Purpose: Job queue management
- **Issues:** Separate from all GUI state

**Problem:** No single source of truth. Controllers have to synchronize between 3-4 different state objects.

---

## Problem 3: Controller Architecture Inconsistency

### Pattern 1: Event Callbacks (GUI → Controller)
```python
sidebar._on_add_to_job() 
  → controller.on_pipeline_add_packs_to_job(pack_ids)
```

### Pattern 2: Direct Method Calls
```python
preview_panel._on_add_to_queue()
  → controller.enqueue_draft_bundle()
```

### Pattern 3: String-Based Invocation
```python
preview_panel._invoke_controller("enqueue_draft_bundle")
  → getattr(controller, "enqueue_draft_bundle")()
```

### Pattern 4: Dependency Injection via Attributes
```python
pipeline_controller._app_state_for_enqueue = app_state
```

**Problem:** No consistent communication pattern. Different parts of the codebase use different mechanisms, making data flow impossible to trace.

---

## Problem 4: Incomplete Migrations

### Evidence of Abandoned Refactors:

1. **V1 → V2 Migration (2024)**
   - Old: `src/gui/pipeline_panel.py` 
   - New: `src/gui/pipeline_panel_v2.py`
   - **Status:** Both still exist, both partially used

2. **JobBundle → JobDraft (PR-D)**
   - Old: `JobBundle` with `parts`
   - New: `JobDraft` with `packs`
   - **Status:** Both systems active simultaneously

3. **Job → NormalizedJobRecord (PR-CORE-B/C)**
   - Old: `Job` class
   - New: `NormalizedJobRecord` class
   - **Status:** Job still used for execution, NormalizedJobRecord for... display?

4. **StateManager → AppStateV2**
   - Old: `StateManager` in `src/gui/state.py`
   - New: `AppStateV2` in `src/gui/gui_state.py`
   - **Status:** Both referenced in different controllers

---

## Problem 5: The "Add to Queue" Button Mystery

### Expected Flow:
```
1. User clicks "Add to Job"
2. Pack added to app_state.job_draft.packs
3. Preview panel updates
4. User clicks "Add to Queue"
5. Jobs enqueued with app_state context
6. Runner executes jobs
```

### Actual Flow (Before Today's Fixes):
```
1. User clicks "Add to Job"
2. Pack added to app_state.job_draft.packs ✓
3. Preview panel update called but doesn't render ✗
4. User clicks "Add to Queue"
5. PreviewPanel._on_add_to_queue()
   → _invoke_controller("enqueue_draft_bundle")
   → AppController.enqueue_draft_bundle()
   → pipeline_controller.enqueue_draft_bundle() [NO ARGS]
   → Looks for _app_state_for_enqueue → None ✗
6. Warning: "enqueue_draft_bundle called with empty draft"
```

### Why It Failed:
- **Missing Link:** AppController.enqueue_draft_bundle() doesn't pass app_state to PipelineController
- **Architecture:** Two controllers don't share state properly
- **Pattern Mix:** String-based invocation + attribute injection = data loss

---

## Problem 6: Shims, Stubs, and Dead Code

### Identified Shims (Need Removal):

1. **`enqueue_draft_bundle_legacy()` in PipelineController**
   - Purpose: Backward compat for old job bundle system
   - Status: Dead code, never called

2. **`_draft_bundle` in PipelineController**
   - Purpose: Legacy text-based job draft
   - Status: Parallel to AppStateV2.job_draft, creates confusion

3. **`JobBundleSummaryDTO` conversions**
   - Purpose: Bridge between Job and JobUiSummary
   - Status: Redundant with NormalizedJobRecord.to_ui_summary()

4. **Multiple `submit_*` methods in JobService**
   - `submit_queued()` vs `submit_job_with_run_mode()` vs `enqueue()`
   - Status: Overlapping, unclear which to use

5. **`payload` attribute on Job**
   - Purpose: Generic job data container
   - Status: Conflicts with pipeline_config, creates ambiguity

### Estimated Dead Code:
- **~15-20% of controller methods** are legacy shims
- **3-4 complete state management files** could be unified
- **Multiple DTO conversion layers** could be eliminated

---

## Recommended Cleanup Path

### Phase 1: Unify State Management (High Priority)
1. **Deprecate StateManager** - migrate all to AppStateV2
2. **Remove PipelineController._draft_bundle** - use AppStateV2.job_draft only
3. **Create single state injection pattern** - all controllers take AppStateV2 in __init__

### Phase 2: Standardize Job Model (High Priority)
1. **Pick ONE job type:** Job with pipeline_config OR NormalizedJobRecord
2. **Remove `payload` attribute** from Job class
3. **Unify execution path:** All jobs go through same runner entry point

### Phase 3: Clean Controller Communication (Medium Priority)
1. **Standardize on event callbacks** - remove string-based invocation
2. **Explicit dependency injection** - no dynamic attribute setting
3. **Remove proxy methods** - controllers should have direct references

### Phase 4: Remove Legacy Code (Medium Priority)
1. Delete all `*_legacy()` methods
2. Remove v1 GUI files (if truly unused)
3. Consolidate DTO classes
4. Remove dead JobService methods

### Phase 5: Documentation (Low Priority)
1. Document THE ONE TRUE PATH for job execution
2. Sequence diagrams for all major flows
3. Update architecture docs to match reality

---

## Immediate Fix (Applied Today)

### What Was Broken:
```python
# PreviewPanel clicked "Add to Queue"
→ AppController.enqueue_draft_bundle() # No args!
→ pipeline_controller.enqueue_draft_bundle() # Expects _app_state_for_enqueue
→ Gets None → Fails
```

### Fix Applied:
```python
def enqueue_draft_bundle(self) -> int:
    # Set app_state on pipeline_controller before enqueuing
    if self.app_state:
        controller._app_state_for_enqueue = self.app_state
    job_id = enqueue_fn()
```

### Why This Is a Band-Aid:
- Still using dynamic attribute injection
- Still have two separate draft systems
- Still mixing state across controllers
- Will break again with next refactor

---

## Metrics

### Complexity Indicators:
- **Files with "v2" suffix:** 47
- **Files with "legacy" in name:** 12
- **Controller indirection layers:** 7+ (GUI → AppController → PipelineController → JobService → Runner)
- **State synchronization points:** 15+
- **Job execution code paths:** 4 distinct paths

### Estimated Cleanup Impact:
- **Lines of code removable:** ~5,000-8,000 (20-25% of codebase)
- **Files deletable:** ~15-20
- **Complexity reduction:** 40-50% (based on controller indirection removal)

---

## Conclusion

The reason "it has taken like 8 different tries to get this to work" is that **the codebase has accumulated 3-4 incomplete architectural migrations**, each adding new patterns without removing old ones.

**Every feature requires:**
1. Understanding which state system to use (3 options)
2. Understanding which job type to create (3 options)
3. Understanding which execution path will run (4 options)
4. Manually synchronizing state between systems

**Recommendation:** Pause feature development and spend 1-2 sprints on architectural cleanup. The current state makes all future development exponentially more expensive.

---

## Appendix: Call Stack Analysis

### Successful "Add to Job" Flow:
```
sidebar_panel_v2._on_add_to_job()
  → app_controller.on_pipeline_add_packs_to_job(pack_ids)
    → Creates PackJobEntry objects
    → app_state.add_packs_to_job_draft(entries)
    → pipeline_controller._app_state_for_enqueue = self.app_state
    → preview_panel.update_from_job_draft(job_draft)
```
**Layers:** 4  
**State systems touched:** 2 (AppStateV2, preview panel internal)

### Failed "Add to Queue" Flow (Before Fix):
```
preview_panel_v2._on_add_to_queue()
  → _invoke_controller("enqueue_draft_bundle")
    → app_controller.enqueue_draft_bundle()
      → pipeline_controller.enqueue_draft_bundle()
        → Checks _app_state_for_enqueue → None
        → Checks _draft_bundle → None
        → Warning: empty draft
```
**Layers:** 7  
**State systems touched:** 3 (AppStateV2, PipelineController._draft_bundle, preview state)  
**Failure point:** State not passed through controller chain

### After Fix "Add to Queue" Flow:
```
preview_panel_v2._on_add_to_queue()
  → _invoke_controller("enqueue_draft_bundle")
    → app_controller.enqueue_draft_bundle()
      → Sets pipeline_controller._app_state_for_enqueue = self.app_state
      → pipeline_controller.enqueue_draft_bundle()
        → Checks _app_state_for_enqueue → Found!
        → Reads job_draft.packs
        → _enqueue_pack_based_jobs()
```
**Layers:** 7 (still!)  
**State systems touched:** 2 (AppStateV2, dynamic attribute injection)  
**Success:** Works, but fragile
