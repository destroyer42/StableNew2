"""PR-VID-184S arm harness (qualification-only): one arm (B1 / A / B2) per invocation.

Extends the PR-VID-184R harness (``run_arm_b``) rather than replacing it: gates, ownership check,
teardown, telemetry loop and safety stop are reused. Each arm requires a fresh operator-mediated
Windows boot; this harness never reboots the machine. ``--dry`` runs every gate and the launch/
verification but submits nothing and may be repeated. A real run performs exactly ONE submission
and refuses to run again for the same arm.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.qualification.vid184r import run_arm_b as rab  # noqa: E402
from tools.qualification.vid184s import arms  # noqa: E402

ROOT = Path(arms.EVIDENCE_ROOT)
ENV = rab.ENV


def boot_time_iso() -> str:
    return rab.sh(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')"]
    ).stdout.strip()  # fmt: skip


def prior_boots(arm: str) -> list[str]:
    boots = []
    for other in arms.ARMS:
        if other == arm:
            continue
        p = ROOT / other / "arm_record.json"
        if p.exists():
            boots.append(json.loads(p.read_text())["boot_time"])
    return boots


def sequence_failures(arm: str) -> list[str]:
    """Enforce B1 -> A -> B2, one submission per arm, and reconcile interrupted arms."""
    fails: list[str] = []
    for other in arms.ARMS:
        marker = ROOT / other / "SUBMITTED.marker"
        record = ROOT / other / "arm_record.json"
        if marker.exists() and not record.exists() and other != arm:
            fails.append(
                f"{other} was submitted but has no arm_record (interrupted: reconcile first)"
            )
    idx = arms.ARMS.index(arm)
    if (ROOT / arm / "SUBMITTED.marker").exists():
        fails.append(f"{arm} already submitted: no retry is authorized")
    own_record = ROOT / arm / "arm_record.json"
    if own_record.exists():
        # A matched-state gate miss writes arm_record.json without SUBMITTED.marker (no
        # submission occurred), so the marker check above would not catch a repeat attempt.
        # Any existing record -- submitted or gate-miss -- is a terminal result for this arm.
        own_status = arms.arm_status(json.loads(own_record.read_text()))
        fails.append(
            f"{arm} already produced arm_record.json (outcome {own_status!r}): no repeat attempt is authorized"
        )
    for prev in arms.ARMS[:idx]:
        prev_record = ROOT / prev / "arm_record.json"
        if not prev_record.exists():
            fails.append(f"{prev} has not been run: order is B1 -> A -> B2")
            continue
        status = arms.arm_status(json.loads(prev_record.read_text()))
        # Per the pre-registered protocol: B1 must COMPLETE before A runs (any failure there
        # invalidates the causal comparison). Before A -> B2, only a SEVERE system-level fault
        # or a matched-state gate miss stops the package; GPU loss or a clean failure in A is
        # an authorized continuation point (operator-mediated recovery reboot before B2).
        stops_here = status == "SEVERE" or status == "MATCHED_STATE_GATE_NOT_MET" or (
            prev == "B1" and status != "COMPLETED"
        )  # fmt: skip
        if stops_here:
            fails.append(
                f"{prev} outcome was {status!r}: the pre-registered protocol requires the "
                f"package to stop before {arm} runs"
            )
    if arm != "B1" and not (ROOT / "reference_state.json").exists():
        fails.append("B1 reference state missing")
    return fails


def frozen_bands() -> dict[str, Any]:
    return {
        "commit_percent_points": arms.BAND_COMMIT_PERCENT_POINTS,
        "physical_available_gb": arms.BAND_PHYSICAL_AVAILABLE_GB,
        "free_vram_mib": arms.BAND_FREE_VRAM_MIB,
        "max_minutes_since_boot": arms.MAX_MINUTES_SINCE_BOOT,
        "pressure_commit_peak_delta_points": arms.PRESSURE_COMMIT_PEAK_DELTA_POINTS,
    }


def idle_baseline() -> list[dict[str, Any]]:
    out = []
    for _ in range(5):
        out.append({"commit": rab.commit_snapshot(), "gpu": rab.gpu_query()})
        time.sleep(2)
    return out


def launch(arm: str, log_path: Path) -> Any:
    import subprocess

    log = log_path.open("wb")
    return subprocess.Popen(
        [rab.am.PY_EXE, *arms.launch_args(arm)], cwd=rab.am.COMFY_ROOT, stdout=log,
        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )  # fmt: skip


def pagefile_usage() -> str:
    return rab.sh(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_PageFileUsage | Select Name,AllocatedBaseSize,CurrentUsage,PeakUsage | ConvertTo-Json -Compress"]
    ).stdout.strip()  # fmt: skip


def lock_frozen_bands() -> str | None:
    """Write ``frozen_bands.json`` once, before Arm B1; on every later invocation verify the
    on-disk bands still match the checked-out ``arms.py`` constants instead of overwriting them,
    so the audit trail of "frozen before any result" cannot be silently replaced later."""
    path = ROOT / "frozen_bands.json"
    current = frozen_bands()
    if not path.exists():
        path.write_text(json.dumps(current, indent=2))
        return None
    existing = json.loads(path.read_text())
    if existing != current:
        return "frozen_bands.json exists and differs from the current arms.py constants"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=arms.ARMS, required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument(
        "--allow-stale-boot", action="store_true", help="dry-run only: skip the fresh-boot gate"
    )
    args = ap.parse_args()
    arm = args.arm
    evid = ROOT / arm
    evid.mkdir(parents=True, exist_ok=True)
    rab.EVID = evid
    tag = "dry" if args.dry else "run"
    ROOT.mkdir(parents=True, exist_ok=True)
    bands_mismatch = lock_frozen_bands()

    manifest = arms.arm_manifest(arm)
    manifest_ok = (
        arms.execution_equivalent(manifest, arms.arm_manifest("B1"))
        if arm != "A"
        else set(rab.am.diff_manifests(arms.arm_manifest("B1"), manifest)) <= arms.ALLOWED_DIFF_KEYS
    )
    (evid / f"manifest_{tag}.json").write_text(json.dumps(manifest, indent=2))

    g = rab.gate()
    g["arm"] = arm
    g["boot_time"] = boot_time_iso()
    g["sequence_failures"] = sequence_failures(arm)
    g["hidden_flags"] = arms.hidden_flag_check(arm)
    g["manifest_ok"] = manifest_ok
    stale_ok = args.dry and args.allow_stale_boot
    if not stale_ok and (
        g["minutes_since_boot"] is None or g["minutes_since_boot"] > arms.MAX_MINUTES_SINCE_BOOT
    ):
        g["failures"].append(f"not a fresh boot (>{arms.MAX_MINUTES_SINCE_BOOT} min since boot)")
    if not stale_ok and g["boot_time"] in prior_boots(arm):
        g["failures"].append("same boot as a previous arm: a fresh reboot is required")
    g["failures"] += g["sequence_failures"] if not args.dry else []
    if g["hidden_flags"] or not manifest_ok:
        g["failures"].append("manifest/flag check failed")
    if g.get("other_gpu_compute_processes"):
        g["failures"].append(
            "another GPU compute process is present: the qualification env must be the only "
            "GPU workload (matched-state protocol precondition)"
        )
    if bands_mismatch:
        g["failures"].append(bands_mismatch)
    g["idle_baseline"] = idle_baseline()
    (evid / f"gate_{tag}.json").write_text(json.dumps(g, indent=2, default=str))
    print(
        json.dumps(
            {
                k: g[k]
                for k in (
                    "arm",
                    "failures",
                    "sequence_failures",
                    "graph_validation",
                    "minutes_since_boot",
                    "boot_time",
                )
            },
            indent=2,
        )
    )
    if g["failures"]:
        print("GATE FAILED - no launch, no submission")
        return 2

    log_path = evid / f"comfy_server_{tag}.log"
    launch_time = time.time()
    proc = launch(arm, log_path)
    summary: dict[str, Any] = {"tag": tag, "arm": arm, "launch_args": arms.launch_args(arm),
                               "pid": proc.pid, "launch_time": launch_time}  # fmt: skip
    code = 0
    try:
        if not rab.wait_ready(proc, log_path):
            summary["error"] = "server did not become ready"
            return 3
        summary["ready_seconds"] = round(time.time() - launch_time, 1)
        text = log_path.read_text(encoding="utf-8", errors="replace")
        startup = arms.analyze_log(text)
        summary["startup_log"] = startup
        lp = rab.port_listener_pid()
        summary["listener_pid"] = lp
        summary["listener_parent_pid"] = rab.parent_pid(lp) if lp else None
        owned = lp is not None and (lp == proc.pid or summary["listener_parent_pid"] == proc.pid)
        summary["listener_is_owned_process"] = owned
        pinned_on = startup["enabled_pinned_memory_line"] is not None
        expected_on = arm == "A"
        if pinned_on != expected_on or not owned:
            summary["error"] = "pinned-memory state / ownership verification failed - no submission"
            return 4
        commit = rab.commit_snapshot()
        gpu = rab.gpu_query()
        state = arms.state_vector(commit, gpu)
        summary["pre_dispatch_state"] = state
        summary["pre_dispatch_commit"] = commit
        summary["pre_dispatch_gpu"] = gpu
        if arm == "B1":
            if not args.dry:
                (ROOT / "reference_state.json").write_text(json.dumps(state, indent=2))
        else:
            ref_path = ROOT / "reference_state.json"
            if args.dry and not ref_path.exists():
                summary["dry_run_ok"] = True
                summary["note"] = "no B1 reference yet: matched-state check skipped in dry run"
                return 0
            ref = json.loads(ref_path.read_text())
            match = arms.matched_state_check(ref, state)
            summary["matched_state"] = match
            if not match["matched"]:
                summary["matched_state_gate_not_met"] = True
                summary["error"] = "MATCHED_STATE_GATE_NOT_MET - no submission"
                code = 6
                return 6
        if args.dry:
            summary["dry_run_ok"] = True
            return 0
        (evid / "SUBMITTED.marker").write_text(str(time.time()))  # before the one submission
        summary["snapshot_before_submit"] = commit
        result = rab.run_and_monitor(proc, log_path)
        summary.update(result)
        summary["teardown"] = rab.teardown(proc)  # stop the workload before slow diagnostics
        summary["history_messages"] = result.get("history_status", {}).get("messages")
        summary["gpu_after_teardown"] = rab.gpu_query()
        summary["pagefile_after"] = pagefile_usage()
        minutes = max(5, int((time.time() - result["submit_time"]) / 60) + 2)
        # The PowerShell query window is intentionally wider than the run itself (safety margin),
        # but every arm starts shortly after a fresh boot, so it can otherwise include pre-submit
        # boot-time events; filter down to the actual post-submit interval before persisting.
        summary["events_since_submit"] = _events_since(
            rab.event_log(minutes), result["submit_time"]
        )
        final_text = log_path.read_text(encoding="utf-8", errors="replace")
        summary["final_log"] = arms.analyze_log(final_text)
        code = 0 if result.get("outcome") == "COMPLETED" else 5
        return code
    finally:
        summary.setdefault("teardown", None)
        if summary["teardown"] is None:
            summary["teardown"] = rab.teardown(proc)
        outs = list((ENV / "outputs").iterdir())
        summary["outputs_after"] = [p.name for p in outs]
        if not args.dry and outs:
            dest = evid / "output"
            dest.mkdir(exist_ok=True)
            for p in outs:
                shutil.move(str(p), dest / p.name)
                summary.setdefault("output_files", []).append(
                    {"name": p.name, "sha256": rab.sha256(dest / p.name)}
                )
        (evid / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2, default=str))
        if not args.dry and (
            (evid / "SUBMITTED.marker").exists() or summary.get("matched_state_gate_not_met")
        ):
            record = build_record(arm, g, summary)
            (evid / "arm_record.json").write_text(json.dumps(record, indent=2, default=str))
        print(
            json.dumps(
                {
                    k: summary.get(k)
                    for k in ("arm", "outcome", "error", "last_step", "peaks", "wall_seconds")
                },
                indent=2,
                default=str,
            )
        )


def _as_event_list(events: Any) -> list[dict[str, Any]]:
    """``ConvertTo-Json`` emits a bare object (not a one-element array) when PowerShell's
    filtered event query matches exactly one event; normalize before iterating."""
    if events is None:
        return []
    if isinstance(events, dict):
        return [events]
    return list(events)


def _event_epoch_seconds(event: dict[str, Any]) -> float | None:
    """Parse PowerShell's ``ConvertTo-Json`` .NET date format, e.g. ``/Date(1790504626168)/``."""
    m = re.match(r"/Date\((\d+)\)/", str(event.get("TimeCreated", "")))
    return int(m.group(1)) / 1000.0 if m else None


