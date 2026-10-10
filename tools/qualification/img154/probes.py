"""Strictly read-only Windows telemetry probes (opt-in; the offline contracts never import this module's live paths).

* The only subprocesses are the allow-listed read-only queries in ``ALLOW_LISTED_COMMANDS``; ``run_allow_listed`` refuses any
  other argv. Nothing is started, stopped, written, configured or sent to a runtime.
* Commit and physical-memory readings reuse ``tools/qualification/vid160c/win_memory.py`` (ctypes ``GetPerformanceInfo``); the
  GPU snapshot and process list reuse ``src/utils/process_inspector_v2`` (read-only ``nvidia-smi`` and ``psutil``).
* The only network activity is one TCP connect to the loopback qualification port (no HTTP), and it is injectable.
* Every provider is injected so the logic is exercised with fakes; a failing or missing provider yields an observation whose
  status is not ``ok``, never a zero.
"""

from __future__ import annotations

import json
import ntpath
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.qualification.img151.feasibility import READ_ONLY_COMMANDS as _IMG151_COMMANDS

from .core import ERROR, GIB, MIB, MISSING, OK, Observation, digest, is_hex_digest
from .evidence import (
    ACCEPTED_BASELINE_COVERAGE,
    BOUNDED,
    COMPLETE,
    FAULT_SOURCES,
    INACCESSIBLE,
    NOT_COLLECTED,
    FaultSnapshot,
    FaultSourceSnapshot,
    hash_files,
)
from .isolation import (
    QUALIFICATION_PORT,
    PortObservation,
    ProcessObservation,
)
from .preflight import ESSENTIAL_TELEMETRY

_EVENT_LOOKBACK = 100


def _events_command(log: str, providers: str) -> tuple[str, ...]:
    script = (
        "try { Get-WinEvent -FilterHashtable @{LogName='"
        + log
        + "';ProviderName="
        + providers
        + "} "
        "-MaxEvents " + str(_EVENT_LOOKBACK) + " -ErrorAction Stop "
        "| Select-Object RecordId,Id | ConvertTo-Json -Compress } "
        "catch { if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { '[]' } else { throw } }"
    )
    return ("powershell", "-NoProfile", "-NonInteractive", "-Command", script)


#: Fixed argv only. Event queries are ``Get-WinEvent`` reads; the catch block turns "no matching events" into an empty list so
#: that an empty result (complete coverage) is distinguishable from an inaccessible log (a non-zero exit).
ALLOW_LISTED_COMMANDS: Mapping[str, tuple[str, ...]] = {
    "pagefile": _IMG151_COMMANDS["pagefile"],
    "gpu_shared_memory": _IMG151_COMMANDS["gpu_shared_memory"],
    "hard_fault_pages": (
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "(Get-Counter '\\Memory\\Pages Input/sec' -ErrorAction Stop).CounterSamples | "
        "Select-Object -First 1 -ExpandProperty CookedValue",
    ),
    "boot_identity": (
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')",
    ),
    "events_whea": _events_command("System", "'Microsoft-Windows-WHEA-Logger'"),
    "events_display_driver": _events_command(
        "System", "'nvlddmkm','Display','Microsoft-Windows-Kernel-Power'"
    ),
    "events_wer": _events_command("Application", "'Windows Error Reporting'"),
}

CommandRunner = Callable[[Sequence[str]], str | None]

#: Directories (read-only listing) where Windows Error Reporting keeps report folders; LiveKernelEvent folders are named
#: ``Kernel_<code>_...``. Access may be denied; that is recorded as inaccessible, never as "none".
WER_DIRECTORIES = (
    Path(os.environ.get("ProgramData", "C:\\ProgramData"))
    / "Microsoft"
    / "Windows"
    / "WER"
    / "ReportArchive",
    Path(os.environ.get("ProgramData", "C:\\ProgramData"))
    / "Microsoft"
    / "Windows"
    / "WER"
    / "ReportQueue",
)


