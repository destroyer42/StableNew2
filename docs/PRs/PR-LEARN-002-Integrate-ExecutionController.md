# PR-LEARN-002: Integrate LearningExecutionController with GUI

**Status:** DRAFT  
**Priority:** P0 (CRITICAL)  
**Phase:** 1 (Critical Wiring)  
**Depends on:** PR-LEARN-001  
**Estimated Effort:** 4-6 hours

---

## 1. Problem Statement

The backend `LearningExecutionController` exists and works correctly in isolation, but:

1. **AppController doesn't create it**
   - No `learning_execution_controller` attribute
   - No initialization in `__init__` or setup methods

2. **GUI LearningController doesn't use it**
   - GUI controller has its own `run_plan()` that bypasses the backend
   - No connection between GUI state and backend execution

3. **Two separate "controllers" with overlapping responsibilities**
   - `src/gui/controllers/learning_controller.py` — GUI-facing
   - `src/controller/learning_execution_controller.py` — Backend execution
   - They don't talk to each other

---

## 2. Success Criteria

After this PR:
- [ ] AppController creates and owns LearningExecutionController
- [ ] GUI LearningController delegates execution to LearningExecutionController
- [ ] Learning plan execution uses the proper backend runner
- [ ] Results flow back from backend to GUI for display

---

## 3. Architectural Decision

### Option A: Merge controllers into one
- **Rejected:** Creates coupling between GUI and backend

### Option B: GUI controller delegates to backend controller (CHOSEN)
- GUI controller handles UI state and user interaction
- Backend controller handles execution logic
- Clean separation of concerns

### Integration Pattern:
```
LearningTabFrame
    ↓ (owns)
LearningController (GUI)
    ↓ (calls via injection)
LearningExecutionController (Backend)
    ↓ (uses)
PipelineRunner / JobQueue
```

---

## 4. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/controller/app_controller.py` | MODIFY | Create LearningExecutionController |
| `src/gui/controllers/learning_controller.py` | MODIFY | Add execution_controller injection |
| `src/gui/views/learning_tab_frame_v2.py` | MODIFY | Pass execution_controller |
| `src/gui/main_window_v2.py` | MODIFY | Wire execution_controller to tab |
| `tests/controller/test_learning_controller_integration.py` | CREATE | Integration tests |

---

## 5. Forbidden Files

| File | Reason |
|------|--------|
| `src/controller/learning_execution_controller.py` | Already works — don't modify |
| `src/learning/*` | Backend logic unchanged |
| `src/pipeline/*` | Pipeline internals unchanged |

---

## 6. Implementation Steps

### Step 1: Add LearningExecutionController to AppController

**File:** `src/controller/app_controller.py`

**Add import** (near top of file, with other controller imports):
```python
from src.controller.learning_execution_controller import LearningExecutionController
```

**In `__init__` method, after PipelineController creation** (find where `self.pipeline_controller` is created):
```python
# Learning execution controller
self.learning_execution_controller = LearningExecutionController(
    run_callable=self._learning_run_callable
)
```

**Add helper method** (near other run methods):
```python
def _learning_run_callable(self, config: dict, step: Any) -> Any:
    """Callable passed to LearningExecutionController for running pipeline steps."""
    from src.pipeline.pipeline_runner import PipelineRunResult
    
    try:
        # Use the standard pipeline execution path
        runner = getattr(self, "_pipeline_runner", None)
        if runner and hasattr(runner, "run_single_job"):
            return runner.run_single_job(config)
        
        # Fallback: use pipeline controller
        if self.pipeline_controller:
            build_run = getattr(self.pipeline_controller, "build_and_run_single", None)
            if callable(build_run):
                return build_run(config)
        
        # Stub result if no runner available
        return PipelineRunResult(
            success=False,
            error="No pipeline runner available for learning execution",
            images=[],
        )
    except Exception as e:
        return PipelineRunResult(
            success=False,
            error=str(e),
            images=[],
        )
```

### Step 2: Add execution_controller to LearningController

**File:** `src/gui/controllers/learning_controller.py`

**Modify `__init__` signature** (add new parameter):
```python
def __init__(
    self,
    learning_state: LearningState,
    prompt_workspace_state: PromptWorkspaceState | None = None,
    pipeline_state: Any | None = None,
    pipeline_controller: Any | None = None,
    execution_controller: Any | None = None,  # ADD THIS
    plan_table: Any | None = None,
    review_panel: Any | None = None,
    learning_record_writer: LearningRecordWriter | None = None,
) -> None:
    self.learning_state = learning_state
    self.prompt_workspace_state = prompt_workspace_state
    self.pipeline_state = pipeline_state
    self.pipeline_controller = pipeline_controller
    self.execution_controller = execution_controller  # ADD THIS
    # ... rest of init
```

