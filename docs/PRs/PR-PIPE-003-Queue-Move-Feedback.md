# PR-PIPE-003 – Queue Move Feedback & Visual Polish

## Context

When users click the "▲ Up" or "▼ Down" buttons in the queue panel, the job order changes but there is no visual feedback confirming the action succeeded. Users report uncertainty about whether their click registered:

1. **No visual confirmation** - The listbox updates but items look identical
2. **Selection may jump unexpectedly** - Current selection logic tries to follow the moved item but can fail
3. **No animation or flash** - Standard UX practice is to briefly highlight moved items
4. **No status message** - No toast or log entry confirms the operation

Additionally, the queue panel lacks keyboard shortcuts for common operations.

## Non-Goals

- Drag-and-drop reordering (future enhancement, more complex)
- Undo/redo functionality for queue operations
- Multi-select operations (move multiple jobs at once)
- Changing the underlying queue data structure
- Adding new queue operations (only improving existing ones)

## Invariants

- Queue order changes must be atomic and consistent
- Visual feedback must not block UI responsiveness
- All operations must work with keyboard navigation
- Existing test assertions about queue behavior must continue to pass
- Move operations must be idempotent (moving first item up = no-op)

## Allowed Files

- `src/gui/panels_v2/queue_panel_v2.py` - Visual feedback, keyboard shortcuts
- `src/gui/theme_v2.py` - Add highlight color constants (if needed)
- `src/gui/status_bar_v2.py` - Optional: toast messages
- `tests/gui_v2/test_queue_panel_move_feedback.py` (new)

## Do Not Touch

- `src/controller/app_controller.py` - Move logic unchanged
- `src/controller/pipeline_controller.py` - Move logic unchanged
- `src/queue/*` - Queue data structures unchanged
- `src/services/job_service.py` - Service layer unchanged

## Interfaces

### Visual Feedback Methods

```python
class QueuePanelV2(ttk.Frame):
    
    def _flash_item(self, index: int, color: str = "#4a90d9", duration_ms: int = 300) -> None:
        """
        Briefly highlight a listbox item to indicate action completion.
        
        Args:
            index: Listbox index to highlight
            color: Highlight color (default: accent blue)
            duration_ms: How long to show highlight before reverting
        """
    
    def _show_move_feedback(self, direction: str, success: bool) -> None:
        """
        Show feedback after a move operation.
        
        Args:
            direction: "up" or "down"
            success: Whether the move was actually performed
        """
    
    def _bind_keyboard_shortcuts(self) -> None:
        """Bind keyboard shortcuts for queue operations."""
```

### Status Message Protocol

```python
def _emit_status_message(self, message: str, level: str = "info") -> None:
    """
    Emit a status message via controller or status bar.
    
    Args:
        message: Short status text (e.g., "Moved job up")
        level: "info", "success", "warning", "error"
    """
```

### Error Behavior

- Move at boundary (top job up, bottom job down): No-op, subtle feedback
- Empty queue: Buttons remain disabled (existing behavior)
- Selection lost during move: Restore selection to moved item

## Implementation Steps (Order Matters)

### Step 1: Add Highlight Color Constants

In `src/gui/theme_v2.py`, add (if not present):

```python
# Feedback colors
HIGHLIGHT_SUCCESS = "#4a9f4a"  # Green flash for successful operations
HIGHLIGHT_MOVE = "#4a90d9"     # Blue flash for move operations
HIGHLIGHT_WARNING = "#d9a04a"  # Orange for warnings
HIGHLIGHT_DURATION_MS = 300    # Default flash duration
```

### Step 2: Implement Flash Animation

In `src/gui/panels_v2/queue_panel_v2.py`:

