import threading
import time

class SystemWatchdogV2:
    def __init__(self, app_controller, diagnostics_service):
        self.app = app_controller
        self.diagnostics = diagnostics_service
        self._stop = threading.Event()

    def start(self):
        threading.Thread(
            target=self._loop,
            daemon=True,
            name="SystemWatchdogV2"
        ).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            self._check()
            time.sleep(1.0)

    def _check(self):
        now = time.monotonic()
        # UI heartbeat stall
        if now - getattr(self.app, 'last_ui_heartbeat_ts', 0) > 3.0:
            self._trigger("ui_heartbeat_stall")
        # Queue/runner stall
        if self._queue_running_but_stalled(now):
            self._trigger("queue_runner_stall")

    def _queue_running_but_stalled(self, now):
        # Must define has_running_jobs() on app_controller
        return (
            hasattr(self.app, 'has_running_jobs') and self.app.has_running_jobs()
            and now - getattr(self.app, 'last_runner_activity_ts', 0) > 10.0
        )

    def _trigger(self, reason: str):
        # diagnostics_service must provide build_async()
        self.diagnostics.build_async(
            reason=reason,
            include_process_state=True,
            include_queue_state=True
        )
