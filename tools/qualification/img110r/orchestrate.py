"""Fresh-process orchestration, fault capture and matrix reporting for PR-IMG-110R.

    python -m tools.qualification.img110r.orchestrate run --runtime official-staged --level 1
    python -m tools.qualification.img110r.orchestrate matrix

The orchestrator (standard library only) starts *one* run in a fresh child process inside the
disposable environment, bounds it in wall time and host RAM, terminates only that child, and
records Windows GPU/WHEA/WER events for the run window.  After a CUDA fault, a vanished
process or an unresolved in-flight run it refuses to start another until the machine has
rebooted (or the crash is explicitly acknowledged).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.qualification.img110r.common import (
    LEVELS,
    RunRecord,
    classify_failure,
    query_gpu,
)
from tools.qualification.img110r.verdict import decide

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVIDENCE = REPO_ROOT / "reports" / "img110r"
DEFAULT_ROOT = Path.home() / "img110r"
STATE_FILE = "state.json"
MIN_FREE_RAM_GB = 6.0
LOW_RAM_GB = 0.4
LOW_RAM_SECONDS = 30
BOUNDS = {1: 900, 2: 1500, 3: 2400, 4: 5400}

RUNTIMES: dict[str, dict[str, Any]] = {
    "official-as-shipped": {
        "module": "run_official",
        "env": "venv-ref",
        "args": ["--mode", "as_shipped"],
    },
    "official-staged": {"module": "run_official", "env": "venv-ref", "args": ["--mode", "staged"]},
    "official-staged-swap": {
        "module": "run_official",
        "env": "venv-ref",
        "args": ["--mode", "staged_swap"],
    },
    "diffusers-cuda": {"module": "run_diffusers", "env": "venv-dfz", "args": ["--mode", "cuda"]},
    "diffusers-cpu-offload": {
        "module": "run_diffusers",
        "env": "venv-dfz",
        "args": ["--mode", "cpu_offload"],
    },
    "diffusers-staged": {
        "module": "run_diffusers",
        "env": "venv-dfz",
        "args": ["--mode", "staged"],
    },
    "diffusers-staged-swap": {
        "module": "run_diffusers",
        "env": "venv-dfz",
        "args": ["--mode", "staged_swap"],
    },
    "diffusers-group-leaf": {
        "module": "run_diffusers",
        "env": "venv-dfz",
        "args": ["--mode", "group_leaf"],
    },
}

_EVENT_SCRIPT = r"""
$start = [datetime]::Parse('{start}')
$found = @()
$found += Get-WinEvent -FilterHashtable @{{LogName='System'; StartTime=$start;
    ProviderName='nvlddmkm','Display','Microsoft-Windows-WHEA-Logger'}} -ErrorAction SilentlyContinue
$found += Get-WinEvent -FilterHashtable @{{LogName='System'; StartTime=$start; Id=41}} -ErrorAction SilentlyContinue
$found += Get-WinEvent -FilterHashtable @{{LogName='Application'; StartTime=$start;
    ProviderName='Windows Error Reporting'}} -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Message -match 'LiveKernelEvent|nvlddmkm|python' }}
$found | Sort-Object TimeCreated | ForEach-Object {{
    [pscustomobject]@{{ time=$_.TimeCreated.ToString('s'); provider=$_.ProviderName; id=$_.Id;
        message=(($_.Message -split "`n")[0]) }} }} | ConvertTo-Json -Compress