```python
def _flash_item(self, index: int, color: str = "#4a90d9", duration_ms: int = 300) -> None:
    """Briefly highlight a listbox item to indicate action completion."""
    if index < 0 or index >= self.job_listbox.size():
        return
    
    # Store original colors
    original_bg = self.job_listbox.cget("bg")
    original_select_bg = self.job_listbox.cget("selectbackground")
    
    # Apply highlight to the specific item
    self.job_listbox.itemconfig(index, bg=color, selectbackground=color)
    
    def _restore():
        try:
            if self.job_listbox.winfo_exists():
                self.job_listbox.itemconfig(index, bg=original_bg, selectbackground=original_select_bg)
        except tk.TclError:
            pass  # Widget destroyed
    
    # Schedule restore
    self.after(duration_ms, _restore)


def _flash_success(self, index: int) -> None:
    """Flash item green to indicate success."""
    self._flash_item(index, color="#4a9f4a", duration_ms=250)


def _flash_move(self, index: int) -> None:
    """Flash item blue to indicate move completed."""
    self._flash_item(index, color="#4a90d9", duration_ms=300)
```

### Step 3: Update Move Up Handler

Replace the existing `_on_move_up` method:

```python
def _on_move_up(self) -> None:
    """Move the selected job up in the queue with visual feedback."""
    job = self._get_selected_job()
    idx = self._get_selected_index()
    
    if not job or idx is None:
        return
    
    # Check if already at top
    if idx == 0:
        # Subtle feedback: item is already at top
        self._show_boundary_feedback("top")
        return
    
    # Perform the move
    if self.controller:
        success = self.controller.on_queue_move_up_v2(job.job_id)
        
        if success:
            # Update selection to follow the moved item
            new_idx = idx - 1
            
            # Schedule visual feedback after listbox updates
            def _apply_feedback():
                self._select_index(new_idx)
                self._flash_move(new_idx)
                self._emit_status_message(f"Moved job to position #{new_idx + 1}")
            
            # Small delay to let update_jobs complete
            self.after(50, _apply_feedback)
        else:
            self._emit_status_message("Move failed", level="warning")


def _show_boundary_feedback(self, boundary: str) -> None:
    """Show subtle feedback when job is at queue boundary."""
    idx = self._get_selected_index()
    if idx is not None:
        # Brief orange flash to indicate "can't go further"
        self._flash_item(idx, color="#d9a04a", duration_ms=150)
```

### Step 4: Update Move Down Handler

Replace the existing `_on_move_down` method:

```python
def _on_move_down(self) -> None:
    """Move the selected job down in the queue with visual feedback."""
    job = self._get_selected_job()
    idx = self._get_selected_index()
    
    if not job or idx is None:
        return
    
    # Check if already at bottom
    if idx >= len(self._jobs) - 1:
        self._show_boundary_feedback("bottom")
        return
    
    # Perform the move
    if self.controller:
        success = self.controller.on_queue_move_down_v2(job.job_id)
        
        if success:
            new_idx = idx + 1
            
            def _apply_feedback():
                self._select_index(new_idx)
                self._flash_move(new_idx)
                self._emit_status_message(f"Moved job to position #{new_idx + 1}")
            
            self.after(50, _apply_feedback)
        else:
            self._emit_status_message("Move failed", level="warning")
```

### Step 5: Add Status Message Emission

```python
def _emit_status_message(self, message: str, level: str = "info") -> None:
    """Emit a status message via controller or status bar."""
    # Try controller's append_log
    if self.controller and hasattr(self.controller, "_append_log"):
        prefix = {"info": "[queue]", "success": "[queue] ✓", "warning": "[queue] ⚠", "error": "[queue] ✗"}
        self.controller._append_log(f"{prefix.get(level, '[queue]')} {message}")
    
    # Try status bar if available
    if self.app_state and hasattr(self.app_state, "set_status_message"):
        try:
            self.app_state.set_status_message(message)
        except Exception:
            pass
```

### Step 6: Add Keyboard Shortcuts

