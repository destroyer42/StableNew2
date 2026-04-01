from __future__ import annotations

from pathlib import Path

from src.services.diagnostics_service_v2 import DiagnosticsServiceV2


def test_build_async_accepts_legacy_context_alias(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_bundle_build_async(**kwargs):
        captured.update(kwargs)
        on_done = kwargs.get("on_done")
        if callable(on_done):
            on_done()
        return None

    monkeypatch.setattr(
        "src.services.diagnostics_service_v2.bundle_build_async",
        _fake_bundle_build_async,
    )

    service = DiagnosticsServiceV2(tmp_path / "diagnostics")
    service.build_async(
        reason="queue_runner_stall",
        context={"runner_activity_age_s": 12.5, "watchdog_reason": "queue_runner_stall"},
    )

    assert captured["extra_context"] == {
        "runner_activity_age_s": 12.5,
        "watchdog_reason": "queue_runner_stall",
    }

