"""Opt-in parent for GUI-PORT-742: a bounded, owned, sequential Tk/PySide6 qualification on the real Windows desktop.

Read-only: it launches only this package's proof children, never the application, a job database, a backend or a
generator. Without ``--allow-gui`` it reports NOT RUN and imports nothing toolkit-related.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tools.qualification.gui_port_740.common import ROOT, runtime
from tools.qualification.gui_port_742.evidence import (
    EvidenceError,
    compare_parity,
    dispatch_policy_ratio,
    interpret_dpi,
    summarize,
    validate_process_record,
    validate_visibility,
)

PACKAGE = "tools.qualification.gui_port_742"
SOURCE_FILES = (
    "src/gui_v2/design_values.py",
    "src/gui/ui_tokens.py",
    "src/gui_v2/history_browser_model.py",
    "src/gui/view_contracts/task_navigation_contract.py",
    "src/controller/ports/ui_dispatcher.py",
    "src/gui/app_state_v2.py",
    "src/gui/app_state_projection_sink.py",
    "src/gui/ui_dispatcher.py",
    "src/gui/gui_invoker.py",
    "src/queue/history_query.py",
    "tools/qualification/gui_port_740/qt_dispatcher.py",
    "tools/qualification/gui_port_740/common.py",
)
# (requested DPI label, viewport, simulated factor). 1920x1080 at a simulated 150% needs 2880x1620 physical pixels,
# which this 2560x1440 desktop cannot show, so it is recorded as UNQUALIFIED rather than run at a clamped size.
EXPECTED_STEPS = (
    12  # the scripted journey; a record with fewer or more steps is not the same experiment
)
MATRIX = (
    ("actual-100", "1366x768", 1.0),
    ("actual-100", "1920x1080", 1.0),
    ("actual-100", "max", 1.0),
    ("simulated-150", "1366x768", 1.5),
    ("simulated-150", "max", 1.5),
)
UNQUALIFIED = (
    {
        "cell": "simulated-150 @ 1920x1080",
        "reason": "needs 2880x1620 physical pixels; the only monitor is 2560x1440",
    },
    {
        "cell": "actual-150 (any viewport)",
        "reason": "no 150% monitor available; system scaling is not changed",
    },
    {
        "cell": "fractional or mixed-DPI, multi-monitor",
        "reason": "a single 2560x1440 monitor at 100% is attached",
    },
    {
        "cell": "screen reader (Narrator/NVDA/JAWS) behavior",
        "reason": "no assistive technology was run",
    },
)
CONDITIONS = (("tk", "native"), ("qt", "native"), ("qt", "matched"))

UIA_SCRIPT = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, {pid})
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if ($null -eq $win) { '{"window": false}' ; exit 0 }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$items = @()
foreach ($e in $all) {
  $c = $e.Current
  $items += [pscustomobject]@{ type = $c.ControlType.ProgrammaticName; name = $c.Name; cls = $c.ClassName; focusable = $c.IsKeyboardFocusable }
}
[pscustomobject]@{ window = $true; window_name = $win.Current.Name; count = $all.Count; items = ($items | Select-Object -First 400) } | ConvertTo-Json -Depth 4 -Compress
"""


def fingerprint() -> dict[str, str]:
    files = {f: ROOT / f for f in SOURCE_FILES}
    files.update(
        {
            f"{PACKAGE.replace('.', '/')}/{p.name}": p
            for p in sorted((Path(__file__).parent).glob("*.py"))
        }
    )
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}


def uia_inspect(pid: int) -> dict[str, Any]:
    """Read-only UI Automation dump of the proof window this harness launched (owned PID reported by the child)."""

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            UIA_SCRIPT.replace("{pid}", str(int(pid))),
        ],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    try:
        raw = json.loads(completed.stdout or "{}")
    except ValueError:
        return {"window": None, "error": (completed.stderr or completed.stdout)[:300]}
    if not raw.get("window"):
        return {"window": False}
    items = raw.get("items") or []
    if isinstance(items, dict):
        items = [items]
    named = [i for i in items if (i.get("name") or "").strip()]
    return {
        "window": True,
        "window_name": raw.get("window_name"),
        "descendants": raw.get("count"),
        "named_descendants": len(named),
        "types": sorted({i["type"] for i in items}),
        "classes": sorted({i["cls"] for i in items if i.get("cls")})[:12],
        "named_sample": [{"type": i["type"], "name": i["name"][:60]} for i in named[:14]],
        "focusable": sum(1 for i in items if i.get("focusable")),
    }


