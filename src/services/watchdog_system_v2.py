import threading
import time
from collections import defaultdict


class SystemWatchdogV2:
    # Tune these as needed
    UI_STALL_S = 3.0
    RUNNER_STALL_S = 10.0
    LOOP_PERIOD_S = 1.0

    # Cooldowns prevent spam while a condition remains true
    COOLDOWN_S = {
        "ui_heartbeat_stall": 30.0,
        "queue_runner_stall": 30.0,
    }

    def __init__(self, app_controller, diagnostics_service):
        self.app = app_controller
        self.diagnostics = diagnostics_service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        self._last_trigger_ts: dict[str, float] = defaultdict(lambda: 0.0)
        self._in_flight: dict[str, bool] = defaultdict(lambda: False)

    def start(self) -> None:
        t = threading.Thread(target=self._loop, daemon=True, name="SystemWatchdogV2")
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            # best effort join; don't hang shutdown
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check()
            except Exception:
                # watchdog must never crash the app
                pass
            time.sleep(self.LOOP_PERIOD_S)

    def _check(self) -> None:
        now = time.monotonic()

        ui_age = now - float(getattr(self.app, "last_ui_heartbeat_ts", 0) or 0)
        if ui_age > self.UI_STALL_S:
            self._trigger("ui_heartbeat_stall", now)

        if self._queue_running_but_stalled(now):
            self._trigger("queue_runner_stall", now)

    def _queue_running_but_stalled(self, now: float) -> bool:
        return (
            hasattr(self.app, "has_running_jobs")
            and bool(self.app.has_running_jobs())
            and (now - float(getattr(self.app, "last_runner_activity_ts", 0) or 0)) > self.RUNNER_STALL_S
        )

    def _trigger(self, reason: str, now: float) -> None:
        cooldown = float(self.COOLDOWN_S.get(reason, 30.0))

        with self._lock:
            if self._in_flight[reason]:
                return
            if (now - self._last_trigger_ts[reason]) < cooldown:
                return

            self._in_flight[reason] = True
            self._last_trigger_ts[reason] = now

        context = {
            "ui_heartbeat_age_s": now - float(getattr(self.app, "last_ui_heartbeat_ts", 0) or 0),
            "queue_activity_age_s": now - float(getattr(self.app, "last_queue_activity_ts", 0) or 0)
                if hasattr(self.app, "last_queue_activity_ts") else None,
            "runner_activity_age_s": now - float(getattr(self.app, "last_runner_activity_ts", 0) or 0),
            "queue_state": getattr(self.app, "get_queue_state", lambda: None)(),
            "watchdog_reason": reason,
        }

        def _done_callback():
            with self._lock:
                self._in_flight[reason] = False

        # Prefer async build (don't block watchdog loop)
        try:
            # If your diagnostics_service has build_async, use it.
            if hasattr(self.diagnostics, "build_async"):
                # Call with on_done if supported; fall back if not accepted by signature.
                try:
                    self.diagnostics.build_async(reason=reason, context=context, on_done=_done_callback)  # type: ignore[arg-type]
                except TypeError:
                    # Older API: call without on_done and clear in-flight in a spawned thread
                    def _fallback_worker():
                        try:
                            self.diagnostics.build(reason=reason, context=context)
                        finally:
                            _done_callback()
                    threading.Thread(target=_fallback_worker, daemon=True, name=f"DiagTrigger-{reason}").start()
            else:
                # Fall back to spawning a thread here.
                def _worker():
                    try:
                        self.diagnostics.build(reason=reason, context=context)
                    finally:
                        _done_callback()
                threading.Thread(target=_worker, daemon=True, name=f"DiagTrigger-{reason}").start()
        except Exception:
            _done_callback()
