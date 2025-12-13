import threading
import time

class SystemWatchdogV2:
    def __init__(self, app_controller, diagnostics_service):
        self.app = app_controller
        self.diagnostics = diagnostics_service
        self._stop = threading.Event()

    def start(self) -> None:
        t = threading.Thread(
            target=self._loop,
            daemon=True,
            name="SystemWatchdogV2"
        )
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._check()
            time.sleep(1.0)

    def _check(self) -> None:
        now = time.monotonic()
        # UI heartbeat stall
        if now - getattr(self.app, 'last_ui_heartbeat_ts', 0) > 3.0:
            self._trigger("ui_heartbeat_stall")
        # Queue/runner stall
        if self._queue_running_but_stalled(now):
            self._trigger("queue_runner_stall")

    def _queue_running_but_stalled(self, now: float) -> bool:
        # Must define has_running_jobs() on app_controller
        return (
            hasattr(self.app, 'has_running_jobs') and self.app.has_running_jobs()
            and now - getattr(self.app, 'last_runner_activity_ts', 0) > 10.0
        )

    def _trigger(self, reason: str) -> None:
        # Synchronous diagnostics emission with context
        context = {
            "ui_heartbeat_age_s": time.monotonic() - getattr(self.app, 'last_ui_heartbeat_ts', 0),
            "queue_activity_age_s": None,  # Not tracked in DummyAppController
            "runner_activity_age_s": time.monotonic() - getattr(self.app, 'last_runner_activity_ts', 0),
            "queue_state": getattr(self.app, 'get_queue_state', lambda: None)(),
        }
        self.diagnostics.build(reason=reason, context=context)
