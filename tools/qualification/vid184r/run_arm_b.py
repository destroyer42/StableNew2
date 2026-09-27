"""PR-VID-184R Arm B harness (qualification-only).

Runs the frozen PR-VID-184 workload against the preserved isolated qualification Comfy, with the
single intended change ``--disable-pinned-memory``. ``--dry`` performs every gate and the server
launch/verification but submits nothing. Without ``--dry`` it performs exactly ONE submission.

The harness owns only the Comfy process it launches; it never touches the StableNew-managed Comfy,
A1111, or any other process. Unlike PR-VID-184's monitor, samples are persisted incrementally and
the monitor survives an ``nvidia-smi`` failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.qualification.vid160c.telemetry import (  # noqa: E402
    COMMIT_HEADROOM_ABORT_GB,
    COMMIT_PERCENT_ABORT,
    EMERGENCY_RAM_GB,
)
from tools.qualification.vid160c.win_memory import (  # noqa: E402
    read_process_memory,
    read_system_commit,
)
from tools.qualification.vid184r import arm_manifest as am  # noqa: E402

ENV = Path(r"C:\Users\rob\qual\vid184\env")
EVID = ENV / "evidence_184r"
GRAPH = ENV / "evidence" / "run5_flat_graph.json"
BASE = f"http://127.0.0.1:{am.PORT}"
CONSECUTIVE = 2
SAMPLE_SECONDS = 2.0
RUN_TIMEOUT_SECONDS = 1200.0
EVENT_QUERY = (
    "Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddMinutes(-%d)} "
    "-ErrorAction SilentlyContinue | Where-Object { $_.Id -in @(1,41,153,157,4101,6008) -or "
    "$_.ProviderName -like '*nvlddmkm*' -or $_.ProviderName -like '*WHEA*' } | "
    "Select-Object TimeCreated,Id,ProviderName | ConvertTo-Json -Compress"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def sh(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def event_log(minutes: int) -> Any:
    out = sh(["powershell", "-NoProfile", "-Command", EVENT_QUERY % minutes]).stdout.strip()
    return json.loads(out) if out else []


def gpu_query() -> dict[str, Any] | None:
    r = sh(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ],
        timeout=20,
    )
    if r.returncode != 0:
        return None
    f = [x.strip() for x in r.stdout.strip().split(",")]
    return {
        "name": f[0], "driver": f[1], "vram_total_mib": float(f[2]), "vram_used_mib": float(f[3]),
        "vram_free_mib": float(f[4]), "temp_c": float(f[5]), "power_w": float(f[6]),
    }  # fmt: skip


def heavy_gpu_processes() -> str:
    return sh(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"]
    ).stdout.strip()


def commit_snapshot() -> dict[str, float]:
    c = read_system_commit()
    return {
        "commit_percent": round(c.commit_percent, 2), "commit_total_gb": round(c.commit_total_gb, 2),
        "commit_limit_gb": round(c.commit_limit_gb, 2), "commit_headroom_gb": round(c.commit_headroom_gb, 2),
        "physical_available_gb": round(c.physical_available_gb, 2), "physical_total_gb": round(c.physical_total_gb, 2),
    }  # fmt: skip


def port_listener_pid() -> int | None:
    out = sh(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-NetTCPConnection -LocalPort {am.PORT} -State Listen -ErrorAction SilentlyContinue | Select -First 1).OwningProcess"]
    ).stdout.strip()  # fmt: skip
    return int(out) if out.isdigit() else None


def parent_pid(pid: int) -> int | None:
    out = sh(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').ParentProcessId",
        ]
    ).stdout.strip()
    return int(out) if out.isdigit() else None


def gate() -> dict[str, Any]:
    g: dict[str, Any] = {"time": time.time(), "failures": []}
    g["gpu"] = gpu_query()
    if g["gpu"] is None or "4070 Ti" not in g["gpu"]["name"]:
        g["failures"].append("GPU not reported normally by nvidia-smi")
    g["other_gpu_compute_processes"] = heavy_gpu_processes()
    g["windows_commit"] = commit_snapshot()
    g["port_free"] = port_listener_pid() is None
    if not g["port_free"]:
        g["failures"].append(f"port {am.PORT} already in use")
    boot = sh(["powershell", "-NoProfile", "-Command",
               "((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes"]).stdout.strip()  # fmt: skip
    g["minutes_since_boot"] = float(boot) if boot else None
    g["event_log_baseline_last_60min"] = event_log(60)
    g["pagefile_read_only"] = sh(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_PageFileUsage | Select Name,AllocatedBaseSize,CurrentUsage | ConvertTo-Json -Compress"]).stdout.strip()  # fmt: skip
    a, b = am.arm_manifest("A"), am.arm_manifest("B")
    g["manifest_diff_keys"] = sorted(am.diff_manifests(a, b))
    g["launch_arg_difference"] = am.launch_arg_difference(a, b)
    if g["launch_arg_difference"] != [am.PINNED_FLAG]:
        g["failures"].append("Arm A/B launch difference is not exactly the pinned-memory flag")
    fw = am.FROZEN_WORKLOAD
    hashes = {"graph": sha256(GRAPH), "reference": sha256(ENV / "inputs" / "source_fullbody.png"),
              "driving_39f": sha256(ENV / "inputs" / "B_locomotion_driving_39f_candidate.mp4")}  # fmt: skip
    for name in fw["model_sha256"]:
        hashes[name] = sha256(ENV / "models" / name)
    g["hashes"] = hashes
    expected = {"graph": fw["graph_sha256"], "reference": fw["reference_sha256"], "driving_39f": fw["driving_39f_sha256"], **fw["model_sha256"]}  # fmt: skip
    for k, v in expected.items():
        if hashes[k] != v:
            g["failures"].append(f"hash mismatch: {k}")
    g["outputs_dir_entries"] = len(list((ENV / "outputs").iterdir()))
    if g["outputs_dir_entries"]:
        g["failures"].append("outputs directory not empty")
    v = subprocess.run(
        [am.PY_EXE, "vid184_validate.py"], cwd=am.COMFY_ROOT, capture_output=True, text=True, timeout=300
    )  # fmt: skip
    g["graph_validation"] = [
        ln
        for ln in v.stdout.splitlines()
        if ln.startswith(("VALID", "GOOD_OUTPUTS", "NODE_ERRORS"))
    ]
    if "VALID: True" not in v.stdout:
        g["failures"].append("graph validation failed")
    return g


def launch(log_path: Path) -> subprocess.Popen[bytes]:
    log = log_path.open("wb")
    return subprocess.Popen(
        [am.PY_EXE, *am.launch_args("B")], cwd=am.COMFY_ROOT, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )  # fmt: skip


def wait_ready(proc: subprocess.Popen[bytes], log_path: Path, timeout: float = 240) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        if "To see the GUI go to" in log_path.read_text(encoding="utf-8", errors="replace"):
            return True
        time.sleep(2)
    return False


def teardown(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Terminate ONLY the process this harness launched."""
    info: dict[str, Any] = {"pid": proc.pid, "was_alive": proc.poll() is None}
    # /T kills only the tree rooted at the PID this harness launched (shim + its interpreter child)
    if proc.poll() is None or port_listener_pid() is not None:
        sh(["taskkill", "/T", "/F", "/PID", str(proc.pid)])
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            pass
    info["exit_code"] = proc.returncode
    info["port_still_listening"] = port_listener_pid() is not None
    return info


