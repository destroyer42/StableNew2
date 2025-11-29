# Thread-Safety Fix for Model Refresh

## Issue
The GUI was updating Tkinter widgets from a background worker thread, which violates Tkinter's thread-safety requirements and could cause:
- Intermittent `TclError` exceptions
- GUI freezes
- Unpredictable behavior

## Root Cause
In `_update_api_status()`, a background thread was created that directly called:
- `_refresh_models()`
- `_refresh_vae_models()`
- `_refresh_upscalers()`
- `_refresh_schedulers()`

These methods updated combobox `values` and showed message boxes directly from the worker thread.

## Solution
Created thread-safe async versions of each method:
- `_refresh_models_async()`
- `_refresh_vae_models_async()`
- `_refresh_upscalers_async()`
- `_refresh_schedulers_async()`

### Pattern Used
```python
def _refresh_models_async(self):
    """Thread-safe version"""
    try:
        # 1. Perform blocking API call in worker thread
        models = self.client.get_models()

        # 2. Marshal widget updates to main thread
        def update_widgets():
            self.model_combo["values"] = models

        self.root.after(0, update_widgets)
    except Exception as exc:
        # 3. Marshal errors to main thread too
        self.root.after(
            0,
            lambda err=exc: messagebox.showerror("Error", f"Failed: {err}")
        )
```

### Key Points
1. **API calls**: Executed in worker thread (OK to block)
2. **Widget updates**: Scheduled on main thread via `root.after(0, ...)`
3. **Error dialogs**: Also scheduled on main thread
4. **Lambda closures**: Use default arguments to capture exception values

## Testing
Added comprehensive tests in `tests/gui/test_main_window_threading.py`:
- Validates all four async methods
- Tests error handling
- Uses proper Tkinter event pumping (no thread joins)
- All tests marked with `@pytest.mark.gui`

## Backward Compatibility
Original methods (`_refresh_models()`, etc.) remain unchanged for:
- Manual refresh button clicks (already on main thread)
- Legacy code that may call them directly