def _resolve_executable(name: str) -> str | None:
    """Absolute path for the one interpreter the allow-list uses, so a file planted in the working directory or on a user
    PATH entry is never executed. ``None`` when it does not exist (non-Windows hosts)."""

    if name != "powershell":
        return None
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    candidate = ntpath.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else None


def run_allow_listed(argv: Sequence[str], *, timeout_s: float = 20.0) -> str | None:
    """Run one allow-listed read-only query; ``None`` when it fails. Anything else is refused outright."""

    if tuple(argv) not in set(ALLOW_LISTED_COMMANDS.values()):
        raise PermissionError("command is not an allow-listed read-only query")
    executable = _resolve_executable(argv[0])
    if executable is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603
            [executable, *argv[1:]], capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def collect_code_revision() -> dict[str, Any]:
    """Read-only Git revision plus actual qualification-source hashes, including dirty bytes.

    A clean HEAD is asserted only when Git verifies the checkout and the entire status is clean.
    Hashes provide an inspectable code identifier even when Git is unavailable; no model is read.
    """
    root = Path(__file__).resolve().parents[3]
    paths = sorted(Path(__file__).parent.rglob("*.py"))
    hashes = {str(p.relative_to(root)).replace("\\", "/"): hash_files([p])[p.name] for p in paths}
    info: dict[str, Any] = {
        "state": "unverifiable",
        "sha": None,
        "source_sha256": digest(hashes),
        "source_hashes": hashes,
    }
    git = shutil.which("git")
    if git is None:
        return info
    try:
        # Fixed read-only commands. No fetch, hooks, checkout, or repository mutation.
        head = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--show-toplevel", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        status = subprocess.run(
            [
                git,
                "--no-optional-locks",
                "-C",
                str(root),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        lines = head.stdout.strip().splitlines()
        if (
            head.returncode == status.returncode == 0
            and len(lines) == 2
            and Path(lines[0]).resolve() == root
            and is_hex_digest(lines[1], length=40)
        ):
            info.update(sha=lines[1], state="dirty" if status.stdout.strip() else "clean")
    except (OSError, subprocess.SubprocessError):
        pass
    return info


# ---------------------------------------------------------------------------------------------- observation helpers


@dataclass(frozen=True)
class Clocks:
    mono: Callable[[], float] = time.monotonic
    utc: Callable[[], str] = lambda: datetime.now(UTC).isoformat()  # noqa: E731


def _obs(
    clocks: Clocks,
    name: str,
    value: float | int | str | bool | None,
    units: str,
    source: str,
    *,
    status: str = OK,
    detail: str = "",
) -> Observation:
    return Observation(name, value, units, source, clocks.mono(), clocks.utc(), status, detail)


def _failed(
    clocks: Clocks, name: str, units: str, source: str, detail: str, *, status: str = MISSING
) -> Observation:
    return _obs(clocks, name, None, units, source, status=status, detail=detail)


@dataclass
class ProbeResult:
    observations: dict[str, Observation] = field(default_factory=dict)
    telemetry_coverage: dict[str, str] = field(default_factory=dict)
    processes: list[ProcessObservation] | None = None
    port: PortObservation | None = None
    fault_snapshot: FaultSnapshot | None = None
    gaps: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)


def _json(text: str | None) -> Any:
    try:
        return json.loads(text) if text and text.strip() else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------- individual probes


def _default_memory_reader() -> Callable[[], Any]:
    from tools.qualification.vid160c.win_memory import read_system_commit

    return read_system_commit


def _default_gpu_snapshot() -> Callable[[], dict[str, object] | None]:
    from src.utils.process_inspector_v2 import collect_gpu_survivor_snapshot

    return collect_gpu_survivor_snapshot


def _default_process_memory_reader() -> Callable[[int], Any]:
    from tools.qualification.vid160c.win_memory import read_process_memory

    return read_process_memory


def _default_process_iterator() -> Callable[[], Any]:
    from src.utils.process_inspector_v2 import iter_python_processes

    return iter_python_processes


