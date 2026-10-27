"""Tripwires for the canonical fake-client cancellation harness, never real endpoints."""

from pathlib import Path

import pytest

from src.api.webui_runtime_identity import WebUIRuntimeIdentity
from src.controller.runtime_state import CancelToken
from tests.helpers.runtime_isolation import isolated_image_backends
from tests.pipeline.test_pr_harden_009_r1a_txt2img_cancellation import (
    _BlockingTxt2ImgClient,
    _build_pipeline_runner,
    _build_record,
)


@pytest.mark.parametrize("ambient_state", ["free", "occupied", "unresponsive"])
def test_fake_client_runner_never_observes_host_endpoints(
    monkeypatch, tmp_path: Path, ambient_state
):
    attempts = []

    def host_probe(*args, **kwargs):
        attempts.append((args, kwargs))
        return "free" if ambient_state == "free" else "occupied"

    monkeypatch.setattr("src.api.healthcheck.probe_webui_endpoint", host_probe)
    monkeypatch.setattr("src.video.comfy_healthcheck.probe_comfy_endpoint", host_probe)
    monkeypatch.setattr(
        "src.api.webui_runtime_identity.probe_endpoint_runtime_identity",
        lambda *_a, **_k: WebUIRuntimeIdentity("forge_webui"),
    )

    def forbidden_request(*args, **kwargs):
        attempts.append((args, kwargs))
        pytest.fail("fake-client cancellation must never reach HTTP transport")

    monkeypatch.setattr("requests.sessions.Session.request", forbidden_request)
    client = _BlockingTxt2ImgClient(release_immediately=True)
    runner = _build_pipeline_runner(monkeypatch, tmp_path, client)
    result = runner.run_njr(_build_record(tmp_path, job_id="isolated-client"), CancelToken())

    assert attempts == [], "fake-client runner escaped to configured host endpoint probes"
    assert result.success
    assert client.post_count == 1


@pytest.mark.parametrize("refusal", ["identity", "conflicting_runtime"])
def test_isolated_runner_still_refuses_before_generation(monkeypatch, tmp_path: Path, refusal):
    client = _BlockingTxt2ImgClient(release_immediately=True)
    runner = _build_pipeline_runner(monkeypatch, tmp_path, client)
    if refusal == "identity":
        client.probe_runtime_identity = lambda: WebUIRuntimeIdentity("forge_webui")
    else:
        runner._image_backends = isolated_image_backends(
            webui_present=True, webui_identity="forge_webui"
        )
    result = runner.run_njr(_build_record(tmp_path, job_id="refused-client"), CancelToken())

    assert not result.success
    assert "forge_webui" in result.error
    assert client.post_count == 0
    assert client.interrupt_count == 0
