from __future__ import annotations

from src.gui.app_state_v2 import AppStateV2


def test_app_state_unsubscribe_removes_listener() -> None:
    state = AppStateV2()
    calls: list[str] = []

    def _listener() -> None:
        calls.append("called")

    state.subscribe("history_items", _listener)
    state.set_history_items([object()])  # type: ignore[list-item]
    assert calls == ["called"]

    state.unsubscribe("history_items", _listener)
    state.set_history_items([])
    assert calls == ["called"]
