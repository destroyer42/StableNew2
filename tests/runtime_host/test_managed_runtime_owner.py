from __future__ import annotations

import pytest

from src.runtime_host.managed_runtime import ManagedRuntimeOwner


@pytest.mark.parametrize(
    ("runtime_name", "load_target", "wait_target", "worker_name", "config", "base_url"),
    [
        (
            "webui",
            "src.runtime_host.managed_runtime.load_webui_config",
            "src.runtime_host.managed_runtime.wait_for_webui_ready",
            "_bootstrap_webui_worker",
            {"webui_base_url": "http://127.0.0.1:7860"},
            "http://127.0.0.1:7860",
        ),
        (
            "comfy",
            "src.runtime_host.managed_runtime.load_comfy_config",
            "src.runtime_host.managed_runtime.wait_for_comfy_ready",
            "_bootstrap_comfy_worker",
            {"comfy_base_url": "http://127.0.0.1:8000"},
            "http://127.0.0.1:8000",
        ),
    ],
)
def test_background_unmanaged_bootstrap_waits_patiently_and_stays_disconnected(
    monkeypatch,
    runtime_name,
    load_target,
    wait_target,
    worker_name,
    config,
    base_url,
):
    owner = ManagedRuntimeOwner()
    calls = []

    monkeypatch.setattr(load_target, lambda: dict(config))

    def fake_wait(url, timeout=0.0, poll_interval=0.0, **kwargs):
        calls.append((url, timeout, poll_interval, dict(kwargs)))
        raise RuntimeError("still starting")

    monkeypatch.setattr(wait_target, fake_wait)

    getattr(owner, worker_name)()

    snapshot = owner.get_snapshot()[runtime_name]
    assert calls == [
        (
            base_url,
            10.0,
            1.0,
            {"respect_failure_backoff": False} if runtime_name == "webui" else {},
        )
    ]
    assert snapshot["state"] == "disconnected"
    assert snapshot["startup_error"] == "still starting"