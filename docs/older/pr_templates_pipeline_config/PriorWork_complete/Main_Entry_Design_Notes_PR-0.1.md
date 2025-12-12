Main Entry Design Notes (PR-0.1)
================================

Context
-------
- Previous snapshots show `src/main.py` as responsible for:
  - Optional logging bypass (`STABLENEW_LOGGING_BYPASS`).
  - Single-instance lock on a fixed TCP port (`_INSTANCE_PORT`).
  - Constructing and running `StableNewGUI` from `src.gui.main_window`.

- Architecture_v2 introduces:
  - `MainWindow_v2` in `src.gui.main_window_v2`.
  - `AppController` in `src.controller.app_controller`.
  - A `PipelineRunner` abstraction (with `DummyPipelineRunner` as a stub).

The goal in PR-0.1 is to make `src/main.py` use the v2 stack while preserving the process-level behavior.

Key Design Decisions
--------------------
- `main()` remains the single entrypoint for the application.
- The single-instance lock is still enforced before any GUI is created.
- The v2 GUI uses Tk directly; `main()` will now create the Tk root and pass it into `MainWindow_v2`.
- `AppController` owns lifecycle, cancellation, and all interactions between GUI and pipeline.

Suggested Pseudocode
--------------------

    def main() -> None:
        setup_logging("INFO")
        lock_sock = _acquire_single_instance_lock()
        if lock_sock is None:
            # show "already running" message (unchanged)
            return

        root = tk.Tk()
        window = MainWindow(root)
        controller = AppController(window, threaded=True)
        root.mainloop()

Later, when a real pipeline runner is used, `AppController` can be constructed with an explicit `RealPipelineRunner`, but that is beyond the scope of PR-0.1.

Notes
-----
- Keep `if __name__ == "__main__": main()` intact.
- Do not change the module-level constants or environment variable checks.
- Avoid introducing additional side effects in `main.py`; keep it focused on:
  - Logging setup
  - Instance lock
  - GUI + controller creation
  - Tk mainloop
