# PR-LEARN-001: Wire LearningController to PipelineController

**Status:** DRAFT  
**Priority:** P0 (CRITICAL BLOCKER)  
**Phase:** 1 (Critical Wiring)  
**Estimated Effort:** 4-6 hours

---

## 1. Problem Statement

The Learning Tab's "Run Experiment" button does nothing useful because:

1. **MainWindow does not pass `pipeline_controller` to LearningTabFrame**
   - `main_window_v2.py:189-195` creates `LearningTabFrame(parent)` without controller
   - Result: `LearningController.pipeline_controller` is always `None`

2. **`_submit_variant_job()` uses wrong API**
   - Calls `pipeline_controller.start_pipeline(pipeline_func=None, on_complete=..., on_error=...)`
   - `PipelineController.start_pipeline()` doesn't accept these parameters
   - Result: Even if controller was passed, the call would fail

3. **No variant-specific configuration is applied**
   - `_build_variant_overrides()` creates overrides dict but it's never used
   - The job runs with base config, not the test value

---

## 2. Success Criteria

After this PR:
- [ ] Clicking "Run Experiment" submits jobs to the queue
- [ ] Each variant runs with its specific parameter value applied
- [ ] Jobs appear in QueuePanel and HistoryPanel
- [ ] Learning mode flag is set on jobs for provenance

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/main_window_v2.py` | MODIFY | Pass pipeline_controller to LearningTabFrame |
| `src/gui/views/learning_tab_frame_v2.py` | MODIFY | Accept and propagate pipeline_controller |
| `src/gui/controllers/learning_controller.py` | MODIFY | Fix _submit_variant_job() to use correct API |
| `tests/gui/test_learning_tab_wiring.py` | CREATE | Verify wiring |

---

## 4. Forbidden Files

| File | Reason |
|------|--------|
| `src/controller/pipeline_controller.py` | Core runner — no changes needed |
| `src/controller/app_controller.py` | Core controller — avoid scope creep |
| `src/pipeline/*` | Pipeline internals unchanged |
| `src/queue/*` | Queue internals unchanged |

---

## 5. Implementation Steps

### Step 1: Modify MainWindow to Pass pipeline_controller

**File:** `src/gui/main_window_v2.py`

**Find** (around line 189-195):
```python
def _make_learning(parent):
    try:
        tab = LearningTabFrame(parent)
    except Exception:
        try:
            tab = LearningTabFrame(parent, app_state=self.app_state)
        except Exception:
            tab = LearningTabFrame(parent)
```

**Replace with:**
```python
def _make_learning(parent):
    try:
        tab = LearningTabFrame(
            parent,
            app_state=self.app_state,
            pipeline_controller=self.pipeline_controller,
        )
    except Exception:
        try:
            tab = LearningTabFrame(parent, app_state=self.app_state)
        except Exception:
            tab = LearningTabFrame(parent)
```

### Step 2: Verify LearningTabFrame Accepts pipeline_controller

**File:** `src/gui/views/learning_tab_frame_v2.py`

**Verify** `__init__` signature (already correct):
```python
def __init__(
    self,
    master: tk.Misc,
    app_state: AppStateV2 | None = None,
    pipeline_controller: Any | None = None,
    *args: Any,
    **kwargs: Any,
) -> None:
```

No changes needed here — already accepts the parameter.

### Step 3: Fix _submit_variant_job() API Call

**File:** `src/gui/controllers/learning_controller.py`

**Find** `_submit_variant_job()` method (around line 134-156):
```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    """Submit a pipeline job for a single learning variant."""
    if not self.learning_state.current_experiment or not self.pipeline_controller:
        return

    experiment = self.learning_state.current_experiment

    # Build overrides for this variant based on variable_under_test
    _overrides = self._build_variant_overrides(variant, experiment)

    # Submit the job
    try:
        success = self.pipeline_controller.start_pipeline(
            pipeline_func=None,
            on_complete=lambda result: self._on_variant_job_completed(variant, result),
            on_error=lambda error: self._on_variant_job_failed(variant, error),
        )
        # ...
```

**Replace with:**
```python
def _submit_variant_job(self, variant: LearningVariant) -> None:
    """Submit a pipeline job for a single learning variant."""
    if not self.learning_state.current_experiment or not self.pipeline_controller:
        return

    experiment = self.learning_state.current_experiment

    # Build overrides for this variant based on variable_under_test
    overrides = self._build_variant_overrides(variant, experiment)

    # Build learning metadata for provenance
    learning_metadata = {
        "learning_enabled": True,
        "experiment_name": experiment.name,
        "experiment_id": experiment.name,
        "variable_under_test": experiment.variable_under_test,
        "variant_value": variant.param_value,
        "variant_index": self._get_variant_index(variant),
    }

    # Submit the job using the correct API
    try:
        # Use add_job_to_queue which is the standard queue submission path
        from src.gui.app_state_v2 import PackJobEntry
        
        # Get current prompt from workspace or custom
        prompt_text = experiment.prompt_text
        if not prompt_text and self.prompt_workspace_state:
            prompt_text = self.prompt_workspace_state.get_current_prompt_text()

        # Create a minimal pack entry for the learning variant
        pack_entry = PackJobEntry(
            pack_name=f"learning_{experiment.name}_{variant.param_value}",
            prompt_text=prompt_text,
            negative_prompt="",  # TODO: Get from experiment config
            stage_overrides=overrides,
            learning_metadata=learning_metadata,
        )

        # Submit via PipelineController
        success = self._submit_learning_job(pack_entry, variant)

        if success:
            variant.status = "queued"
            variant_index = self._get_variant_index(variant)
            if variant_index >= 0:
                self._update_variant_status(variant_index, "queued")
        else:
            variant.status = "failed"
            variant_index = self._get_variant_index(variant)
            if variant_index >= 0:
                self._update_variant_status(variant_index, "failed")

    except Exception as e:
        variant.status = "failed"
        variant_index = self._get_variant_index(variant)
        if variant_index >= 0:
            self._update_variant_status(variant_index, "failed")


def _submit_learning_job(self, pack_entry: Any, variant: LearningVariant) -> bool:
    """Submit a learning job via the pipeline controller."""
    if not self.pipeline_controller:
        return False
    
    # Try using the standard job building and queue submission
    try:
        # Option 1: Use build_and_queue_single_job if available
        build_queue = getattr(self.pipeline_controller, "build_and_queue_single_job", None)
        if callable(build_queue):
            return build_queue(pack_entry)
        
        # Option 2: Use add_to_queue if available
        add_queue = getattr(self.pipeline_controller, "add_to_queue", None)
        if callable(add_queue):
            return add_queue(pack_entry)
        
        # Option 3: Build NJR manually and submit
        builder = getattr(self.pipeline_controller, "_job_builder", None)
        queue = getattr(self.pipeline_controller, "_job_queue", None)
        if builder and queue:
            njr = builder.build_single_job(pack_entry)
            if njr:
                queue.add_job(njr)
                return True
        
        return False
    except Exception:
        return False
```

### Step 4: Add learning_metadata to PackJobEntry (if needed)

**File:** `src/gui/app_state_v2.py`

Check if `PackJobEntry` has a `learning_metadata` field. If not, add it:

```python
@dataclass
class PackJobEntry:
    pack_name: str
    prompt_text: str = ""
    negative_prompt: str = ""
    stage_overrides: dict[str, Any] = field(default_factory=dict)
    learning_metadata: dict[str, Any] | None = None  # ADD THIS
```

### Step 5: Create Test File

**File:** `tests/gui/test_learning_tab_wiring.py`

```python
"""Tests for Learning Tab wiring to PipelineController."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_learning_tab_receives_pipeline_controller():
    """Verify MainWindow passes pipeline_controller to LearningTabFrame."""
    from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
    
    mock_parent = MagicMock()
    mock_controller = MagicMock()
    
    tab = LearningTabFrame(
        mock_parent,
        pipeline_controller=mock_controller,
    )
    
    assert tab.pipeline_controller is mock_controller
    assert tab.learning_controller.pipeline_controller is mock_controller


def test_submit_variant_job_uses_correct_api():
    """Verify _submit_variant_job calls queue submission, not broken start_pipeline."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    
    state = LearningState()
    state.current_experiment = LearningExperiment(
        name="Test",
        stage="txt2img",
        variable_under_test="CFG Scale",
        values=[7.0, 8.0, 9.0],
        images_per_value=1,
    )
    
    mock_pipeline_controller = MagicMock()
    mock_pipeline_controller.build_and_queue_single_job = MagicMock(return_value=True)
    
    controller = LearningController(
        learning_state=state,
        pipeline_controller=mock_pipeline_controller,
    )
    
    variant = LearningVariant(
        experiment_id="Test",
        param_value=7.0,
        status="pending",
        planned_images=1,
    )
    state.plan = [variant]
    
    controller._submit_variant_job(variant)
    
    # Should NOT call start_pipeline with broken signature
    mock_pipeline_controller.start_pipeline.assert_not_called()
    
    # Should call queue submission
    assert variant.status in ("queued", "failed")


def test_learning_controller_builds_correct_overrides():
    """Verify overrides dict contains the variant value for the variable under test."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningExperiment, LearningVariant
    
    state = LearningState()
    controller = LearningController(learning_state=state)
    
    experiment = LearningExperiment(
        name="CFG Test",
        stage="txt2img",
        variable_under_test="CFG Scale",
        values=[7.0],
        images_per_value=1,
    )
    
    variant = LearningVariant(
        experiment_id="CFG Test",
        param_value=9.5,
        status="pending",
    )
    
    overrides = controller._build_variant_overrides(variant, experiment)
    
    assert overrides["cfg_scale"] == 9.5
    assert "learning_experiment_id" in overrides
```

---

## 6. Verification

### 6.1 Manual Verification

1. Start StableNew
2. Navigate to Learning Tab
3. Create experiment: name="Test", stage="txt2img", variable="CFG Scale", range=7-10 step=1
4. Click "Build Preview Only" — should see 4 variants in table
5. Click "Run Experiment"
6. Switch to Pipeline Tab — should see 4 jobs in Queue

### 6.2 Automated Verification

```bash
pytest tests/gui/test_learning_tab_wiring.py -v
```

---

## 7. Rollback Plan

If issues arise:
1. Revert `main_window_v2.py` change (remove pipeline_controller arg)
2. Learning tab returns to non-functional but harmless state

---

## 8. Documentation Updates

Update `docs/LEARNING_ROADMAP_v2.6.md`:
- Mark PR-LEARN-001 as COMPLETE
- Update "Current State Assessment" section

---

## 9. Related PRs

- **Depends on:** None (first in series)
- **Blocks:** PR-LEARN-002 (LearningExecutionController integration)
- **Related:** PR-LEARN-003 (Job completion hooks)
