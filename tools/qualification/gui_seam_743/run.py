"""Opt-in parent for GUI-SEAM-743: a bounded, owned, sequential Tk dispatcher-budget qualification on the Windows desktop.

Read-only and Tk-only: it launches only this package's proof child (one process per run), never the application, a job
database, a backend or a generator. Without ``--allow-gui`` it reports NOT RUN.

Phases: ``primary`` runs the declared one-factor matrix; ``confirmation`` (after the primary result is known) runs at most
two predeclared combinations built only from tested values and screens them against the primary control runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tools.qualification.gui_port_740.common import ROOT, runtime
from tools.qualification.gui_port_742 import run as run742
from tools.qualification.gui_seam_743.config import (
    CONTROL,
    MATRIX,
    MIN_SAMPLES,
    ConfigError,
    PumpConfig,
    RunSpec,
    describe,
    plan_runs,
    validate_confirmations,
    validate_matrix,
)
from tools.qualification.gui_seam_743.evidence import (
    EvidenceError,
    aggregate,
    run_scalars,
    screen,
    validate_experiment,
    validate_run,
    verdict,
)
from tools.qualification.gui_seam_743.inject import production_defaults

PACKAGE = "tools.qualification.gui_seam_743"
EXTRA_SOURCE_FILES = (
    "src/gui/gui_invoker.py",
    "src/gui/ui_dispatcher.py",
    "src/controller/ports/ui_dispatcher.py",
    "src/gui/app_state_v2.py",
    "src/gui/app_state_projection_sink.py",
)


def fingerprint() -> dict[str, str]:
    files = {name: ROOT / name for name in EXTRA_SOURCE_FILES}
    files.update(
        {
            f"{PACKAGE.replace('.', '/')}/{p.name}": p
            for p in sorted(Path(__file__).parent.glob("*.py"))
        }
    )
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    return run742.fingerprint() | digests


def parse_confirmation(text: str) -> PumpConfig:
    """``NAME=interval_ms,max_callbacks,max_pump_ms`` (e.g. ``H=10,64,8``)."""

    try:
        name, values = text.split("=", 1)
        interval, callbacks, pump = values.split(",")
        return PumpConfig(name.strip(), int(interval), int(callbacks), float(pump)).validate()
    except (ValueError, ConfigError) as error:
        raise ConfigError(f"bad confirmation {text!r}: {error}") from error


def child_arguments(config: PumpConfig) -> list[str]:
    return [
        "--name",
        config.name,
        "--interval-ms",
        str(config.interval_ms),
        "--max-callbacks",
        str(config.max_callbacks),
        "--max-pump-ms",
        str(config.max_pump_ms),
    ]


def build_plan(args: argparse.Namespace) -> tuple[list[PumpConfig], list[RunSpec]]:
    """Everything that can be rejected before a window opens is rejected here."""

    validate_matrix()
    if args.phase == "primary":
        configs = list(MATRIX)
    else:
        configs = validate_confirmations([parse_confirmation(c) for c in args.confirm or []])
    return configs, plan_runs(configs, phase=args.phase, samples=args.samples, seed=args.seed)


def spec_dict(spec: RunSpec) -> dict[str, Any]:
    return {
        "run_id": spec.run_id,
        "kind": spec.kind,
        "round": spec.round,
        "position": spec.position,
        "config": describe(spec.config),
    }


def host_snapshot() -> dict[str, Any]:
    import psutil

    memory = psutil.virtual_memory()
    return {
        "cpu_percent_500ms": psutil.cpu_percent(interval=0.5),
        "available_memory_mib": memory.available // (1024 * 1024),
        "logical_cpus": psutil.cpu_count(),
    }


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-gui", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--phase", choices=("primary", "confirmation"), default="primary")
    parser.add_argument("--samples", type=int, default=MIN_SAMPLES)
    parser.add_argument("--seed", type=int, default=743)
    parser.add_argument(
        "--confirm", action="append", help="NAME=interval_ms,max_callbacks,max_pump_ms"
    )
    parser.add_argument("--primary", type=Path, help="primary metrics.json (confirmation phase)")
    parser.add_argument(
        "--plan-only", action="store_true", help="print the validated run plan and exit"
    )
    args = parser.parse_args(argv)
    try:
        configs, plan = build_plan(args)
    except ConfigError as error:
        parser.error(str(error))
    if args.phase == "confirmation" and (not args.primary or not args.primary.is_file()):
        parser.error("--primary <metrics.json> is required for the confirmation phase")
    if args.plan_only:
        print(json.dumps([spec_dict(s) for s in plan], indent=1))
        return 0
    if not args.allow_gui:
        print(json.dumps({"status": "NOT RUN", "reason": "Explicit --allow-gui required"}))
        return 2
    if not args.output or not args.output.is_absolute():
        parser.error("a new absolute --output is required")
    args.output.mkdir(parents=True, exist_ok=False)
    from tools.qualification.gui_port_742.launch import run_child

    defaults = production_defaults()
    primary = json.loads(args.primary.read_text(encoding="utf8")) if args.primary else None
    report: dict[str, Any] = {
        "identity": {
            "experiment": "GUI-SEAM-743",
            "phase": args.phase,
            "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_sha": _git("rev-parse", "HEAD"),
            "worktree_clean": not _git("status", "--porcelain"),
            "windows": platform.platform(),
            "parent": runtime(),
            "samples": args.samples,
            "seed": args.seed,
            "fingerprint": fingerprint(),
            "production_defaults": defaults,
            "control": CONTROL.as_dict(),
            "host_start": host_snapshot(),
            "primary_sha256": hashlib.sha256(args.primary.read_bytes()).hexdigest()
            if args.primary
            else None,
        },
        "plan": [spec_dict(s) for s in plan],
        "phases": {},
        "validity": {"failures": []},
    }
    failures: list[str] = report["validity"]["failures"]
    if primary is not None:
        for key in ("source_sha", "fingerprint"):
            if primary["identity"][key] != report["identity"][key]:
                failures.append(f"confirmation {key} differs from the primary run it extends")
    phase: dict[str, Any] = {"conditions": {}}
    report["phases"][args.phase] = phase
    for config in configs:
        phase["conditions"][config.name] = {"config": describe(config), "warmup": None, "runs": []}

    def save() -> None:
        (args.output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf8")

    for spec in plan:
        host = host_snapshot()  # 500 ms of host load immediately BEFORE this child starts
        record = run_child(args.python, f"{PACKAGE}.child", child_arguments(spec.config))
        entry: dict[str, Any] = {
            "run_id": spec.run_id,
            "round": spec.round,
            "position": spec.position,
            "host": host,
            "process": {k: v for k, v in record.items() if k not in {"result"}},
        }
        condition = phase["conditions"][spec.config.name]
        try:
            validate_run(record, spec.config, defaults)
            entry["scalars"] = run_scalars(record)
            entry["result"] = record["result"]
        except (EvidenceError, KeyError, TypeError) as error:
            failures.append(f"{spec.run_id}: {error!r}")
            entry["invalid"] = repr(error)
            entry["result"] = record.get("result")
        if spec.kind == "warmup":
            condition["warmup"] = entry
        elif "scalars" in entry:
            condition["runs"].append(entry)
        else:
            condition.setdefault("invalid_runs", []).append(entry)
        save()

    scalars = {
        name: [r["scalars"] for r in cond["runs"]] for name, cond in phase["conditions"].items()
    }
    phase["aggregate"] = {}
    for name, runs in scalars.items():
        try:
            phase["aggregate"][name] = aggregate(runs, expected_n=args.samples, label=name)
        except EvidenceError as error:
            failures.append(f"aggregate {name}: {error}")
    if primary is not None:
        baseline = [r["scalars"] for r in primary["phases"]["primary"]["conditions"]["A"]["runs"]]
    else:
        baseline = scalars.get("A", [])
    phase["screens"] = {}
    for name, runs in scalars.items():
        if name == "A" and primary is None:
            continue
        try:
            phase["screens"][name] = screen(baseline, runs)
        except EvidenceError as error:
            failures.append(f"screen {name}: {error}")
    problems = validate_experiment(report)
    for problem in problems:
        if problem not in failures and not problem.startswith("invalid run:"):
            failures.append(problem)
    report["validity"]["status"] = "PASS" if not failures else "FAIL"
    if phase["screens"] and not failures:
        confirmation_names = list(phase["screens"]) if args.phase == "confirmation" else []
        report["verdict"] = verdict(phase["screens"], confirmation_names)
    report["identity"]["finished_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save()
    print(
        json.dumps(
            {
                "validity": report["validity"]["status"],
                "failures": failures[:20],
                "verdict": report.get("verdict"),
            }
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
