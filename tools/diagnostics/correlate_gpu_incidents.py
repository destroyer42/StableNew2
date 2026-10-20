"""Read-only correlation of Windows incidents with StableNew survivor evidence.

This operational tool intentionally has no access to queue mutation, runtime
ownership, or GPU control.  It turns supplied timestamps and durable local
records into a machine-readable timeline without inferring absent evidence.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from xml.etree import ElementTree


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 instant; a value without an offset is UTC.

    Every source this tool reads is UTC by contract: the job repository writes naive
    ``datetime.utcnow()`` values, telemetry and Windows events carry ``timestamp_utc`` /
    ``SystemTime``, and ``--incident`` is documented as UTC. Reading a naive value as local
    time shifted repository jobs by the machine's UTC offset and hid the active job.
    """

    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _parse_timestamp(str(value))
    except ValueError:
        return None


def read_sqlite_jobs(path: Path) -> list[dict[str, Any]]:
    """Read only lifecycle columns needed for correlation, never NJR payloads."""

    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT job_id, status, started_at, completed_at, updated_at, source
            FROM jobs
            """
        ).fetchall()
    return [
        {
            "job_id": str(job_id),
            "status": str(status),
            "started_at": started_at,
            "completed_at": completed_at,
            "updated_at": updated_at,
            "source": source,
        }
        for job_id, status, started_at, completed_at, updated_at, source in rows
    ]


def read_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return records


def _active_jobs(incident: datetime, jobs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for job in jobs:
        started_at = _safe_time(job.get("started_at"))
        completed_at = _safe_time(job.get("completed_at"))
        if started_at is None or started_at > incident:
            continue
        if completed_at is not None and completed_at < incident:
            continue
        active.append(
            {
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "source": job.get("source"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
            }
        )
    return active


_TERMINAL_FAILURE_STATUSES = frozenset(
    {
        "failed",
        "error",
        "errored",
        "cancelled",
        "canceled",
        "aborted",
        "timed_out",
        "timeout",
    }
)


def _nearby_jobs(
    incident: datetime,
    jobs: Iterable[Mapping[str, Any]],
    *,
    window: timedelta,
) -> list[dict[str, Any]]:
    """Return lifecycle records near an incident without inferring causation.

    A job is nearby when one of its durable lifecycle timestamps falls inside
    the configured window, or when its known interval overlaps the incident.
    The relation is deliberately descriptive: a completed or failed job near
    an incident was not active at that incident unless its interval proves it.
    """

    selected: list[dict[str, Any]] = []
    lower = incident - window
    upper = incident + window
    for job in jobs:
        parsed = {
            name: _safe_time(job.get(name))
            for name in ("started_at", "completed_at", "updated_at")
        }
        started_at = parsed["started_at"]
        completed_at = parsed["completed_at"]
        updated_at = parsed["updated_at"]
        active_at_incident = bool(
            started_at is not None
            and started_at <= incident
            and (completed_at is None or completed_at >= incident)
        )
        lifecycle_times = [(name, value) for name, value in parsed.items() if value is not None]
        in_window = any(lower <= value <= upper for _, value in lifecycle_times)
        interval_overlaps = bool(
            started_at is not None
            and started_at <= upper
            and (completed_at is None or completed_at >= lower)
        )
        if not in_window and not interval_overlaps:
            continue

        status = str(job.get("status") or "").strip().lower()
        if active_at_incident:
            relation = "active_at_incident"
            relevant_name, relevant_time = "started_at", started_at
        elif started_at is not None and started_at > incident and started_at <= upper:
            relation = "started_after_incident"
            relevant_name, relevant_time = "started_at", started_at
        elif (
            status in _TERMINAL_FAILURE_STATUSES
            and (completed_at is not None and completed_at <= incident)
        ):
            relation = "failed_before_incident"
            relevant_name, relevant_time = "completed_at", completed_at
        elif completed_at is not None and completed_at <= incident:
            relation = "completed_before_incident"
            relevant_name, relevant_time = "completed_at", completed_at
        elif updated_at is not None and updated_at <= incident:
            relation = (
                "failed_before_incident"
                if status in _TERMINAL_FAILURE_STATUSES
                else "completed_before_incident"
            )
            relevant_name, relevant_time = "updated_at", updated_at
        else:
            relation = "nearby_lifecycle"
            relevant_name, relevant_time = min(
                lifecycle_times, key=lambda item: abs(item[1] - incident)
            )

        selected.append(
            {
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "source": job.get("source"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "updated_at": job.get("updated_at"),
                "relation": relation,
                "relevant_lifecycle_field": relevant_name,
                "relevant_lifecycle_timestamp": (
                    relevant_time.isoformat() if relevant_time is not None else None
                ),
                "delta_seconds": (
                    round((relevant_time - incident).total_seconds(), 3)
                    if relevant_time is not None
                    else None
                ),
            }
        )
    selected.sort(key=lambda item: abs(float(item["delta_seconds"] or 0)))
    return selected


def _telemetry_scope(record: Mapping[str, Any]) -> str:
    """Return ``session`` for app-lifetime observations and ``job`` for records of a pipeline job.

    Newer records carry an explicit ``scope``. Older ones do not, so a ``session-`` job id also marks a session
    record; anything else is job telemetry (the only kind that existed before the session recorder).
    """

    scope = record.get("scope")
    if scope is not None:
        return "session" if str(scope) == "session" else "job"
    return "session" if str(record.get("job_id") or "").startswith("session-") else "job"


def _telemetry_near(
    incident: datetime,
    records: Iterable[Mapping[str, Any]],
    *,
    window: timedelta,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        timestamp = _safe_time(record.get("timestamp_utc"))
        if timestamp is None or abs(timestamp - incident) > window:
            continue
        selected.append(
            {
                "timestamp_utc": record.get("timestamp_utc"),
                "kind": record.get("kind"),
                "scope": _telemetry_scope(record),
                "event": record.get("event"),
                "job_id": record.get("job_id"),
                "run_id": record.get("run_id"),
                "backend_id": record.get("backend_id"),
                "stage": record.get("stage"),
            }
        )
    return selected


# --- Windows Kernel-PnP "query remove vetoed" marker (read-only) -------------------------------------------------

PNP_PROVIDER = "Microsoft-Windows-Kernel-PnP"
PNP_CHANNEL = "Microsoft-Windows-Kernel-PnP/Device Management"
PNP_QUERY_REMOVE_VETOED_EVENT_ID = 1000
DEFAULT_PNP_WINDOW = timedelta(seconds=120)
DEFAULT_GPU_VENDOR_ID = "VEN_10DE"
_EVENT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
# PNP_VETO_TYPE from the Windows SDK (cfgmgr32.h). The number is always reported; the label is a reading aid.
PNP_VETO_TYPE_LABELS = {
    0: "Unknown",
    1: "LegacyDevice",
    2: "PendingClose",
    3: "WindowsApp",
    4: "WindowsService",
    5: "OutstandingOpen",
    6: "Device",
    7: "Driver",
    8: "IllegalDeviceRequest",
    9: "InsufficientPower",
    10: "NonDisableable",
    11: "LegacyDriver",
    12: "InsufficientRights",
}
PNP_INTERPRETATION = (
    "Kernel-PnP event 1000 is a timing marker only: Windows asked to remove the device and the request was vetoed. "
    "It does not establish hardware failure, that the GPU disappeared, or which component is responsible."
)
_POWERSHELL_TIMEOUT_S = 30.0


class PnpRead(NamedTuple):
    """Parsed Kernel-PnP events, or why none could be read. ``events`` is None when the source was unavailable."""

    events: list[dict[str, Any]] | None
    status: str
    detail: str = ""


def parse_pnp_events_xml(xml_documents: Iterable[str]) -> list[dict[str, Any]]:
    """Parse exported event XML, keeping only Kernel-PnP / Device Management event 1000.

    Provider, channel and event id must all match exactly; anything else, and anything malformed, is dropped.
    """

    events: list[dict[str, Any]] = []
    for document in xml_documents:
        try:
            root = ElementTree.fromstring(document)
        except ElementTree.ParseError:
            continue
        system = root.find(f"{_EVENT_NS}System")
        if system is None:
            continue
        provider = system.find(f"{_EVENT_NS}Provider")
        channel = system.findtext(f"{_EVENT_NS}Channel")
        event_id = system.findtext(f"{_EVENT_NS}EventID")
        created = system.find(f"{_EVENT_NS}TimeCreated")
        if (
            provider is None
            or provider.get("Name") != PNP_PROVIDER
            or channel != PNP_CHANNEL
            or str(event_id).strip() != str(PNP_QUERY_REMOVE_VETOED_EVENT_ID)
            or created is None
        ):
            continue
        timestamp = _safe_time(created.get("SystemTime"))
        if timestamp is None:
            continue
        data = {
            item.get("Name"): (item.text or "")
            for item in root.findall(f"{_EVENT_NS}EventData/{_EVENT_NS}Data")
            if item.get("Name")
        }
        device_id = data.get("DeviceInstanceId", "").strip()
        if not device_id:
            continue
        try:
            veto_type: int | None = int(data.get("VetoType", "").strip())
        except ValueError:
            veto_type = None
        record_id = system.findtext(f"{_EVENT_NS}EventRecordID")
        events.append(
            {
                "timestamp_utc": timestamp.isoformat(),
                "event_record_id": int(record_id) if record_id and record_id.isdigit() else None,
                "provider": PNP_PROVIDER,
                "channel": PNP_CHANNEL,
                "event_id": PNP_QUERY_REMOVE_VETOED_EVENT_ID,
                "device_instance_id": device_id,
                "veto_type": veto_type,
                "veto_type_label": PNP_VETO_TYPE_LABELS.get(veto_type) if veto_type is not None else None,
                "vetoed_by": data.get("VetoName", "").strip() or None,
            }
        )
    return events


def _powershell_utc_to_local(expression: str) -> str:
    return f"[DateTimeOffset]::Parse('{expression}').LocalDateTime"


def _pnp_event_script(since: datetime, until: datetime) -> str:
    """Read-only PowerShell: list Kernel-PnP event 1000 as XML, one document per line."""

    return (
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        f"  $s = {_powershell_utc_to_local(since.astimezone(UTC).isoformat())}\n"
        f"  $e = {_powershell_utc_to_local(until.astimezone(UTC).isoformat())}\n"
        f"  Get-WinEvent -FilterHashtable @{{LogName='{PNP_CHANNEL}';Id={PNP_QUERY_REMOVE_VETOED_EVENT_ID};"
        "StartTime=$s;EndTime=$e} | ForEach-Object { $_.ToXml() -replace \"[\\r\\n]+\", ' ' }\n"
        "} catch {\n"
        "  if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { exit 0 }\n"
        "  [Console]::Error.WriteLine($_.Exception.Message); exit 3\n"
        "}\n"
    )


def _gpu_device_script() -> str:
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "try { Get-PnpDevice -Class Display | ForEach-Object { $_.InstanceId } }\n"
        "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 3 }\n"
    )


def _run_powershell(script: str) -> tuple[int, str, str]:
    executable = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        raise FileNotFoundError("PowerShell is not available")
    completed = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=_POWERSHELL_TIMEOUT_S,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


PowerShellRunner = Callable[[str], tuple[int, str, str]]


def _run_read_only(script: str, runner: PowerShellRunner) -> tuple[str, str, str]:
    """Return ``(status, stdout, detail)``; ``status`` is ``ok`` or an unavailability reason."""

    try:
        returncode, stdout, stderr = runner(script)
    except FileNotFoundError:
        return "powershell_unavailable", "", "PowerShell was not found"
    except subprocess.TimeoutExpired:
        return "timeout", "", f"PowerShell exceeded {_POWERSHELL_TIMEOUT_S:.0f}s"
    except OSError as exc:
        return "error", "", type(exc).__name__
    if returncode != 0:
        return "log_inaccessible", "", " ".join(stderr.split())[:200]
    return "ok", stdout, ""


def read_windows_pnp_events(
    *,
    since: datetime,
    until: datetime,
    runner: PowerShellRunner = _run_powershell,
    platform: str = sys.platform,
) -> PnpRead:
    """Read Kernel-PnP event 1000 between two instants without modifying the event log."""

    if not platform.startswith("win"):
        return PnpRead(None, "unavailable_not_windows")
    status, stdout, detail = _run_read_only(_pnp_event_script(since, until), runner)
    if status != "ok":
        return PnpRead(None, status, detail)
    documents = [line for line in stdout.splitlines() if line.lstrip().startswith("<Event")]
    return PnpRead(parse_pnp_events_xml(documents), "ok")


def read_gpu_device_ids(
    *,
    vendor_id: str = DEFAULT_GPU_VENDOR_ID,
    runner: PowerShellRunner = _run_powershell,
    platform: str = sys.platform,
) -> tuple[list[str] | None, str]:
    """List display-class device instance ids from this vendor; ``None`` when they cannot be read."""

    if not platform.startswith("win"):
        return None, "unavailable_not_windows"
    status, stdout, _detail = _run_read_only(_gpu_device_script(), runner)
    if status != "ok":
        return None, status
    wanted = vendor_id.upper()
    return [line.strip() for line in stdout.splitlines() if wanted in line.upper()], "ok"


def match_pnp_markers(
    incident: datetime,
    events: Iterable[Mapping[str, Any]],
    *,
    device_ids: Iterable[str],
    window: timedelta = DEFAULT_PNP_WINDOW,
) -> list[dict[str, Any]]:
    """Return events for the given device instances within ``window`` of ``incident``, nearest first.

    ``delta_seconds`` is signed: event time minus incident time, so a negative value happened before the incident.
    """

    wanted = {device_id.strip().casefold() for device_id in device_ids if device_id.strip()}
    markers: list[dict[str, Any]] = []
    for event in events:
        device_id = str(event.get("device_instance_id") or "")
        timestamp = _safe_time(event.get("timestamp_utc"))
        if timestamp is None or device_id.casefold() not in wanted:
            continue
        delta = (timestamp - incident).total_seconds()
        if abs(delta) > window.total_seconds():
            continue
        relation = "before_incident" if delta < 0 else "after_incident" if delta > 0 else "at_incident"
        markers.append({**event, "delta_seconds": round(delta, 3), "relation": relation})
    markers.sort(key=lambda item: abs(item["delta_seconds"]))
    return markers


def _windows_pnp_section(
    incident: datetime,
    *,
    pnp: PnpRead | None,
    gpu_device_ids: Iterable[str] | None,
    window: timedelta,
) -> dict[str, Any]:
    """Describe the PnP marker without feeding it into the StableNew-activity classification."""

    if pnp is None:
        return {"status": "not_requested", "markers": []}
    if pnp.events is None:
        return {"status": f"unavailable_{pnp.status}", "detail": pnp.detail, "markers": []}
    ids = [device_id for device_id in (gpu_device_ids or []) if device_id.strip()]
    if not ids:
        return {"status": "gpu_device_unknown", "markers": []}
    markers = match_pnp_markers(incident, pnp.events, device_ids=ids, window=window)
    section: dict[str, Any] = {
        "status": "marker_near_incident" if markers else "no_marker_near_incident",
        "window_seconds": window.total_seconds(),
        "gpu_device_ids": ids,
        "markers": markers,
    }
    if markers:
        section["interpretation"] = PNP_INTERPRETATION
    return section


def correlate(
    incidents: Iterable[Mapping[str, Any]],
    *,
    jobs: Iterable[Mapping[str, Any]] | None,
    telemetry: Iterable[Mapping[str, Any]] | None,
    webui_log_files: Iterable[Path] | None,
    window: timedelta = timedelta(minutes=10),
    pnp: PnpRead | None = None,
    gpu_device_ids: Iterable[str] | None = None,
    pnp_window: timedelta = DEFAULT_PNP_WINDOW,
) -> list[dict[str, Any]]:
    """Classify only what supplied evidence proves; unavailable remains unknown."""

    jobs_list = list(jobs or [])
    telemetry_list = list(telemetry or [])
    webui_files = list(webui_log_files or [])
    sqlite_available = jobs is not None
    telemetry_available = telemetry is not None
    webui_available = webui_log_files is not None
    timeline: list[dict[str, Any]] = []
    for raw_incident in incidents:
        timestamp = _parse_timestamp(str(raw_incident["timestamp_utc"]))
        active_jobs = _active_jobs(timestamp, jobs_list)
        nearby_jobs = _nearby_jobs(timestamp, jobs_list, window=window)
        nearby_telemetry = _telemetry_near(timestamp, telemetry_list, window=window)
        telemetry_times = [
            sample_time
            for record in telemetry_list
            if (sample_time := _safe_time(record.get("timestamp_utc"))) is not None
        ]
        telemetry_covers_incident = bool(
            telemetry_times
            and min(telemetry_times) - window <= timestamp <= max(telemetry_times) + window
        )
        nearby_webui = [
            {"path": str(path), "last_write_utc": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()}
            for path in webui_files
            if abs(datetime.fromtimestamp(path.stat().st_mtime, UTC) - timestamp) <= window
        ]
        # Only job-scoped telemetry can show generation was active. A session sample proves the app was open and the
        # GPU observed, which is weaker, so it can never raise the classification to proven active work.
        nearby_job_telemetry = [item for item in nearby_telemetry if item["scope"] != "session"]
        nearby_session_telemetry = [item for item in nearby_telemetry if item["scope"] == "session"]
        if active_jobs or nearby_job_telemetry:
            classification = "proven_active_stablenew_gpu_work"
        elif nearby_jobs:
            classification = "nearby_stablenew_lifecycle_no_proven_active_generation"
        elif nearby_webui or nearby_session_telemetry:
            classification = "stablenew_open_no_proven_active_generation"
        elif sqlite_available and telemetry_covers_incident and webui_available:
            classification = "no_stablenew_evidence"
        else:
            classification = "evidence_unavailable"
        timeline.append(
            {
                "timestamp_utc": timestamp.isoformat(),
                "incident": dict(raw_incident),
                "classification": classification,
                "active_sqlite_jobs": active_jobs,
                "nearby_sqlite_jobs": nearby_jobs,
                "nearby_survivor_telemetry": nearby_telemetry,
                "nearby_webui_log_files": nearby_webui,
                "windows_pnp": _windows_pnp_section(
                    timestamp, pnp=pnp, gpu_device_ids=gpu_device_ids, window=pnp_window
                ),
                "source_availability": {
                    "sqlite": sqlite_available,
                    "survivor_telemetry": telemetry_available,
                    "survivor_telemetry_covers_incident": telemetry_covers_incident,
                    "webui_log_inventory": webui_available,
                },
            }
        )
    return timeline


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", action="append", required=True, help="UTC ISO-8601 timestamp")
    parser.add_argument("--sqlite", type=Path)
    parser.add_argument("--telemetry-dir", type=Path)
    parser.add_argument("--webui-log-dir", type=Path)
    parser.add_argument(
        "--windows-pnp",
        action="store_true",
        help="read Kernel-PnP event 1000 (query-remove vetoed) from the Windows event log, read-only",
    )
    parser.add_argument(
        "--pnp-events-xml",
        type=Path,
        help="offline alternative to --windows-pnp: a file of exported event XML, one event per line",
    )
    parser.add_argument(
        "--gpu-instance-id",
        action="append",
        default=[],
        help="GPU device instance id to match (repeatable); default: display devices with the vendor id",
    )
    parser.add_argument("--gpu-vendor-id", default=DEFAULT_GPU_VENDOR_ID)
    parser.add_argument("--pnp-window-seconds", type=float, default=DEFAULT_PNP_WINDOW.total_seconds())
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    jobs = read_sqlite_jobs(args.sqlite) if args.sqlite and args.sqlite.exists() else None
    telemetry_paths = (
        sorted(args.telemetry_dir.rglob("*.jsonl*"))
        if args.telemetry_dir and args.telemetry_dir.exists()
        else None
    )
    telemetry = read_jsonl(telemetry_paths or []) if telemetry_paths is not None else None
    webui_files = (
        list(args.webui_log_dir.glob("*.log"))
        if args.webui_log_dir and args.webui_log_dir.exists()
        else None
    )
    incidents = [{"timestamp_utc": timestamp, "source": "operator_supplied"} for timestamp in args.incident]
    pnp_window = timedelta(seconds=max(0.0, args.pnp_window_seconds))
    pnp: PnpRead | None = None
    gpu_device_ids: list[str] = list(args.gpu_instance_id)
    if args.pnp_events_xml is not None:
        if args.pnp_events_xml.exists():
            lines = args.pnp_events_xml.read_text(encoding="utf-8", errors="replace").splitlines()
            pnp = PnpRead(parse_pnp_events_xml(line for line in lines if line.lstrip().startswith("<Event")), "ok")
        else:
            pnp = PnpRead(None, "events_file_missing", str(args.pnp_events_xml))
    elif args.windows_pnp:
        instants = [_parse_timestamp(str(item["timestamp_utc"])) for item in incidents]
        pnp = read_windows_pnp_events(since=min(instants) - pnp_window, until=max(instants) + pnp_window)
    if pnp is not None and not gpu_device_ids:
        detected, _status = read_gpu_device_ids(vendor_id=args.gpu_vendor_id)
        gpu_device_ids = detected or []
    output = {
        "schema": "stablenew.gpu-incident-timeline.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "timeline": correlate(
            incidents,
            jobs=jobs,
            telemetry=telemetry,
            webui_log_files=webui_files,
            pnp=pnp,
            gpu_device_ids=gpu_device_ids,
            pnp_window=pnp_window,
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
