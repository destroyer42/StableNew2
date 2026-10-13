"""PR-QUEUE-GPU-180: the GPU device-loss operator-readiness condition (pure projection, no Tk, no probe)."""
from __future__ import annotations

from pathlib import Path

from src.controller.gpu_loss_coordinator import GpuLossCoordinator
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.services.operator_readiness_service import (
    OperatorReadinessService,
    OperatorReadinessState,
    gpu_release_message,
)
from src.utils.gpu_device_health import HostGpuEvidence, HostGpuState
from src.video.svd_config import SVDConfig
from tests.queue.test_webui_outage_containment_171 import image, svd
from tests.services.test_operator_readiness_service import _preflight, _Repository, _WebUIConnection

LOST = HostGpuEvidence(HostGpuState.DEVICE_LOST, "gpu_is_lost")
HEALTHY = HostGpuEvidence(HostGpuState.HEALTHY, "gpu_enumerated", device_count=1)


def _service(tmp_path: Path, provider) -> OperatorReadinessService:
    (tmp_path / "packs").mkdir(exist_ok=True)
    (tmp_path / "output").mkdir(exist_ok=True)
    return OperatorReadinessService(
        repository=_Repository(),
        webui_connection=_WebUIConnection("ready"),  # a perfectly healthy WebUI
        prompt_pack_dir_provider=lambda: tmp_path / "packs",
        output_dir_provider=lambda: tmp_path / "output",
        svd_config_provider=SVDConfig,
        svd_preflight_provider=lambda _c, *, source_image_path=None: _preflight(source_path=source_image_path),
        ffmpeg_resolver=lambda: tmp_path / "ffmpeg.exe",
        python_version_provider=lambda: (3, 14, 0),
        free_threaded_provider=lambda: False,
        jit_enabled_provider=lambda: False,
        gpu_loss_provider=provider,
    )


def _quarantined(tmp_path: Path):
    repository = JobRepository(tmp_path / "queue.db")
    queue = JobQueue(repository=repository)
    for job in (image("a"), svd("b"), image("c")):
        queue.submit(job)
    probes: list[HostGpuEvidence] = [LOST]
    coordinator = GpuLossCoordinator(queue, probe=lambda: probes[-1])
    return repository, queue, coordinator, probes


def test_no_record_exists_without_an_active_quarantine(tmp_path: Path) -> None:
    baseline = _service(tmp_path, None).collect()
    _repo, _queue, coordinator, _probes = _quarantined(tmp_path)
    clear = _service(tmp_path, coordinator.snapshot).collect()
    assert baseline.record_for("gpu_device") is None and clear.record_for("gpu_device") is None
    assert [r.id for r in clear.records] == [r.id for r in baseline.records]
    _repo.close()


def test_confirmed_loss_is_the_first_actionable_record_even_with_a_healthy_webui(tmp_path: Path) -> None:
    repository, queue, coordinator, probes = _quarantined(tmp_path)
    queue.quarantine_gpu_dispatch(
        {
            "incident_id": "gpu-abc12345",
            "evidence_class": "confirmed_device_loss",
            "established_at": "2026-10-13T02:28:05.283+00:00",
            "trigger": {"job_id": "forge-00", "stage": "txt2img", "accelerator_fault": "device_fault"},
            "host_evidence": LOST.to_dict(),
            "release_requirements": ["positive_host_gpu_evidence", "operator_confirmation"],
        }
    )
    snapshot = _service(tmp_path, coordinator.snapshot).collect()
    record = snapshot.records[0]
    assert record.id == "gpu_device" and record.state is OperatorReadinessState.ACTION_REQUIRED
    text = " ".join(record.blocking_reasons)
    assert "gpu-abc12345" in text and "confirmed_device_loss" in text and "gpu_is_lost" in text
    assert "3 GPU job(s) are held" in text and "forge-00" in text
    assert "explicit confirmation" in text
    assert any("reboot" in action for action in record.operator_actions)
    assert any("does not" in action for action in record.operator_actions)  # StableNew will not reboot/reset/restart
    # The WebUI record is a different subject and is not softened or overridden by it (and vice versa).
    assert snapshot.record_for("webui").state is OperatorReadinessState.READY
    assert coordinator.snapshot()["operator_confirmation_required"] is True
    repository.close()


def test_projection_never_probes_and_reflects_a_refused_release(tmp_path: Path) -> None:
    repository, queue, coordinator, probes = _quarantined(tmp_path)
    queue.quarantine_gpu_dispatch({"incident_id": "gpu-1", "evidence_class": "confirmed_device_loss"})
    calls = {"n": 0}

    def counting() -> HostGpuEvidence:
        calls["n"] += 1
        return LOST

    coordinator = GpuLossCoordinator(queue, probe=counting)
    service = _service(tmp_path, coordinator.snapshot)
    service.collect()
    service.collect()
    assert calls["n"] == 0  # collect() runs on the Tk thread: it must never run the host probe
    refused = coordinator.release(operator_confirmed=True)
    assert calls["n"] == 1 and refused.released is False
    reasons = " ".join(service.collect().record_for("gpu_device").blocking_reasons)
    assert "Last release attempt was refused" in reasons and "does not yet enumerate" in reasons
    repository.close()


def test_release_message_vocabulary_is_operator_readable() -> None:
    for code in (
        "released",
        "not_quarantined",
        "operator_confirmation_required",
        "incident_mismatch",
        "no_positive_recovery_evidence",
        "release_not_durable",
    ):
        assert gpu_release_message({"reason": code}) and "_" not in gpu_release_message({"reason": code})
    assert gpu_release_message({"reason": "something_new"}) == "The release was not performed."