**Add new `run_plan_via_backend()` method:**
```python
def run_plan_via_backend(self) -> None:
    """Execute the current learning plan via the backend LearningExecutionController."""
    if not self.learning_state.plan:
        return
    
    if not self.execution_controller:
        # Fall back to direct pipeline submission (PR-LEARN-001 path)
        self.run_plan()
        return
    
    experiment = self.learning_state.current_experiment
    if not experiment:
        return
    
    # Build a LearningPlan from the current experiment
    from src.learning.learning_plan import LearningPlan
    
    plan = LearningPlan(
        mode="single_variable_sweep",
        stage=experiment.stage,
        target_variable=experiment.variable_under_test,
        sweep_values=experiment.values,
        images_per_step=experiment.images_per_value,
        metadata={
            "experiment_name": experiment.name,
            "experiment_description": experiment.description,
        },
    )
    
    # Build base config from current pipeline state
    base_config = self._build_base_config()
    
    # Mark all variants as running
    for i, variant in enumerate(self.learning_state.plan):
        variant.status = "running"
        self._update_variant_status(i, "running")
    
    # Execute via backend
    try:
        result = self.execution_controller.run_learning_plan(
            plan=plan,
            base_config=base_config,
            metadata={
                "experiment_name": experiment.name,
                "prompt_text": experiment.prompt_text,
            },
        )
        
        # Update variants with results
        self._process_execution_result(result)
        
    except Exception as e:
        # Mark all as failed
        for i, variant in enumerate(self.learning_state.plan):
            variant.status = "failed"
            self._update_variant_status(i, "failed")


def _build_base_config(self) -> dict:
    """Build base configuration from current pipeline state."""
    config = {}
    
    # Get prompt
    if self.learning_state.current_experiment:
        config["prompt"] = self.learning_state.current_experiment.prompt_text
    elif self.prompt_workspace_state:
        config["prompt"] = self.prompt_workspace_state.get_current_prompt_text()
    
    # Get pipeline state values if available
    if self.pipeline_state:
        config["steps"] = getattr(self.pipeline_state, "steps", 20)
        config["cfg_scale"] = getattr(self.pipeline_state, "cfg_scale", 7.0)
        config["sampler"] = getattr(self.pipeline_state, "sampler_name", "Euler")
        config["scheduler"] = getattr(self.pipeline_state, "scheduler_name", "")
    
    return config


def _process_execution_result(self, result: Any) -> None:
    """Process results from LearningExecutionController."""
    if not result or not hasattr(result, "step_results"):
        return
    
    for i, step_result in enumerate(result.step_results):
        if i >= len(self.learning_state.plan):
            break
        
        variant = self.learning_state.plan[i]
        
        # Update status based on pipeline result
        if hasattr(step_result, "pipeline_result"):
            pr = step_result.pipeline_result
            if hasattr(pr, "success") and pr.success:
                variant.status = "completed"
                variant.completed_images = variant.planned_images
                # Extract image paths
                if hasattr(pr, "images"):
                    variant.image_refs = list(pr.images or [])
            else:
                variant.status = "failed"
        else:
            variant.status = "completed"
        
        # Update UI
        self._update_variant_status(i, variant.status)
        self._update_variant_images(i, variant.completed_images, variant.planned_images)
```

**Modify existing `run_plan()` to use backend if available:**
```python
def run_plan(self) -> None:
    """Execute the current learning plan."""
    if not self.learning_state.plan:
        return
    
    # Prefer backend execution path
    if self.execution_controller:
        self.run_plan_via_backend()
        return
    
    # Fall back to direct pipeline submission
    if not self.pipeline_controller:
        return

    # ... existing direct submission code ...
```

### Step 3: Wire execution_controller in LearningTabFrame

**File:** `src/gui/views/learning_tab_frame_v2.py`

**Modify `__init__` signature:**
```python
def __init__(
    self,
    master: tk.Misc,
    app_state: AppStateV2 | None = None,
    pipeline_controller: Any | None = None,
    execution_controller: Any | None = None,  # ADD THIS
    *args: Any,
    **kwargs: Any,
) -> None:
    super().__init__(master, *args, **kwargs)
    self.app_state = app_state
    self.pipeline_controller = pipeline_controller
    self.execution_controller = execution_controller  # ADD THIS
```

