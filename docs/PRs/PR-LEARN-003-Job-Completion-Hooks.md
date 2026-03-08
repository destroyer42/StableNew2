# PR-LEARN-003: Add Learning Job Completion Hooks

**Status:** DRAFT  
**Priority:** P1 (HIGH)  
**Phase:** 2 (Job Completion Integration)  
**Depends on:** PR-LEARN-002  
**Estimated Effort:** 3-4 hours

---

## 1. Problem Statement

When a learning experiment runs jobs via the pipeline, there's no mechanism to:

1. **Identify learning-related jobs** — Jobs lack metadata indicating they're part of a learning experiment
2. **Route completion events** — JobHistoryService and runners don't notify the learning subsystem
3. **Update variant status** — The GUI can't display real-time progress

---

## 2. Success Criteria

After this PR:
- [ ] NormalizedJobRecord includes optional `learning_context` field
- [ ] Job completion events are routed to learning subsystem
- [ ] LearningController receives completion callbacks
- [ ] Variant status updates automatically on job completion

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/pipeline/job_models_v2.py` | MODIFY | Add learning_context field to NJR |
| `src/controller/job_service.py` | MODIFY | Add completion handler registration |
| `src/gui/controllers/learning_controller.py` | MODIFY | Register for completion events |
| `src/controller/app_controller.py` | MODIFY | Wire learning completion handler |
| `tests/learning_v2/test_job_completion_hooks.py` | CREATE | Test completion routing |

---

## 4. Implementation Steps

### Step 1: Add LearningJobContext to job_models_v2.py

**File:** `src/pipeline/job_models_v2.py`

**Add new dataclass** (near top with other dataclasses):
```python
@dataclass(frozen=True)
class LearningJobContext:
    """Metadata for jobs that are part of a learning experiment."""
    experiment_id: str
    experiment_name: str
    variant_index: int
    variable_under_test: str
    variant_value: Any
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "variant_index": self.variant_index,
            "variable_under_test": self.variable_under_test,
            "variant_value": self.variant_value,
        }
```

**Modify NormalizedJobRecord** (add new optional field):
```python
@dataclass
class NormalizedJobRecord:
    # ... existing fields ...
    learning_context: LearningJobContext | None = None
```

### Step 2: Add Completion Handler Registration to JobService

**File:** `src/controller/job_service.py`

**Add handler registration:**
```python
class JobService:
    def __init__(self, ...):
        # ... existing init ...
        self._completion_handlers: list[Callable[[NormalizedJobRecord, Any], None]] = []
    
    def register_completion_handler(
        self, 
        handler: Callable[[NormalizedJobRecord, Any], None]
    ) -> None:
        """Register a callback to be invoked when jobs complete."""
        if handler not in self._completion_handlers:
            self._completion_handlers.append(handler)
    
    def unregister_completion_handler(
        self,
        handler: Callable[[NormalizedJobRecord, Any], None]
    ) -> None:
        """Remove a completion handler."""
        if handler in self._completion_handlers:
            self._completion_handlers.remove(handler)
    
    def _notify_completion(self, job: NormalizedJobRecord, result: Any) -> None:
        """Notify all registered handlers of job completion."""
        for handler in self._completion_handlers:
            try:
                handler(job, result)
            except Exception:
                logger.exception("Completion handler failed")
```

**Call `_notify_completion` after job completes** (find job completion logic):
```python
# After job execution completes successfully or fails
self._notify_completion(job, result)
```

### Step 3: Add Completion Handler to LearningController

**File:** `src/gui/controllers/learning_controller.py`

**Add method:**
```python
def on_job_completed_callback(
    self, 
    job: Any, 
    result: Any
) -> None:
    """Handle job completion events from the pipeline.
    
    This is registered as a callback with JobService to receive
    notifications when learning-related jobs complete.
    """
    # Check if this is a learning job
    learning_ctx = getattr(job, "learning_context", None)
    if not learning_ctx:
        return
    
    # Check if it belongs to our current experiment
    if not self.learning_state.current_experiment:
        return
    
    if learning_ctx.experiment_id != self.learning_state.current_experiment.name:
        return
    
    # Find the variant by index
    variant_index = learning_ctx.variant_index
    if variant_index < 0 or variant_index >= len(self.learning_state.plan):
        return
    
    variant = self.learning_state.plan[variant_index]
    
    # Update variant based on result
    if hasattr(result, "success") and result.success:
        self._on_variant_job_completed(variant, result)
    else:
        error = getattr(result, "error", Exception("Unknown error"))
        self._on_variant_job_failed(variant, error)
