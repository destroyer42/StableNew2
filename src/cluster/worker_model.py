# Subsystem: Cluster
# Role: Describes individual worker capabilities for cluster scheduling.

"""Worker descriptor models for cluster-aware execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

WorkerId = str


class WorkerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"
    DEGRADED = "degraded"


@dataclass
class WorkerDescriptor:
    id: WorkerId
    name: str
    is_local: bool = False
    gpus: int = 0
    vram_gb: float = 0.0
    tags: list[str] = field(default_factory=list)
    status: WorkerStatus = WorkerStatus.ONLINE
    last_heartbeat: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def default_local_worker() -> WorkerDescriptor:
    """Return a basic descriptor for the local worker."""

    return WorkerDescriptor(
        id="local",
        name="local-worker",
        is_local=True,
        gpus=1,
        vram_gb=0.0,
        tags=["local"],
        status=WorkerStatus.ONLINE,
        last_heartbeat=datetime.utcnow(),
    )
