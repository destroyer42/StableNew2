import threading
import time
from collections import defaultdict


class SystemWatchdogV2:
    # Tune these as needed
    # PR-HEARTBEAT-FIX: Set to 10s for fast failure detection
    # Rationale: We want to detect true hangs/freezes quickly (fail fast).
    # BUT during active generation, progress polling updates the heartbeat,
    # so working-but-slow operations won't trigger false positives.
    # Result: 10s detects broken/frozen state fast, but active work keeps heartbeat alive.
    UI_STALL_S = 10.0
    RUNNER_STALL_S = 10.0
    LOOP_PERIOD_S = 1.0

    # Cooldowns prevent spam while a condition remains true
    COOLDOWN_S = {
        "ui_heartbeat_stall": 120.0,
        "queue_runner_stall": 90.0,
    }
    _ACTIVE_LOCK = threading.Lock()
    _ACTIVE_THREAD: threading.Thread | None = None

    def __init__(
        self, app_controller, diagnostics_service, *, check_interval_s: float | None = None
    ):
        self.app = app_controller
        self.diagnostics = diagnostics_service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._last_trigger_ts: dict[str, float] = defaultdict(lambda: 0.0)
        self._in_flight: dict[str, bool] = defaultdict(lambda: False)
        self._loop_period = (
            float(check_interval_s) if check_interval_s is not None else float(self.LOOP_PERIOD_S)
        )

    def start(self) -> None:
        """Start the watchdog monitoring thread.
        
        PR-WATCHDOG-001: Changed to non-daemon for clean shutdown.
        """
        with self._ACTIVE_LOCK:
            if self._thread and self._thread.is_alive():
                return
            if self.__class__._ACTIVE_THREAD and self.__class__._ACTIVE_THREAD.is_alive():
                return
        # PR-WATCHDOG-001: Changed from daemon=True to daemon=False
        t = threading.Thread(
            target=self._loop,
            daemon=False,  # Changed for clean shutdown
            name="SystemWatchdogV2"
        )
        t.start()
        self._thread = t
        with self._ACTIVE_LOCK:
            self.__class__._ACTIVE_THREAD = t

    def stop(self) -> None:
        """Stop the watchdog thread gracefully.
        
        PR-WATCHDOG-001: Increased timeout from 2s to 10s for clean shutdown.
        """
        self._stop.set()
        if self._thread and self._thread.is_alive():
            # PR-WATCHDOG-001: Increased timeout for reliable shutdown
            self._thread.join(timeout=10.0)
        with self._ACTIVE_LOCK:
            if self.__class__._ACTIVE_THREAD is self._thread:
                self.__class__._ACTIVE_THREAD = None
        wait_for_idle = getattr(self.diagnostics, "wait_for_idle", None)
        if callable(wait_for_idle):
            try:
                wait_for_idle(timeout_s=5.0)
            except Exception:
                pass

    def _loop(self) -> None:
        """Main watchdog loop - monitors system health.
        
        PR-WATCHDOG-001: Added shutdown check to prevent diagnostics during shutdown.
        """
        while not self._stop.is_set():
            try:
                # PR-WATCHDOG-001: Skip checks if shutdown requested
                if hasattr(self.app, '_is_shutting_down') and self.app._is_shutting_down:
                    break
                if not threading.main_thread().is_alive():
                    break
                self._check()
            except Exception:
                # watchdog must never crash the app
                pass
            time.sleep(self._loop_period)

    def _check(self) -> None:
        now = time.monotonic()
        heartbeat_ts = getattr(self.app, "last_ui_heartbeat_ts", None)
        if heartbeat_ts:
            ui_age = now - float(heartbeat_ts)
            if ui_age > self.UI_STALL_S:
                self._trigger("ui_heartbeat_stall", now)

        if self._queue_running_but_stalled(now):
            self._trigger("queue_runner_stall", now)

    def _queue_running_but_stalled(self, now: float) -> bool:
        runner_ts = getattr(self.app, "last_runner_activity_ts", None)
        if not runner_ts:
            return False
        return (
            hasattr(self.app, "has_running_jobs")
            and bool(self.app.has_running_jobs())
            and (now - float(runner_ts)) > self.RUNNER_STALL_S
        )

    def _trigger(self, reason: str, now: float) -> None:
        if not threading.main_thread().is_alive():
            return
        if hasattr(self.app, "_is_shutting_down") and self.app._is_shutting_down:
            return
        cooldown = float(self.COOLDOWN_S.get(reason, 30.0))

        with self._lock:
            if self._in_flight[reason]:
                return
            if (now - self._last_trigger_ts[reason]) < cooldown:
                return

            self._in_flight[reason] = True
            self._last_trigger_ts[reason] = now

        # PR-HB-003: Enhanced context for heartbeat stall diagnostics
        ui_heartbeat_ts = float(getattr(self.app, "last_ui_heartbeat_ts", 0) or 0)
        ui_age_s = now - ui_heartbeat_ts if ui_heartbeat_ts else None
        
        context = {
            "ui_age_s": ui_age_s,  # PR-HB-003: Explicit ui_age_s field
            "ui_heartbeat_age_s": ui_age_s,  # Keep for compatibility
            "queue_activity_age_s": now - float(getattr(self.app, "last_queue_activity_ts", 0) or 0)
            if hasattr(self.app, "last_queue_activity_ts")
            else None,
            "runner_activity_age_s": now
            - float(getattr(self.app, "last_runner_activity_ts", 0) or 0),
            "queue_state": getattr(self.app, "get_queue_state", lambda: None)(),
            "watchdog_reason": reason,
            # PR-HB-003: Add operation tracking and thresholds
            "current_operation_label": getattr(self.app, "current_operation_label", None),
            "last_ui_action": getattr(self.app, "last_ui_action", None),
            "ui_stall_threshold_s": self.UI_STALL_S,
            "last_ui_heartbeat_ts": ui_heartbeat_ts,
            "watchdog_now_ts": now,
            "shutdown_in_progress": bool(getattr(self.app, "_is_shutting_down", False)),
            "main_thread_alive": bool(threading.main_thread().is_alive()),
        }

        def _done_callback():
            with self._lock:
                self._in_flight[reason] = False

        diagnostics = getattr(self, "diagnostics", None)
        if diagnostics is None:
            _done_callback()
            return

        # Prefer async build (don't block watchdog loop)
        try:
            # If your diagnostics_service has build_async, use it.
            if hasattr(diagnostics, "build_async"):
                webui_tail = None
                try:
                    from src.api.webui_process_manager import get_global_webui_process_manager

                    manager = get_global_webui_process_manager()
                    if manager is not None:
                        webui_tail = manager.get_recent_output_tail(max_lines=200)
                except Exception:
                    webui_tail = None
                # Call with on_done if supported; fall back if not accepted by signature.
                try:
                    diagnostics.build_async(
                        reason=reason,
                        context=context,
                        on_done=_done_callback,
                        include_process_state=True,
                        webui_tail=webui_tail,
                        cooldown_s=cooldown,
                    )  # type: ignore[arg-type]
                except TypeError:
                    # Older API: call without on_done and clear in-flight in a spawned thread
                    def _fallback_worker():
                        try:
                            diagnostics.build(reason=reason, context=context)
                        finally:
                            _done_callback()

                    # PR-THREAD-001: Use ThreadRegistry for fallback worker
                    from src.utils.thread_registry import get_thread_registry
                    registry = get_thread_registry()
                    registry.spawn(
                        target=_fallback_worker,
                        name=f"DiagTrigger-{reason}",
                        daemon=False,
                        purpose=f"Fallback diagnostics trigger for {reason}"
                    )
            else:
                # Fall back to spawning a thread here.
                def _worker():
                    try:
                        diagnostics.build(reason=reason, context=context)
                    finally:
                        _done_callback()

                # PR-THREAD-001: Use ThreadRegistry for worker
                from src.utils.thread_registry import get_thread_registry
                registry = get_thread_registry()
                registry.spawn(
                    target=_worker,
                    name=f"DiagTrigger-{reason}",
                    daemon=False,
                    purpose=f"Diagnostics trigger for {reason}"
                )
        except Exception:
            _done_callback()