def scalars(record: dict[str, Any]) -> dict[str, float]:
    b = record["result"]["benchmark"]
    second = b["second_window"]
    mib = 1024 * 1024
    hb_idle, hb_load, dispatch, callback = (
        b["idle_heartbeat"],
        b["sustained_heartbeat"],
        b["burst_dispatch_ms"],
        b["burst_callback_ms"],
    )
    return {
        "startup_ms": record["startup_ms"],
        "construct_ms": b["construct_ms"],
        "populate_ms": b["populate_ms"],
        "show_to_paint_ms": b["show_to_paint_ms"],
        "second_window_construct_ms": second["construct_ms"],
        "second_window_painted_ms": second["to_painted_ms"],
        "idle_working_set_mib": b["idle_memory"]["working_set"] / mib,
        "peak_tree_working_set_mib": record["peak_sampled_working_set"] / mib,
        "filter_handler_ms": b["filter_handler_ms"],
        "filter_visible_ms": b["filter_visible_ms"],
        "select_handler_ms": b["select_handler_ms"],
        "select_visible_ms": b["select_visible_ms"],
        "refresh_to_visible_ms": b["refresh_to_visible_ms"],
        "refresh_render_ms_median": b["refresh_render_ms_median"],
        "sustained_renders": b["sustained_renders"],
        "sustained_render_ms_median": b["sustained_render_ms_median"],
        "idle_heartbeat_median_ms": hb_idle["median"],
        "idle_heartbeat_max_ms": hb_idle["max"],
        "loaded_heartbeat_median_ms": hb_load["median"],
        "loaded_heartbeat_p95_ms": hb_load["p95"],
        "loaded_heartbeat_max_ms": hb_load["max"],
        "burst_dispatch_median_ms": dispatch["median"],
        "burst_dispatch_p95_ms": dispatch["p95"],
        "burst_dispatch_max_ms": dispatch["max"],
        "burst_callback_median_ms": callback["median"],
        "burst_total_ms": b["burst_total_ms"],
        "burst_flush_ms": b["burst_flush_ms"],
        "burst_peak_backlog": b["burst_peak_backlog"],
        "close_to_exit_ms": record["close_to_exit_ms"],
    }


def validate_benchmark(record: dict[str, Any], toolkit: str) -> None:
    validate_process_record(record)
    validate_visibility(
        record["first_visible"], record["result"], toolkit, require_second_window=True
    )
    b = record["result"]["benchmark"]
    for key in ("populated", "burst_arrived", "refresh_arrived", "refresh_selection_kept"):
        if b.get(key) is not True:
            raise EvidenceError(f"benchmark check failed: {key}")
    if b.get("burst_problem"):
        raise EvidenceError(f"burst sequence invalid: {b['burst_problem']}")
    if record.get("close_to_exit_ms") is None:
        raise EvidenceError("close timestamp missing")


