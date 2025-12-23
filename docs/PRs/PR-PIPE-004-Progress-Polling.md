# PR-PIPE-004 – Running Job Progress from WebUI Polling

## Context

The current progress bar in the Running Job Panel only updates between pipeline stages, not during image generation. When generating a complex image that takes 60+ seconds, users see:

1. Progress bar stuck at 0% during txt2img
2. Sudden jump to 33% when txt2img completes
3. Stuck again during adetailer
4. Jump to 66%, etc.

This provides poor user experience. The Stable Diffusion WebUI exposes a `/sdapi/v1/progress` endpoint that returns:
- Current step number
- Total steps
- Progress percentage (0.0-1.0)
- ETA in seconds
- Current preview image (optional)

By polling this endpoint during generation, we can show real-time progress and potentially display in-progress preview images.

## Non-Goals

- Modifying how WebUI generates images
- Changing the executor's stage-based progress reporting
- WebSocket-based progress (polling is simpler and sufficient)
- High-frequency polling (keep at 1-2 Hz to avoid overhead)
- Displaying preview images (Phase 2 enhancement, noted but not implemented)

## Invariants

- Polling must not block the generation thread
- Polling failures must not abort the generation
- Progress must only update forward (never regress)
- Existing stage-based progress continues to work as fallback
- Polling stops immediately when generation completes or is cancelled
- Network errors during polling are silently ignored

## Allowed Files

- `src/api/client.py` - Add `get_progress()` method
- `src/pipeline/executor.py` - Add polling during `_generate_images`
- `src/gui/panels_v2/running_job_panel_v2.py` - Handle finer progress updates
- `src/gui/controller.py` - Progress callback handling (if needed)
- `tests/api/test_client_progress.py` (new)
- `tests/pipeline/test_executor_progress_polling.py` (new)

## Do Not Touch

- `src/api/healthcheck.py` - Different purpose
- `src/controller/app_controller.py` - Controller logic unchanged
- `src/queue/*` - Queue system unchanged
- `src/pipeline/job_models_v2.py` - NJR unchanged

## Interfaces

### SDWebUIClient Progress Method

```python
@dataclass
class ProgressInfo:
    """Progress information from WebUI."""
    
    progress: float           # 0.0 to 1.0
    eta_relative: float       # Seconds remaining (estimate)
    current_step: int | None  # Current sampling step
    total_steps: int | None   # Total sampling steps
    current_image: str | None # Base64 preview (optional, may be None)
    state: dict[str, Any]     # Raw state dict from WebUI


class SDWebUIClient:
    
    def get_progress(self, *, skip_current_image: bool = True) -> ProgressInfo | None:
        """
        Get current generation progress from WebUI.
        
        Args:
            skip_current_image: If True, don't request preview image (faster)
            
        Returns:
            ProgressInfo if generation in progress, None if idle or error
        """
```

### Executor Polling Integration

```python
class PipelineExecutor:
    
    def _generate_images_with_polling(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        poll_interval: float = 0.5,
        progress_callback: Callable[[float, float | None], None] | None = None,
    ) -> dict[str, Any]:
        """
        Call generation endpoint with progress polling.
        
        Args:
            endpoint: "txt2img" or "img2img"
            payload: Generation payload
            poll_interval: Seconds between progress polls
            progress_callback: Called with (progress, eta_seconds)
            
        Returns:
            Generation response
        """
```

### Progress Callback Protocol

```python
# Progress callbacks receive (percent, eta_seconds)
# percent: 0.0 to 100.0 (stage-relative)
# eta_seconds: Estimated seconds remaining (or None if unknown)

def on_progress(percent: float, eta_seconds: float | None) -> None: ...
```

### Error Behavior

- Progress endpoint returns error: Ignore, continue with generation
- Progress endpoint times out: Skip poll cycle, continue
- Progress regresses: Ignore regressed value, keep highest seen
- Generation completes before poll: Return result immediately
- Cancellation during poll: Stop polling, handle cancel

## Implementation Steps (Order Matters)

### Step 1: Add ProgressInfo Dataclass

