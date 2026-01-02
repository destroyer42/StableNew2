# GUI V2 Queue Tests - ARCHIVED

**Date Archived:** January 1, 2026  
**Reason:** Testing deprecated functionality removed in CORE1 architectural transition  
**Decision:** Archive rather than update, as underlying code no longer exists

---

## Summary

These 10 test files were archived because they test the **deprecated V2 queue system** (`QueueJobV2` and `JobQueueV2`) that was completely removed during the CORE1 job model unification.

**Archived Files:**
1. `test_job_queue_v2.py` - Tests for QueueJobV2 dataclass and JobQueueV2 queue operations
2. `test_queue_panel_autorun_and_send_job_v2.py` - Queue panel autorun behavior
3. `test_queue_panel_behavior_v2.py` - Queue panel UI behavior tests
4. `test_queue_panel_eta.py` - Queue ETA estimation tests
5. `test_queue_panel_move_feedback.py` - Queue reordering feedback tests
6. `test_queue_panel_v2.py` - Main queue panel tests
7. `test_queue_panel_v2_normalized_jobs.py` - Queue panel with NJR integration
8. `test_queue_persistence_v2.py` - Queue persistence tests
9. `test_running_job_panel_controls_v2.py` - Running job panel controls
10. `test_running_job_panel_v2.py` - Running job panel display

---

## What Was Removed

### QueueJobV2 Class (Deprecated)
```python
# REMOVED - Was in src/pipeline/job_models_v2.py
@dataclass
class QueueJobV2:
    job_id: str
    config_snapshot: dict
    status: JobStatusV2
    progress: float
    # ... other fields
    
    @classmethod
    def create(cls, config: dict) -> QueueJobV2:
        """Factory method to create jobs"""
        
    def to_dict(self) -> dict:
        """Serialize to dict"""
        
    @classmethod
    def from_dict(cls, data: dict) -> QueueJobV2:
        """Deserialize from dict"""
        
    def get_display_summary(self) -> str:
        """Get display string"""
```

### JobQueueV2 Class (Deprecated)
```python
# REMOVED - Was in src/pipeline/job_queue_v2.py
class JobQueueV2:
    def add_job(self, job: QueueJobV2) -> None
    def remove_job(self, job_id: str) -> QueueJobV2 | None
    def move_job_up(self, job_id: str) -> bool
    def move_job_down(self, job_id: str) -> bool
    def start_next_job(self) -> QueueJobV2 | None
    def complete_running_job(self, success: bool) -> QueueJobV2 | None
    # ... other methods
```

---

## Current System (CORE1 v2.6)

### Replacement Classes

**For Job Representation:**
- `NormalizedJobRecord` (NJR) - The canonical job representation
- `UnifiedJobSummary` - GUI display summary derived from NJR
- `Job` - Queue job model (in `src/queue/job_model.py`)

**For Queue Management:**
- `JobQueue` - Current queue implementation (`src/queue/job_queue.py`)
- `SingleNodeRunner` - Job execution runner
- `JobHistoryStore` - Persistent job history

**For GUI Display:**
- `QueuePanelV2` - Uses `UnifiedJobSummary` for display
- `RunningJobPanelV2` - Uses `UnifiedJobSummary` + `RuntimeJobStatus`

---

## Why Archive Instead of Update?

### Reason 1: Completely Different Architecture
The V2 queue system was a self-contained queue with its own job model. The current system:
- Uses NJR as the single source of truth
- Has separate queue, execution, and history layers
- Different data flow: PromptPack → Builder → NJR → Queue → Runner

### Reason 2: Tests Would Need Complete Rewrite
Updating these tests would mean:
- Rewriting every test from scratch
- Creating new fixtures for NJR/JobQueue
- Different test structure (no more QueueJobV2.create())
- Testing different functionality entirely

This is not "fixing" tests - it's writing new tests.

### Reason 3: Current System Already Has Tests
The current queue system has comprehensive tests:
- `tests/queue/test_job_queue_basic.py` - JobQueue operations
- `tests/queue/test_single_node_runner.py` - Runner tests
- `tests/queue/test_job_variant_metadata_v2.py` - Job metadata
- `tests/pipeline/test_job_builder_v2.py` - Job building
- `tests/pipeline/test_job_model_unification_v2.py` - NJR/UnifiedJobSummary

---

## Historical Context

### When QueueJobV2 Was Removed
From `src/pipeline/job_models_v2.py` line 1009:
```python
# PR-QUEUE-PERSIST: QueueJobV2 removed (V2 queue system abandoned)
```

This happened during the CORE1 job model unification, which established:
1. NormalizedJobRecord as the single job representation
2. JobQueue as the queue implementation
3. UnifiedJobSummary for GUI display

### What These Tests Originally Validated
- ✅ Job creation with unique IDs
- ✅ Job serialization/deserialization
- ✅ Queue FIFO/priority ordering
- ✅ Queue operations (add, remove, reorder)
- ✅ Job status transitions
- ✅ Queue persistence
- ✅ GUI panel integration

All of this functionality exists in the current system, just with different classes and architecture.

---

## If Tests Are Needed for Current System

### Create New Tests For:

**JobQueue Tests:**
```python
# tests/queue/test_job_queue_operations.py
def test_submit_job_adds_to_queue()
def test_get_next_job_respects_priority()
def test_mark_completed_updates_status()
```

**GUI Panel Tests:**
```python
# tests/gui_v2/test_queue_panel_current.py
def test_queue_panel_displays_unified_job_summary()
def test_running_job_panel_shows_runtime_status()
```

**NJR/UnifiedJobSummary Tests:**
Already exist in:
- `tests/pipeline/test_job_model_unification_v2.py`

---

## Migration Path If Needed

If GUI queue functionality needs more test coverage:

1. **Audit Current Coverage:**
   - Run coverage report: `pytest --cov=src/queue --cov=src/gui/panels_v2`
   - Identify gaps

2. **Write Targeted Tests:**
   - Focus on current architecture
   - Use NJR and UnifiedJobSummary
   - Test actual GUI panels (not mocked old classes)

3. **Reference Archived Tests:**
   - Use as inspiration for test scenarios
   - Translate concepts to current architecture
   - Don't try to port directly

---

## Related Documentation

- **ARCHITECTURE_v2.6.md** - Current job model architecture
- **D-TEST-001-Test-Suite-Technical-Debt-Discovery.md** - Discovery leading to this archival
- **PR-TEST-001-Test-Suite-Cleanup-Plan.md** - Original cleanup plan (Phase A revised)
- **src/queue/job_queue.py** - Current queue implementation
- **src/pipeline/job_models_v2.py** - Current job models (NJR, UnifiedJobSummary)

---

## Conclusion

These tests validated functionality that no longer exists. Archiving them:
- ✅ Acknowledges they tested real functionality (at the time)
- ✅ Preserves them for historical reference
- ✅ Prevents confusion about what's current
- ✅ Frees development effort for current system tests

If queue/GUI functionality needs more test coverage, write new tests for the current architecture rather than trying to resurrect these.

---

**Status:** ✅ ARCHIVED  
**Archived By:** GitHub Copilot (PR-TEST-001-A revision)  
**Can Be Deleted:** Yes, after 6 months if no one references them