```python
def _bind_keyboard_shortcuts(self) -> None:
    """Bind keyboard shortcuts for queue operations."""
    # Alt+Up: Move selected job up
    self.job_listbox.bind("<Alt-Up>", lambda e: self._on_move_up())
    
    # Alt+Down: Move selected job down
    self.job_listbox.bind("<Alt-Down>", lambda e: self._on_move_down())
    
    # Delete: Remove selected job
    self.job_listbox.bind("<Delete>", lambda e: self._on_remove())
    
    # Ctrl+Delete: Clear all (with confirmation)
    self.job_listbox.bind("<Control-Delete>", lambda e: self._on_clear_with_confirm())


def _on_clear_with_confirm(self) -> None:
    """Clear all with confirmation dialog."""
    if not self._jobs:
        return
    
    from tkinter import messagebox
    if messagebox.askyesno("Clear Queue", f"Remove all {len(self._jobs)} jobs from queue?"):
        self._on_clear()
```

Call `_bind_keyboard_shortcuts()` at the end of `__init__`.

### Step 7: Update Remove Handler with Feedback

```python
def _on_remove(self) -> None:
    """Remove the selected job from the queue with feedback."""
    job = self._get_selected_job()
    idx = self._get_selected_index()
    
    if not job:
        return
    
    if self.controller:
        self.controller.on_queue_remove_job_v2(job.job_id)
        self._emit_status_message(f"Removed job from position #{idx + 1}")
        
        # Select next item if available
        if self._jobs and idx is not None:
            new_idx = min(idx, len(self._jobs) - 1)
            if new_idx >= 0:
                self.after(50, lambda: self._select_index(new_idx))
```

### Step 8: Write Tests

Create `tests/gui_v2/test_queue_panel_move_feedback.py`.

## Acceptance Criteria

1. **Given** a queue with 3 jobs and the 2nd job selected, **when** clicking "▲ Up", **then** the job moves to position 1 AND a blue flash appears on that item.

2. **Given** the first job in queue is selected, **when** clicking "▲ Up", **then** an orange flash appears (boundary feedback) AND no move occurs.

3. **Given** a queue with 3 jobs and the 2nd job selected, **when** pressing Alt+Down, **then** the job moves to position 3 with visual feedback.

4. **Given** a job is moved, **when** the operation completes, **then** a log entry appears: "[queue] Moved job to position #N".

5. **Given** a job is selected, **when** pressing Delete, **then** the job is removed and the next job becomes selected.

6. **Given** jobs in the queue, **when** pressing Ctrl+Delete, **then** a confirmation dialog appears before clearing.

7. **Given** a move operation, **when** visual feedback animates, **then** the UI remains responsive (no blocking).

## Test Plan

### Unit Tests

```bash
pytest tests/gui_v2/test_queue_panel_move_feedback.py -v
```

**Test Cases:**

1. `test_flash_item_changes_color` - Verify itemconfig is called
2. `test_flash_item_restores_color` - Verify restoration after delay
3. `test_move_up_triggers_flash` - Flash called on successful move
4. `test_move_up_boundary_shows_warning` - Orange flash at top
5. `test_move_down_boundary_shows_warning` - Orange flash at bottom
6. `test_keyboard_alt_up_moves_job` - Alt+Up triggers move
7. `test_keyboard_alt_down_moves_job` - Alt+Down triggers move
8. `test_keyboard_delete_removes_job` - Delete key works
9. `test_selection_follows_moved_item` - Selection tracking
10. `test_status_message_emitted_on_move` - Log entry created

### Manual Verification

1. Open queue panel with multiple jobs
2. Click move up/down and observe flash animation
3. Try moving first job up (should see orange flash)
4. Use Alt+Up and Alt+Down keyboard shortcuts
5. Press Delete to remove a job
6. Verify log messages appear

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- All changes are UI-only
- No data structure changes
- Move logic unchanged in controllers
- Flash animations are purely visual

## Dependencies

- None

## Dependents

- None (standalone polish PR)