In `src/api/client.py` or `src/api/types.py`:

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class ProgressInfo:
    """Progress information from WebUI /sdapi/v1/progress endpoint."""
    
    progress: float           # 0.0 to 1.0
    eta_relative: float       # Seconds remaining
    current_step: int | None
    total_steps: int | None
    current_image: str | None
    state: dict[str, Any]
    
    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "ProgressInfo":
        """Parse from WebUI response."""
        state = data.get("state", {})
        return cls(
            progress=float(data.get("progress", 0.0)),
            eta_relative=float(data.get("eta_relative", 0.0)),
            current_step=state.get("sampling_step"),
            total_steps=state.get("sampling_steps"),
            current_image=data.get("current_image"),
            state=state,
        )
```

### Step 2: Add get_progress Method to SDWebUIClient

In `src/api/client.py`:

```python
def get_progress(self, *, skip_current_image: bool = True) -> ProgressInfo | None:
    """
    Get current generation progress from WebUI.
    
    Args:
        skip_current_image: If True, don't include preview image in response
        
    Returns:
        ProgressInfo if generation in progress, None if idle or error
    """
    try:
        url = f"{self.base_url}/sdapi/v1/progress"
        params = {"skip_current_image": str(skip_current_image).lower()}
        
        response = self._session.get(
            url,
            params=params,
            timeout=(DEFAULT_CONNECT_TIMEOUT, 5.0),  # Short read timeout
        )
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        
        # Check if actually generating (progress > 0 or job running)
        state = data.get("state", {})
        if not state.get("job") and data.get("progress", 0) == 0:
            return None  # Idle
        
        return ProgressInfo.from_response(data)
        
    except Exception as exc:
        logger.debug("Progress poll failed: %s", exc)
        return None
```

### Step 3: Add Polling Helper to Executor

In `src/pipeline/executor.py`:

```python
import threading
from concurrent.futures import Future, ThreadPoolExecutor

class PipelineExecutor:
    
    def __init__(self, ...):
        # ... existing init ...
        self._progress_poll_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="progress_poll")
        self._current_generation_progress: float = 0.0
        self._progress_lock = threading.Lock()
    
    def _poll_progress_loop(
        self,
        stop_event: threading.Event,
        poll_interval: float,
        progress_callback: Callable[[float, float | None], None] | None,
        stage_label: str,
    ) -> None:
        """Background thread that polls WebUI for progress."""
        highest_progress = 0.0
        
        while not stop_event.is_set():
            try:
                info = self.client.get_progress(skip_current_image=True)
                
                if info is not None and info.progress > highest_progress:
                    highest_progress = info.progress
                    
                    with self._progress_lock:
                        self._current_generation_progress = highest_progress
                    
                    if progress_callback:
                        # Convert 0-1 to percentage
                        percent = highest_progress * 100.0
                        eta = info.eta_relative if info.eta_relative > 0 else None
                        progress_callback(percent, eta)
                        
            except Exception:
                pass  # Ignore polling errors
            
            # Wait for next poll or stop signal
            stop_event.wait(poll_interval)
    
    def _generate_images_with_progress(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        poll_interval: float = 0.5,
        progress_callback: Callable[[float, float | None], None] | None = None,
        stage_label: str = "generating",
    ) -> dict[str, Any]:
        """Call generation endpoint with concurrent progress polling."""
        
        stop_event = threading.Event()
        poll_future: Future | None = None
        
        try:
            # Start polling in background
            if progress_callback:
                poll_future = self._progress_poll_executor.submit(
                    self._poll_progress_loop,
                    stop_event,
                    poll_interval,
                    progress_callback,
                    stage_label,
                )
            
            # Make the actual generation request (blocking)
            response = self._generate_images(endpoint, payload)
            
            return response
            
        finally:
            # Stop polling
            stop_event.set()
            if poll_future:
                try:
                    poll_future.result(timeout=1.0)
                except Exception:
                    pass
```

### Step 4: Integrate Polling into txt2img

Update `_run_txt2img_impl` to use polling:

```python
def _run_txt2img_impl(self, ...):
    # ... existing payload setup ...
    
    # Create progress callback that reports to controller
    def on_txt2img_progress(percent: float, eta: float | None) -> None:
        if self.progress_controller:
            eta_text = self._format_eta(eta) if eta else "ETA: --"
            self.progress_controller.report_progress("txt2img", percent, eta_text)
    
    # Use polling version
    response = self._generate_images_with_progress(
        "txt2img",
        payload,
        poll_interval=0.5,
        progress_callback=on_txt2img_progress,
        stage_label="txt2img",
    )
    
    # ... rest of method unchanged ...
