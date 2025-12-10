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

### Path 1: Legacy Payload-Based (Resolved in CORE1-B5)
```python
Job.payload = {"packs": [...], "run_config": {...}}
↓
AppController._execute_job() → reads payload dict
↓
_execute_pack_entry() → legacy execution
```

> **Status:** Resolved (CORE1-B5). Payload-based entry points (`Job.payload`, `_execute_pack_entry`, `_build_pack_result`, RunPayload) have been removed; no new jobs use this path.

### Path 2: PipelineConfig-Based (Legacy-only after CORE1-C2)
```python
# Legacy jobs imported from history still carry pipeline_config blobs.
job = Job(job_id="legacy", pipeline_config=None)
job.pipeline_config = PipelineConfig(...)
?+
AppController._execute_job() ?+' detects the legacy config
?+
_run_pipeline_via_runner_only()
```
> **Status:** Restricted to legacy history imports (PR-CORE1-C2). New jobs never populate `pipeline_config`; any legacy payloads are rehydrated from history via the adapter.

### Path 3: NormalizedJobRecord-Based (PR-CORE-B/C - Incomplete)
```python
NormalizedJobRecord → "canonical job representation"
↓
??? (No clear execution path)
```

### Path 4: Direct Runner Invocation (Tests/Debug) *(Resolved in CORE1-B4)*
```python
PipelineRunner.run(config) → Direct execution
```

**Problem:** These paths used to diverge, but most have now been collapsed: Path 1 was deleted in CORE1-B5, Path 4 was migrated through the NJR adapter in CORE1-B4, and Path 2 now exists only for legacy history imports (PR-CORE1-C2), leaving the canonical NormalizedJobRecord path as the sole active execution model.

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
     - **Status:** JobBundle-centric flows retired in CORE1-C3B; AppStateV2.job_draft alone manages draft intent while JobBuilderV2 produces NJRs.

3. **Job → NormalizedJobRecord (PR-CORE-B/C)**
   - Old: `Job` class
   - New: `NormalizedJobRecord` class
   - **Status:** Job still used for execution, NormalizedJobRecord for... display?

4. **StateManager → AppStateV2**
   - Old: `StateManager` in `src/gui/state.py`
   - New: `AppStateV2` in `src/gui/gui_state.py`
   - **Status:** AppStateV2 is now the canonical cross-subsystem state; GUI retains a local state machine
   - **Resolution:** PR-CORE1-C1 and PR-CORE1-C3A removed StateManager from core controllers and controller tests, while GUI/legacy state coverage now lives in `tests/gui/test_state_manager_legacy.py`
   - **Remaining:** GUI still owns StateManager for UI-only state; removal planned for PR-GUI-C-series

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
     - Status: Removed in favor of NJR→JobUiSummary mappings; legacy DTOs are no longer produced for current flows.

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
1. **Pick ONE job type:** NormalizedJobRecord; pipeline_config-only jobs are retired and exist solely as legacy history blobs (PR-CORE1-C2).
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
- **Controller indirection layers:** 5 (GUI → AppController → PipelineController → JobExecutionController → Runner); PR-CORE1-C5 removed the QueueExecutionController façade.
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

---

## Status Update: PR-CORE1-A3 (December 9, 2025)

### ✅ **Resolved in PR-CORE1-A3: Display Layer Unification**

**What Was Fixed:**
1. **Preview/Queue/History Panels Now NJR-Only**
   - All display panels use `UnifiedJobSummary`, `JobQueueItemDTO`, `JobHistoryItemDTO`
   - DTOs derive from `NormalizedJobRecord` snapshots, NOT from `pipeline_config`
   - JobService and JobHistoryService prefer NJR snapshots for display data
   - Legacy `pipeline_config` fallback preserved only for old jobs without NJR snapshots

2. **JobBundle/JobBundleBuilder Retired (CORE1-C3B)**
     - JobBundle-based helpers have been removed entirely; controllers no longer expose `_draft_bundle` or bundle DTOs.
     - AppStateV2.job_draft plus JobBuilderV2 now drive preview and queue flows.
     - Documentation and tests updated to reflect the NJR-only pipeline and the lack of JobBundle targets.

3. **Documentation Updated**
   - `ARCHITECTURE_v2.6.md` now documents **CORE1 Hybrid State**
   - `Builder Pipeline Deep-Dive v2.6` clarifies JobBuilderV2 vs JobBundle roles
   - Test files updated to assert NJR-based display

