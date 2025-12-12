
# JT-07 — Startup and Async WebUI Bootstrap (Journey Test Specification)
### Version: 2025-11-26_1134
### StableNewV2 — High-Fidelity Journey Test Document

## 1. Summary
Validates StableNewV2 startup performance and asynchronous WebUI bootstrap process, ensuring fast GUI initialization, non-blocking WebUI detection, proper caching mechanisms, and correct application state transitions from launch to READY status.

## 2. Problem
StableNew startup must be fast and responsive. Blocking GUI initialization during WebUI detection creates poor user experience. WebUI bootstrap must be asynchronous, with proper caching to avoid repeated expensive operations. Status transitions must accurately reflect system state to prevent user confusion.

## 3. Goals

- Validate sub-second GUI initialization without WebUI blocking
- Confirm asynchronous WebUI detection and connection establishment
- Test proper status transitions (CONNECTING → READY)
- Verify WebUI cache creation and reuse for warm starts
- Ensure successful job execution after bootstrap completion
- Validate error handling for WebUI unavailability or connection failures

## 4. Non-Goals

- WebUI installation or configuration validation
- Detailed WebUI performance benchmarking
- Network connectivity testing beyond WebUI reachability
- GUI layout or styling validation
- Multi-user or concurrent startup scenarios
- System resource monitoring beyond basic responsiveness

## 5. Preconditions

- WebUI binary installed and executable
- WebUI cache file removed for cold start testing
- Sufficient system resources for GUI and WebUI processes
- Network connectivity to localhost WebUI endpoints
- No existing StableNew processes running
- Clean application state (no residual cache or configuration conflicts)

## 6. Test Steps

### 6.1 Cold Start Bootstrap Test

1. Ensure WebUI is not running and cache is cleared
2. Launch StableNewV2 application
3. Measure GUI initialization time (should be < 2 seconds)
4. Observe status transitions: LAUNCHING → CONNECTING → READY
5. Verify WebUI auto-detection and connection establishment
6. Confirm WebUI cache file creation with valid metadata
7. Execute a simple test job to validate full system readiness
8. Verify cache persistence across application restart

### 6.2 Warm Start Cache Test

1. Ensure WebUI is already running with valid cache present
2. Launch StableNewV2 application
3. Measure GUI initialization time (should be < 1 second)
4. Verify immediate READY status without CONNECTING phase
5. Confirm cache file is read and validated
6. Execute test job to ensure cached connection is functional
7. Test cache invalidation scenarios (WebUI restart, port changes)

### 6.3 Bootstrap Error Handling Test

1. Configure invalid WebUI endpoints or ports
2. Launch StableNewV2 application
3. Verify appropriate error status (CONNECTION_FAILED, WEBUI_NOT_FOUND)
4. Test timeout handling for unresponsive WebUI
5. Validate error recovery when WebUI becomes available
6. Confirm graceful degradation without application crashes

## 7. Expected Artifacts

- WebUI cache file with connection metadata and validation timestamps
- Application logs showing bootstrap sequence and status transitions
- Successful job execution artifacts (images, metadata) proving full system readiness
- Performance metrics for GUI initialization and WebUI connection times
- StructuredLogger entries documenting bootstrap process and cache operations

## 8. Edge Cases

- WebUI process starts after StableNew launch but before timeout
- Network interruptions during bootstrap causing temporary unavailability
- Invalid or corrupted cache files requiring regeneration
- Multiple WebUI instances running on different ports
- System resource constraints affecting startup performance
- Unicode characters in WebUI paths or cache file locations
- Permission issues preventing cache file creation or access

## 9. Acceptance Criteria

- GUI initialization completes in under 2 seconds for cold starts, under 1 second for warm starts
- No blocking operations during WebUI detection phase
- Accurate status transitions reflecting actual system state
- WebUI cache file created with valid connection metadata
- Successful job execution after READY status is reached
- Proper error handling for WebUI connection failures without crashes
- Cache validation and regeneration when WebUI configuration changes

## 10. Rollback Plan

- If startup performance regresses: Profile initialization code, optimize blocking operations
- If WebUI detection fails: Verify WebUI endpoints, check network connectivity, validate cache integrity
- If status transitions are incorrect: Review state management logic, fix async operation handling
- If cache becomes corrupted: Implement cache validation, add regeneration logic
- Restore previous working cache file if new cache causes issues