def _events_since(events: Any, since_epoch_s: float) -> list[dict[str, Any]]:
    """Drop events timestamped before ``since_epoch_s``; keep an unparseable timestamp rather
    than silently discard evidence."""
    kept = []
    for e in _as_event_list(events):
        ts = _event_epoch_seconds(e)
        if ts is None or ts >= since_epoch_s:
            kept.append(e)
    return kept


# Event-log signals EVENT_QUERY (run_arm_b.py) was built to catch, mapped to the outcome they
# indicate. WHEA is a hardware-level fault (SEVERE). A display-driver reset (4101, or any
# nvlddmkm-provider event) is a GPU-loss signature that recovers without a reboot. Id 41
# (Kernel-Power, unexpected shutdown) and 6008 (unexpected previous shutdown) indicate the system
# actually went down, which is more severe than a driver TDR. Ids 1/153/157 alone are the
# generic-informational false positives already documented (EVENT_QUERY's ``Id -in @(...)``
# matches many unrelated providers) and are not treated as either signal.
_SEVERE_EVENT_IDS = frozenset({41, 6008})
_GPU_LOST_EVENT_IDS = frozenset({4101})


def _classify_events(events: list[dict[str, Any]]) -> tuple[bool, bool]:
    """Returns (severe_system_fault, gpu_lost_signature) from the queried Windows events."""
    severe = False
    gpu_lost = False
    for e in events:
        provider = str(e.get("ProviderName", ""))
        event_id = e.get("Id")
        if "WHEA" in provider:
            severe = True
        elif "nvlddmkm" in provider:
            gpu_lost = True
        elif event_id in _SEVERE_EVENT_IDS:
            severe = True
        elif event_id in _GPU_LOST_EVENT_IDS:
            gpu_lost = True
    return severe, gpu_lost