**Impact:**
- ❌ Removed: `pipeline_config` introspection for display purposes (new jobs)
- ✅ Preserved: `pipeline_config` execution path (unchanged per CORE1-A3 scope)
- ✅ Unified: Preview, queue, history all use same NJR-derived DTOs

### ⏳ **Remaining Technical Debt (Deferred to CORE1-B)**

**Display Layer Unification (CORE1-A3):** ✅ **COMPLETE**
- Preview/queue/history DTOs use NJR snapshots
- No display logic introspects `pipeline_config`
- JobBuilderV2 is canonical job builder

**Execution Path Migration (CORE1-B2):** ✅ **RESOLVED for New Jobs**
- ✅ **NJR is the ONLY execution path for new queue jobs** (PR-CORE1-B2 complete)
- ✅ `AppController._execute_job()` uses NJR-only execution when `_normalized_record` present
- ✅ No fallback to `pipeline_config` for NJR-backed jobs (failures return error status)
- ✅ Routes to `PipelineController._run_job()` → `PipelineRunner.run_njr()` exclusively
- ✅ All jobs created via `_to_queue_job()` have `_normalized_record` attached
- ⚠️ PR-CORE1-B3: _to_queue_job() clears pipeline_config, so NJR-only jobs never expose it
- ⏳ `pipeline_config` field still exists as **legacy debug field** for inspection
- ⏳ `pipeline_config` execution branch preserved for **legacy jobs only** (pre-v2.6, imported)
- **Remaining work: Full pipeline_config field/method removal (CORE1-C) - after legacy job migration complete**

**State System Consolidation (CORE1-C/D - NOT YET STARTED):**
- Multiple state systems still exist (StateManager, AppStateV2, PipelineController._draft_bundle)
- Dynamic attribute injection (`_app_state_for_enqueue`) and reflection-based dispatch have been replaced by the explicit controller event API (PR-CORE1-C4A); controllers now rely on AppStateV2 job drafts only.
- Full state unification deferred to later phases

**Controller Pattern Unification (CORE1-E - NOT YET STARTED):**
- Explicit controller event entrypoints have been published (PR-CORE1-C4A), addressing the mixed callback/reflection patterns noted earlier.
- 7-layer indirection chains remain unchanged
- QueueExecutionController has been removed (PR-CORE1-C5), collapsing the queue execution path down to PipelineController → JobExecutionController → Runner.
- Architectural simplification deferred

### 📊 **Updated Metrics**

| Metric | Before CORE1-A3 | After CORE1-A3 | After CORE1-B1 | After CORE1-B2 | Target (CORE1 Complete) |
|--------|----------------|----------------|----------------|----------------|------------------------|
| Job execution paths | 4 | **3** (display unified) | **2** (NJR preferred) | **1.5** (NJR-only for new) | 1 |
| State management systems | 4 | 4 | 4 | 4 | 1 |
| Display DTO sources | Mixed | **NJR-only** ✅ | **NJR-only** ✅ | **NJR-only** ✅ | NJR-only |
| Execution payload | `pipeline_config` | `pipeline_config` | **Hybrid (NJR preferred)** | **NJR-only (new jobs, pipeline_config removed)** ✅ | NJR |
| JobBuilder implementations | 2 (JobBuilderV2 + JobBundleBuilder) | 2 (transitional) | 2 (transitional) | 1 (JobBuilderV2 only) | 1 |

**Key Achievements:** 
- ✅ Display layer is NJR-driven (CORE1-A3)
- ✅ Execution layer is NJR-only for new jobs, legacy support for old jobs (CORE1-B2)
- ✅ PR-CORE1-B4 removes `PipelineRunner.run(config)` and routes every execution through `run_njr` via the legacy NJR adapter.
- ✅ CORE1-D1 migrates legacy history to NJR-only snapshots; history replay no longer depends on pipeline_config payloads.
- ƒo. PR-CORE1-B3 ensures _to_queue_job() clears pipeline_config, so new jobs carry only NJR snapshots

**Next Steps (CORE1-C):**
1. ✅ CORE1-D1: Legacy history entries auto-migrate to NJR snapshots; pipeline_config/draft-bundle persistence removed from history.
2. Remove `run(config)` method from PipelineRunner (keep only `run_njr`)
3. Clean up legacy execution branches in AppController
4. Add explicit tests for NJR-only execution
5. Remove dynamic attribute injection workarounds
