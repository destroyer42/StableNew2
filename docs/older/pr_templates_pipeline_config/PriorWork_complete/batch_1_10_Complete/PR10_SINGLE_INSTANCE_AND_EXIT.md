# PR10 — Single-Instance Lock & Reliable Exit

## Problems Addressed

1. Launching a second StableNew window silently spawned another Tk process that competed for packs/configs.
2. Closing the GUI sometimes left zombie python.exe processes running because Tk refused to quit cleanly after a crash.

## Implementation Summary

- `src/main.py`
  - Introduced `_acquire_single_instance_lock()` which binds a fixed localhost port (47631) as a lightweight mutex.
  - `main()` checks the lock before initialising Tk. If the port is already in use, the user is shown a modal error (and a stderr message fallback) explaining that another instance is running.
d - Added the optional Tk `messagebox` import early so the modal works even before StableNewGUI is constructed.
- `StableNewGUI._graceful_exit()`
  - Persists preferences, requests the controller to stop, and waits briefly for cleanup while logging failures.
  - Always tears down Tk, and finally calls `os._exit(0)` to make sure no orphaned process remains if Tk gets stuck.

## Tests

- `tests/test_main_single_instance.py` confirms that the lock allows the first caller and rejects the second while the socket is held.
- Existing GUI smoke tests continue to exercise `_graceful_exit()` via the `WM_DELETE_WINDOW` wiring.

## User Impact

- Double-clicking StableNew twice now provides a clear message instead of running two conflicting GUIs.
- Closing the window (or hitting the Exit button) guarantees the background process terminates, avoiding the “stuck python.exe” issue reported after recent hangs.
