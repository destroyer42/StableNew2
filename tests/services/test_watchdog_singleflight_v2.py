from __future__ import annotations

from types import SimpleNamespace

from src.services.watchdog_system_v2 import SystemWatchdogV2


class _Diagnostics:
    def wait_for_idle(self, timeout_s: float = 5.0) -> None:  # noqa: ARG002
        return None


def test_watchdog_start_is_single_instance_per_process(monkeypatch) -> None:
    started: list[str] = []

    class _DummyThread:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = False

        def start(self) -> None:
            self._alive = True
            started.append("started")

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float | None = None) -> None:  # noqa: ARG002
            self._alive = False

    monkeypatch.setattr("src.services.watchdog_system_v2.threading.Thread", _DummyThread)

    app = SimpleNamespace(_is_shutting_down=False)
    first = SystemWatchdogV2(app, diagnostics_service=_Diagnostics())
    second = SystemWatchdogV2(app, diagnostics_service=_Diagnostics())

    first.start()
    second.start()

    assert started == ["started"]

    first.stop()

