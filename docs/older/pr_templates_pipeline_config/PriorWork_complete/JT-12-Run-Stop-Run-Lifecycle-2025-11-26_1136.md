
# JT-12 — Run / Stop / Run Lifecycle (Journey Test Specification)
### Version: 2025-11-26_1136
### StableNewV2 — High-Fidelity Journey Test

## 1. Summary
Validates the complete controller lifecycle stability, ensuring proper state transitions between IDLE, RUNNING, STOPPING, and ERROR states during repeated pipeline executions, cancellations, and error recovery scenarios for reliable long-term application operation.

## 2. Problem
Controller state management is critical for application stability. Improper state transitions, deadlocks, or hanging processes can lead to unresponsive UI and resource leaks. The run/stop/run lifecycle must handle repeated operations gracefully while maintaining thread safety and proper cleanup.

- Verify transitions: IDLE → RUNNING → STOPPING → IDLE
- Run after stop must still work
- UI controls must lock/unlock correctly

## 3. Preconditions

- Pipeline controller operational
- CTRL-LC-001 implemented

## 4. Steps

1. Start txt2img run
2. Click Stop
3. Observe transitions
4. Start another run
5. Trigger error scenario to validate error state

## 5. Acceptance Criteria

- No deadlocks
- No hanging RUNNING state
- UI never becomes unresponsive

## 6. Non-Goals

- Performance benchmarking
- Memory leak detection
- Multi-threaded stress testing
- Network failure simulation

## 7. Expected Artifacts

### State Transition Logs

- Controller state change records in application logs
- Timestamped transitions between IDLE, RUNNING, STOPPING, ERROR states
- Thread lifecycle events and cleanup confirmations

### Generated Images

- Successful image outputs from completed runs
- Partial or interrupted outputs from stopped runs
- Error state artifacts if applicable

### UI Responsiveness Records

- Button state changes (enabled/disabled) during transitions
- Progress indicator updates and completion signals
- Error message displays and user notifications

## 8. Edge Cases

### Rapid State Transitions

- Multiple stop/start commands in quick succession
- Stop command issued immediately after start
- Concurrent UI interactions during state changes

### Resource Exhaustion

- Memory pressure during long-running operations
- Disk space exhaustion during image generation
- Network timeouts affecting external API calls

### Error State Recovery

- Pipeline failures leaving controller in ERROR state
- Recovery attempts from ERROR back to IDLE
- Multiple error conditions occurring simultaneously

### UI Responsiveness Issues

- Main thread blocking during intensive operations
- Progress updates failing to display correctly
- Button states not updating in sync with controller state

## 9. Rollback Plan

### State Recovery

- Force controller state reset to IDLE through emergency stop
- Clear any hanging RUNNING or STOPPING states
- Reset UI controls to default enabled/disabled states

### Process Cleanup

- Terminate any orphaned worker threads
- Clean up temporary files and partial outputs
- Reset pipeline configuration to known good state

### Log Analysis

- Review application logs for state transition anomalies
- Identify root cause of lifecycle failures
- Preserve logs for debugging before cleanup

### Application Restart

- Graceful application shutdown and restart
- Verify clean startup without state corruption
- Confirm controller returns to functional IDLE state