"""


def fault_events_since(start: datetime) -> list[dict[str, Any]]:
    """GPU/WHEA/reset/WER events logged since ``start`` (empty list when the log is quiet)."""

    script = _EVENT_SCRIPT.format(start=start.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return [{"provider": "orchestrator", "message": f"event query failed: {exc}"}]
    if not out:
        return []
    parsed = json.loads(out)
    return parsed if isinstance(parsed, list) else [parsed]


def _boot_time() -> float:
    import psutil

    return round(psutil.boot_time(), 0)


def _state_path(evidence: Path) -> Path:
    return evidence / STATE_FILE


def _load_state(evidence: Path) -> dict[str, Any]:
    path = _state_path(evidence)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_state(evidence: Path, state: dict[str, Any]) -> None:
    evidence.mkdir(parents=True, exist_ok=True)
    _state_path(evidence).write_text(json.dumps(state, indent=2), encoding="utf-8")


def preflight(evidence: Path, *, acknowledge_crash: bool) -> dict[str, Any]:
    """Refuse to start on a dirty machine/context; return the baseline that is recorded."""

    import psutil

    state = _load_state(evidence)
    if state.get("in_flight") and not acknowledge_crash:
        raise SystemExit(
            f"run {state['in_flight']} never finished (orchestrator or machine died); "
            "review it, then pass --acknowledge-crash to continue"
        )
    if state.get("reboot_required") and state.get("boot_time") == _boot_time():
        raise SystemExit("a CUDA fault/poisoned context was recorded; reboot before more GPU runs")
    try:
        gpu = query_gpu()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SystemExit(f"nvidia-smi is not healthy ({exc}); reboot before more GPU runs") from exc
    free_ram = psutil.virtual_memory().available / 1e9
    if free_ram < MIN_FREE_RAM_GB:
        raise SystemExit(
            f"only {free_ram:.1f} GB RAM available (< {MIN_FREE_RAM_GB}); free memory first"
        )
    return {
        "vram_used_mib": gpu.vram_used_mib,
        "vram_total_mib": gpu.vram_total_mib,
        "temp_c": gpu.temp_c,
        "ram_available_gb": round(free_ram, 1),
    }


def _next_run_id(evidence: Path, runtime: str, level: int, tag: str) -> str:
    base = f"L{level}-{runtime}{'-' + tag if tag else ''}"
    existing = sorted(evidence.glob(f"{base}-r*.json"))
    return f"{base}-r{len(existing) + 1}"


def run_one(args: argparse.Namespace) -> int:
    import psutil

    evidence: Path = args.evidence_dir
    spec = RUNTIMES[args.runtime]
    baseline = preflight(evidence, acknowledge_crash=args.acknowledge_crash)
    python = args.root / spec["env"] / "Scripts" / "python.exe"
    run_id = _next_run_id(evidence, args.runtime, args.level, args.tag)
    command = [
        str(python),
        "-m",
        f"tools.qualification.img110r.{spec['module']}",
        *spec["args"],
        "--level",
        str(args.level),
        "--out-dir",
        str(evidence),
        "--run-id",
        run_id,
    ]
    if args.vram_cap_mib:
        command += ["--vram-cap-mib", str(args.vram_cap_mib)]
    if spec["module"] == "run_diffusers":
        command += ["--max-seq", args.max_seq]
    bound = args.bound_seconds or BOUNDS[args.level]
    state = _load_state(evidence)
    state.update(in_flight=run_id, boot_time=_boot_time(), reboot_required=False)
    _save_state(evidence, state)

    window_start = datetime.now()
    log_path = evidence / f"{run_id}.log"
    began = time.monotonic()
    timed_out = ram_killed = False
    print(f"[{run_id}] start bound={bound}s baseline={baseline}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, disposable qualification env
            command, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
        )
        low_since: float | None = None
        while process.poll() is None:
            time.sleep(2)
            if time.monotonic() - began > bound:
                timed_out = True
                break
            available = psutil.virtual_memory().available / 1e9
            if available < LOW_RAM_GB:
                low_since = low_since or time.monotonic()
                if time.monotonic() - low_since > LOW_RAM_SECONDS:
                    ram_killed = True
                    break
            else:
                low_since = None
        if process.poll() is None:  # only our own child is ever terminated
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=30)
    wall = round(time.monotonic() - began, 1)
    result_path = evidence / f"{run_id}.json"
    if result_path.exists():
        record = RunRecord.read(result_path)
    else:
        spec_level = LEVELS[args.level]
        record = RunRecord(
            run_id=run_id,
            runtime=args.runtime,
            family="official" if args.runtime.startswith("official") else "diffusers",
            level=args.level,
            width=spec_level.width,
            height=spec_level.height,
            preset=spec_level.preset,
            steps=0,
            stage="created",
        )
    record.timed_out = timed_out
    if ram_killed:
        record.notes.append("terminated by the orchestrator: host RAM exhausted")
    record.notes.append(f"wall {wall}s, exit {process.returncode}, baseline {baseline}")
    if not record.success and not record.exception_type:
        record.exception_type = "Timeout" if timed_out else "ProcessExit"
        record.exception = (
            f"bound {bound}s reached at stage {record.stage}"
            if timed_out
            else f"process exited {process.returncode} at stage {record.stage} without a record"
        )
    time.sleep(3)
    record.fault_events = fault_events_since(window_start)
    try:
        after = query_gpu()
        record.notes.append(f"post-run VRAM used {after.vram_used_mib} MiB, temp {after.temp_c} C")
        healthy = True
    except (OSError, subprocess.SubprocessError, ValueError):
        record.notes.append("post-run nvidia-smi FAILED (GPU lost?)")
        healthy = False
    record.classification = classify_failure(record)
    if record.fault_events and record.classification == "success":
        record.notes.append("success, but fault-class events were logged in the run window")
    record.write(result_path)
    stop = record.context_poisoned or not healthy or bool(record.fault_events)
    state.update(in_flight=None, reboot_required=stop, boot_time=_boot_time())
    _save_state(evidence, state)
    print(
        f"[{run_id}] {record.classification} stage={record.stage} wall={wall}s "
        f"faults={len(record.fault_events)} stop={stop}",
        flush=True,
    )
    if stop:
        print("STOP: reboot before further CUDA inference.", file=sys.stderr)
    return 0 if record.success else 1


def load_records(evidence: Path) -> list[RunRecord]:
    records = []
    for path in sorted(evidence.glob("L*-r*.json")):
        try:
            records.append(RunRecord.read(path))
        except (TypeError, json.JSONDecodeError):
            continue
    return records


def matrix(evidence: Path) -> int:
    records = load_records(evidence)
    header = (
        "run", "runtime", "res", "preset", "class", "load_s", "1st_step_s", "gen_s",
        "vramPeak", "torchRes", "privMiB", "ramMin", "temp", "faults",
    )  # fmt: skip
    print(" | ".join(header))
    for r in records:
        t, p = r.timing, r.peaks
        print(
            " | ".join(
                str(x)
                for x in (
                    r.run_id, r.runtime, f"{r.width}x{r.height}", r.preset, r.classification or "?",
                    t.get("load_s", "-"), t.get("first_step_seconds", "-"), t.get("generate_total_s", "-"),
                    p.get("vram_used_mib", "-"), p.get("torch_max_reserved_mib", "-"),
                    p.get("proc_private_mib", "-"), p.get("ram_available_min_gb", "-"),
                    p.get("temp_c", "-"), len(r.fault_events),
                )
            )
        )  # fmt: skip
    print(json.dumps(decide(records).as_dict(), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--runtime", choices=sorted(RUNTIMES), required=True)
    run.add_argument("--level", type=int, choices=sorted(LEVELS), required=True)
    run.add_argument("--max-seq", choices=("default", "fit"), default="fit")
    run.add_argument("--vram-cap-mib", type=int)
    run.add_argument("--bound-seconds", type=int)
    run.add_argument("--tag", default="")
    run.add_argument("--acknowledge-crash", action="store_true")
    run.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="folder holding venv-ref/venv-dfz"
    )
    run.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    report = sub.add_parser("matrix")
    report.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    if args.command == "run":
        return run_one(args)
    return matrix(args.evidence_dir)


if __name__ == "__main__":
    raise SystemExit(main())
