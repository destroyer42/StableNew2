# PR-HB-067: Heartbeat Watchdog Wiring Cleanup

## Summary

Small cleanup pass on the heartbeat/watchdog subsystem after `PR-RECOV-066`.

This PR does not change the watchdog policy. Heartbeat stalls remain a
diagnostics signal, not an automatic WebUI restart trigger.

## Discovery Findings

1. `AppController` wired `on_runner_activity=self.notify_runner_activity` but
   did not define `notify_runner_activity()`.
2. `SystemWatchdogV2` could spawn background thread exceptions when a stall was
   detected before a diagnostics service had been attached.
3. The existing watchdog-context tests were stale against the current
   `SystemWatchdogV2` contract and were not isolating queue-runner stall checks.

## Changes

- Added `AppController.notify_runner_activity()` to update
  `last_runner_activity_ts`.
- Hardened `SystemWatchdogV2._trigger()` to no-op cleanly when diagnostics are
  unavailable instead of spawning failing worker threads.
- Rewrote the watchdog UI-stall context tests around the current async/build
  contract and added a controller test for runner activity timestamp updates.

## Intent

Keep heartbeat stalls useful as diagnostics while removing avoidable noise and
ensuring the runner activity hook is real.

## Verification

- `pytest tests/controller/test_heartbeat_stall_fix.py tests/services/test_watchdog_ui_stall_context.py -q`
- `python -m compileall src/controller/app_controller.py src/services/watchdog_system_v2.py tests/controller/test_heartbeat_stall_fix.py tests/services/test_watchdog_ui_stall_context.py`
