"""Explicitly authorized WAN-321F qualification, never a production submission path.

No import-time device, runtime or filesystem operations. Launch/stop ownership stays
with ComfyProcessManager; this adapter supplies bounded qualification policy only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.qualification.wan321f.controls import (
    AttemptLedger,
    SafetyGuard,
    Sample,
    owned_session,
    write_new_json,
)
from tools.qualification.wan321f.plan import (
    EVIDENCE_ROOT,
    INPUT_PATH,
    INPUT_SHA,
    INSTALL,
    asset_refusals,
    build_graph,
    digest,
    frozen_plan,
    source_refusals,
)

PLAN_SHA = "7b47d278e1519574330a3d912009fb14dba54d3090b5788ee6164c481562b976"
DEVICE_LOSS = re.compile(
    r"GPU is lost|GPU has fallen off|CUDA error: (?:unknown|.*device)|device-side assert", re.I
)
ALLOCATION_FAILURE = re.compile(
    r"out.?of.?memory|\bOOM\b|Allocation on device|CUDA.*alloc.*fail", re.I
)


class AllocationFailure(RuntimeError):
    """A structured Comfy allocation failure is NO-GO for this exact workload."""


def event_log(start: datetime) -> dict[str, Any]:
    stamp = start.isoformat()
    script = (
        "$ErrorActionPreference='Stop'; Get-WinEvent -LogName System -MaxEvents 1 | Out-Null; "
        f"$start=[datetime]::Parse('{stamp}'); "
        "@(Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$start} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Id -in @(1,41,153,157,4101,6008) -or $_.ProviderName -like '*nvlddmkm*' "
        "-or $_.ProviderName -like '*WHEA*' } | Select-Object TimeCreated,Id,ProviderName,Message) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=15
    )
    if result.returncode:
        raise RuntimeError("System event log unavailable: " + result.stderr[-1000:])
    return {
        "start_utc": stamp,
        "events": json.loads(result.stdout) if result.stdout.strip() else [],
    }


def gpu_sample() -> dict[str, Any]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            "0",
            "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,power.draw,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=1.5,
        check=True,
    )
    name, driver, total, used, free, temp, power, util = [
        v.strip() for v in result.stdout.strip().split(",")
    ]
    return {
        "name": name,
        "driver": driver,
        "total_mib": float(total),
        "used_mib": float(used),
        "free_mib": float(free),
        "temperature_c": float(temp),
        "power_w": float(power),
        "utilization": float(util),
    }


class Monitor:
    """Independent sampling and deadline watchdogs; only the supplied manager stops its child."""

    def __init__(self, manager: Any, root: Path, policy: dict[str, Any]) -> None:
        self.manager, self.root, self.policy = manager, root, dict(policy)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.reason = ""
        self.prompt_id: str | None = None
        self.guard = SafetyGuard({**policy, "attempt_seconds": policy["session_seconds"]})
        self.epoch = time.monotonic()
        self.attempt_timer: threading.Timer | None = None
        self.session_timer = threading.Timer(
            policy["session_seconds"], self.abort, args=("session time limit",)
        )
        self.thread = threading.Thread(target=self.loop, name="WAN321F-telemetry")
        self.watchdog = threading.Thread(target=self.watchdog_loop, name="WAN321F-freshness")
        self.last_completed_sample = time.monotonic()
        self.last_sample: dict[str, Any] | None = None
        self.error: str | None = None
        self.children: set[int] = set()

    def abort(self, reason: str) -> None:
        with self.lock:
            first = not self.reason
            if first:
                self.reason = reason
        # Killing this manager's contained child ends only this qualification session.
        # Do not wait for HTTP or a possibly blocked driver probe to enforce the deadline.
        if self.manager.owns_process:
            self.manager.stop(grace_seconds=0)
        if first:
            try:
                write_new_json(
                    self.root / "safety-stop.json",
                    {"reason": self.reason, "utc": datetime.now(UTC).isoformat()},
                )
            except Exception as exc:
                self.error = "Safety evidence write failed: " + str(exc)

    def arm(self) -> None:
        with self.lock:
            self.epoch = time.monotonic()
            self.guard = SafetyGuard(self.policy)
        self.attempt_timer = threading.Timer(
            self.policy["attempt_seconds"], self.abort, args=("attempt time limit",)
        )
        self.attempt_timer.start()

    def disarm(self) -> None:
        if self.attempt_timer:
            self.attempt_timer.cancel()
            self.attempt_timer.join()
            self.attempt_timer = None
        with self.lock:
            self.epoch = time.monotonic()
            self.guard = SafetyGuard(
                {**self.policy, "attempt_seconds": self.policy["session_seconds"]}
            )

    def sample_once(self) -> None:
        import psutil

        from tools.qualification.vid160c.win_memory import read_process_memory, read_system_commit

        commit = read_system_commit()
        gpu = gpu_sample()
        if gpu["name"] != "NVIDIA GeForce RTX 4070 Ti" or gpu["total_mib"] != 12282:
            raise RuntimeError("Target GPU identity mismatch")
        if not 31 <= commit.physical_total_gb <= 32:
            raise RuntimeError("Target 32 GB host memory identity mismatch")
        pid = self.manager.pid
        process = read_process_memory(pid) if pid else None
        if pid and process is None:
            raise RuntimeError("Owned-process memory telemetry unavailable")
        if pid:
            self.children.update(p.pid for p in psutil.Process(pid).children(recursive=True))
        logs = "\n".join(self.manager.get_stdout_tail() + self.manager.get_stderr_tail())
        if ALLOCATION_FAILURE.search(logs):
            self.abort("allocation failure")
        with self.lock:
            sample = Sample(
                time.monotonic() - self.epoch,
                commit.commit_percent,
                commit.commit_headroom_gb,
                commit.physical_available_gb,
                process.working_set_gb if process else 0,
                process.private_usage_gb if process else 0,
                gpu["used_mib"],
                gpu["total_mib"],
                device_loss=bool(DEVICE_LOSS.search(logs)),
            )
            reason = self.guard.observe(sample)
            record = {
                "utc": datetime.now(UTC).isoformat(),
                "sample": asdict(sample),
                "gpu": gpu,
                "system": asdict(commit),
                "process": asdict(process) if process else None,
                "owned_pid": pid,
            }
            self.last_sample = record
        if reason:
            self.abort(reason)  # Stop before potentially blocking evidence I/O.
        # No filesystem I/O holds the watchdog's policy lock.
        with (self.root / "telemetry.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.last_completed_sample = time.monotonic()

    def loop(self) -> None:
        while not self.stop_event.wait(self.policy["sample_seconds"]):
            try:
                self.sample_once()
            except BaseException as exc:
                self.error = type(exc).__name__ + ": " + str(exc)
                self.abort("missing or invalid telemetry: " + self.error)
                return

    def watchdog_loop(self) -> None:
        while not self.stop_event.wait(0.1):
            if (
                self.reason
                or time.monotonic() - self.last_completed_sample
                > self.policy["telemetry_gap_seconds"]
            ):
                self.abort(self.reason or "missing telemetry: freshness deadline exceeded")

    def start(self) -> None:
        self.sample_once()  # A complete baseline is required before launch.
        if self.reason:
            raise RuntimeError(self.reason)
        self.session_timer.start()
        self.thread.start()
        self.watchdog.start()

    def close(self) -> None:
        self.disarm()
        self.session_timer.cancel()
        if self.session_timer.ident:
            self.session_timer.join()
        self.stop_event.set()
        if self.thread.ident:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError("Telemetry worker did not stop")
        if self.watchdog.ident:
            self.watchdog.join(timeout=5)
            if self.watchdog.is_alive():
                raise RuntimeError("Freshness watchdog did not stop")


def validate_schema(info: dict[str, Any], graph: dict[str, Any]) -> None:
    for node in graph.values():
        schema = info.get(node["class_type"])
        if not isinstance(schema, dict):
            raise RuntimeError("Missing stock node: " + node["class_type"])
        inputs = schema.get("input", {})
        required = inputs.get("required", {})
        declared = {**required, **inputs.get("optional", {})}
        if set(required) - set(node["inputs"]):
            raise RuntimeError("Missing required node inputs: " + node["class_type"])
        for key, value in node["inputs"].items():
            if key not in declared:
                raise RuntimeError("Unsupported node input: " + node["class_type"] + "." + key)
            descriptor = declared[key]
            if (
                isinstance(value, str)
                and isinstance(descriptor[0], list)
                and value not in descriptor[0]
            ):
                raise RuntimeError("Unavailable node option: " + value)


def validate_outputs(history: dict[str, Any], output_root: Path) -> dict[str, Any]:
    from PIL import Image

    images = history.get("outputs", {}).get("16", {}).get("images", [])
    if len(images) != 81:
        raise RuntimeError(f"Expected 81 PNG frames, found {len(images)}")
    records = []
    seen: set[Path] = set()
    for image in images:
        if image.get("type") != "output":
            raise RuntimeError("Unexpected output file type")
        path = (output_root / image.get("subfolder", "") / image["filename"]).resolve()
        if (
            not path.is_relative_to(output_root.resolve())
            or path in seen
            or path.suffix.lower() != ".png"
        ):
            raise RuntimeError("Escaped, duplicate or invalid frame path")
        seen.add(path)
        with Image.open(path) as frame:
            frame.load()
            if frame.size != (480, 832) or frame.mode not in ("RGB", "RGBA"):
                raise RuntimeError("Invalid frame geometry or channels")
        with path.open("rb") as handle:
            sha = hashlib.file_digest(handle, "sha256").hexdigest()
        records.append({"path": str(path), "sha256": sha, "bytes": path.stat().st_size})
    return {"valid": True, "count": len(records), "frames": records}


def wait_attempt(
    client: Any, monitor: Any, prompt_id: str, *, clock=time.monotonic, sleep=time.sleep
) -> dict[str, Any]:
    deadline = clock() + 300
    while clock() < deadline:
        if monitor.reason:
            raise RuntimeError(monitor.reason)
        history = client.get_history(prompt_id, timeout=2).get(prompt_id)
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                return history  # Preserve the complete error history before interpretation.
            if status.get("completed"):
                return history
        sleep(0.5)
    monitor.abort("attempt time limit")
    raise RuntimeError("attempt time limit")


def summarize(root: Path, verdict: str) -> dict[str, Any]:
    path = root / "telemetry.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    samples = [r["sample"] for r in rows]
    if not samples:
        return {"verdict": "INCONCLUSIVE", "samples": 0}
    return {
        "verdict": verdict,
        "samples": len(samples),
        "commit_percent_peak": max(s["commit_percent"] for s in samples),
        "commit_headroom_min_gib": min(s["commit_headroom_gib"] for s in samples),
        "physical_available_min_gib": min(s["physical_available_gib"] for s in samples),
        "owned_working_set_peak_gib": max(s["owned_working_set_gib"] for s in samples),
        "owned_private_peak_gib": max(s["owned_private_gib"] for s in samples),
        "vram_peak_mib": max(s["vram_used_mib"] for s in samples),
        "vram_free_min_mib": min(s["vram_total_mib"] - s["vram_used_mib"] for s in samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-plan", required=True)
    args = parser.parse_args()
    plan = frozen_plan()
    if args.authorize_plan != PLAN_SHA or digest(plan) != PLAN_SHA:
        raise SystemExit("Authorization does not match the frozen plan")
    root = Path(EVIDENCE_ROOT) / "physical-001"
    root.mkdir()  # Persistent session claim: no restart or second execution of this budget.
    write_new_json(
        root / "execution-manifest.json",
        {
            "proposal": plan,
            "proposal_sha256": PLAN_SHA,
            "owner_authorization": "Authorize the physical work.",
            "memory_limits_accepted": True,
            "authorization": {
                "asset_download": True,
                "owned_runtime_start": True,
                "generation": True,
                "runtime_restart": False,
                "production_promotion": False,
            },
            "executed_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "physical_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "maximum_attempts": 3,
            "maximum_retries": 1,
            "attempt_seconds": 300,
        },
    )
    failures = asset_refusals() + source_refusals()
    if failures:
        write_new_json(root / "preflight-refusal.json", failures)
        raise SystemExit("Preflight refused; see preserved evidence")
    import psutil

    from src.video.comfy_api_client import ComfyApiClient
    from src.video.comfy_process_manager import ComfyProcessConfig, ComfyProcessManager

    started = datetime.now(UTC)
    write_new_json(root / "events-before.json", event_log(started))
    runtime = Path(EVIDENCE_ROOT) / "runtime"
    if runtime.exists():
        raise SystemExit("Frozen runtime scratch already exists; refusing reuse")
    for folder in ("input", "output", "temp", "user"):
        (runtime / folder).mkdir(parents=True)
    source = Path(INPUT_PATH).read_bytes()
    if hashlib.sha256(source).hexdigest() != INPUT_SHA:
        raise SystemExit("Input changed")
    (runtime / "input/wan321f-source.png").write_bytes(source)
    paths = {"wan321f": plan["runtime"]["extra_model_paths"]}
    (runtime / "extra_model_paths.yaml").write_text(
        json.dumps(paths), encoding="utf-8"
    )  # JSON is valid YAML.
    if shutil.disk_usage(runtime).free < 1364875264:
        raise SystemExit("Insufficient evidence capacity")
    manager = ComfyProcessManager(
        ComfyProcessConfig(
            command=plan["launch_command"],
            working_dir=f"{INSTALL}/source",
            base_url=plan["runtime"]["base_url"],
            log_path=root / "comfy.log",
            startup_timeout_seconds=240,
        )
    )
    client = ComfyApiClient(base_url=plan["runtime"]["base_url"])
    monitor = Monitor(manager, root, plan["safety_proposal"])
    verdict, completed, pid, children = "INCONCLUSIVE", 0, None, []
    try:
        monitor.start()
        with owned_session(manager):
            pid = manager.pid
            children = [p.pid for p in psutil.Process(pid).children(recursive=True)]
            if monitor.reason:
                raise RuntimeError(monitor.reason)
            manager.check_health()
            stats = client.get_system_stats(timeout=5)
            write_new_json(root / "runtime-stats.json", stats)
            system = stats.get("system", {})
            if (
                system.get("comfyui_version") != "0.38.0"
                or system.get("pytorch_version") != "2.14.0+cu130"
                or not str(system.get("python_version", "")).startswith("3.13.")
            ):
                raise RuntimeError("Pinned runtime identity mismatch")
            info = client.get_object_info(timeout=15)
            validate_schema(info, build_graph(1))
            write_new_json(
                root / "node-schema.json",
                {k: info[k] for k in {n["class_type"] for n in build_graph(1).values()}},
            )
            ledger = AttemptLedger(root)
            for attempt in (1, 2, 3):
                if monitor.reason or not manager.is_running():
                    raise RuntimeError(monitor.reason or "Owned runtime exited")
                monitor.arm()
                reply = ledger.dispatch_once(attempt, client.queue_prompt)
                monitor.prompt_id = reply["prompt_id"]
                history = wait_attempt(client, monitor, reply["prompt_id"])
                write_new_json(root / f"attempt-{attempt}/history.json", history)
                if history.get("status", {}).get("status_str") == "error":
                    detail = json.dumps(history["status"])
                    kind = AllocationFailure if ALLOCATION_FAILURE.search(detail) else RuntimeError
                    raise kind("Comfy execution error: " + detail[-3000:])
                validity = validate_outputs(history, runtime / "output")
                write_new_json(root / f"attempt-{attempt}/validity.json", validity)
                monitor.disarm()
                completed += 1
            verdict = "PASS" if completed == 3 else "INCONCLUSIVE"
            children = [p.pid for p in psutil.Process(pid).children(recursive=True)]
    except BaseException as exc:
        message = type(exc).__name__ + ": " + str(exc)
        if isinstance(exc, AllocationFailure) or any(
            s in (monitor.reason + message).lower()
            for s in ("safety stop", "allocation failure", "out of memory", "device loss")
        ):
            verdict = "NO-GO"
        write_new_json(root / "failure.json", {"message": message, "safety_reason": monitor.reason})
    finally:
        if manager.owns_process:
            manager.stop(grace_seconds=0)
        try:
            monitor.close()
        except Exception as exc:
            verdict = "INCONCLUSIVE"
            write_new_json(root / "monitor-close-failure.json", {"error": str(exc)})
        client.close()
        children = sorted(set(children) | getattr(monitor, "children", set()))
        alive = [p for p in ([pid] if pid else []) + children if psutil.pid_exists(p)]
        write_new_json(
            root / "teardown.json",
            {
                "owned_pid": pid,
                "observed_children": children,
                "surviving_pids": alive,
                "verified": pid is not None and not alive,
            },
        )
        if alive or pid is None:
            verdict = "INCONCLUSIVE"
        try:
            write_new_json(root / "events-after.json", event_log(started))
        except Exception as exc:
            write_new_json(root / "event-log-failure.json", {"error": str(exc)})
            verdict = "INCONCLUSIVE"
        if monitor.reason and verdict == "PASS":
            verdict = "INCONCLUSIVE"
        result = {
            **summarize(root, verdict),
            "completed_attempts": completed,
            "safety_reason": monitor.reason,
            "automatic_retries": 0,
        }
        write_new_json(root / "result.json", result)
        print(json.dumps(result), flush=True)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