def host_snapshot() -> dict[str, Any]:
    import psutil

    memory = psutil.virtual_memory()
    return {
        "cpu_percent_500ms": psutil.cpu_percent(interval=0.5),
        "available_memory_mib": memory.available // (1024 * 1024),
        "logical_cpus": psutil.cpu_count(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-gui", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--phases", default="matrix,a11y,benchmark")
    args = parser.parse_args(argv)
    if not args.allow_gui:
        print(
            json.dumps(
                {
                    "status": "NOT RUN",
                    "reason": "Explicit --allow-gui required",
                    "pyside_available_in_parent": importlib.util.find_spec("PySide6") is not None,
                }
            )
        )
        return 2
    phases = {p.strip() for p in args.phases.split(",") if p.strip()}
    if (
        not args.output
        or not args.output.is_absolute()
        or not 5 <= args.samples <= 10
        or not phases <= {"matrix", "a11y", "benchmark"}
    ):
        parser.error("new absolute --output, 5-10 samples and valid --phases required")
    if not 64 <= args.rows <= 2000:
        parser.error("bounded proof inputs required")
    args.output.mkdir(parents=True, exist_ok=False)
    from tools.qualification.gui_port_742.launch import run_child

    report: dict[str, Any] = {
        "identity": {
            "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "worktree_clean": not subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip(),
            "windows": platform.platform(),
            "parent": runtime(),
            "rows_per_table": args.rows,
            "samples": args.samples,
            "fingerprint": fingerprint(),
        },
        "unqualified": list(UNQUALIFIED),
        "matrix": [],
        "a11y": [],
        "benchmark": {"runs": [], "warmups": []},
        "validity": {"failures": []},
    }
    failures: list[str] = report["validity"]["failures"]

    def save() -> None:
        (args.output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf8")

    def execute(
        toolkit: str, arguments: list[str], *, env: dict[str, str] | None = None, on_event=None
    ):
        host = host_snapshot()  # 500 ms of host load immediately BEFORE this child starts
        record = run_child(
            args.python, f"{PACKAGE}.{toolkit}_child", arguments, env_extra=env, on_event=on_event
        )
        record["host"] = host
        return record

    base = ["--rows", str(args.rows)]
    # ---- 1. functional matrix: viewport x DPI, identical scenario on both toolkits ------------------------------
    if "matrix" in phases:
        for requested, viewport, factor in MATRIX:
            pair: dict[str, dict[str, Any]] = {}
            for toolkit in ("tk", "qt"):
                shot = []
                if viewport == "1366x768":
                    shot = [
                        "--screenshot",
                        str(args.output / f"{toolkit}-{requested}-{viewport}.png"),
                    ]
                env = (
                    {"QT_SCALE_FACTOR": str(factor)} if toolkit == "qt" and factor != 1.0 else None
                )
                record = execute(
                    toolkit,
                    [
                        *base,
                        "--mode",
                        "matrix",
                        "--viewport",
                        viewport,
                        "--sim-scale",
                        str(factor),
                        "--requested-dpi",
                        requested,
                        *shot,
                    ],
                    env=env,
                )
                label = f"{toolkit} {requested} {viewport}"
                try:
                    validate_process_record(record)
                    validate_visibility(record["first_visible"], record["result"], toolkit)
                except EvidenceError as error:
                    failures.append(f"{label}: {error}")
                matrix = (record.get("result") or {}).get("matrix") or {}
                dpi = interpret_dpi((record.get("result") or {}).get("dpi") or {})
                if not dpi["valid"]:
                    failures.append(f"{label}: DPI record invalid: {dpi['reasons']}")
                steps = matrix.get("steps", [])
                if len(steps) != EXPECTED_STEPS:
                    failures.append(
                        f"{label}: {len(steps)} scenario steps recorded, expected {EXPECTED_STEPS}"
                    )
                focus = matrix.get("focus") or {}
                if not focus.get("window_active"):
                    failures.append(
                        f"{label}: window was not the foreground window during focus evidence"
                    )
                if not focus.get("visible_indicator"):
                    failures.append(
                        f"{label}: keyboard focus indicator not proven visible: {focus.get('controls')}"
                    )
                failed = [s["name"] for s in steps if not s["ok"]]
                if failed:
                    failures.append(f"{label}: scenario steps failed: {failed}")
                if matrix.get("reachability_issues"):
                    failures.append(f"{label}: reachability: {matrix['reachability_issues']}")
                report["matrix"].append(
                    {
                        "toolkit": toolkit,
                        "requested": requested,
                        "viewport": viewport,
                        "dpi_interpretation": dpi,
                        "process": {k: v for k, v in record.items() if k not in {"result"}},
                        "result": record.get("result"),
                    }
                )
                pair[toolkit] = matrix
                save()
            diffs = compare_parity(pair["tk"].get("steps", []), pair["qt"].get("steps", []))
            report.setdefault("parity", {})[f"{requested}@{viewport}"] = diffs
            failures.extend(f"parity {requested}@{viewport}: {d}" for d in diffs)
    # ---- 2. external UI Automation inspection (read-only, owned window) ------------------------------------------
    if "a11y" in phases:
        for toolkit in ("tk", "qt"):
            hold = args.output / f"hold-{toolkit}.flag"
            captured: dict[str, Any] = {}

            def on_event(
                event: dict[str, Any], toolkit=toolkit, hold=hold, captured=captured
            ) -> None:
                if event.get("event") == "inspect_ready" and not captured:
                    captured.update(uia_inspect(event["pid"]))
                    captured["pid_owned"] = True
                    hold.write_text("done", encoding="utf8")

            record = execute(
                toolkit, [*base, "--mode", "a11y", "--hold-file", str(hold)], on_event=on_event
            )
            try:
                validate_process_record(record)
            except EvidenceError as error:
                failures.append(f"a11y {toolkit}: {error}")
            report["a11y"].append(
                {"toolkit": toolkit, "uia": captured, "process_ok": record["exit_code"] == 0}
            )
            save()
    # ---- 3. benchmark: interleaved rounds so slow host drift hits every condition equally ------------------------
    if "benchmark" in phases:
        for sample in range(args.samples + 1):
            for toolkit, dispatcher in CONDITIONS:
                label = "warmup" if sample == 0 else f"sample-{sample}"
                record = execute(
                    toolkit,
                    [
                        *base,
                        "--mode",
                        "benchmark",
                        "--viewport",
                        "1366x768",
                        "--dispatcher",
                        dispatcher,
                    ],
                )
                entry = {
                    "toolkit": toolkit,
                    "dispatcher": dispatcher,
                    "label": label,
                    "process": {k: v for k, v in record.items() if k not in {"result"}},
                }
                try:
                    validate_benchmark(record, toolkit)
                    entry["scalars"] = scalars(record)
                    entry["burst"] = {
                        k: record["result"]["benchmark"][k]
                        for k in ("burst_dispatch_ms", "burst_callback_ms")
                    }
                    entry["late"] = record["result"].get("late")
                except (EvidenceError, KeyError, TypeError) as error:
                    failures.append(f"benchmark {toolkit}/{dispatcher} {label}: {error!r}")
                    entry["result"] = record.get("result")
                report["benchmark"]["warmups" if sample == 0 else "runs"].append(entry)
                save()
        summary: dict[str, dict[str, Any]] = {}
        for toolkit, dispatcher in CONDITIONS:
            runs = [
                r
                for r in report["benchmark"]["runs"]
                if r["toolkit"] == toolkit and r["dispatcher"] == dispatcher and "scalars" in r
            ]
            key = f"{toolkit}-{dispatcher}"
            try:
                summary[key] = {
                    metric: summarize(
                        [r["scalars"][metric] for r in runs],
                        expected_n=args.samples,
                        label=f"{key}.{metric}",
                    )
                    for metric in (runs[0]["scalars"] if runs else {})
                }
            except EvidenceError as error:
                failures.append(f"summary {key}: {error}")
        report["benchmark"]["summary"] = summary
        try:
            report["benchmark"]["h1_dispatch_median_ms"] = dispatch_policy_ratio(
                summary["qt-native"]["burst_dispatch_median_ms"]["median"],
                summary["qt-matched"]["burst_dispatch_median_ms"]["median"],
                summary["tk-native"]["burst_dispatch_median_ms"]["median"],
            )
        except (KeyError, EvidenceError) as error:
            failures.append(f"h1 decomposition unavailable: {error!r}")
    report["validity"]["status"] = "PASS" if not failures else "FAIL"
    report["identity"]["finished_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save()
    print(json.dumps({"validity": report["validity"]["status"], "failures": failures[:20]}))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
