import threading
from typing import Any

from src.api.webui_api import WebUIAPI


class _CountingClient:
    def __init__(self) -> None:
        self.update_calls = 0
        self.payloads: list[dict[str, Any]] = []
        self._options_write_enabled = True

    @property
    def options_write_enabled(self) -> bool:
        return self._options_write_enabled

    def set_options_write_enabled(self, enabled: bool) -> None:
        self._options_write_enabled = bool(enabled)

    def update_options(self, payload: dict[str, Any]) -> None:
        self.update_calls += 1
        self.payloads.append(dict(payload))
        return {"status": "ok"}


def test_concurrent_apply_options_only_updates_once() -> None:
    stub = _CountingClient()
    api = WebUIAPI(client=stub, options_min_interval=999, time_provider=lambda: 0.0)

    threads = [threading.Thread(target=api.apply_options, args=({"a": 1},)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert stub.update_calls == 1


def test_identical_payload_is_skipped() -> None:
    stub = _CountingClient()
    time_values = iter([0.0, 1.0, 2.0])

    def time_provider() -> float:
        return next(time_values, 3.0)

    api = WebUIAPI(client=stub, options_min_interval=0.0, time_provider=time_provider)

    assert api.apply_options({"a": 1}) is True
    assert api.apply_options({"a": 1}) is False
    assert stub.update_calls == 1


def test_throttle_interval_blocks_rapid_updates() -> None:
    stub = _CountingClient()
    api = WebUIAPI(client=stub, options_min_interval=8.0, time_provider=lambda: 0.0)

    assert api.apply_options({"a": 1}) is True
    assert api.apply_options({"a": 2}) is False
    assert stub.update_calls == 1


def test_throttle_resets_after_interval_allows_update() -> None:
    stub = _CountingClient()
    time_values = iter([0.0, 0.0, 9.0])

    def time_provider() -> float:
        return next(time_values, 9.0)

    api = WebUIAPI(client=stub, options_min_interval=8.0, time_provider=time_provider)

    assert api.apply_options({"a": 1}) is True
    assert api.apply_options({"a": 2}) is False
    assert api.apply_options({"a": 2}) is True
    assert stub.update_calls == 2


def test_apply_options_is_thread_safe_under_high_concurrency() -> None:
    stub = _CountingClient()
    api = WebUIAPI(client=stub, options_min_interval=0.0, time_provider=lambda: 0.0)

    threads = [threading.Thread(target=api.apply_options, args=({"a": 1},)) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert stub.update_calls == 1
