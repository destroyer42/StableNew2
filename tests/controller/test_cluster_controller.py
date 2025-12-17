from src.cluster.worker_model import WorkerStatus
from src.controller.cluster_controller import ClusterController


def test_cluster_controller_initializes_registry():
    controller = ClusterController()
    local = controller.get_local_worker()
    assert local.is_local is True
    assert controller.list_workers()
    controller.get_registry().update_worker_status(local.id, WorkerStatus.MAINTENANCE)
    updated = controller.get_registry().get_worker(local.id)
    assert updated.status == WorkerStatus.MAINTENANCE