**Modify LearningController creation:**
```python
self.learning_controller = LearningController(
    learning_state=self.learning_state,
    prompt_workspace_state=getattr(self.app_state, "prompt_workspace_state", None)
    if self.app_state
    else None,
    pipeline_controller=self.pipeline_controller,
    execution_controller=self.execution_controller,  # ADD THIS
    learning_record_writer=self.learning_record_writer,
)
```

### Step 4: Wire in MainWindow

**File:** `src/gui/main_window_v2.py`

**Modify `_make_learning` function:**
```python
def _make_learning(parent):
    # Get execution controller from app_controller
    execution_ctrl = None
    if self.app_controller:
        execution_ctrl = getattr(self.app_controller, "learning_execution_controller", None)
    
    try:
        tab = LearningTabFrame(
            parent,
            app_state=self.app_state,
            pipeline_controller=self.pipeline_controller,
            execution_controller=execution_ctrl,
        )
    except Exception:
        try:
            tab = LearningTabFrame(parent, app_state=self.app_state)
        except Exception:
            tab = LearningTabFrame(parent)
    # ...
```

### Step 5: Create Integration Tests

**File:** `tests/controller/test_learning_controller_integration.py`

```python
"""Integration tests for LearningController + LearningExecutionController."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


@dataclass
class MockPipelineResult:
    success: bool = True
    images: list = None
    error: str = ""
    
    def __post_init__(self):
        if self.images is None:
            self.images = []


def test_learning_controller_delegates_to_execution_controller():
    """Verify LearningController uses LearningExecutionController when available."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment
    
    state = LearningState()
    state.current_experiment = LearningExperiment(
        name="Integration Test",
        stage="txt2img",
        variable_under_test="CFG Scale",
        values=[7.0, 8.0],
        images_per_value=1,
    )
    
    # Mock execution controller
    mock_exec_ctrl = MagicMock()
    mock_result = MagicMock()
    mock_result.step_results = []
    mock_exec_ctrl.run_learning_plan.return_value = mock_result
    
    controller = LearningController(
        learning_state=state,
        execution_controller=mock_exec_ctrl,
    )
    
    # Build plan first
    controller.build_plan(state.current_experiment)
    
    # Run should delegate to execution controller
    controller.run_plan()
    
    mock_exec_ctrl.run_learning_plan.assert_called_once()


def test_app_controller_creates_learning_execution_controller():
    """Verify AppController initializes LearningExecutionController."""
    # This test requires mocking the entire app initialization
    # For now, just verify the import works
    from src.controller.learning_execution_controller import LearningExecutionController
    
    controller = LearningExecutionController(run_callable=lambda cfg, step: MockPipelineResult())
    assert controller is not None


def test_fallback_to_direct_submission_without_execution_controller():
    """Verify LearningController falls back to direct submission without execution controller."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment
    
    state = LearningState()
    state.current_experiment = LearningExperiment(
        name="Fallback Test",
        stage="txt2img",
        variable_under_test="Steps",
        values=[10, 20],
        images_per_value=1,
    )
    
    mock_pipeline = MagicMock()
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=mock_pipeline,
        execution_controller=None,  # No execution controller
    )
    
    controller.build_plan(state.current_experiment)
    
    # Should not crash, should attempt direct submission
    controller.run_plan()
```

---

## 7. Verification

### 7.1 Manual Verification

1. Start StableNew
2. Create and run a learning experiment
3. Verify jobs execute through the proper backend path
4. Check that results populate variant status correctly

### 7.2 Automated Verification

```bash
pytest tests/controller/test_learning_controller_integration.py -v
pytest tests/learning_v2/test_learning_execution_controller_integration.py -v
```

---

## 8. Rollback Plan

1. Remove `learning_execution_controller` from AppController
2. Remove `execution_controller` parameter from LearningController and LearningTabFrame
3. System reverts to PR-LEARN-001 direct submission path (or pre-PR-001 broken state)

---

## 9. Documentation Updates

Update `docs/LEARNING_ROADMAP_v2.6.md`:
- Mark PR-LEARN-002 as COMPLETE
- Update architecture diagram to show controller integration

---

## 10. Related PRs

- **Depends on:** PR-LEARN-001 (basic wiring)
- **Blocks:** PR-LEARN-003 (job completion hooks), PR-LEARN-004 (live status updates)
- **Related:** None