def http_json(path: str, data: bytes | None = None) -> Any:
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def latest_step(log_path: Path) -> str | None:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    steps = re.findall(r"(\d+)/10 \[[0-9:]+<[0-9:?]+, *([0-9.]+)s/it", text)
    return f"{steps[-1][0]}/10 @ {steps[-1][1]}s/it" if steps else None


def run_and_monitor(proc: subprocess.Popen[bytes], log_path: Path) -> dict[str, Any]:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    payload = json.dumps({"prompt": graph, "client_id": "vid184r-armb"}).encode()
    submit_time = time.time()
    resp = http_json("/prompt", payload)  # THE one GPU submission
    prompt_id = resp["prompt_id"]
    (EVID / "submit_result.json").write_text(
        json.dumps({**resp, "submit_time": submit_time}, indent=2)
    )
    result: dict[str, Any] = {
        "prompt_id": prompt_id,
        "submit_time": submit_time,
        "node_errors": resp.get("node_errors"),
    }
    peaks = {"vram_peak_mib": 0.0, "commit_peak_percent": 0.0, "commit_min_headroom_gb": 1e9,
             "physical_min_available_gb": 1e9, "temp_peak_c": 0.0, "power_peak_w": 0.0, "proc_private_peak_gb": 0.0}  # fmt: skip
    consec = {"pct": 0, "head": 0, "ram": 0}
    gpu_ok = True
    stop_reason = None
    outcome = "TIMEOUT"
    samples = (EVID / "telemetry.jsonl").open("a", encoding="utf-8")
    t0 = time.time()
    while time.time() - t0 < RUN_TIMEOUT_SECONDS:
        s: dict[str, Any] = {
            "t": round(time.time() - t0, 1),
            **commit_snapshot(),
            "step": latest_step(log_path),
        }
        pm = read_process_memory(proc.pid)
        if pm:
            s["proc_private_gb"] = round(pm.private_usage_gb, 2)
            peaks["proc_private_peak_gb"] = max(peaks["proc_private_peak_gb"], pm.private_usage_gb)
        if gpu_ok:
            g = gpu_query()
            if g is None:
                gpu_ok = False
                s["gpu"] = "nvidia-smi FAILED (possible device loss)"
            else:
                s.update(vram_used_mib=g["vram_used_mib"], temp_c=g["temp_c"], power_w=g["power_w"])
                peaks["vram_peak_mib"] = max(peaks["vram_peak_mib"], g["vram_used_mib"])
                peaks["temp_peak_c"] = max(peaks["temp_peak_c"], g["temp_c"])
                peaks["power_peak_w"] = max(peaks["power_peak_w"], g["power_w"])
        samples.write(json.dumps(s) + "\n")
        samples.flush()
        peaks["commit_peak_percent"] = max(peaks["commit_peak_percent"], s["commit_percent"])
        peaks["commit_min_headroom_gb"] = min(
            peaks["commit_min_headroom_gb"], s["commit_headroom_gb"]
        )
        peaks["physical_min_available_gb"] = min(
            peaks["physical_min_available_gb"], s["physical_available_gb"]
        )

        consec["pct"] = consec["pct"] + 1 if s["commit_percent"] >= COMMIT_PERCENT_ABORT else 0
        consec["head"] = (
            consec["head"] + 1 if s["commit_headroom_gb"] < COMMIT_HEADROOM_ABORT_GB else 0
        )
        consec["ram"] = consec["ram"] + 1 if s["physical_available_gb"] < EMERGENCY_RAM_GB else 0
        if max(consec.values()) >= CONSECUTIVE:
            stop_reason = f"commit-aware safety stop: {consec} at t={s['t']}s"
            outcome = "SAFETY_STOP"
            break
        if proc.poll() is not None:
            outcome = "PROCESS_EXITED"
            break
        try:
            h = http_json(f"/history/{prompt_id}").get(prompt_id)
        except (urllib.error.URLError, OSError):
            h = None
        if h and h.get("status", {}).get("completed") is not None:
            outcome = "COMPLETED" if h["status"]["completed"] else "EXECUTION_ERROR"
            result["history_status"] = h["status"]
            break
        time.sleep(SAMPLE_SECONDS)
    samples.close()
    result.update(outcome=outcome, safety_stop=stop_reason, gpu_query_failed=not gpu_ok, peaks=peaks,
                  wall_seconds=round(time.time() - t0, 1), last_step=latest_step(log_path))  # fmt: skip
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="gate + launch + verify, submit nothing")
    args = ap.parse_args()
    EVID.mkdir(exist_ok=True)
    tag = "dry" if args.dry else "run"

    g = gate()
    (EVID / f"gate_{tag}.json").write_text(json.dumps(g, indent=2))
    print(
        json.dumps(
            {
                k: g[k]
                for k in (
                    "failures",
                    "graph_validation",
                    "launch_arg_difference",
                    "minutes_since_boot",
                )
            },
            indent=2,
        )
    )
    if g["failures"]:
        print("GATE FAILED - no launch, no submission")
        return 2

    log_path = EVID / f"comfy_server_{tag}.log"
    proc = launch(log_path)
    summary: dict[str, Any] = {"tag": tag, "launch_args": am.launch_args("B"), "pid": proc.pid}
    try:
        if not wait_ready(proc, log_path):
            summary["error"] = "server did not become ready"
            return 3
        text = log_path.read_text(encoding="utf-8", errors="replace")
        summary["enabled_pinned_memory_log_line_present"] = "Enabled pinned memory" in text
        summary["listener_pid"] = port_listener_pid()
        lp = summary["listener_pid"]
        summary["listener_parent_pid"] = parent_pid(lp) if lp else None
        # venv launcher shim (proc.pid) parents the real interpreter that binds the port
        summary["listener_is_owned_process"] = lp is not None and (
            lp == proc.pid or summary["listener_parent_pid"] == proc.pid
        )
        summary["startup_log_versions"] = [
            ln for ln in text.splitlines() if "version" in ln.lower()
        ][:8]
        if (
            summary["enabled_pinned_memory_log_line_present"]
            or not summary["listener_is_owned_process"]
        ):
            summary["error"] = "flag effect / ownership verification failed - no submission"
            return 4
        if args.dry:
            summary["dry_run_ok"] = True
            return 0
        summary["snapshot_before_submit"] = commit_snapshot()
        summary["gpu_before_submit"] = gpu_query()
        summary.update(run_and_monitor(proc, log_path))
        summary["events_after_60min"] = event_log(60)
        return 0
    finally:
        summary["teardown"] = teardown(proc)
        summary["outputs_after"] = [p.name for p in (ENV / "outputs").iterdir()]
        (EVID / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2, default=str))
        print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
