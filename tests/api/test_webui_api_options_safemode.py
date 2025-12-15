from __future__ import annotations

from typing import Any

from src.api.webui_api import OptionsApplyResult, WebUIAPI


class _SafeModeClient:
    def __init__(self) -> None:
        self.update_calls = 0

    @property
    def options_write_enabled(self) -> bool:
        return False

    def check_api_ready(self) -> bool:
        return True

    def update_options(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.update_calls += 1
        return {}


def test_apply_options_skips_updates_during_safemode() -> None:
    client = _SafeModeClient()
    api = WebUIAPI(client=client, options_min_interval=0.0)

    result = api.apply_options({"enable": True}, return_status=True)

    assert result == OptionsApplyResult.SKIPPED_SAFEMODE
    assert client.update_calls == 0