```

### Step 4: Register Handler in AppController

**File:** `src/controller/app_controller.py`

**In initialization, after learning_execution_controller is created:**
```python
# Register learning completion handler
if self.job_service and hasattr(self, "learning_execution_controller"):
    self._learning_completion_handler = self._create_learning_completion_handler()
    self.job_service.register_completion_handler(self._learning_completion_handler)


def _create_learning_completion_handler(self):
    """Create a completion handler that routes to learning subsystem."""
    def handler(job, result):
        # Route to learning execution controller
        if hasattr(self, "learning_execution_controller"):
            callback = getattr(
                self.learning_execution_controller, 
                "on_job_completed", 
                None
            )
            if callable(callback):
                callback(job, result)
    return handler
```

**In shutdown, unregister:**
```python
def _shutdown_learning_hooks(self) -> None:
    # Unregister completion handler
    if hasattr(self, "_learning_completion_handler") and self.job_service:
        self.job_service.unregister_completion_handler(self._learning_completion_handler)
    
    # ... existing shutdown code ...
```

### Step 5: Create Tests

**File:** `tests/learning_v2/test_job_completion_hooks.py`

```python
"""Tests for learning job completion routing."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass


@dataclass
class MockResult:
    success: bool = True
    images: list = None
    error: str = ""


def test_learning_context_added_to_njr():
    """Verify LearningJobContext can be attached to NormalizedJobRecord."""
    from src.pipeline.job_models_v2 import NormalizedJobRecord, LearningJobContext
    
    ctx = LearningJobContext(
        experiment_id="test-exp",
        experiment_name="CFG Sweep",
        variant_index=2,
        variable_under_test="CFG Scale",
        variant_value=8.5,
    )
    
    # Verify context is valid
    assert ctx.experiment_id == "test-exp"
    assert ctx.variant_value == 8.5
    
    # Verify it can be converted to dict
    d = ctx.to_dict()
    assert d["experiment_name"] == "CFG Sweep"


def test_completion_handler_receives_learning_jobs():
    """Verify completion handlers are called for learning jobs."""
    from src.controller.job_service import JobService
    
    # Create mock job service
    service = JobService.__new__(JobService)
    service._completion_handlers = []
    
    # Register handler
    received = []
    def handler(job, result):
        received.append((job, result))
    
    service.register_completion_handler(handler)
    
    # Simulate completion
    mock_job = MagicMock()
    mock_result = MockResult(success=True)
    service._notify_completion(mock_job, mock_result)
    
    assert len(received) == 1
    assert received[0][1].success is True


def test_learning_controller_filters_by_experiment():
    """Verify LearningController only processes its own experiment's jobs."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    from src.pipeline.job_models_v2 import LearningJobContext
    
    state = LearningState()
    state.current_experiment = LearningExperiment(
        name="my-experiment",
        stage="txt2img",
        variable_under_test="Steps",
        values=[10, 20],
    )
    state.plan = [
        LearningVariant(experiment_id="my-experiment", param_value=10, status="running"),
        LearningVariant(experiment_id="my-experiment", param_value=20, status="running"),
    ]
    
    controller = LearningController(learning_state=state)
    
    # Job from different experiment - should be ignored
    wrong_job = MagicMock()
    wrong_job.learning_context = LearningJobContext(
        experiment_id="other-experiment",
        experiment_name="Other",
        variant_index=0,
        variable_under_test="CFG",
        variant_value=7.0,
    )
    
    controller.on_job_completed_callback(wrong_job, MockResult())
    assert state.plan[0].status == "running"  # Unchanged
    
    # Job from our experiment - should update
    our_job = MagicMock()
    our_job.learning_context = LearningJobContext(
        experiment_id="my-experiment",
        experiment_name="My Experiment",
        variant_index=0,
        variable_under_test="Steps",
        variant_value=10,
    )
    
    controller.on_job_completed_callback(our_job, MockResult(success=True))
    assert state.plan[0].status == "completed"
```

---

## 5. Verification

### 5.1 Manual Verification

1. Run a learning experiment
2. Watch variant table update in real-time as jobs complete
3. Verify correct variant rows are updated (not random ones)

### 5.2 Automated Verification

```bash
pytest tests/learning_v2/test_job_completion_hooks.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-002
- **Enables:** PR-LEARN-004 (Live Variant Status Updates), PR-LEARN-005 (Image Result Integration)
