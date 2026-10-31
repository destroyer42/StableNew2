"""VID-RES-350: advisory admission, authoritative post-handoff GPU guard. Fakes only."""

from __future__ import annotations

import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.api.http_transport import DispatchOutcomeUnknown
from src.services.runtime_transition_service import RUNTIME_FORGE_WEBUI, RuntimeTransitionError
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.workflow_preflight import evaluate_workflow_preflight
from src.video.workflow_readiness import WorkflowResourceReadiness
from tests.services.test_runtime_transition_forge import _coordinator, _WebUIManager
from tests.video.test_pr_vid_ux_311_preflight import TI2V, _gate, _probes, _spec
from tests.video.test_wan22_experimental_workflow import _backend, _FakeComfy, _request


@pytest.mark.parametrize("ram_gb", [0.5, 4.0, 8.0, 15.0])
def test_low_ram_allows_a_cold_backend_dispatch_and_records_the_warning(tmp_path, ram_gb, caplog):
    client = _FakeComfy(tmp_path)
    with caplog.at_level(logging.INFO):
        result = _backend(client, ram_gb=ram_gb).execute(None, _request(tmp_path, opt_in=True))
    assert len(client.queued) == 1
    readiness = result.diagnostic_payload["resource_readiness"]
    assert readiness["ready"] and readiness["blocking"] == []
    assert readiness["observations"]["ram_available_gb"] == ram_gb
    assert "qualification-derived" in readiness["advisories"][0]
    assert "ram_available_gb" in caplog.text and "qualification-derived" in caplog.text


@pytest.mark.parametrize("after_start", [(12282.0, 11000.0), (12282.0, 1500.0), None])
def test_driver_gpu_is_reassessed_after_owned_forge_release_and_comfy_start(tmp_path, after_start):
    events = []
    forge = _WebUIManager(identity=RUNTIME_FORGE_WEBUI)
    stop = forge.stop_webui

    def release():
        events.append("release")
        return stop()

    forge.stop_webui = release
    transition, _ = _coordinator(webui=forge)

    def driver(_index):
        events.append("driver")
        if forge.is_running():
            return (12282.0, 1500.0)
        assert "start" in events and "stats" in events
        return after_start

    preflight = evaluate_workflow_preflight(_spec(TI2V), _probes(vram=driver(0), ram_gb=0.5))
    assert preflight.queueable and _gate(preflight, "vram").state == "advisory"

    class Client(_FakeComfy):
        def get_system_stats(self, **kwargs):
            events.append("stats")
            stats = super().get_system_stats(**kwargs)
            # A misleading Comfy free-memory estimate never overrides the driver guard.
            stats["devices"][0]["vram_free"] = 12000 * 1024 * 1024
            return stats

        def queue_prompt(self, payload, **kwargs):
            events.append("dispatch")
            return super().queue_prompt(payload, **kwargs)

    client = Client(tmp_path)
    backend = ComfyWorkflowVideoBackend(
        client=client,
        transition=transition,
        process_manager=SimpleNamespace(ensure_running=lambda: events.append("start") or True),
        readiness=WorkflowResourceReadiness(ram_probe=lambda: 0.5, gpu_probe=driver),
    )
    if after_start and after_start[1] >= 10000:
        backend.execute(None, _request(tmp_path, opt_in=True))
        assert len(client.queued) == 1
        assert events == ["driver", "release", "start", "stats", "driver", "dispatch"]
    else:
        with pytest.raises(RuntimeError, match="not resource-ready"):
            backend.execute(None, _request(tmp_path, opt_in=True))
        assert client.queued == []
        assert events == ["driver", "release", "start", "stats", "driver"]
    assert forge.stop_calls == 1


@pytest.mark.parametrize("identity", ["forge_webui", "a1111_webui"])
def test_a_conflicting_external_runtime_is_never_stopped_or_adopted(tmp_path, identity):
    external = _WebUIManager(identity=identity, owned=False)
    transition, _ = _coordinator(webui=external)
    client = _FakeComfy(tmp_path)
    backend = _backend(client, ram_gb=0.5)
    backend._transition = transition
    with pytest.raises(RuntimeTransitionError, match="action_required"):
        backend.execute(None, _request(tmp_path, opt_in=True))
    assert external.stop_calls == 0 and external.is_running() and not external.owns_process
    assert client.queued == []


def test_an_unavailable_ram_measurement_is_advisory_and_cannot_hide_the_gpu_guard():
    def unavailable():
        raise OSError("RAM probe unavailable")

    readiness = WorkflowResourceReadiness(
        ram_probe=unavailable, gpu_probe=lambda _i: (12282, 11000)
    )
    spec = _spec(TI2V)
    stats = {"devices": [{"type": "cuda", "index": 0}]}
    result = readiness.evaluate(spec, system_stats=stats)
    assert result.ready and "RAM probe unavailable" in result.advisories[0]
    assert not readiness.evaluate(spec, system_stats={"devices": []}).ready


def test_resource_interpretation_does_not_mutate_the_published_workflow_spec():
    spec = _spec(TI2V)
    snapshot = deepcopy(spec.to_dict())
    evaluate_workflow_preflight(spec, _probes(ram_gb=0.5, vram=(12282, 500)))
    WorkflowResourceReadiness(ram_probe=lambda: 0.5, gpu_probe=lambda _i: (12282, 11000)).evaluate(
        spec, system_stats={"devices": [{"type": "cuda", "index": 0}]}
    )
    assert spec.to_dict() == snapshot


@pytest.mark.parametrize(
    "error",
    [MemoryError("host allocation failed"), DispatchOutcomeUnknown("prompt outcome unknown")],
)
def test_allocation_or_ambiguous_dispatch_error_is_never_retried(tmp_path, error):
    class Failing(_FakeComfy):
        def queue_prompt(self, payload, **kwargs):
            super().queue_prompt(payload, **kwargs)
            raise error

    client = Failing(tmp_path)
    with pytest.raises(type(error), match=str(error)) as caught:
        _backend(client, ram_gb=0.5).execute(None, _request(tmp_path, opt_in=True))
    assert caught.value is error and len(client.queued) == 1
