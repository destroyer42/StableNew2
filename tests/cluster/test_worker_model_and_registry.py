from src.cluster.worker_model import WorkerDescriptor, WorkerStatus, default_local_worker
from src.cluster.worker_registry import WorkerRegistry


def test_local_worker_defaults():
    local = default_local_worker()
    assert local.is_local is True
    assert local.status == WorkerStatus.ONLINE
    assert local.id == "local"


def test_worker_registry_register_and_update():
    registry = WorkerRegistry()
    local = registry.get_local_worker()
    assert registry.get_worker(local.id) is not None

    worker = WorkerDescriptor(
        id="node-1", name="node-1", is_local=False, gpus=2, vram_gb=16.0, status=WorkerStatus.ONLINE
    )
    registry.register_worker(worker)

    all_workers = registry.list_workers()
    assert len(all_workers) >= 2

    registry.update_worker_status("node-1", WorkerStatus.MAINTENANCE)
    updated = registry.get_worker("node-1")
    assert updated is not None
    assert updated.status == WorkerStatus.MAINTENANCE
