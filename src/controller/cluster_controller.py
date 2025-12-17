"""Cluster controller responsible for worker registry initialization."""

from __future__ import annotations

from src.cluster.worker_model import WorkerDescriptor, WorkerStatus
from src.cluster.worker_registry import WorkerRegistry


class ClusterController:
    """Lightweight facade for worker registry access."""

    def __init__(
        self, registry: WorkerRegistry | None = None, local_worker: WorkerDescriptor | None = None
    ) -> None:
        self._registry = registry or WorkerRegistry(local_worker=local_worker)

    def get_registry(self) -> WorkerRegistry:
        return self._registry

    def get_local_worker(self) -> WorkerDescriptor:
        return self._registry.get_local_worker()

    def list_workers(self, status: WorkerStatus | None = None):
        return self._registry.list_workers(status=status)
