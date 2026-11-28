"""VID-WARM-373: consecutive Wan2.2 I2V-A14B jobs reuse the StableNew-owned ComfyUI.

Fakes only: no GPU, model, network or real process. The A14B spec declares
``keep_warm_between_jobs_seconds``; after a successful job the backend holds the owned process instead of
stopping it, the next job of the same workflow reuses it, and every other path still releases it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.runtime_state import CancellationError
from src.services.runtime_transition_service import RuntimeTransitionCoordinator
from src.services.runtime_warm_hold import RuntimeWarmHold
from src.video.comfy_process_manager import ComfyStartupError
from src.video.comfy_workflow_backend import _keep_warm_seconds
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_FULL_PICTURE_ID,
    WAN_A14B_ID,
    WAN_A14B_VERSION,
)
from src.video.workflow_readiness import WorkflowResourceReadiness
from src.video.workflow_registry import build_default_workflow_registry
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_info,
    _a14b_request,
    _fake_export,
    _FramesFake,
)
from tests.video.test_wan22_experimental_workflow import WAN_ID, _stats


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


class _Spawned:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def run_last(self) -> None:
        call = self.calls[-1]
        call["target"](*call["args"])


def _slot() -> tuple[RuntimeWarmHold, _Clock, _Spawned]:
    clock, spawned = _Clock(), _Spawned()
    slot = RuntimeWarmHold(
        clock=clock,
        spawn=spawned,
        shutdown_requested=lambda: False,
        add_shutdown_listener=lambda _listener: None,
        interpreter_running=lambda: True,
    )
    return slot, clock, spawned


def _client(tmp_path: Path) -> _FramesFake:
    return _FramesFake(tmp_path, save_node="16", info=_a14b_info(), stats=_stats(free_mib=11800.0))


def _run(backend: Any, tmp_path: Path, job: str) -> Any:
    request = _a14b_request(tmp_path)
    request.job_id = job
    request.output_dir = tmp_path / f"run-{job}"
    return backend.execute(None, request)


def test_the_a14b_spec_declares_a_bounded_idle_grace() -> None:
    spec = build_default_workflow_registry().get(WAN_A14B_ID, WAN_A14B_VERSION)

    policy = spec.backend_defaults["runtime_policy"]
    assert policy["release_owned_runtime_after_job"] is True
    assert policy["keep_warm_between_jobs_seconds"] == 120
    assert _keep_warm_seconds(spec) == 120.0


@pytest.mark.parametrize("value", [None, 0, -5, True, "120"])
def test_an_absent_or_malformed_grace_keeps_the_release_after_every_job(value: Any) -> None:
    spec = SimpleNamespace(
        backend_defaults={
            "runtime_policy": {
                "release_owned_runtime_after_job": True,
                "keep_warm_between_jobs_seconds": value,
            }
        }
    )

    assert _keep_warm_seconds(spec) == 0.0


def test_a_successful_job_keeps_the_owned_runtime_warm_instead_of_stopping_it(
    tmp_path: Path, _no_encode
) -> None:
    slot, _, spawned = _slot()
    backend = _a14b_backend(_client(tmp_path), tmp_path, warm_hold=slot)

    result = _run(backend, tmp_path, "job-1")

    manager = backend.fake_manager
    assert manager.stops == 0 and manager.running
    release = result.backend_metadata["runtime_release"]
    assert release == {
        "policy": "keep_warm_between_jobs",
        "ownership": "owned",
        "pid": manager.pid,
        "released": False,
        "held": True,
        "idle_release_seconds": 120.0,
    }
    assert slot.snapshot()["key"] == [WAN_A14B_ID, WAN_A14B_VERSION]
    assert len(spawned.calls) == 1


def test_the_next_a14b_job_reuses_the_same_process_and_is_judged_warm(
    tmp_path: Path, _no_encode
) -> None:
    slot, clock, _ = _slot()
    client = _client(tmp_path)
    first = _a14b_backend(client, tmp_path, warm_hold=slot)
    _run(first, tmp_path, "job-1")
    manager = first.fake_manager
    pid = manager.pid

    # A fresh backend instance (a new PipelineRunner per job) over the same owned process.
    second = _a14b_backend(client, tmp_path, warm_hold=slot)
    second._process_manager = manager
    clock.now += 40
    result = _run(second, tmp_path, "job-2")

    assert manager.starts == 1 and manager.stops == 0 and manager.pid == pid
    reuse = result.backend_metadata["runtime_reuse"]
    assert reuse["status"] == "warm" and reuse["pid"] == pid and reuse["idle_seconds"] == 40.0
    assert result.backend_metadata["runtime_release"]["held"] is True


def test_the_idle_grace_releases_the_owned_runtime(tmp_path: Path, _no_encode) -> None:
    slot, clock, spawned = _slot()
    backend = _a14b_backend(_client(tmp_path), tmp_path, warm_hold=slot)
    _run(backend, tmp_path, "job-1")

    clock.now += 121
    spawned.run_last()

    manager = backend.fake_manager
    assert manager.stops == 1 and not manager.running
    assert slot.snapshot() is None


def test_same_owned_warm_process_skips_the_vram_check_between_jobs(
    tmp_path: Path, _no_encode
) -> None:
    slot, _, _ = _slot()
    client = _client(tmp_path)
    first = _a14b_backend(client, tmp_path, warm_hold=slot)
    _run(first, tmp_path, "job-1")
    manager = first.fake_manager
    pid = manager.pid
    # Live ComfyUI reported only 64 MiB reserved by PyTorch after generation. The
    # old per-job check added that to 8,071 MiB driver free and rejected the warm job.
    client.stats = _stats(free_mib=8071.0, held_mib=64.0)
    second = _a14b_backend(client, tmp_path, warm_hold=slot)
    second._process_manager = manager
    driver_probes: list[int] = []

    def probe(index: int) -> tuple[float, float]:
        driver_probes.append(index)
        return 12282.0, 8071.0

    second._readiness = WorkflowResourceReadiness(ram_probe=lambda: 5.7, gpu_probe=probe)

    result = _run(second, tmp_path, "job-2")

    assert driver_probes == []
    assert len(client.queued) == 2
    assert manager.starts == 1 and manager.stops == 0 and manager.pid == pid
    assert result.backend_metadata["runtime_reuse"]["status"] == "warm"
    readiness = result.diagnostic_payload["resource_readiness"]
    assert readiness["observations"]["vram_check"] == "skipped_owned_warm_reuse"
    assert readiness["observations"]["ram_available_gb"] == 5.7


def test_warm_hold_does_not_exempt_a_replacement_process_from_the_vram_check(
    tmp_path: Path, _no_encode
) -> None:
    slot, _, _ = _slot()
    client = _client(tmp_path)
    first = _a14b_backend(client, tmp_path, warm_hold=slot)
    _run(first, tmp_path, "job-1")
    manager = first.fake_manager
    held_pid = manager.pid
    manager.stop()
    manager.ensure_running()

    client.stats = _stats(free_mib=8071.0, held_mib=64.0)
    second = _a14b_backend(client, tmp_path, warm_hold=slot)
    second._process_manager = manager
    assert manager.pid != held_pid

    with pytest.raises(RuntimeError, match="only 8135 MiB"):
        _run(second, tmp_path, "job-2")
    assert len(client.queued) == 1


def _segment(backend: Any, tmp_path: Path, job: str, **identity: Any) -> Any:
    """One segment of a sequence job (a Storyboard continuation is one): ``hold_runtime`` keeps ComfyUI up."""

    request = _a14b_request(tmp_path, **identity)
    request.job_id = job
    request.output_dir = tmp_path / f"run-{job}"
    request.hold_runtime = True
    return backend.execute(None, request)


def _held_model(client: _FramesFake) -> None:
    """ComfyUI now holds its model and PyTorch reports almost none of it: 8,135 MiB counts as available."""

    client.stats["devices"][0].update(_driver_free_mib=8071.0, torch_vram_total=64 * 1024 * 1024)


@pytest.mark.parametrize("before", ["a standalone job", "an earlier segment"])
def test_a_sequence_segment_on_the_same_warm_process_skips_the_vram_check(
    tmp_path: Path, _no_encode, before: str
) -> None:
    slot, _, _ = _slot()
    client = _client(tmp_path)
    backend = _a14b_backend(client, tmp_path, warm_hold=slot)
    (_run if before == "a standalone job" else _segment)(backend, tmp_path, "job-1")
    _held_model(client)

    result = _segment(backend, tmp_path, "job-2")

    assert len(client.queued) == 2 and backend.fake_manager.starts == 1
    observations = result.diagnostic_payload["resource_readiness"]["observations"]
    assert observations["vram_check"] == "skipped_owned_warm_reuse"


@pytest.mark.parametrize("change", ["nothing ran before", "another process", "another workflow"])
def test_the_vram_check_still_refuses_a_segment_that_is_not_a_verified_reuse(
    tmp_path: Path, _no_encode, change: str
) -> None:
    slot, _, _ = _slot()
    client = _client(tmp_path)
    backend = _a14b_backend(client, tmp_path, warm_hold=slot)
    manager = backend.fake_manager
    identity: dict[str, Any] = {}
    if change != "nothing ran before":
        _segment(backend, tmp_path, "job-1")
    if change == "another process":
        manager.stop()
        manager.ensure_running()
    if change == "another workflow":
        identity = {"workflow_id": WAN_A14B_FULL_PICTURE_ID}
    queued = len(client.queued)
    _held_model(client)

    with pytest.raises(RuntimeError, match="only 8135 MiB"):
        _segment(backend, tmp_path, "job-2", **identity)

    assert len(client.queued) == queued


def test_a_warm_claim_whose_launch_check_fails_releases_the_claimed_process(
    tmp_path: Path, _no_encode
) -> None:
    slot, _, _ = _slot()
    client = _client(tmp_path)
    first = _a14b_backend(client, tmp_path, warm_hold=slot)
    _run(first, tmp_path, "job-1")
    manager = first.fake_manager
    second = _a14b_backend(client, tmp_path, warm_hold=slot)
    second._process_manager = manager

    def refuse(_spec: Any) -> None:
        raise RuntimeError("launch flags unverifiable")

    second._verify_required_launch_flags = refuse  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="launch flags"):
        _run(second, tmp_path, "job-2")

    assert manager.stops == 1 and not manager.running and slot.snapshot() is None


def test_a_failed_job_still_releases_and_holds_nothing(tmp_path: Path, _no_encode) -> None:
    slot, _, spawned = _slot()
    client = _client(tmp_path)

    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("queue refused")

    client.queue_prompt = broken  # type: ignore[method-assign]
    backend = _a14b_backend(client, tmp_path, warm_hold=slot)

    with pytest.raises(RuntimeError, match="queue refused"):
        _run(backend, tmp_path, "job-1")

    assert backend.fake_manager.stops == 1
    assert slot.snapshot() is None and spawned.calls == []


def test_a_cancelled_job_releases_and_holds_nothing(tmp_path: Path, _no_encode) -> None:
    slot, _, _ = _slot()
    client = _client(tmp_path)

    def cancelled(*_a: Any, **_k: Any) -> Any:
        raise CancellationError("operator cancelled")

    client.queue_prompt = cancelled  # type: ignore[method-assign]
    backend = _a14b_backend(client, tmp_path, warm_hold=slot)

    with pytest.raises(CancellationError):
        _run(backend, tmp_path, "job-1")

    assert backend.fake_manager.stops == 1 and slot.snapshot() is None


def test_a_job_for_another_comfy_workflow_releases_the_held_runtime_first(
    tmp_path: Path, _no_encode
) -> None:
    slot, _, _ = _slot()
    backend = _a14b_backend(_client(tmp_path), tmp_path, warm_hold=slot)
    _run(backend, tmp_path, "job-1")
    manager = backend.fake_manager

    claim = slot.claim(runtime="comfy", key=(WAN_ID, "1.3.0"), current_pid=lambda: manager.pid)

    assert claim.status == "released" and manager.stops == 1 and not manager.running


def test_a_relaunched_process_is_never_stopped_by_a_stale_hold(tmp_path: Path, _no_encode) -> None:
    slot, clock, spawned = _slot()
    backend = _a14b_backend(_client(tmp_path), tmp_path, warm_hold=slot)
    _run(backend, tmp_path, "job-1")
    manager = backend.fake_manager
    # Something else stopped and relaunched the owned runtime (a new pid) without claiming the hold.
    manager.stop()
    manager.ensure_running()
    stops_before = manager.stops

    clock.now += 121
    spawned.run_last()

    assert manager.stops == stops_before and manager.running


def test_an_unowned_runtime_is_never_held(tmp_path: Path, _no_encode) -> None:
    slot, _, spawned = _slot()
    backend = _a14b_backend(_client(tmp_path), tmp_path, warm_hold=slot)
    backend.fake_manager._owns = False

    with pytest.raises(ComfyStartupError, match="StableNew-owned"):
        _run(backend, tmp_path, "job-1")

    assert spawned.calls == [] and slot.snapshot() is None
    assert backend.fake_manager.stops == 0


def test_an_unarmed_hold_falls_back_to_the_release(tmp_path: Path, _no_encode) -> None:
    slot = RuntimeWarmHold(
        spawn=lambda **_k: None,
        shutdown_requested=lambda: True,
        add_shutdown_listener=lambda _listener: None,
    )
    backend = _a14b_backend(_client(tmp_path), tmp_path, warm_hold=slot)

    result = _run(backend, tmp_path, "job-1")

    assert backend.fake_manager.stops == 1
    assert result.backend_metadata["runtime_release"]["released"] is True


def test_preparing_another_runtime_ends_the_hold_through_the_coordinator() -> None:
    ended: list[str] = []
    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None,
        comfy_manager_getter=lambda: None,
        svd_service_factory=lambda: SimpleNamespace(clear_model_cache=lambda: None),
        webui_endpoint_present=lambda: False,
        webui_endpoint_identity=lambda: "",
        comfy_endpoint_present=lambda: False,
        warm_hold_ender=ended.append,
    )

    coordinator.prepare_for("forge_webui")
    coordinator.prepare_for("comfy")

    assert ended == ["runtime transition to forge_webui", "runtime transition to comfy"]


def test_a_failing_hold_ender_never_breaks_a_transition() -> None:
    def boom(_reason: str) -> None:
        raise RuntimeError("slot broken")

    coordinator = RuntimeTransitionCoordinator(
        webui_manager_getter=lambda: None,
        comfy_manager_getter=lambda: None,
        svd_service_factory=lambda: SimpleNamespace(clear_model_cache=lambda: None),
        webui_endpoint_present=lambda: False,
        webui_endpoint_identity=lambda: "",
        comfy_endpoint_present=lambda: False,
        warm_hold_ender=boom,
    )

    assert coordinator.prepare_for("comfy").ready
