"""Read-only observations scoped to owned processes and containers."""

from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address


@dataclass(frozen=True, slots=True)
class ProcessTreeSample:
    root_pid: int
    process_count: int
    private_bytes: int
    working_set_bytes: int
    cpu_seconds: float
    priority_verified: bool | None
    priority_class: int | None = None


@dataclass(frozen=True, slots=True)
class ProcessLifecycleEvent:
    """One kernel notification from the owned container: ``new``, ``exit``, ``abnormal_exit`` or ``active_zero``.

    ``observed_ns`` is ``time.perf_counter_ns()`` when the runner drained the notification; it is never earlier than
    the event and is at most one runner poll interval later."""

    kind: str
    pid: int | None
    observed_ns: int
    #: For ``new``: the member's executable path, read from a handle proven to be in this container. ``None`` when the
    #: member had already gone or could not be read; an unidentified member is never assumed to be harmless.
    image: str | None = None


@dataclass(frozen=True, slots=True)
class OwnedTreeEvidence:
    """What the container itself recorded about one bounded child's whole tree, from launch to verified teardown.

    Only the owned container produces this (job-object completion port and accounting), never a command-line or PID
    search. It covers the members of the container only: a process that Windows creates outside the job (for example
    through a spoofed parent process or an in-process COM service) is not in it, so channel providers that fill that gap
    must be system-wide, not per-member. ``complete`` is true only when every cross-check holds: each member's creation and exit notification was
    received, the notification counts equal the container's own process total, and no member remained after teardown.
    An incomplete record is not evidence of a clean tree."""

    root_pid: int
    events: tuple[ProcessLifecycleEvent, ...]
    total_processes: int
    survivors_at_end: int
    runner_terminated_survivors: bool
    active_after_teardown: int
    io_read_bytes: int
    io_write_bytes: int
    io_other_bytes: int
    complete: bool
    problems: tuple[str, ...] = ()


def observe_owned_tcp_listener(
    root_pid: int,
    addresses: Sequence[IPv4Address | IPv6Address],
    port: int,
    *,
    include_descendants: bool,
) -> IPv4Address | IPv6Address | None:
    """Return the first endpoint whose matching sockets all belong to the live owned tree."""

    import psutil

    if root_pid <= 0:
        return None
    try:
        root = psutil.Process(root_pid)
        # The contained Windows venv launcher can start a serving interpreter as a child.
        tree = [root, *root.children(recursive=True)] if include_descendants else [root]
        owned = {member.pid for member in tree if member.is_running()}
        listeners = [
            (ip_address(connection.laddr.ip), connection.pid)
            for connection in psutil.net_connections(kind="tcp")
            if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port
        ]
        for address in addresses:
            owners = {
                owner
                for listener, owner in listeners
                if listener == address
                or (
                    address.is_loopback
                    and listener.is_unspecified
                    and listener.version == address.version
                )
            }
            if owners and owners <= owned:
                return address
    except psutil.Error as exc:
        raise OSError("Could not observe listeners for the managed launch.") from exc
    return None