def probe_system_memory(
    clocks: Clocks, reader: Callable[[], Any] | None = None
) -> list[Observation]:
    """Actual Windows commit total/limit/headroom and available physical RAM (never ``RAM + pagefile - reserve``)."""

    source = "GetPerformanceInfo (tools/qualification/vid160c/win_memory.py)"
    try:
        info = (reader or _default_memory_reader())()
    except Exception as exc:  # noqa: BLE001 - recorded as a failed observation, never a guessed value
        detail = type(exc).__name__
        return [
            _failed(clocks, name, "bytes", source, detail, status=ERROR)
            for name in (
                "commit_headroom_bytes",
                "commit_limit_bytes",
                "commit_total_bytes",
                "ram_available_bytes",
            )
        ]
    return [
        _obs(clocks, "commit_headroom_bytes", info.commit_headroom_gb * GIB, "bytes", source),
        _obs(clocks, "commit_limit_bytes", info.commit_limit_gb * GIB, "bytes", source),
        _obs(clocks, "commit_total_bytes", info.commit_total_gb * GIB, "bytes", source),
        _obs(clocks, "ram_available_bytes", info.physical_available_gb * GIB, "bytes", source),
        _obs(clocks, "ram_total_bytes", info.physical_total_gb * GIB, "bytes", source),
    ]


def probe_pagefile(
    clocks: Clocks, runner: CommandRunner, disk_free: Callable[[str], int] | None = None
) -> list[Observation]:
    source = "Win32_PageFileUsage + disk usage of the pagefile volume"
    parsed = _json(runner(ALLOW_LISTED_COMMANDS["pagefile"]))
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not parsed:
        return [
            _failed(clocks, "pagefile_allocated_bytes", "bytes", source, "no pagefile record"),
            _failed(clocks, "pagefile_volume_free_bytes", "bytes", source, "no pagefile record"),
        ]
    try:
        allocated = sum(int(item.get("AllocatedBaseSize") or 0) for item in parsed) * MIB
        name = str(parsed[0].get("Name") or "")
        drive = ntpath.splitdrive(name)[0]
        free_fn = disk_free or (lambda root: shutil.disk_usage(root).free)
        free = free_fn(drive + "\\") if drive else None
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return [
            _failed(
                clocks,
                "pagefile_allocated_bytes",
                "bytes",
                source,
                type(exc).__name__,
                status=ERROR,
            )
        ]
    result = [_obs(clocks, "pagefile_allocated_bytes", allocated, "bytes", source)]
    if free is None:
        result.append(
            _failed(
                clocks, "pagefile_volume_free_bytes", "bytes", source, "pagefile volume unknown"
            )
        )
    else:
        result.append(_obs(clocks, "pagefile_volume_free_bytes", free, "bytes", source))
    return result


def probe_gpu(
    clocks: Clocks, snapshot: Callable[[], dict[str, object] | None] | None = None
) -> list[Observation]:
    source = "nvidia-smi via src/utils/process_inspector_v2.collect_gpu_survivor_snapshot"
    try:
        data = (snapshot or _default_gpu_snapshot())()
    except Exception as exc:  # noqa: BLE001
        data = None
        detail = type(exc).__name__
    else:
        detail = "no snapshot"
    names = (
        "vram_used_bytes",
        "vram_total_bytes",
        "gpu_temperature_c",
        "gpu_utilization_percent",
        "gpu_board_power_w",
    )
    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list) or not devices or not isinstance(devices[0], dict):
        units = {
            "gpu_temperature_c": "celsius",
            "gpu_utilization_percent": "percent",
            "gpu_board_power_w": "watts",
        }
        return [
            _failed(clocks, name, units.get(name, "bytes"), source, detail) for name in names
        ] + [
            _obs(
                clocks,
                "gpu_device_present",
                False,
                "boolean",
                source,
                status=MISSING,
                detail="no device reported",
            )
        ]
    device = devices[0]

    def mib(key: str) -> float | None:
        value = device.get(key)
        return (
            float(value) * MIB
            if isinstance(value, int | float) and not isinstance(value, bool)
            else None
        )

    def plain(key: str) -> float | None:
        value = device.get(key)
        return (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        )

    readings = (
        ("vram_used_bytes", mib("memory_used_mb"), "bytes"),
        ("vram_total_bytes", mib("memory_total_mb"), "bytes"),
        ("gpu_temperature_c", plain("temperature_c"), "celsius"),
        ("gpu_utilization_percent", plain("utilization_gpu_pct"), "percent"),
        ("gpu_board_power_w", plain("power_draw_w"), "watts"),
    )
    result = [
        _obs(clocks, name, value, units, source)
        if value is not None
        else _failed(clocks, name, units, source, "field not reported")
        for name, value, units in readings
    ]
    result.append(_obs(clocks, "gpu_device_present", True, "boolean", source))
    return result


