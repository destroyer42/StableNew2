"""Read-only snapshots of a bounded child's owned container; no lifecycle authority."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessTreeSample:
    root_pid: int
    process_count: int
    private_bytes: int
    working_set_bytes: int
    cpu_seconds: float
    priority_verified: bool | None
    priority_class: int | None = None