def build_record(arm: str, gate: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
    events = _as_event_list(s.get("events_since_submit"))
    event_severe, event_gpu_lost = _classify_events(events)
    fl = s.get("final_log") or {}
    # Device loss requires nvidia-smi itself to have failed, a loss-specific log signature
    # (device-side assert / illegal memory access / unspecified launch failure / "GPU is lost"),
    # or a matching queried Windows event (display-driver reset). A recoverable CUDA error (e.g.
    # plain OOM) or a HostBuffer error with nvidia-smi still healthy is a clean failure, not
    # device loss -- classify() treats those differently.
    gpu_lost = bool(s.get("gpu_query_failed") or fl.get("gpu_lost") or event_gpu_lost)
    return {
        "arm": arm,
        "boot_time": gate["boot_time"],
        "minutes_since_boot": gate["minutes_since_boot"],
        "outcome": s.get("outcome"),
        "peaks": s.get("peaks"),
        "gpu_lost": gpu_lost,
        "severe_system_fault": event_severe,
        "matched_state_gate_not_met": bool(s.get("matched_state_gate_not_met")),
        "pre_dispatch_state": s.get("pre_dispatch_state"),
        "matched_state": s.get("matched_state"),
        "wall_seconds": s.get("wall_seconds"),
        "final_log": fl,
        "output_files": s.get("output_files"),
    }


if __name__ == "__main__":
    sys.exit(main())