def probe_gpu_shared_memory(clocks: Clocks, runner: CommandRunner) -> Observation:
    source = "Get-Counter '\\GPU Adapter Memory(*)\\Shared Usage' (summed)"
    raw = runner(ALLOW_LISTED_COMMANDS["gpu_shared_memory"])
    try:
        return (
            _obs(clocks, "shared_vram_bytes", int(float(raw.strip())), "bytes", source)
            if raw and raw.strip()
            else _failed(clocks, "shared_vram_bytes", "bytes", source, "counter unavailable")
        )
    except ValueError:
        return _failed(
            clocks, "shared_vram_bytes", "bytes", source, "counter value unparseable", status=ERROR
        )


def probe_hard_faults(clocks: Clocks, runner: CommandRunner) -> Observation:
    source = "\\Memory\\Pages Input/sec (hard-fault page reads; NOT total Page Faults/sec)"
    raw = runner(ALLOW_LISTED_COMMANDS["hard_fault_pages"])
    try:
        return (
            _obs(clocks, "hard_fault_pages_input_per_s", float(raw.strip()), "per_second", source)
            if raw and raw.strip()
            else _failed(
                clocks, "hard_fault_pages_input_per_s", "per_second", source, "counter unavailable"
            )
        )
    except ValueError:
        return _failed(
            clocks,
            "hard_fault_pages_input_per_s",
            "per_second",
            source,
            "unparseable",
            status=ERROR,
        )


def probe_evidence_volume(
    clocks: Clocks, directory: Path | str, disk_free: Callable[[str], int] | None = None
) -> Observation:
    source = "disk usage of the named evidence volume"
    try:
        target = Path(directory)
        probe_root = next((p for p in (target, *target.parents) if p.exists()), None)
        if probe_root is None:
            return _failed(
                clocks, "evidence_volume_free_bytes", "bytes", source, "no existing ancestor"
            )
        free = (disk_free or (lambda root: shutil.disk_usage(root).free))(str(probe_root))
        return _obs(clocks, "evidence_volume_free_bytes", free, "bytes", source)
    except OSError as exc:
        return _failed(
            clocks, "evidence_volume_free_bytes", "bytes", source, type(exc).__name__, status=ERROR
        )


_REFUSED = {10061, 111, 61}  # WSAECONNREFUSED, ECONNREFUSED (Linux, macOS): nothing is listening


def _tcp_state(host: str, port: int) -> bool | None:
    """``True`` connected, ``False`` actively refused, ``None`` anything else (a timeout is not proof of a free port)."""

    with socket.socket() as sock:
        # Windows reports a refused loopback connect only after about 2 s (0.5 s yields WSAEWOULDBLOCK)
        sock.settimeout(4.0)
        code = sock.connect_ex((host, port))
    if code == 0:
        return True
    return False if code in _REFUSED else None


def probe_port(
    host: str = "127.0.0.1",
    port: int = QUALIFICATION_PORT,
    connect: Callable[[str, int], bool | None] | None = None,
) -> PortObservation:
    """One loopback TCP connect (no HTTP): ``occupied`` if it connects, ``free`` only if actively refused."""

    try:
        state = (connect or _tcp_state)(host, port)
    except OSError:
        return PortObservation(host, port, "unverifiable", "loopback connect")
    if state is None:
        return PortObservation(host, port, "unverifiable", "loopback connect")
    return PortObservation(host, port, "occupied" if state else "free", "loopback connect")


