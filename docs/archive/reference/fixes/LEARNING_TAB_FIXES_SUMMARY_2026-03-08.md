# Learning Tab Critical Bugfixes

## Date: 2024
## Status: COMPLETED

## Issues Fixed

### Issue 1: Learning Jobs Crashing with TypeError
**Symptom**: Learning tab submitted jobs failed with:
```
TypeError: unsupported operand type(s) for -: 'float' and 'NoneType'
```

**Root Cause**: WebUI subseed operations require non-None values for `subseed_strength` parameter. Learning jobs were missing:
- `subseed`
- `subseed_strength`
- `seed_resize_from_h`
- `seed_resize_from_w`

**Fix**: Added default values to baseline config:
- `subseed = -1`
- `subseed_strength = 0.0`
- `seed_resize_from_h = 0`
- `seed_resize_from_w = 0`

**Files Modified**:
- `src/gui/controllers/learning_controller.py` (lines 282-293, 312-315)

---

### Issue 2: Queue Pause Button Not Working
**Symptom**: Queue pause button and auto-run checkbox had no effect. Queue kept running.

**Root Cause**: `SingleNodeJobRunner._worker_loop()` never checked pause state. It only checked `_stop_event` for shutdown, but not the pause state from `JobService._queue_status`.

**Fix**: 
1. Added `is_paused` callback parameter to `SingleNodeJobRunner.__init__()`
2. Added pause check in `_worker_loop()` before dequeuing jobs
3. Wired callback from `JobService` to query `_queue_status == 'paused'`

**Files Modified**:
- `src/queue/single_node_runner.py` (lines 216, 228, 314-318)
- `src/controller/job_service.py` (lines 181-187)

---

### Issue 3: Empty Configuration Values in Learning Jobs
**Symptom**: `run_metadata.json` showed empty/null values:
```json
{
  "model": "",
  "sampler": null,
  "vae": "",
  "scheduler": "",
  "seed": null,
  "subseed": null,
  "subseed_strength": null
}
```

**Root Cause**: Learning controller's `_get_baseline_config()` method couldn't access stage cards:
- Method tried `pipeline_controller._get_stage_cards_panel()` which doesn't exist
- The method exists on `app_controller`, not `pipeline_controller`
- Learning controller didn't have `app_controller` reference
- Silent exception caused fallback to inadequate `app_state.current_config`

**Fix**:
1. Added `app_controller` parameter to `LearningController.__init__()`
2. Updated `_get_baseline_config()` to use `app_controller._get_stage_cards_panel()`
3. Added logging to track config retrieval success/failure
4. Ensured subseed parameters are added in both success and fallback paths

**Files Modified**:
- `src/gui/controllers/learning_controller.py` (lines 21, 27, 264-360)
- `src/gui/views/learning_tab_frame_v2.py` (line 54)

---

## Technical Details

### Configuration Flow (After Fix)

```
Learning Tab
    └─> LearningController (has app_controller reference)
        └─> _get_baseline_config()
            ├─> app_controller._get_stage_cards_panel()
            │   └─> stage_cards_panel.txt2img_card.to_config_dict()
            │       └─> Returns full config with model, vae, sampler, etc.
            │
            └─> Add subseed parameters
                ├─> subseed = -1
                ├─> subseed_strength = 0.0
                ├─> seed_resize_from_h = 0
                └─> seed_resize_from_w = 0
```

### Queue Pause Flow (After Fix)

```
User clicks pause button
    └─> JobService.pause_queue()
        └─> Sets _queue_status = 'paused'
            └─> SingleNodeJobRunner._worker_loop()
                └─> Checks self._is_paused() callback
                    └─> Returns True if _queue_status == 'paused'
                        └─> Skips job dequeuing
                        └─> Waits until unpaused
```

---

## Testing

### Test 1: Subseed Parameters
**Expected**: Jobs should not crash with TypeError
**Verification**: Check that baseline config has subseed parameters with defaults

### Test 2: Queue Pause
**Expected**: Queue stops processing after current job completes
**Verification**: 
1. Click pause button
2. Observe queue stops dequeuing new jobs
3. Click resume or enable auto-run
4. Queue resumes processing

### Test 3: Configuration Propagation
**Expected**: Learning jobs should use current stage card configuration
**Verification**: Check `run_metadata.json` in job output directory:
```json
{
  "model": "<actual model name>.safetensors",
  "sampler": "<actual sampler name>",
  "vae": "<actual vae name>.safetensors",
  "scheduler": "<actual scheduler>",
  "seed": <actual seed value>,
  "subseed": -1,
  "subseed_strength": 0.0
}
```

---

## Architectural Lessons

1. **Dependency Injection**: Controllers must receive all necessary dependencies at initialization. Trying to access methods through intermediate controllers leads to silent failures.

2. **Silent Exceptions**: Try/except blocks without logging can mask architectural problems. The original code silently failed when accessing non-existent methods, falling back to inadequate alternatives.

3. **Parameter Defaults**: Integration with external systems (WebUI) requires complete parameter sets. Missing optional parameters can cause runtime errors in unexpected places.

4. **State Checking**: Background workers must explicitly check all relevant state flags (pause, stop, etc.), not just assume shutdown is the only control mechanism.

---

## Remaining Considerations

1. **Logging**: The fix adds extensive logging to `_get_baseline_config()`. Monitor logs during learning job submission to verify config retrieval is working.

2. **Fallback Path**: The fallback config path (when no app_controller) still relies on `app_state.current_config`. This may have incomplete data if stage cards haven't synced to app_state.

3. **Test Coverage**: Existing tests instantiate LearningController without app_controller. This is fine for unit tests, but integration tests should verify the full config retrieval path.

---

## Files Changed Summary

| File | Lines | Changes |
|------|-------|---------|
| `src/gui/controllers/learning_controller.py` | 21, 27, 264-360 | Added app_controller param, rewrote _get_baseline_config with logging |
| `src/gui/views/learning_tab_frame_v2.py` | 54 | Pass app_controller to LearningController |
| `src/queue/single_node_runner.py` | 216, 228, 314-318 | Added is_paused callback and pause checking |
| `src/controller/job_service.py` | 181-187 | Wire pause callback to runner |

---

## Conclusion

All three critical bugs in the learning tab are now fixed:
1. ✅ Jobs no longer crash with subseed TypeError
2. ✅ Queue respects pause button and auto-run checkbox
3. ✅ Learning jobs receive full configuration from stage cards (model, vae, sampler, etc.)

The fixes follow architectural principles by:
- Using proper dependency injection
- Adding comprehensive logging
- Ensuring parameter completeness
- Implementing explicit state checking

Learning tab should now be fully functional for job submission and queue control.
