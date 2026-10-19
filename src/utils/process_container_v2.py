"""OS-level process container helpers (job objects / cgroup v2) for StableNew."""

from __future__ import annotations

import logging
import platform
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from src.utils import LogContext, log_with_ctx

if TYPE_CHECKING:
    from src.utils.cgroup_v2 import LinuxCGroupV2
    from src.utils.win_jobobject import WindowsJobObject

logger = logging.getLogger(__name__)
PROCESS_CONTAINER_LOG_PREFIX = "[CONTAINER]"


@dataclass
class ProcessContainerConfig:
    enabled: bool = True
    memory_limit_mb: float | None = None
    cpu_limit_percent: float | None = None
    max_processes: int | None = None


class ProcessContainer(ABC):
    #: A container that can adopt a child created suspended (``CREATE_SUSPENDED``), so the child provably runs no
    #: instruction, and spawns no descendant, before it is inside the container.
    supports_suspended_start: bool = False

    def __init__(self, job_id: str, config: ProcessContainerConfig) -> None:
        self.job_id = job_id
        self.config = config

    @abstractmethod
    def add_pid(self, pid: int) -> bool:
        """Place ``pid`` in the container.  Returns ``True`` only if the OS accepted it."""
        raise NotImplementedError

    def resume_suspended(self, pid: int) -> bool:
        """Resume a child created suspended and already placed in this container (``True`` only if the OS accepted).

        Only a container with ``supports_suspended_start`` can honour this; any other refuses, so a caller that
        created a child suspended never believes it is running when it is not."""
        return False

    def kill_all(self) -> None:
        """Kill all processes managed by this container."""
        raise NotImplementedError

    def teardown(self) -> None:
        """Release container resources."""
        raise NotImplementedError

    def inspect(self) -> dict[str, Any]:
        """Return debugging info."""
        return {
            "job_id": self.job_id,
            "container_type": type(self).__name__,
            "config": asdict(self.config),
        }


class NullProcessContainer(ProcessContainer):
    """No containment.  ``reason`` says why (``disabled``, ``unsupported_platform: ...``, ``construction_failed: ...``)
    so a caller that requires containment can refuse instead of silently running uncontained."""

    def __init__(
        self, job_id: str, config: ProcessContainerConfig, reason: str = "disabled"
    ) -> None:
        super().__init__(job_id, config)
        self.reason = reason

    def add_pid(self, pid: int) -> bool:
        return False

    def kill_all(self) -> None:
        pass

    def teardown(self) -> None:
        pass


def build_process_container(job_id: str, config: ProcessContainerConfig) -> ProcessContainer:
    if not config.enabled:
        return NullProcessContainer(job_id, config, "disabled")
    system = platform.system().lower()
    if system.startswith("windows"):
        try:
            from .win_jobobject import WindowsJobObject

            container = WindowsJobObject(
                name=f"StableNewJob-{job_id}",
                memory_limit_mb=config.memory_limit_mb,
            )
            return WindowsContainerAdapter(job_id, config, container)
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.WARNING,
                "Failed to build Windows job object container",
                ctx=LogContext(job_id=job_id, subsystem="process_container"),
                extra_fields={"error": str(exc)},
            )
            return NullProcessContainer(
                job_id, config, f"construction_failed: windows job object: {exc}"
            )
    if system.startswith("linux"):
        try:
            from .cgroup_v2 import LinuxCGroupV2

            container = LinuxCGroupV2(
                job_id,
                memory_limit_mb=config.memory_limit_mb,
                cpu_limit_percent=config.cpu_limit_percent,
                max_processes=config.max_processes,
            )
            return LinuxContainerAdapter(job_id, config, container)
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.WARNING,
                "Failed to build Linux cgroup container",
                ctx=LogContext(job_id=job_id, subsystem="process_container"),
                extra_fields={"error": str(exc)},
            )
            return NullProcessContainer(
                job_id, config, f"construction_failed: linux cgroup v2: {exc}"
            )
    return NullProcessContainer(job_id, config, f"unsupported_platform: {system or 'unknown'}")


class WindowsContainerAdapter(ProcessContainer):
    supports_suspended_start = True

    def __init__(
        self,
        job_id: str,
        config: ProcessContainerConfig,
        inner: WindowsJobObject,
    ) -> None:
        super().__init__(job_id, config)
        self._inner = inner

    def add_pid(self, pid: int) -> bool:
        return bool(self._inner.assign(pid))

    def resume_suspended(self, pid: int) -> bool:
        from src.utils.win_jobobject import resume_suspended_process

        return bool(resume_suspended_process(pid))

    def kill_all(self) -> None:
        self._inner.kill_all()

    def teardown(self) -> None:
        self._inner.close()

    def inspect(self) -> dict[str, Any]:
        info = super().inspect()
        info.update(self._inner.inspect())
        return info


class LinuxContainerAdapter(ProcessContainer):
    def __init__(
        self,
        job_id: str,
        config: ProcessContainerConfig,
        inner: LinuxCGroupV2,
    ) -> None:
        super().__init__(job_id, config)
        self._inner = inner

    def add_pid(self, pid: int) -> bool:
        return bool(self._inner.add_pid(pid))

    def kill_all(self) -> None:
        self._inner.kill_all()

    def teardown(self) -> None:
        self._inner.teardown()

    def inspect(self) -> dict[str, Any]:
        info = super().inspect()
        info.update(self._inner.inspect())
        return info