def _own_process_chain() -> set[int]:
    """This process and its ancestors: an observer is never a competing runtime (and is never touched)."""

    chain = {os.getpid()}
    try:
        import psutil

        chain.update(parent.pid for parent in psutil.Process().parents())
    except Exception:  # noqa: BLE001
        chain.add(os.getppid())
    return chain


def probe_processes(
    iterate: Callable[[], Any] | None = None,
    listeners: Callable[[], dict[int, tuple[int, ...]]] | None = None,
    exclude_pids: set[int] | None = None,
) -> list[ProcessObservation] | None:
    """Python processes (the family every StableNew runtime belongs to) with any listening ports. ``None`` when unreadable."""

    try:
        iterate = iterate or _default_process_iterator()
        ports = (listeners or _listening_ports)()
        excluded = _own_process_chain() if exclude_pids is None else exclude_pids
        return [
            ProcessObservation(
                pid=int(p.pid),
                name=str(p.name or ""),
                cmdline=tuple(str(part) for part in (p.cmdline or ())),
                listening_ports=ports.get(int(p.pid), ()),
                owner="unknown",
            )
            for p in iterate()
            if int(p.pid) not in excluded
        ]
    except Exception:  # noqa: BLE001
        return None


def _listening_ports() -> dict[int, tuple[int, ...]]:
    import psutil

    found: dict[int, list[int]] = {}
    for conn in psutil.net_connections(kind="inet"):
        if conn.status == psutil.CONN_LISTEN and conn.pid:
            found.setdefault(int(conn.pid), []).append(int(conn.laddr.port))
    return {pid: tuple(sorted(ports)) for pid, ports in found.items()}


# ----------------------------------------------------------------------------------------------------- fault events


def _event_source(
    name: str, runner: CommandRunner, *, command: str, id_prefix: str = ""
) -> FaultSourceSnapshot:
    raw = runner(ALLOW_LISTED_COMMANDS[command])
    parsed = _json(raw)
    if raw is None or parsed is None:
        return FaultSourceSnapshot(
            name, INACCESSIBLE, frozenset(), "query failed or returned nothing parseable"
        )
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return FaultSourceSnapshot(name, INACCESSIBLE, frozenset(), "unexpected result shape")
    ids = frozenset(
        f"{id_prefix}{item.get('RecordId')}"
        for item in parsed
        if isinstance(item, dict) and item.get("RecordId") is not None
    )
    # a full page means older records may be unseen; continuity is proven when snapshots are compared
    coverage = BOUNDED if len(ids) >= _EVENT_LOOKBACK else COMPLETE
    return FaultSourceSnapshot(name, coverage, ids, f"{len(ids)} records")


def _wer_sources(
    listing: Callable[[Path], list[str]] | None = None,
) -> tuple[FaultSourceSnapshot, FaultSourceSnapshot]:
    names: set[str] = set()
    denied = False
    reader = listing or (lambda directory: os.listdir(directory))
    for directory in WER_DIRECTORIES:
        try:
            names.update(reader(directory))
        except OSError:
            denied = True
    coverage = INACCESSIBLE if denied else COMPLETE
    live = frozenset(
        n for n in names if n.lower().startswith("kernel_") or "livekernel" in n.lower()
    )
    note = "directory listing denied or absent" if denied else "directory listing"
    return (
        FaultSourceSnapshot("wer_reports", coverage, frozenset(names), note),
        FaultSourceSnapshot("live_kernel", coverage, live, note),
    )


def collect_fault_snapshot(
    clocks: Clocks, runner: CommandRunner, *, wer_listing: Callable[[Path], list[str]] | None = None
) -> FaultSnapshot:
    """Read-only baseline/after snapshot of System/Application/WHEA/WER/LiveKernel evidence. Nothing is cleared or written."""

    boot_raw = runner(ALLOW_LISTED_COMMANDS["boot_identity"])
    boot = boot_raw.strip() if boot_raw and boot_raw.strip() else None
    wer, live = _wer_sources(wer_listing)
    sources = {
        "whea": _event_source("whea", runner, command="events_whea"),
        "system_log": _event_source("system_log", runner, command="events_display_driver"),
        "application_log": _event_source("application_log", runner, command="events_wer"),
        "wer_reports": wer,
        "live_kernel": live,
    }
    return FaultSnapshot(clocks.utc(), boot, sources)


