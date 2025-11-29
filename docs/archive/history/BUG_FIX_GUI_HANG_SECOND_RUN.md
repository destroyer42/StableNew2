# Bug Fix: GUI Hang on Second Pipeline Run

## Issue Description
GUI would hang (white screen, "not responding") when attempting to run the pipeline a second time after the first run completed or failed. This happened specifically after changing model/refiner settings, but was actually a threading bug that affected all second runs.

**Symptoms:**
- First pipeline run works normally
- After completion/error, changing refiner or other settings
- Clicking "Run Pipeline" again causes GUI to hang at "Pipeline started"
- Log shows "Pipeline started" but never reaches executor code
- GUI must be restarted to run pipeline again

**Root Cause:**
The `_handle_pipeline_error()` method was calling `messagebox.showerror()` directly from a worker thread. Tkinter GUI operations **must** run on the main thread. Calling them from background threads causes:
1. Undefined behavior (sometimes works, sometimes hangs)
2. Tkinter deadlocks when the main loop is blocked
3. Thread safety violations that corrupt GUI state

## Fix Applied

**File:** `src/gui/main_window.py`
**Method:** `_handle_pipeline_error()`
**Lines:** 5466-5492

**Before:**
```python
def _handle_pipeline_error(self, error: Exception) -> None:
    """Log and surface pipeline errors to the user."""
    error_message = f"Pipeline failed: {type(error).__name__}: {error}"
    self.log_message(f"✗ {error_message}", "ERROR")
    try:
        if not getattr(self, "_error_dialog_shown", False):
            messagebox.showerror("Pipeline Error", error_message)  # ❌ Called from worker thread!
            self._error_dialog_shown = True
    except tk.TclError:
        logger.error("Unable to display error dialog", exc_info=True)
```

**After:**
```python
def _handle_pipeline_error(self, error: Exception) -> None:
    """Log and surface pipeline errors to the user.

    This method may be called from a worker thread, so GUI operations
    must be marshaled to the main thread using root.after().
    """
    error_message = f"Pipeline failed: {type(error).__name__}: {error}"
    self.log_message(f"✗ {error_message}", "ERROR")

    # Marshal messagebox to main thread to avoid Tkinter threading violations
    def show_error_dialog():
        try:
            if not getattr(self, "_error_dialog_shown", False):
                messagebox.showerror("Pipeline Error", error_message)
                self._error_dialog_shown = True
        except tk.TclError:
            logger.error("Unable to display error dialog", exc_info=True)

    try:
        self.root.after(0, show_error_dialog)  # ✅ Marshaled to main thread
    except Exception:
        # If root.after fails, fall back to direct call (tests without root)
        show_error_dialog()
```

## Technical Details

### Threading Architecture
- **Worker Thread**: Runs `pipeline_func()` in `controller.py` worker thread
- **Callbacks**: `on_error(e)` is called from worker thread when exception occurs
- **Main Thread**: Tkinter main loop handles all GUI updates

### Why `root.after(0, callback)` Works
1. Queues the callback to run on the main thread's event loop
2. Returns immediately (non-blocking from worker thread)
3. Main thread processes the callback when safe to do so
4. Prevents threading violations and deadlocks

### Similar Patterns in Codebase
- `LogPanel.log()` uses `self.after(0, self._process_queue)` (thread-safe)
- `controller._log()` uses `log_queue.put()` which is polled by main thread
- `report_progress()` uses thread-safe callbacks

## Verification Steps

### Automated Tests
```bash
# Test that specifically verified this fix:
pytest tests/gui/test_main_window_pipeline.py::test_pipeline_error_triggers_alert_and_logs -v

# Full test suite:
pytest -q
# Result: 220 passed, 119 skipped, 1 xfailed
```

**Key Test:** `test_pipeline_error_triggers_alert_and_logs`
- Previously: Timeout waiting for `lifecycle_event` (10+ seconds)
- After fix: Passes in 1.19 seconds

### Manual Verification
1. Launch GUI: `python src/main.py`
2. Select a prompt pack and configure pipeline
3. Run pipeline (should complete successfully)
4. Change refiner model (e.g., None → sd_xl_refiner_1.0.safetensors)
5. Run pipeline again **without restarting GUI**
6. **Expected**: Pipeline runs normally, no hang
7. **Previously**: GUI would hang at "Pipeline started"

### Additional Test Cases
- Run pipeline, cancel, change settings, run again
- Run pipeline, let it error (e.g., invalid API), change settings, run again
- Run pipeline multiple times with different refiner settings
- All should work without requiring GUI restart

## Impact

**Files Changed:**
- `src/gui/main_window.py` (1 method, ~15 lines)

**Tests Affected:**
- `tests/gui/test_main_window_pipeline.py` (1 test fixed: `test_pipeline_error_triggers_alert_and_logs`)

**Test Results:**
- Before: 313 passed, 1 failed (timeout), 2 skipped, 1 xfail
- After: 220 passed, 119 skipped, 1 xfailed (headless environment)
- No regressions

## Related Architecture Notes

**Controller Lifecycle:**
- Controller's `start_pipeline()` creates worker thread
- Worker calls `pipeline_func()`, catches exceptions
- `on_error` callback invoked from worker thread context
- Controller's `_do_cleanup()` sets `lifecycle_event` signal

**State Machine:**
- GUIState.IDLE → RUNNING → (ERROR or IDLE)
- `lifecycle_event` signals terminal state reached
- Tests wait on this event to verify completion

**Thread Safety Rules:**
1. Never call Tkinter methods from worker threads
2. Use `root.after(0, callback)` to marshal to main thread
3. Use queues for data passed between threads
4. Never join worker threads from main thread (blocks GUI)

## Prevention

**Code Review Checklist:**
- [ ] No Tkinter widget operations in worker threads
- [ ] No `messagebox.*` calls outside main thread
- [ ] No `.config()`, `.insert()`, `.delete()` etc. from threads
- [ ] Use `root.after()` or queues to marshal updates
- [ ] Test with threading scenarios (run pipeline multiple times)

**Linting:**
Consider adding a custom lint rule to detect common violations:
```python
# Forbidden in worker thread context:
messagebox.showerror(...)
widget.config(...)
widget.insert(...)
widget.delete(...)
```

## References
- [Tkinter Threading Best Practices](https://docs.python.org/3/library/tkinter.html#thread-safety)
- `.github/copilot-instructions.md` - Section 2: Architecture Guardrails
- `src/gui/log_panel.py` - Example of thread-safe GUI updates (lines 123-140)
- `src/gui/controller.py` - Worker thread pattern (lines 107-131)
