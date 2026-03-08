# PR-LEARN-004: Live Variant Status Updates

**Status:** DRAFT  
**Priority:** P1 (HIGH)  
**Phase:** 2 (Job Completion Integration)  
**Depends on:** PR-LEARN-003  
**Estimated Effort:** 2-3 hours

---

## 1. Problem Statement

Even with completion hooks in place (PR-LEARN-003), the GUI update mechanism needs refinement:

1. **Thread safety** — Completion callbacks come from worker threads, but Tkinter requires main thread updates
2. **Visual feedback** — Need progress indicators (running row highlight, percentage complete)
3. **Error display** — Failed variants should show error details

---

## 2. Success Criteria

After this PR:
- [ ] Variant table updates safely from any thread
- [ ] Currently running variant is highlighted
- [ ] Progress bar or percentage shows overall progress
- [ ] Failed variants show error indicator
- [ ] All updates occur on main thread via `after()` scheduling

---

## 3. Allowed Files

| File | Action | Justification |
|------|--------|---------------|
| `src/gui/views/learning_plan_table.py` | MODIFY | Add thread-safe update scheduling |
| `src/gui/controllers/learning_controller.py` | MODIFY | Use scheduled updates |
| `src/gui/views/learning_tab_frame_v2.py` | MODIFY | Add progress indicator |
| `tests/gui/test_learning_live_updates.py` | CREATE | Test thread-safe updates |

---

## 4. Implementation Steps

### Step 1: Add Thread-Safe Update Methods to LearningPlanTable

**File:** `src/gui/views/learning_plan_table.py`

**Add scheduled update wrapper:**
```python
def schedule_update_row_status(self, index: int, status: str) -> None:
    """Thread-safe status update using Tkinter's after() method."""
    try:
        self.after(0, lambda: self.update_row_status(index, status))
    except Exception:
        pass  # Widget may be destroyed

def schedule_update_row_images(self, index: int, completed: int, planned: int) -> None:
    """Thread-safe image count update."""
    try:
        self.after(0, lambda: self.update_row_images(index, completed, planned))
    except Exception:
        pass

def schedule_highlight_row(self, index: int, highlight: bool = True) -> None:
    """Thread-safe row highlight update."""
    try:
        self.after(0, lambda: self.highlight_row(index, highlight))
    except Exception:
        pass
```

**Add error indicator support:**
```python
def update_row_error(self, index: int, error_msg: str) -> None:
    """Mark a row as having an error with tooltip."""
    try:
        item = self.tree.get_children()[index]
        self.tree.item(item, tags=("error",))
        # Store error for tooltip
        self._row_errors[index] = error_msg
    except (IndexError, TypeError):
        pass

def _on_row_hover(self, event):
    """Show error tooltip on hover."""
    item = self.tree.identify_row(event.y)
    if item:
        index = self.tree.index(item)
        error = self._row_errors.get(index)
        if error:
            self._show_tooltip(event.x_root, event.y_root, error)
```

**Configure tags in `_create_table()`:**
```python
# Add after tree creation
self.tree.tag_configure("highlight", background="#FFC805", foreground="#000000")
self.tree.tag_configure("error", background="#FF4444", foreground="#FFFFFF")
self.tree.tag_configure("completed", background="#44FF44", foreground="#000000")

# Error tooltip storage
self._row_errors: dict[int, str] = {}
```

### Step 2: Modify LearningController to Use Scheduled Updates

**File:** `src/gui/controllers/learning_controller.py`

**Replace direct update calls with scheduled versions:**
```python
def _update_variant_status(self, variant_index: int, status: str) -> None:
    """Update the status of a specific variant in the table."""
    if self._plan_table:
        # Use thread-safe scheduled update
        schedule = getattr(self._plan_table, "schedule_update_row_status", None)
        if callable(schedule):
            schedule(variant_index, status)
        elif hasattr(self._plan_table, "update_row_status"):
            self._plan_table.update_row_status(variant_index, status)

def _update_variant_images(self, variant_index: int, completed: int, planned: int) -> None:
    """Update the image count of a specific variant in the table."""
    if self._plan_table:
        schedule = getattr(self._plan_table, "schedule_update_row_images", None)
        if callable(schedule):
            schedule(variant_index, completed, planned)
        elif hasattr(self._plan_table, "update_row_images"):
            self._plan_table.update_row_images(variant_index, completed, planned)

def _highlight_variant(self, variant_index: int, highlight: bool = True) -> None:
    """Highlight or unhighlight a specific variant in the table."""
    if self._plan_table:
        schedule = getattr(self._plan_table, "schedule_highlight_row", None)
        if callable(schedule):
            schedule(variant_index, highlight)
        elif hasattr(self._plan_table, "highlight_row"):
            self._plan_table.highlight_row(variant_index, highlight)
```