# ------------------------------------------------------------------------------------------------------ assembly


def collect_live_observations(
    clocks: Clocks | None = None,
    *,
    runner: CommandRunner = run_allow_listed,
    evidence_dir: Path | str | None = None,
    port: int = QUALIFICATION_PORT,
    memory_reader: Callable[[], Any] | None = None,
    gpu_snapshot: Callable[[], dict[str, object] | None] | None = None,
    port_connect: Callable[[str, int], bool | None] | None = None,
    process_memory_reader: Callable[[int], Any] | None = None,
    process_iterator: Callable[[], Any] | None = None,
    listeners: Callable[[], dict[int, tuple[int, ...]]] | None = None,
    wer_listing: Callable[[Path], list[str]] | None = None,
    disk_free: Callable[[str], int] | None = None,
) -> ProbeResult:
    """Everything read-only, in one deterministic pass. Failures become non-``ok`` observations and named gaps."""

    clk = clocks or Clocks()
    result = ProbeResult()
    gathered: list[Observation] = []
    # Slow queries first and the resource readings the thresholds depend on LAST, so the assessed values are the freshest.
    result.fault_snapshot = collect_fault_snapshot(clk, runner, wer_listing=wer_listing)
    result.processes = probe_processes(process_iterator, listeners)
    result.port = probe_port(port=port, connect=port_connect)
    gathered += probe_pagefile(clk, runner, disk_free)
    gathered.append(probe_hard_faults(clk, runner))
    gathered.append(probe_gpu_shared_memory(clk, runner))
    if evidence_dir is not None:
        gathered.append(probe_evidence_volume(clk, evidence_dir, disk_free))
    gathered += probe_gpu(clk, gpu_snapshot)
    gathered += probe_system_memory(clk, memory_reader)
    result.observations = {item.name: item for item in gathered}

    def usable(*names: str) -> bool:
        return all(n in result.observations and result.observations[n].status == OK for n in names)

    # The process-tree readers must actually work (not merely import): exercise them on this very process.
    try:
        reader = process_memory_reader or _default_process_memory_reader()
        tree_capability = reader(os.getpid()) is not None
    except Exception:  # noqa: BLE001
        tree_capability = False
    coverage = {
        "commit_headroom_bytes": usable("commit_headroom_bytes", "commit_limit_bytes"),
        "ram_available_bytes": usable("ram_available_bytes"),
        "vram_used_bytes": usable("vram_used_bytes"),
        "vram_total_bytes": usable("vram_total_bytes"),
        "gpu_temperature_c": usable("gpu_temperature_c"),
        "gpu_device_present": usable("gpu_device_present"),
        "pagefile_status": usable("pagefile_allocated_bytes"),
        "forge_process_tree": tree_capability,
    }
    result.telemetry_coverage = {
        name: ("available" if ok else "unavailable") for name, ok in coverage.items()
    }
    for name in ESSENTIAL_TELEMETRY:
        if result.telemetry_coverage.get(name) != "available":
            result.gaps.append(f"essential telemetry unavailable: {name}")
    for name in ("shared_vram_bytes", "hard_fault_pages_input_per_s"):
        if not usable(name):
            result.gaps.append(f"planned telemetry unavailable: {name}")
    for source_name in FAULT_SOURCES:
        state = result.fault_snapshot.sources.get(source_name)
        if state is None or state.coverage not in ACCEPTED_BASELINE_COVERAGE:
            result.gaps.append(
                f"fault source not complete: {source_name} ({state.coverage if state else NOT_COLLECTED})"
            )
    offset = datetime.now().astimezone().utcoffset()
    result.environment = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timezone_utc_offset_minutes": int(offset.total_seconds() // 60)
        if offset is not None
        else None,
        "boot_identity": result.fault_snapshot.boot_id,
    }
    return result
