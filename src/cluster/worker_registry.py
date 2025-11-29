# Subsystem: Cluster
# Role: Tracks available workers and their state for distributed execution.

"""In-memory worker registry for cluster V2 foundation."""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from src.cluster.worker_model import WorkerDescriptor, WorkerId, WorkerStatus, default_local_worker


class WorkerRegistry:
    """Thread-safe registry of workers."""

    def __init__(self, *, local_worker: WorkerDescriptor | None = None) -> None:
        self._lock = threading.Lock()
        self._workers: Dict[WorkerId, WorkerDescriptor] = {}
        self._local = local_worker or default_local_worker()
        self.register_worker(self._local)

    def register_worker(self, descriptor: WorkerDescriptor) -> None:
        with self._lock:
            self._workers[descriptor.id] = descriptor

    def update_worker_status(self, worker_id: WorkerId, status: WorkerStatus) -> None:
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker:
                worker.status = status

    def get_worker(self, worker_id: WorkerId) -> Optional[WorkerDescriptor]:
        with self._lock:
            return self._workers.get(worker_id)

    def list_workers(self, status: WorkerStatus | None = None) -> List[WorkerDescriptor]:
        with self._lock:
            workers = list(self._workers.values())
        if status is None:
            return workers
        return [w for w in workers if w.status == status]

    def get_local_worker(self) -> WorkerDescriptor:
        return self._local