```

### Step 5: Integrate Polling into img2img

Apply same pattern to `run_img2img`.

### Step 6: Integrate Polling into ADetailer

Apply same pattern to `run_adetailer`.

### Step 7: Update Running Job Panel for Smoother Updates

In `src/gui/panels_v2/running_job_panel_v2.py`, ensure `update_progress` handles frequent updates smoothly:

```python
def update_progress(self, progress: float, eta_seconds: float | None = None) -> None:
    """Update progress bar and ETA display."""
    if self._dispatch_to_ui(lambda: self.update_progress(progress, eta_seconds)):
        return
    
    # Clamp progress to valid range
    clamped = max(0.0, min(100.0, progress))
    
    # Update progress bar smoothly
    self.progress_bar.configure(value=clamped)
    self.progress_label.configure(text=f"{int(clamped)}%")
    
    # Update ETA if provided
    if eta_seconds is not None:
        self.eta_label.configure(text=self._format_eta(eta_seconds))
```

### Step 8: Write Tests

Create test files for new functionality.

## Acceptance Criteria

1. **Given** a txt2img generation with 40 steps, **when** the job is running, **then** the progress bar updates approximately every 0.5 seconds showing increasing percentages.

2. **Given** a generation in progress, **when** polling the progress endpoint, **then** the request completes within 5 seconds and does not block generation.

3. **Given** progress polls returning values [0.2, 0.1, 0.5], **when** processing updates, **then** only 0.2 and 0.5 are applied (0.1 is ignored as regression).

4. **Given** the progress endpoint is unavailable, **when** generating images, **then** generation completes successfully with stage-based progress only.

5. **Given** a generation that takes 60 seconds, **when** watching progress, **then** the ETA display updates with decreasing time remaining.

6. **Given** a job is cancelled mid-generation, **when** cancellation occurs, **then** progress polling stops immediately.

7. **Given** WebUI is busy, **when** polling times out, **then** next poll cycle occurs normally without errors.

## Test Plan

### Unit Tests

```bash
pytest tests/api/test_client_progress.py -v
pytest tests/pipeline/test_executor_progress_polling.py -v
```

**API Tests:**

1. `test_get_progress_returns_progress_info` - Valid response parsing
2. `test_get_progress_returns_none_when_idle` - No generation in progress
3. `test_get_progress_handles_timeout` - Returns None on timeout
4. `test_get_progress_handles_connection_error` - Returns None on error
5. `test_progress_info_from_response` - Correct field extraction

**Executor Tests:**

1. `test_poll_progress_loop_calls_callback` - Callback invoked
2. `test_poll_progress_loop_stops_on_event` - Respects stop signal
3. `test_poll_progress_loop_ignores_regression` - Only forward progress
4. `test_generate_with_progress_completes` - Full generation works
5. `test_generate_with_progress_no_callback` - Works without callback
6. `test_progress_polling_concurrent_with_generation` - Polling doesn't block

### Integration Test

```python
def test_txt2img_shows_real_progress(webui_client, executor):
    """Verify progress updates during actual generation."""
    progress_values = []
    
    def on_progress(percent, eta):
        progress_values.append(percent)
    
    executor.progress_controller = MockProgressController(on_progress)
    executor.run_txt2img(prompt="test", config={...}, run_dir=..., batch_size=1)
    
    # Should have multiple progress updates
    assert len(progress_values) > 3
    # Should be monotonically increasing
    assert progress_values == sorted(progress_values)
```

## Rollback

```bash
git revert <commit-hash>
```

Rollback is safe because:
- Generation logic is unchanged
- `_generate_images_with_progress` wraps existing `_generate_images`
- Stage-based progress continues working as fallback
- Polling is additive, not replacing anything

## Dependencies

- None

## Dependents

- PR-PIPE-008 (Stage Timeline) could use fine-grained progress for timeline visualization