### Step 3: Add Progress Indicator to LearningTabFrame

**File:** `src/gui/views/learning_tab_frame_v2.py`

**Add progress bar to header:**
```python
# In __init__, after header_label
self.progress_var = tk.DoubleVar(value=0.0)
self.progress_bar = ttk.Progressbar(
    self.header_frame,
    variable=self.progress_var,
    maximum=100,
    length=150,
    mode="determinate",
)
self.progress_bar.pack(side="right", padx=8)
self.progress_bar.pack_forget()  # Hide initially

self.progress_label = ttk.Label(self.header_frame, text="")
self.progress_label.pack(side="right")
```

**Add progress update method:**
```python
def update_progress(self, completed: int, total: int) -> None:
    """Update the progress indicator."""
    if total <= 0:
        self.progress_bar.pack_forget()
        self.progress_label.config(text="")
        return
    
    percentage = (completed / total) * 100
    self.progress_var.set(percentage)
    self.progress_label.config(text=f"{completed}/{total}")
    
    if completed > 0:
        self.progress_bar.pack(side="right", padx=8)
    
    if completed >= total:
        self.after(2000, self._hide_progress)

def _hide_progress(self) -> None:
    """Hide progress bar after completion."""
    self.progress_bar.pack_forget()
    self.progress_label.config(text="")
```

**Wire progress updates from controller:**
```python
# In LearningController, add method:
def _update_overall_progress(self) -> None:
    """Update overall experiment progress."""
    if not self.learning_state.plan:
        return
    
    total = len(self.learning_state.plan)
    completed = sum(1 for v in self.learning_state.plan if v.status in ("completed", "failed"))
    
    # Find parent tab frame and update progress
    if self._plan_table:
        tab_frame = self._plan_table.master.master  # Navigate to LearningTabFrame
        if hasattr(tab_frame, "update_progress"):
            tab_frame.after(0, lambda: tab_frame.update_progress(completed, total))
```

### Step 4: Create Tests

**File:** `tests/gui/test_learning_live_updates.py`

```python
"""Tests for thread-safe learning tab updates."""
from __future__ import annotations

import pytest
import threading
import time
from unittest.mock import MagicMock, patch


def test_scheduled_update_uses_after():
    """Verify scheduled updates use Tkinter's after() method."""
    from src.gui.views.learning_plan_table import LearningPlanTable
    
    mock_master = MagicMock()
    
    # Create table with mocked after
    with patch.object(LearningPlanTable, "__init__", lambda x, y: None):
        table = LearningPlanTable(mock_master)
        table.tree = MagicMock()
        table.after = MagicMock()
        
        # Call scheduled update
        table.schedule_update_row_status(0, "completed")
        
        # Should use after() for thread safety
        table.after.assert_called_once()


def test_concurrent_updates_are_safe():
    """Verify multiple threads can request updates without crashes."""
    updates_received = []
    
    def mock_after(delay, func):
        updates_received.append(func)
    
    class MockTable:
        after = mock_after
        
        def schedule_update_row_status(self, index, status):
            try:
                self.after(0, lambda: updates_received.append((index, status)))
            except Exception:
                pass
    
    table = MockTable()
    
    # Simulate concurrent updates from multiple threads
    def update_from_thread(index):
        for status in ["queued", "running", "completed"]:
            table.schedule_update_row_status(index, status)
            time.sleep(0.001)
    
    threads = [threading.Thread(target=update_from_thread, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # All updates should have been scheduled without exception
    assert len(updates_received) > 0


def test_progress_updates_correctly():
    """Verify progress calculation is accurate."""
    from src.gui.controllers.learning_controller import LearningController
    from src.gui.learning_state import LearningState, LearningVariant
    
    state = LearningState()
    state.plan = [
        LearningVariant(experiment_id="test", param_value=1, status="completed"),
        LearningVariant(experiment_id="test", param_value=2, status="running"),
        LearningVariant(experiment_id="test", param_value=3, status="pending"),
        LearningVariant(experiment_id="test", param_value=4, status="failed"),
    ]
    
    controller = LearningController(learning_state=state)
    
    total = len(state.plan)
    completed = sum(1 for v in state.plan if v.status in ("completed", "failed"))
    
    assert completed == 2  # completed + failed
    assert total == 4
```

---

## 5. Verification

### 5.1 Manual Verification

1. Run a multi-variant experiment
2. Watch table rows update in real-time
3. Verify progress bar advances correctly
4. Confirm no UI freezing or crashes

### 5.2 Automated Verification

```bash
pytest tests/gui/test_learning_live_updates.py -v
```

---

## 6. Related PRs

- **Depends on:** PR-LEARN-003
- **Enables:** PR-LEARN-005 (Image Result Integration)
