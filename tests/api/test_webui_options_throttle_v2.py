from __future__ import annotations

from typing import Any

from src.api.client import SDWebUIClient
from src.api.types import GenerateOutcome, GenerateResult
from src.api.webui_api import WebUIAPI


class _StubResult(GenerateResult):
    def __init__(self, stage: str) -> None:
        super().__init__(images=[], info={}, stage=stage)


def test_options_payload_is_deduped(monkeypatch):
    client = SDWebUIClient()
    calls: list[dict[str, Any]] = []

    def fake_update(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(payload))
        return {"status": "ok"}

    monkeypatch.setattr(client, "update_options", fake_update)
    time_values = iter([0.0, 0.0, 2.0, 6.0])
    webui_api = WebUIAPI(client=client, options_min_interval=5.0, time_provider=lambda: next(time_values))

    assert webui_api.apply_options({"foo": "bar"})
    assert len(calls) == 1

    # identical payload should be ignored even without advancing time
    assert not webui_api.apply_options({"foo": "bar"})
    assert len(calls) == 1

    # new payload but still inside throttle window should be skipped
    assert not webui_api.apply_options({"foo": "baz"})
    assert len(calls) == 1

    # after throttle window we should make a new request
    assert webui_api.apply_options({"foo": "baz"})
    assert len(calls) == 2


def test_stage_call_not_blocked(monkeypatch):
    client = SDWebUIClient()
    applied: list[dict[str, Any]] = []
    stages: list[str] = []

    monkeypatch.setattr(client, "update_options", lambda updates: applied.append(dict(updates)) or {})

    def fake_generate(stage: str, payload: dict[str, Any], **kwargs: Any) -> GenerateOutcome:
        stages.append(stage)
        return GenerateOutcome(result=_StubResult(stage=stage))

    monkeypatch.setattr(client, "generate_images", fake_generate)

    webui_api = WebUIAPI(client=client, options_min_interval=0.0, time_provider=lambda: 0.0)

    assert webui_api.apply_options({"foo": "bar"})
    outcome = webui_api.run_stage(stage="txt2img", payload={"prompt": "hi"})

    assert outcome.result is not None
    assert stages == ["txt2img"]
    assert len(applied) == 1
